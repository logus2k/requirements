"""reqoach's thin lifecycle backend — the cross-cutting things no single agent owns.

Today that is the per-project git repository (see
`documents/project_git_repo_requirement.md`). reqoach creates and owns the LOCAL repo;
each agent writes into its own area and reqoach commits (agents need no git). The GitHub
REMOTE is a UI pending-action, never automated here.

Project creation itself is the Analyst's (`:7803`); reqoach does not intercept it (the
frontend calls `/analyst/…` directly). Instead:
  - `POST /repos/{pid}/ensure`  — create (idempotently) the repo for one project.
  - `POST /repos:reconcile`     — ensure a repo for every Analyst project (catch-up).
  - `GET  /repos/{pid}`         — repo status + pending actions (for the UI).
Writes are gated at the edge (nginx `@reqoach_write`), so no auth logic lives here.
"""

from __future__ import annotations

import json
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import repo

ANALYST_URL = os.environ.get("ANALYST_URL", "http://localhost:7803").rstrip("/")

router = APIRouter(tags=["lifecycle"])


def _project(pid: str) -> dict | None:
    """Fetch a project record from the Analyst, or None if it does not exist / unreachable."""
    try:
        r = httpx.get(f"{ANALYST_URL}/projects/{pid}", timeout=30)
    except httpx.RequestError:
        return None
    return r.json() if r.status_code == 200 else None


def _slug(s: str) -> str:
    """Match mermaid.py's file naming: runs of non-alphanumerics -> single underscore."""
    out, prev_us = [], False
    for c in s:
        if c.isalnum():
            out.append(c); prev_us = False
        elif not prev_us:
            out.append("_"); prev_us = True
    return "".join(out).strip("_")


@router.get("/repos/{pid}/architecture")
def architecture_view(pid: str) -> dict:
    """Read the FULL committed architecture output for the UI — per aspect: scope, components
    (with responsibilities), interfaces (with purpose), functions, cross-aspect consumes, and
    that aspect's diagram — plus the system-overview diagram and open issues. Empty structure
    if the Architect has not run yet."""
    area = os.path.join(repo.repo_path(pid), "architecture")

    diagrams: dict = {}
    system_overview = None
    dd = os.path.join(area, "diagrams")
    if os.path.isdir(dd):
        for fn in sorted(f for f in os.listdir(dd) if f.endswith(".mmd")):
            try:
                mmd = open(os.path.join(dd, fn)).read()
            except OSError:
                continue
            stem = fn[:-4]
            if stem == "_system_overview":
                system_overview = mmd
            else:
                diagrams[stem] = mmd

    aspects, open_issues, contract = [], [], None
    hp = os.path.join(area, "planner_handover.json")
    if os.path.isfile(hp):
        try:
            h = json.load(open(hp))
        except (ValueError, OSError):
            h = {}
        contract = h.get("contract_version")
        open_issues = h.get("open_issues", [])
        for name, a in (h.get("by_aspect") or {}).items():
            aspects.append({
                "name": name,
                "scope": a.get("scope", ""),
                "components": [{"name": c.get("name"), "responsibility": c.get("responsibility", "")}
                               for c in a.get("components", [])],
                "interfaces": [{"name": i.get("name"), "purpose": i.get("purpose", "")}
                               for i in a.get("interfaces", [])],
                "functions": [{"name": f.get("name"), "description": f.get("description", "")}
                              for f in a.get("functions", [])],
                "consumes": [{"concern": c.get("concern"), "why": c.get("why", "")}
                             for c in a.get("consumes", [])],
                "req_ids": a.get("req_ids", []),
                "diagram": diagrams.get(_slug(name)),
            })

    return {"exists": bool(aspects or diagrams), "contract_version": contract,
            "open_issues": open_issues, "system_overview": system_overview, "aspects": aspects}


@router.get("/repos/{pid}")
def repo_status(pid: str) -> dict:
    """Repo path + unfinished pending actions (e.g. create the GitHub remote)."""
    r = repo.get_repo(pid)
    if not r:
        raise HTTPException(404, "no repo for this project yet")
    return r.to_dict()


@router.delete("/repos/{pid}")
def delete_repo(pid: str) -> dict:
    """Remove a project's local repo — called when the project is deleted. Idempotent."""
    try:
        removed = repo.delete_repo(pid)
    except repo.RepoError as e:
        raise HTTPException(400, str(e))
    return {"removed": removed, "project_id": pid}


