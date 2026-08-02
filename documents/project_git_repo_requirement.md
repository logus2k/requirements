# Requirement: One Git Repository per Project

**Status:** specified — implementation starting (during the Analyst vocabulary redesign,
before the Architect per-aspect work).
**Owner:** reqoach (the consolidated control panel / project-lifecycle owner).
**Remote:** GitHub.

---

## 1. Requirement

When a new project is created, a **git repository is automatically created for that
project**. Every document and code file produced by any agent in the pipeline (Analyst,
Architect, Planner, Builder, …) lives under that project's repository, version-controlled,
with **GitHub** as the remote.

Later, the Builder Agent works in **git worktrees — one per main feature** of the
implementation (a "main feature" maps to a branch in the requirements tree / a Planner
epic — see the Analyst `vocabulary_and_structure_redesign.md` and the Architect
`per_aspect_design_redesign.md`).

## 2. Why

Verified today, the chain's outputs are **scattered and unversioned**, three separate
locations keyed by the same `project_id`:
- Analyst → `analyst_agent/store/projects/<pid>/`
- Architect → `architect_agent/data/architecture/<pid>/`
- Planner → `planner_agent/data/plans/<pid>.plan.json`

There is no shared history, no diff between runs, no rollback, no single place a human (or
GitHub) sees "the project." One repo per project gives, for free:
- **Versioned provenance** across the whole chain — diff the architecture between
  requirements v1 and v2; roll back a bad run; see the project at any commit.
- **Git-native hand-off** — an agent *commits* its output; the next agent reads the repo at
  a ref. Every artifact carries an author (which agent), a time, a message.
- **A natural home for the Builder's worktrees** — one per feature/epic.

## 3. The architectural reality this must respect (verified)

reqoach's backend (`src/reqqa/bff.py`) is a **pure pass-through proxy** today: it forwards
`/projects`, `/jobs`, … to the Analyst (`:7803`) and serves the frontend. It holds no
project state; the **Analyst owns project creation and the store.**

**The proxy is redundant and should be retired.** Verified in the edge nginx
(`~/env/assets/proxy_server/conf/nginx.conf`, 199 location blocks): every service is already
exposed under one origin by path — `/llm/` → agent_server, `/bus/` → agent-bus, `/sdlc/`,
`/jenkins/`, etc., and `/reqoach/` → reqoach. The browser always talks to `logus2k.com`, so
CORS/same-origin — the only reason `bff.py` exists — is already solved at the edge. Today's
path is a needless double hop: `browser → /reqoach/ (edge) → bff.py → Analyst`. The right
topology adds per-agent edge routes and drops the internal proxy:

```
browser → logus2k.com/analyst/…   (edge) → Analyst
        → logus2k.com/architect/… (edge) → Architect
        → logus2k.com/reqoach/…   (edge) → reqoach  (frontend + thin lifecycle backend)
```

**So reqoach becomes: static frontend + a thin lifecycle backend** owning only the
cross-cutting things no agent owns — project creation and this git repo. It is NOT a proxy
and NOT a multi-agent router (the edge nginx routes). Repo creation lives in that thin
backend.

So this requirement is **not** a small reqoach-only feature. It has two parts:
- **Easy 10% — create the repo.** Hook project creation; `git init` a repo for the new
  `project_id`; add the GitHub remote.
- **Hard 90% — get every agent's output into it.** Agents currently write to their own
  scattered dirs. For their artifacts to be *in* the repo, the **project repo must become
  the shared data root**: each agent writes under `<repos_root>/<pid>/<its-area>/` instead
  of its private store, and commits there.

Pretending this is "reqoach creates a folder" would be dishonest — it touches where every
agent writes.

## 4. Design

### 4.1 Repo layout (single-owner areas, mirrors the asset/data conventions)
```
<repos_root>/<project_id>/
  requirements/     ← Analyst: package.json, scorecard, glossary, tags, tree
  architecture/     ← Architect: model.sysml, planner_handover.json, diagrams/, artifacts/
  plans/            ← Planner: plan.json
  code/             ← Builder: implementation (worktrees branch from here)
  README.md         ← project metadata
  .gitignore        ← excludes large binaries (see 4.4)
```
Each agent owns one top-level area — no two agents write the same path, which sidesteps
merge conflicts on a shared tree.

