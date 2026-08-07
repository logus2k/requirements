# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is (and is NOT)

This repo is **reqoach** — the **control panel / project-lifecycle owner** for a multi-agent
requirements→architecture→plan chain. It is a **static frontend + a thin Python backend**. It
holds **no analysis data and no analysis engine**.

The INCOSE analysis engine (ingest, segment, score, refine, classify, coverage, package,
reissue) lives in a **separate service and repo**: the **Analyst Agent** at
`~/env/assets/analyst_agent` (`:7803`), which owns the store. reqoach is a *consumer* of it,
exactly like the downstream Architect and Planner agents.

> ⚠️ **`README.md` is stale in its core.** It describes the old single-container monolith with
> `src/reqqa/ingest|segment|score`. Those modules were moved into the Analyst and **deleted from
> here**. `src/reqqa/` now contains only `bff.py`, `lifecycle.py`, `repo.py`, `__init__.py`.
> Trust the code and this file over the README's architecture/pipeline sections. (`specs/` are
> historical design docs from the same pre-split era.)

## The system around this repo

| Service | Port | Repo | Role |
|---|---|---|---|
| **reqoach** (this) | **7802** | here | static frontend + BFF + project git-repo lifecycle |
| **analyst-agent** | 7803 | `~/env/assets/analyst_agent` | the whole INCOSE engine; owns the store |
| agent_server | 7701 | `~/env/assets/agent_server` | LLM presets (Gemma 4 E4B) — judges, reviewer, classifier, framing, coverage |
| ingestion-server | 8700 | `~/env/assets/ingestion_server` | shared Docling document parsing |
| embeddings/reranker | 8601 | shared | dedup + set-level overlap detection |

Agent chain: **Analyst → Architect → Planner → Builder**. reqoach is the shared control panel
across all of them and owns the per-project git repository (below).

Production edge is nginx + oauth2-proxy in `~/env/assets/proxy_server` (not this repo). Public
site: `logus2k.com/reqoach/`.

## Build & run

Everything runs in Docker. From this directory:

```bash
# Build so repos created on the git bind-mount are owned by you, not root:
docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g)
docker compose up -d

curl -s localhost:7802/health          # reqoach itself
curl -s localhost:7802/analyst/health  # reqoach's view of the Analyst
```

- **The frontend is COPYed into the image at build time — there is no live mount.** Any change
  under `frontend/` (HTML/JS/CSS) requires `docker compose build && docker compose up -d` to
  appear. This is the single most common "why didn't my change show up" trap.
- reqoach needs the **Analyst running** at `:7803`: `cd ~/env/assets/analyst_agent/compose &&
  docker compose build && docker compose up -d`.
- `network_mode: host` — binds host `:7802` and reaches the Analyst on `localhost:7803`.
- **Two Dockerfiles exist.** `Dockerfile.orchestration` is reqoach (what compose uses).
  `Dockerfile` is the old decommissioned ingest engine — unused; do not build it.

Local dev without Docker (rarely needed; the Analyst must still be up):
```bash
PYTHONPATH=src ANALYST_URL=http://localhost:7803 uvicorn reqqa.bff:app --port 7802
```

**Tests / lint:** there are none in this repo. `scripts/*.py` are one-off utilities (catalog
builders, agent registration) from the pre-split era — not a test or build system. To verify a
UI change, render it in a headless browser (Playwright); an HTTP 200 from curl proves the asset
is served, **not** that the page works.

## Backend architecture (`src/reqqa/`)

Three small modules, all mounted on one FastAPI app (`reqqa.bff:app`):

- **`bff.py`** — serves `frontend/` statically and reverse-proxies to the Analyst. Proxied
  prefixes: `/analyst/*` (prefix stripped before forwarding — a **local-dev alias**; in
  production nginx routes `/analyst/*` straight to `:7803`, so the browser calls `/analyst/…` in
  both environments and this route is dev-only), plus `/documents` and `/socket.io`. Everything
  else is a static asset. Two non-obvious, load-bearing rewrites: it **drops `content-encoding`
  from proxied responses** (httpx already decompressed the Analyst's gzip; forwarding `gzip`
  causes `ERR_CONTENT_DECODING_FAILED` and silently breaks every API call), and it **rewrites the
  socket.io handshake to advertise no websocket upgrades locally** (no nginx locally to carry the
  upgrade). Proxy prefix routes are registered **before** the `/` StaticFiles mount so they win.