@router.post("/repos/{pid}/ensure")
def ensure_repo(pid: str) -> dict:
    """Create the project's local repo if absent (idempotent). Name comes from the Analyst."""
    proj = _project(pid)
    if not proj:
        raise HTTPException(404, "unknown project (the Analyst has no such id)")
    return repo.create_local_repo(pid, proj.get("name") or "project").to_dict()


def _write_json(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _publish_req(pid: str, name: str) -> dict | None:
    """Snapshot the Analyst's package into `requirements/` and commit it as the Analyst.
    reqoach PULLS the package over HTTP (the Analyst needs no repo mount / no change) and owns
    the git commit. Returns the result dict, or None when there is no package content to
    version yet (so a sweep skips untouched projects). Idempotent — unchanged files → no commit."""
    try:
        r = httpx.get(f"{ANALYST_URL}/projects/{pid}/package", timeout=120)
        r.raise_for_status()
        pkg = r.json()
    except httpx.HTTPError:
        return None
    if not pkg.get("requirements"):
        return None                       # nothing meaningful to version yet
    repo.create_local_repo(pid, name)     # idempotent
    area = os.path.join(repo.repo_path(pid), "requirements")
    os.makedirs(area, exist_ok=True)
    # Full package (the Architect's input contract) plus the split vocab/tree for clean diffs.
    files = {
        "package.json":  pkg,
        "glossary.json": pkg.get("glossary", []),
        "tags.json":     pkg.get("tags", []),
        "tree.json":     pkg.get("tree", {}),
    }
    for fn, data in files.items():
        _write_json(os.path.join(area, fn), data)
    sha = repo.commit_area(pid, "requirements", agent="analyst",
                           message="Analyst: publish requirements package")
    return {"committed": sha is not None, "sha": sha,
            "files": [f"requirements/{fn}" for fn in files]}


@router.post("/repos/{pid}/publish:requirements")
def publish_requirements(pid: str) -> dict:
    """Explicit per-project publish (for a UI 'publish to repo' action). Versioned provenance:
    reqoach commits the Analyst's package into requirements/ as the Analyst."""
    proj = _project(pid)
    if not proj:
        raise HTTPException(404, "unknown project (the Analyst has no such id)")
    res = _publish_req(pid, proj.get("name") or "project")
    if res is None:
        raise HTTPException(409, "no requirements package to publish yet")
    return res


class CommitRequest(BaseModel):
    area: str                       # one of requirements/architecture/plans/code
    agent: str = "reqoach"          # authorship label (see repo.AGENT_AUTHORS)
    message: str | None = None


@router.post("/repos/{pid}/commit")
def commit_area(pid: str, req: CommitRequest) -> dict:
    """Commit whatever an agent wrote into one repo area, authored as that agent.

    The agent writes files into `<repo>/<area>/` (shared volume); reqoach makes the commit.
    Returns the new commit SHA, or `committed: false` when the area had no changes.
    """
    try:
        sha = repo.commit_area(pid, req.area, agent=req.agent, message=req.message)
    except repo.RepoError as e:
        raise HTTPException(400, str(e))
    return {"committed": sha is not None, "sha": sha, "area": req.area, "agent": req.agent}


@router.post("/repos:reconcile")
def reconcile() -> dict:
    """Ensure a local repo exists for every Analyst project — catch-up for projects created
    before this backend, or via the /analyst/ route without a per-create ensure call."""
    try:
        r = httpx.get(f"{ANALYST_URL}/projects", timeout=60)
        r.raise_for_status()
        projects = r.json().get("projects", [])
    except httpx.HTTPError as e:
        raise HTTPException(502, f"cannot reach the Analyst: {e}")
    ensured = []
    for p in projects:
        pid = p.get("id")
        if not pid:
            continue
        name = p.get("name") or "project"
        rr = repo.create_local_repo(pid, name)
        pub = _publish_req(pid, name)          # best-effort snapshot of the Analyst package
        ensured.append({"project_id": pid, "path": rr.path, "pending": len(rr.pending),
                        "requirements_committed": bool(pub and pub["committed"])})
    return {"count": len(ensured), "repos": ensured}