### 4.2 Who creates the repo
**Decided (topology verified, §3): reqoach's thin lifecycle backend owns it.** The redundant
proxy is retired; reqoach keeps the frontend and gains a small backend for cross-cutting
lifecycle — project creation and repo creation live there. Each agent is exposed at its own
edge route (`logus2k.com/<agent>/`) and commits into its own area of the repo; agents do not
depend on reqoach being up to run, only to be *created*.

### 4.3 Commit identity & concurrency
- Each agent commits **only within its own area** → no working-tree races on shared paths.
- Commits are authored per agent (`Analyst Agent <…>`, `Architect Agent <…>`) so history
  shows who produced what.
- Serialise commits per repo (a per-project lock) to avoid concurrent-index corruption when
  two agents finish together.

### 4.4 Big files — do NOT commit blobs
The Architect's toolchain is a **127 MB jar** (already git-ignored); source documents are
PDFs; models are large. "All documents and code" means **agent-produced text/artifacts**,
not binaries. Large/derived assets are excluded via `.gitignore` and handled by the
existing asset conventions (the `ci-ready` skill's asset-pin / RustFS pattern), not stuffed
into git. Diagrams (PNG) are small enough to keep; re-evaluate if they grow.

### 4.5 GitHub remote
- On creation, add a GitHub remote (org/repo naming: `<prefix>-<project_id>` or the project
  slug — TBD).
- Push policy: push on meaningful milestones (package released, architecture approved), not
  every intermediate write. Auth via a machine token, not interactive.
- **Open:** private by default; repo naming; whether one GitHub repo per project or a
  monorepo with per-project directories. Leaning: one repo per project, private.

### 4.6 Builder worktrees (later)
When the Builder runs, it creates a worktree per main feature (branch per epic), builds each
in isolation, and merges. Out of scope for this first implementation; the layout above
(`code/` as the worktree base) anticipates it.

## 5. Phases

1. **Repo creation on project create** (reqoach) — `git init` under `<repos_root>/<pid>/`,
   scaffold the layout + `.gitignore` + README, add the GitHub remote. Verifiable: create a
   project → a repo exists with the layout.
2. **Analyst writes into the repo** — the Analyst publishes its package (and the new
   glossary/tags/tree) under `requirements/` and commits. Done alongside the Analyst
   redesign, since that code is already being changed.
3. **Architect & Planner write into the repo** — repoint their output dirs to
   `architecture/` and `plans/`; commit. (Architect part aligns with its per-aspect
   redesign.)
4. **GitHub push** on milestones; auth via machine token.
5. **Builder worktrees** — per-feature, when the Builder is built.

## 5b. Decisions (owner)

- **Repos root:** `~/env/project-repos` (`PROJECT_REPOS_ROOT`), one repo per project, private.
  In deployment this is a shared volume mounted into each agent container at a common path.
- **GitHub remote — token via UI on publish.** When the user confirms "publish to remote",
  the UI shows an input box; the user pastes a **fine-grained** PAT (scoped to repo
  creation + push only). **v1: use-once** — the token is used for that create+push and
  **never persisted or logged**; the user re-pastes per publish. If "publish without
  re-pasting" is later wanted, store it in **Vault/Infisical** (already running), never in
  plaintext. Transport is the existing TLS edge only. Long-term cleaner option: a GitHub App
  installation (avoids handling user PATs) — deferred.

## 6. Open decisions
- Repo-creator: helper module first vs a small service (recommended: helper now, service if
  cross-container calls appear).
- `<repos_root>` location and how each agent container mounts it (shared volume).
- GitHub: repo-per-project vs monorepo (leaning repo-per-project, private); naming; token.

## 7. Status (living)
- **2026-08 — Requirement written.** Implementation starting at Phase 1.
- **2026-08-02 — Phase 1 DONE + VERIFIED LIVE.** reqoach gained a thin lifecycle backend
  (`src/reqqa/lifecycle.py`, an APIRouter mounted in `bff.py`): `POST /repos/{pid}/ensure`,
  `POST /repos:reconcile`, `GET /repos/{pid}`, `POST /repos/{pid}/commit`. The reqoach image
  now installs `git` and runs as the host UID (repos on the bind mount are host-owned, not
  root); `~/env/project-repos` is mounted at `/app/project-repos` (`PROJECT_REPOS_ROOT`).
  `projects.html` fires `ensure` on project create (fire-and-forget; reconcile is the catch-up).
  Verified: reconcile created 5 repos with the §4.1 layout + initial commit, host-owned,
  idempotent; status returns the GitHub-remote pending action; edge `GET /reqoach/repos/{pid}`
  200, unauth `POST …/ensure` 401 (nginx-gated). **Commit mechanism (the "reqoach commits"
  seam) VERIFIED:** a file written into `requirements/` committed via `POST /repos/{pid}/commit`
  as `Analyst Agent <analyst@logus2k.com>`; no-op on unchanged area → `committed:false`; bad
  area → 400; per-project lock serialises commits.
- **2026-08-02 — Phase 2 (Analyst → `requirements/`) DONE + VERIFIED LIVE.** Implemented as
  **reqoach-pull** (not Analyst-push), which needs ZERO change to the live Analyst container:
  reqoach fetches the Analyst package over HTTP and commits it into `requirements/` as the
  Analyst. `POST /repos/{pid}/publish:requirements` (explicit, for a UI button) + `reconcile`
  now full-syncs (create repo **and** snapshot requirements when there is content). Writes
  `package.json` (the Architect's input contract) + split `glossary/tags/tree.json` for clean
  diffs. Verified across 4 projects (111-req and 386-req scales): committed as
  `Analyst Agent <analyst@logus2k.com>`, content matches the live package, idempotent
  (unchanged → `committed:false`). NOTE this is a **snapshot/publish** model (versioned
  provenance), not the "repo as shared data root" ideal — the Analyst still writes its own
  store; reqoach snapshots the published package. That satisfies §2's provenance goal.
- **2026-08-02 — Phase 3 (Architect → `architecture/`) DONE + VERIFIED (plumbing; full run
  GPU-gated).** The Architect writes files, reqoach commits. `architect_agent/src/architect_agent/
  aspect_pipeline.py` gained `publish_to_repo(pid, out_dir)` (copies the emitted architecture
  output into `<repos_root>/<pid>/architecture/` and POSTs reqoach `/repos/{pid}/commit`,
  agent=architect) + a `--repo` CLI flag + `run(to_repo=True)`. The architect compose mounts
  `${HOME}/env/project-repos:/app/project-repos` (`PROJECT_REPOS_ROOT`), sets
  `REQOACH_URL=http://host.docker.internal:7802` + `extra_hosts host-gateway`. Verified: real
  emit (handover 2.0 + Mermaid diagrams + artifact) published + committed as
  `Architect Agent <architect@logus2k.com>` (5 files); 65 tests pass; image rebuilt with `--repo`;
  architect CONTAINER → reqoach reachability HTTP 200. **Only UNVERIFIED bit (GPU-gated):** a full
  containerized run (fetch package → LLM design → `--repo` publish); the design pipeline itself
  was verified earlier (Restaurant/Jobs), and the publish+commit path is verified here.
- **Delete gap RESOLVED + VERIFIED:** `repo.delete_repo` (path-guarded, alnum id only) +
  `DELETE /repos/{pid}` (idempotent) + `overview.html` calls it after a project delete. Verified:
  delete→removed:true→gone, re-delete→false, bad id→400, reconcile does NOT resurrect a deleted
  project's repo. (reconcile deliberately does NOT auto-prune — a transient empty Analyst list
  would otherwise nuke every repo; explicit delete is the safe path.)
- **Net state:** each project repo now versions `requirements/` (Analyst-authored) and
  `architecture/` (Architect-authored) with distinct git provenance. Remaining: Planner →
  `plans/` (Phase 3-style), GitHub push (Phase 4, use-once token), Builder worktrees (Phase 5).
- **NOT done — Phase 4 GitHub push** (use-once UI token paste) and **Phase 5 Builder worktrees.**
