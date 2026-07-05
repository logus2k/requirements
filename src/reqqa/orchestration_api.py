"""Orchestration API — upload a document, run the pipeline as an async job,
stream progress, serve the scorecard and library (spec §8.5).

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

Run:  PYTHONPATH=src uvicorn reqqa.orchestration_api:asgi --port 7802

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
from fastapi.responses import JSONResponse

from reqqa.ingest.dispatch import SUPPORTED_EXTENSIONS
from reqqa.jobs import JobOptions, iter_job

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STORE = os.environ.get("REQQA_STORE", os.path.join(_REPO, "store"))


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

    def snapshot(self) -> dict:
        return {"job_id": self.job_id, "doc_id": self.doc_id,
                "source_file": self.source_file, "status": self.status,
                "stage": self.stage, "progress": self.progress, "error": self.error,
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
            for event in iter_job(path, options=options):
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


sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
api = FastAPI(title="reqqa-orchestration")
jm = JobManager(sio)


@api.on_event("startup")
async def _startup() -> None:
    jm.bind_loop(asyncio.get_running_loop())
    os.makedirs(STORE, exist_ok=True)


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "store": STORE, "jobs": len(jm.jobs)}


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


asgi = socketio.ASGIApp(sio, other_asgi_app=api)