- **`lifecycle.py`** — the cross-cutting things no single agent owns. Routes: `GET /me` (Google
  identity: email from the nginx-verified header, name/picture fetched from Google UserInfo with
  the forwarded access token), `/repos/*` (per-project git repo status/ensure/commit/reconcile),
  and Architect/Planner passthroughs (`/repos/{pid}/architecture`, `/repos/{pid}/plan`). Project
  *creation* is the Analyst's, not intercepted here.
- **`repo.py`** — the per-project git repository. See `documents/project_git_repo_requirement.md`.

### Per-project git repos (reqoach's distinctive responsibility)

Each project gets a local git repo under `PROJECT_REPOS_ROOT` (`~/env/project-repos`,
bind-mounted). The tree is a **single-owner layout** — `requirements/ architecture/ plans/ code/`,
one agent per top-level dir — so no two agents ever write the same path and there are no merge
races. **reqoach creates the repo and commits; the agents need no git.** The GitHub **remote is
NOT automated** — it needs the user's credentials, so it is surfaced as a *pending action* in the
UI for the user to complete. Only a project's own freshly-created repo is ever touched.

## Frontend (`frontend/`)

Plain HTML + vanilla JS, **no framework and no build step**. Vendored libraries under
`frontend/vendor/` (ECharts, mermaid, pdf.js, socket.io). Pages are self-contained (most logic is
inline `<script>` in the `.html`); shared JS is small:

- **`js/nav.js`** — the shared top nav on every page, **and** the auth layer: it defines global
  `window.ReqoachAuth` (identity via `/oauth2/userinfo`, `canManage(project)`, sign-in/out URLs)
  and renders the sign-in control + theme toggle.
- **`js/app.js`** — the dashboard (`index.html`) rendering: radar, rule bar, distribution,
  set-level, sortable table + detail drawer.
- **`js/pdf-viewer.js`** — single-page pdf.js viewer with bbox highlighting (source-PDF review).

Key pages: `projects.html` (switcher/home), `overview.html` (the pipeline control centre —
Documents → Framing → Quality → Classification → Coverage → Release, plus an Architect row),
`index.html` (dashboard), `review.html` (Review & Reissue), `coverage.html`, `editor.html` (live
single-requirement assessor over socket.io), `architecture.html`, `planning.html`.

**The current project id is URL-only** (`?project=<id>`) after the stateless-project-id
migration — it is no longer stored in localStorage (only the theme is). Project-scoped links must
carry `?project=…`; `nav.js` fetches the project name to fill the chip.

## Auth model — public browse, gated manage

Reads are public; **mutations require Google sign-in**, and per-project management is restricted
to the project **owner or the admin (`logus2k@gmail.com`)**.

- Enforcement is layered: **nginx** (`@reqoach_write`) gates every non-GET to `/oauth2/auth` and
  forwards the verified `X-Auth-Request-Email`; the **Analyst** is the real authority (an
  `_authz` middleware checks owner/admin per project). This repo's frontend `ReqoachAuth` is
  **UX only** — it shows sign-in state and disables actions the user can't perform; it is not a
  security boundary.
- The trust boundary is nginx: `:7802`/`:7803` are localhost-only and trust the forwarded email
  header, which only nginx sets (overwriting any client value) on authenticated writes.

## The Analyst handover contract (why this chain exists)

The Analyst emits an Architect-ready **package** (`GET /analyst/projects/{pid}/package`, or
`:7803/projects/{pid}/package` directly) — a self-describing JSON of scored, classified,
traceable requirements, gated by a human sign-off (`release_status: draft → validated`). The
authoritative contract for downstream consumers is `~/env/assets/analyst_agent/sdk/how_to.md`.
When touching anything that crosses this boundary, read that document — the requirement **trace
key is `req_id`**, and routing is driven by the multi-label `classes[]` field.
