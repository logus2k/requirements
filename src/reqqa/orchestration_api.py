"""reqoach — the single-container backend: static dashboard + editor + the
orchestration API + socket.io (job progress AND live single-requirement assess).

One FastAPI app serves the static frontend (dashboard, editor, vendored libs,
data/) and the REST API; one socket.io server carries both the job-progress
stream (`join` → rooms) and the live assessor (`assess` → per-client). This is
the same-origin backend nginx routes `/reqoach/` and `/reqoach/socket.io/` to.

Wraps `reqqa.jobs.iter_job` in a background worker and exposes:

  POST /documents                    upload → store → create job (returns job_id, doc_id)
  GET  /jobs/{job_id}                job status snapshot (stage, progress, error)
  GET  /jobs/{job_id}/events         buffered events so far (replay for late/polling clients)
  GET  /documents                    library listing
  GET  /documents/{doc_id}/scorecard the assembled scorecard JSON
  GET  /health

Live progress also streams over **socket.io**: a client emits
`join {job_id}` and receives the same events (`stage`, `requirement`,
`review_result`, `set_level`, `aggregates`, `scorecard`, `job_done`,
`job_error`) as the job runs. The job runs in a worker thread; its events are
marshalled onto the asyncio loop with `run_coroutine_threadsafe`.

Run:  PYTHONPATH=src uvicorn reqqa.orchestration_api:asgi --host 0.0.0.0 --port 7802
(or via the `reqoach` compose service, which is how it runs in production)

Persistence is the filesystem under REQQA_STORE (default <repo>/store):
  store/<doc_id>/source.<ext>, scorecard.json, meta.json
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from dataclasses import dataclass, field

import socketio
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from reqqa import framing
from reqqa import projects as pj
from reqqa.assess import iter_assessment
from reqqa.ingest.dispatch import SUPPORTED_EXTENSIONS
from reqqa.jobs import JobOptions, iter_job, iter_project_job
from reqqa.llm.client import AgentServerClient

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STORE = os.environ.get("REQQA_STORE", os.path.join(_REPO, "store"))
_FRONTEND = os.path.join(_REPO, "frontend")


@dataclass
class Job:
    job_id: str
    doc_id: str
    source_file: str
    status: str = "queued"          # queued | running | done | error
    stage: str | None = None
    progress: dict = field(default_factory=dict)   # {done, total} of the active stage
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    project_id: str | None = None   # set for project (multi-doc) runs
    run_id: str | None = None       # == job_id for project runs
    kind: str = "document"          # document | quality (project)

    def snapshot(self) -> dict:
        return {"job_id": self.job_id, "doc_id": self.doc_id,
                "source_file": self.source_file, "status": self.status,
                "stage": self.stage, "progress": self.progress, "error": self.error,
                "project_id": self.project_id, "run_id": self.run_id, "kind": self.kind,
                "event_count": len(self.events)}


class JobManager:
    """Owns jobs, runs each in a worker thread, and fans events out to socket.io
    room == job_id (plus an in-memory buffer for replay)."""

    def __init__(self, sio: socketio.AsyncServer):
        self.sio = sio
        self.jobs: dict[str, Job] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _emit(self, job: Job, event: dict) -> None:
        job.events.append(event)
        # keep a light status snapshot in sync for polling clients
        if event.get("type") == "stage":
            job.stage = event.get("stage")
            job.progress = {"done": event.get("done"), "total": event.get("total"),
                            "status": event.get("status")}
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(
                self.sio.emit(event["type"], {**event, "job_id": job.job_id},
                              room=job.job_id), self._loop)

    def _run(self, job: Job, path: str, options: JobOptions) -> None:
        job.status = "running"
        self._emit(job, {"type": "stage", "stage": "queued", "status": "done"})
        try:
            for event in iter_job(path, options=options, source_file=job.source_file):
                self._emit(job, event)
                if event.get("type") == "scorecard":
                    self._persist_scorecard(job, event["data"])
            job.status = "done"
            self._emit(job, {"type": "job_done", "doc_id": job.doc_id})
        except Exception as e:  # noqa: BLE001 — surface any pipeline failure
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            self._emit(job, {"type": "job_error", "message": job.error})

    def _persist_scorecard(self, job: Job, scorecard: dict) -> None:
        doc_dir = os.path.join(STORE, job.doc_id)
        os.makedirs(doc_dir, exist_ok=True)
        with open(os.path.join(doc_dir, "scorecard.json"), "w", encoding="utf-8") as f:
            json.dump(scorecard, f, indent=1)
        meta = {"doc_id": job.doc_id, "job_id": job.job_id,
                "source_file": job.source_file,
                "total": scorecard.get("aggregates", {}).get("total"),
                "produced_in_s": scorecard.get("produced_in_s"),
                "per_characteristic_mean": scorecard.get("aggregates", {}).get("per_characteristic_mean")}
        with open(os.path.join(doc_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)

    def create(self, path: str, source_file: str, doc_id: str,
               options: JobOptions) -> Job:
        job = Job(job_id=uuid.uuid4().hex, doc_id=doc_id, source_file=source_file)
        self.jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job, path, options),
                         daemon=True).start()
        return job

    # --- project (multi-document) quality runs ---
    def _run_project(self, job: Job, docs: list[dict], source_file: str,
                     options: JobOptions) -> None:
        job.status = "running"
        self._emit(job, {"type": "stage", "stage": "queued", "status": "done"})
        try:
            for event in iter_project_job(docs, source_file, options=options):
                self._emit(job, event)
                if event.get("type") == "scorecard":
                    self._persist_project_scorecard(job, event["data"])
            job.status = "done"
            self._emit(job, {"type": "job_done", "project_id": job.project_id, "run_id": job.run_id})
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            self._emit(job, {"type": "job_error", "message": job.error})

    def _persist_project_scorecard(self, job: Job, scorecard: dict) -> None:
        meta = {"run_id": job.run_id, "project_id": job.project_id, "kind": "quality",
                "finished_at": pj._now(), "source_file": job.source_file,
                "total": scorecard.get("aggregates", {}).get("total"),
                "produced_in_s": scorecard.get("produced_in_s"),
                "documents": scorecard.get("documents", [])}
        pj.save_quality_run(job.project_id, job.run_id, scorecard, meta)

    def create_project_run(self, pid: str, docs: list[dict], source_file: str,
                           options: JobOptions) -> Job:
        job = Job(job_id=uuid.uuid4().hex, doc_id="", source_file=source_file)
        job.project_id, job.run_id, job.kind = pid, job.job_id, "quality"
        self.jobs[job.job_id] = job
        threading.Thread(target=self._run_project, args=(job, docs, source_file, options),
                         daemon=True).start()
        return job


sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
api = FastAPI(title="reqoach")
api.add_middleware(GZipMiddleware, minimum_size=1024)   # big scorecard JSON


@api.middleware("http")
async def _revalidate_assets(request, call_next):
    """Serve HTML/JS/CSS with `Cache-Control: no-cache` so browsers always revalidate
    (cheap 304 via the ETag) instead of silently serving a stale bundle after a rebuild."""
    resp = await call_next(request)
    path = request.url.path
    if path.endswith((".html", ".js", ".css")) or path.endswith("/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


jm = JobManager(sio)


@api.on_event("startup")
async def _startup() -> None:
    jm.bind_loop(asyncio.get_running_loop())
    os.makedirs(STORE, exist_ok=True)


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "store": STORE, "jobs": len(jm.jobs)}


_RULES_META: dict | None = None


@api.get("/rules")
def rules_meta() -> dict:
    """INCOSE rule metadata for the frontend: id -> {name, category, detector,
    text (guidance), terms}. Lets the UI show rule names/guidance instead of bare
    ids, group by category, and label deterministic vs judge-flagged findings.
    Cached after first read; the catalog is static."""
    global _RULES_META
    if _RULES_META is None:
        path = os.path.join(_REPO, "incose", "catalog.json")
        with open(path, encoding="utf-8") as f:
            cat = json.load(f)
        _RULES_META = {r["id"]: {"name": r.get("name"), "category": r.get("category"),
                                 "detector": r.get("detector"), "scope": r.get("scope"),
                                 "text": r.get("text"), "terms": r.get("terms", [])}
                       for r in cat.get("rules", [])}
    return _RULES_META


@api.post("/documents")
async def upload_document(file: UploadFile = File(...),
                          review: bool = True, set_level: bool = True) -> JSONResponse:
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, f"unsupported extension {ext!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")

    doc_id = uuid.uuid4().hex
    doc_dir = os.path.join(STORE, doc_id)
    os.makedirs(doc_dir, exist_ok=True)
    src_path = os.path.join(doc_dir, f"source{ext}")
    with open(src_path, "wb") as f:
        f.write(await file.read())

    job = jm.create(src_path, filename, doc_id,
                    JobOptions(review=review, set_level=set_level))
    return JSONResponse(status_code=202,
                        content={"job_id": job.job_id, "doc_id": doc_id,
                                 "source_file": filename, "status": job.status})


@api.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jm.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return job.snapshot()


@api.get("/jobs/{job_id}/events")
def job_events(job_id: str) -> dict:
    job = jm.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return {"job_id": job_id, "status": job.status, "events": job.events}


@api.get("/documents")
def list_documents() -> dict:
    docs = []
    if os.path.isdir(STORE):
        for doc_id in sorted(os.listdir(STORE)):
            meta_path = os.path.join(STORE, doc_id, "meta.json")
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    docs.append(json.load(f))
    return {"documents": docs}


@api.get("/documents/{doc_id}/scorecard")
def get_scorecard(doc_id: str) -> dict:
    path = os.path.join(STORE, doc_id, "scorecard.json")
    if not os.path.isfile(path):
        raise HTTPException(404, "no scorecard (job not finished or unknown doc)")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@sio.event
async def join(sid, data):
    """Client subscribes to a job's live event stream, and gets a replay of
    events already emitted so it never misses the early stages."""
    job_id = (data or {}).get("job_id")
    job = jm.jobs.get(job_id)
    if not job:
        await sio.emit("job_error", {"message": "unknown job"}, to=sid)
        return
    await sio.enter_room(sid, job_id)
    for event in list(job.events):
        await sio.emit(event["type"], {**event, "job_id": job_id, "replay": True}, to=sid)


# --- Live single-requirement assessor, folded onto the SAME socket.io server ---
# The dashboard/monitor uses `join` (job rooms); the editor uses `assess` (per-sid).
# One server, one origin, one container.
_assess_gen: dict[str, int] = {}
_assess_client = AgentServerClient()


@sio.event
async def connect(sid, environ):
    _assess_gen[sid] = 0


@sio.event
async def disconnect(sid):
    _assess_gen.pop(sid, None)


@sio.event
async def assess(sid, data):
    """Stream a single requirement's live assessment; a newer `assess` from the
    same client supersedes the in-flight one (generation counter)."""
    text = ((data or {}).get("text") or "").strip()
    review = bool((data or {}).get("review", True))
    gen = _assess_gen.get(sid, 0) + 1
    _assess_gen[sid] = gen
    if len(text) < 12:                       # matches verify.MIN_TEXT_LEN
        await sio.emit("idle", {"reason": "too_short"}, to=sid)
        return
    await sio.emit("start", {"gen": gen}, to=sid)

    loop = asyncio.get_running_loop()
    gen_iter = iter_assessment(text, client=_assess_client, review=review)
    sentinel = object()

    def _next():
        try:
            return next(gen_iter)
        except StopIteration:
            return sentinel

    while True:
        if _assess_gen.get(sid) != gen:      # superseded
            gen_iter.close()
            return
        event = await loop.run_in_executor(None, _next)
        if event is sentinel:
            break
        if _assess_gen.get(sid) != gen:
            return
        await sio.emit(event["type"], {**event, "gen": gen}, to=sid)


# --- Projects mode (see specs/projects_mode/): project workspace + project-scoped
# document upload. Uploading stores source + metadata ONLY — it triggers no analysis;
# Quality/Coverage runs are explicit (later phases). ---

@api.post("/projects")
async def create_project(payload: dict | None = None) -> dict:
    return pj.create_project((payload or {}).get("name", ""))


@api.get("/projects")
def list_projects() -> dict:
    return {"projects": pj.list_projects()}


@api.get("/projects/{pid}")
def get_project(pid: str) -> dict:
    proj = pj.get_project(pid)
    if not proj:
        raise HTTPException(404, "unknown project")
    return proj


@api.post("/projects/{pid}/documents")
async def upload_project_documents(pid: str, files: list[UploadFile] = File(...)) -> JSONResponse:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    saved, errors = [], []
    for f in files:
        fn = f.filename or "upload"
        ext = os.path.splitext(fn)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            errors.append({"filename": fn, "error": f"unsupported extension {ext!r}"})
            continue
        saved.append(pj.add_document(pid, fn, ext, await f.read()))
    return JSONResponse(status_code=201, content={"documents": saved, "errors": errors})


@api.get("/projects/{pid}/documents")
def list_project_documents(pid: str) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    return {"documents": pj.list_documents(pid)}


@api.post("/projects/{pid}/quality:run")
async def run_project_quality(pid: str, payload: dict | None = None) -> JSONResponse:
    """Explicit, user-triggered INCOSE quality run over the project's documents
    (all, or a `document_ids` subset). One scorecard; set-level across all docs;
    each requirement traceable to its source document."""
    proj = pj.get_project(pid)
    if not proj:
        raise HTTPException(404, "unknown project")
    wanted = set((payload or {}).get("document_ids") or [])
    docs = [d for d in pj.list_documents(pid) if not wanted or d["id"] in wanted]
    run_docs = []
    for d in docs:
        path = pj.document_path(pid, d["id"])
        if path:
            run_docs.append({"path": path, "source_file": d["filename"], "document_id": d["id"]})
    if not run_docs:
        raise HTTPException(400, "no documents to analyze")
    job = jm.create_project_run(pid, run_docs, proj.get("name") or "project", JobOptions())
    return JSONResponse(status_code=202,
                        content={"job_id": job.job_id, "run_id": job.run_id,
                                 "project_id": pid, "status": job.status,
                                 "document_count": len(run_docs)})


@api.get("/projects/{pid}/quality")
def project_quality_runs(pid: str) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    return {"runs": pj.list_quality_runs(pid)}


@api.get("/projects/{pid}/quality/scorecard")
def project_quality_scorecard(pid: str, run: str | None = None) -> dict:
    sc = pj.get_quality_scorecard(pid, run)
    if not sc:
        raise HTTPException(404, "no quality scorecard yet (run not finished or none run)")
    return sc


# --- Requirements Coverage — Problem Framing (stage 0). Explicit, user-triggered. ---

@api.post("/projects/{pid}/problem-statement:generate")
def generate_problem_statement(pid: str, payload: dict | None = None) -> dict:
    """Distil a structured, provenance-graded problem statement from the project's
    documents (+ optional free-text request). Sync `def` → runs in the threadpool so
    the ~20s LLM call doesn't block the event loop. Saved as an unratified draft."""
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    paths = [p for d in pj.list_documents(pid) if (p := pj.document_path(pid, d["id"]))]
    try:
        statement = framing.frame_problem(paths, (payload or {}).get("user_request", ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"framing failed: {type(e).__name__}: {e}")
    doc = pj.save_problem_statement(pid, statement, ratified=False)
    if not pj.get_coverage_profile(pid):        # seed the profile from the framing output
        pj.save_coverage_profile(pid, {"archetypes": statement.get("candidate_archetypes", []),
                                       "salient_domains": statement.get("salient_domains", []),
                                       "domain_overrides": {}})
    return doc


@api.get("/projects/{pid}/problem-statement")
def get_problem_statement(pid: str) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    return pj.get_problem_statement(pid) or {"version": 0, "statement": None}


@api.put("/projects/{pid}/problem-statement")
async def put_problem_statement(pid: str, payload: dict) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    st = (payload or {}).get("statement")
    if st is None:
        raise HTTPException(400, "missing 'statement'")
    return pj.save_problem_statement(pid, st, ratified=bool((payload or {}).get("ratified", False)))


@api.get("/projects/{pid}/coverage-profile")
def get_coverage_profile(pid: str) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    return pj.get_coverage_profile(pid) or {"version": 0, "profile": None}


@api.put("/projects/{pid}/coverage-profile")
async def put_coverage_profile(pid: str, payload: dict) -> dict:
    if not pj.get_project(pid):
        raise HTTPException(404, "unknown project")
    prof = (payload or {}).get("profile")
    if prof is None:
        raise HTTPException(400, "missing 'profile'")
    return pj.save_coverage_profile(pid, prof)


# --- Coverage catalog (read-only, for the UI) ---

@api.get("/catalog/domains")
def catalog_domains() -> dict:
    return framing.load_domains()


@api.get("/catalog/archetypes")
def catalog_archetypes() -> dict:
    return {"archetypes": framing.load_archetypes()}


@api.get("/catalog/standards")
def catalog_standards() -> dict:
    return {"standards": framing.load_standards()}


# Serve the static frontend (dashboard, editor, vendored libs, existing data/)
# from the SAME origin. Mounted LAST so it never shadows the API routes above;
# socket.io (/socket.io/) is handled by the ASGIApp wrapper before FastAPI.
api.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")

asgi = socketio.ASGIApp(sio, other_asgi_app=api)
