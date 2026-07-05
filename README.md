# reqoach — Requirements Quality Analyzer

**reqoach** ingests a requirements document, splits it into discrete requirements,
scores each against the **INCOSE Guide to Writing Requirements (GtWR v4,
INCOSE-TP-2010-006-04)**, proposes fixes for the weak ones, and visualizes the
whole set — with a live editor that assesses a single requirement as you type.

> **Live:** [logus2k.com/reqoach](https://logus2k.com/reqoach/) — browsing assessed
> results is public; starting an assessment (upload / live editor) requires Google
> sign-in.

Pipeline: **ingest → segment → score → review → visualize**.
Runs entirely on a **local LLM** (Gemma 4 E4B) — no data leaves the host.

Design docs: [specs/technical_architecture.md](specs/technical_architecture.md)
and [specs/requirements_frontend.md](specs/requirements_frontend.md).

---

## What it does

| Stage | Where | What it does |
|-------|-------|--------------|
| **1 · Ingest** | [src/reqqa/ingest/](src/reqqa/ingest/) | Document (`.md/.pdf/.docx/.html/.pptx`) → normalized `SourceItem`s with provenance. Markdown parsed in-process; other formats via a GPU **Docling** service. |
| **2 · Segment** | [src/reqqa/segment/](src/reqqa/segment/) | LLM identifies discrete requirements (identify → gate → assemble → dedup). Anti-hallucination: every requirement must trace to its source block. |
| **3 · Score** | [src/reqqa/score/](src/reqqa/score/) | 9 per-characteristic LLM judges (C1–C9) + 15 deterministic term-list rules. |
| **4 · Set-level** | [src/reqqa/score/setlevel.py](src/reqqa/score/setlevel.py) | C10–C15 across the whole set (reranker overlap → LLM confirm → set judge). |
| **5 · Review** | [incose/judges/reviewer.md](incose/judges/reviewer.md) | Rewrites + advisories for defective requirements. |
| **6 · Visualize** | [frontend/](frontend/) | ECharts dashboard (radar, rule bar, distribution, set-level, sortable table + detail drawer). |

**Key design decisions**
- **The LLM is the sole requirement identifier — no regex.** Requirements are written too many ways to intercept structurally.
- **Judges score 1–5, `batch=1`** (one requirement per call). Batching corrupts scores; pass/fail is derived in code.
- **Local LLM only.** Judges/identifiers are agent_server presets (Gemma 4 E4B, `:7701`); embeddings + rerank run on llama-server (`:8500`). Presets never pick a model — the whole stack runs on the one active model.

---

## Using reqoach

There are two front doors — the interactive **app** and the **batch script**.

### The app (`reqoach`) — upload, watch live, browse

One container serves the entire UI + API + realtime streaming on one origin
(host `:7802`; public at `/reqoach/`):

- **Dashboard** ([frontend/index.html](frontend/index.html)) — the results viewer: C1–C9 radar,
  most-violated rules, score distribution, set-level panel, sortable requirements
  table with a per-requirement detail drawer. *Public.*
- **Ingestion** ([frontend/ingest.html](frontend/ingest.html)) — drag-drop a document → creates an
  async **job** → redirects to the live monitor. *Gated.*
- **Monitor** ([frontend/monitor.html](frontend/monitor.html)) — fills in live as the pipeline runs:
  stage strip, charts as running aggregates, and the requirements table appending
  each requirement the moment its 9 judges finish. *Gated.*
- **Live editor** ([frontend/editor.html](frontend/editor.html)) — assess a **single** requirement as
  you type: instant deterministic flags, then C1–C9 stream in (fast-lane first),
  then a suggested rewrite. *Gated.*

Everything streams over **socket.io** (job progress via `join`, live assessment
via `assess`).

### The batch script

Runs the whole pipeline for one document and writes a dashboard-ready scorecard:

```bash
python scripts/produce_scorecard.py <doc.pdf> frontend/data/scorecard_full.json
```

---

## Deploy

Four moving parts. The first three are this repo's `compose.yaml`; the LLM
backends are shared services.

| Service | Port | Role | Restart |
|---|---|---|---|
| **reqoach** | 7802 | single-container app: static UI + orchestration API + socket.io | `unless-stopped` |
| **ingest** | 5601 | GPU Docling service for PDF/DOCX/HTML/PPTX (markdown bypasses it) | `unless-stopped` |
| **agent_server** | 7701 | hosts the LLM presets (Gemma 4 E4B) | shared |
| **llama-server** | 8500 | bge-m3 embeddings + bge-reranker | shared |

```bash
docker compose up -d ingest reqoach     # build + run the two app containers
# reqoach: http://localhost:7802/   (public entry: the dashboard)
```

- **`reqoach`** ([Dockerfile.orchestration](Dockerfile.orchestration)) is a slim image (no Docling —
  markdown is parsed in-process, PDFs delegate to `ingest`). It uses
  `network_mode: host` so it binds `:7802` and reaches agent_server / llama-server
  / ingest on `localhost` with no rewiring. Persists jobs under `store/`.
- **`ingest`** bakes Docling's layout + TableFormer models offline (see below).

### Public routing & auth (via the logus2k.com reverse proxy)

The app is fronted at `/reqoach/`. Browsing finished results is **public**;
anything that drives the LLM is **gated** to a single Google identity:

| Public | Gated (Google sign-in) |
|---|---|
| `/reqoach/` dashboard | `/reqoach/ingest.html` (upload UI) |
| `GET /documents` (library) | `/reqoach/editor.html`, `/reqoach/monitor.html` |
| scorecard JSON | `POST /documents` (upload) |
|  | `/reqoach/socket.io/` (carries `assess` + `join`) |

Browser clients connect socket.io with a path derived from the mount point
(`io({path: base + "socket.io"})`) so they work at the root and under `/reqoach/`.

### Register the LLM presets (once, idempotent)

```bash
python scripts/register_agents.py          # identify/judge/refine/table/assembler
python scripts/register_incose_judges.py   # incose_c1_necessary … c9, set_judge, reviewer
```

---

## Components in detail

### 1 · Ingestion service (`ingest`, `:5601`)

A GPU FastAPI service turning a document into a normalized `SourceItem` stream
with provenance. Markdown is parsed directly; other formats go through Docling.

> **Bullet glyphs:** Docling emits Word/PDF symbol-font bullets as private-use
> glyphs (U+F0xx — renders blank). `docling_adapter._normalize_text` maps that
> block to `•` at ingestion.

**Prerequisite — download Docling models once** (image is built offline, COPYing
from `models/docling/`):

```bash
mkdir -p models/docling
docker run --rm -v "$PWD/models/docling:/out" reqqa-ingest:latest \
  python3.12 -c "from pathlib import Path; from docling.utils.model_downloader import download_models; \
download_models(output_dir=Path('/out'), progress=True, with_rapidocr=False, with_easyocr=False)"
```

~1.2 GB (layout-heron, TableFormer, CodeFormulaV2, figure classifier). OCR off by
default; enable with `with_rapidocr=True` + `DOCLING_OCR=1`. `page`/`bbox` are set
for PDFs; `char_span` for text sources — the provenance downstream grounding relies on.

### 2 · Segmentation

**identify** (chunked, LLM-only) → **gate** (a judge drops non-requirements and
refines through a bounded loop) → **assemble** (reassemble requirements split
across chunks by author ID) → **dedup** (reranker-based, length-guarded). Each
`DiscreteRequirement` carries provenance + lineage.

```bash
python scripts/segment_doc.py path/to/doc.pdf [--json]
```

### 3–5 · Scoring, set-level, review

9 LLM judges (C1–C9) + deterministic term-list rules from
[incose/catalog.json](incose/catalog.json) (42 rules R1–R42 + 15 characteristics).
Set-level (C10–C15) finds overlap candidates with the reranker, confirms with the
LLM, then runs the set judge. Requirements scoring ≤ 3 on any characteristic go to
the Reviewer. The INCOSE knowledge base lives in [incose/](incose/): `catalog.json`,
`rules/*.md`, `characteristics/*.md`, `judges/*.md` (static judge prompts).

Measured single-requirement latency (E4B, warm): deterministic ~3 ms · each judge
~0.5 s · fast-lane headline (C3·C4·C5·C7) ~2 s · full 9 ~4.5 s · + review ~5.5 s.

### 6 · Frontend

**Apache ECharts 6.1.0** (vendored), light + dark, self-contained. The dashboard
reads the producer's `scorecard_full.json`: on load `js/app.js` fetches
`data/index.json` (the document picker) then the selected scorecard. Add a document:

```bash
python scripts/produce_scorecard.py <doc.pdf> frontend/data/<name>.json
python scripts/build_dashboard_index.py     # rescan data/*.json -> data/index.json
```

`frontend/preview.html` is a single inlined build for sharing (opens on `file://`),
rebuilt with `python scripts/build_preview.py`.

---

## Orchestration API (`reqoach`, `:7802`)

The job body ([src/reqqa/jobs.py](src/reqqa/jobs.py)) runs the pipeline as an
event-emitting generator — a `requirement` event fires the moment its 9 judges
finish, so the monitor fills in live rather than waiting for the whole run. The
service ([src/reqqa/orchestration_api.py](src/reqqa/orchestration_api.py)) wraps it:

| Endpoint | Purpose |
|---|---|
| `POST /documents` | upload → store → async job (returns `job_id`, `doc_id`) — *gated* |
| `GET /jobs/{id}` · `/jobs/{id}/events` | job status / buffered event replay |
| `GET /documents` | library listing |
| `GET /documents/{id}/scorecard` | assembled scorecard JSON |
| socket.io `join {job_id}` | live event stream (with replay for late joiners) |
| socket.io `assess {text}` | live single-requirement assessment |

Produces the same scorecard shape as `produce_scorecard.py`, so the dashboard
consumes both unchanged.

**Not yet built:** the review-workflow endpoints (accept/edit rewrites → versioned
revisions, rescore) and a library UI with run comparison (spec §8.6 steps 5–6).

---

## Repository layout

```
src/reqqa/          ingest/ · segment/ · score/ · llm/ · api.py · assess.py
                    jobs.py (streaming job core) · orchestration_api.py (the reqoach app)
incose/             catalog.json · rules/ · characteristics/ · judges/
scripts/            register_agents · register_incose_judges · segment_doc
                    produce_scorecard · build_dashboard_index · build_preview
frontend/           index.html (dashboard) · ingest.html · monitor.html · editor.html
                    js/app.js · data/ · vendor/ (echarts, socket.io) · preview.html
specs/              technical_architecture.md · requirements_frontend.md
compose.yaml        ingest (GPU) + reqoach (app) services
Dockerfile          ingest image (Docling)
Dockerfile.orchestration   reqoach image (slim, no Docling)
```
