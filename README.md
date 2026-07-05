# Requirements Quality Analyzer (reqqa)

Ingest a requirements document, split it into discrete requirements, score each
against the **INCOSE Guide to Writing Requirements (GtWR v4, INCOSE-TP-2010-006-04)**,
propose fixes for the weak ones, and visualize the whole set.

Pipeline: **ingest → segment → score → review → visualize**.

Design docs: [specs/technical_architecture.md](specs/technical_architecture.md)
and [specs/requirements_frontend.md](specs/requirements_frontend.md).

## Architecture at a glance

| Stage | Where | What it does |
|-------|-------|--------------|
| **1 · Ingest** | [src/reqqa/ingest/](src/reqqa/ingest/) + `POST /ingest` (Docker) | Document → normalized `SourceItem`s with provenance |
| **2 · Segment** | [src/reqqa/segment/](src/reqqa/segment/) | LLM identifies discrete requirements (identify → gate → assemble → dedup) |
| **3 · Score** | [src/reqqa/score/](src/reqqa/score/) | 9 per-characteristic LLM judges (C1–C9) + deterministic term rules |
| **4 · Set-level** | [src/reqqa/score/setlevel.py](src/reqqa/score/setlevel.py) | C10–C15 over the whole set (reranker overlap → LLM confirm → set judge) |
| **5 · Review** | [incose/judges/reviewer.md](incose/judges/reviewer.md) | Proposes rewrites/advisories for defective requirements |
| **6 · Visualize** | [frontend/](frontend/) | ECharts 6.1.0 dashboard (radar, rule bar, distribution, set-level, table) |

Key design decisions:
- **The LLM is the sole requirement identifier — no regex.** Requirements are
  written too many ways to intercept structurally.
- **Judges score on a 1–5 scale, `batch=1`** (one requirement per call). Batching
  corrupts scores; the binary pass/fail is derived in code.
- **Local LLM only.** Judges/identifiers are agent_server presets (Gemma 4 E4B,
  `:7701`); embeddings + rerank run on llama-server (`:8500`).

## Dependencies

- **Ingestion service** — Docker + NVIDIA container toolkit (GPU Docling).
- **agent_server** (`:7701`) — hosts the LLM presets. Register them once with the
  scripts below.
- **llama-server** (`:8500`) — bge-m3 embeddings + bge-reranker, used by set-level
  overlap detection and segmentation dedup.

## Component 1 — Ingestion service

A GPU-enabled FastAPI service that turns a document (`.md`, `.pdf`, `.docx`,
`.html`/`.htm`, `.pptx`) into a normalized stream of `SourceItem`s with
provenance. Markdown is parsed directly; all other formats go through Docling.

> **Bullet glyphs:** Docling emits Word/PDF symbol-font bullets as private-use
> glyphs (U+F0xx, e.g. U+F0B7 — renders blank). `docling_adapter._normalize_text`
> maps that block to `•` at ingestion so downstream text is clean.

### Prerequisite: download Docling models locally (once)

The image is built **offline** — it COPYs Docling's layout + TableFormer models
from `models/docling/` rather than downloading them at build time. Populate that
folder once (requires the image to exist, or any Docling install):

```bash
mkdir -p models/docling
docker run --rm -v "$PWD/models/docling:/out" reqqa-ingest:latest \
  python3.12 -c "from pathlib import Path; from docling.utils.model_downloader import download_models; \
download_models(output_dir=Path('/out'), progress=True, with_rapidocr=False, with_easyocr=False)"
```

This writes ~1.2 GB (layout-heron, TableFormer, CodeFormulaV2, figure
classifier). OCR models are skipped; enable OCR by re-downloading with
`with_rapidocr=True` and setting `DOCLING_OCR=1`.

### Build & run

```bash
docker compose build ingest
docker compose up -d ingest
curl -s http://localhost:5601/health
```

### Ingest a file

```bash
curl -s -X POST http://localhost:5601/ingest -F "file=@path/to/doc.pdf" | jq
```

Response: `{ source_file, format, item_count, items: [ { text, block_type,
section_path, source_file, order, page, bbox, char_span, heading_level } ] }`.

### Notes

- GPU: requires the NVIDIA container toolkit (see `compose.yaml`). The service
  loads Docling's torch models on GPU.
- `page`/`bbox` are populated for paginated sources (PDF); `char_span` is
  populated for text sources (Markdown). This is the provenance downstream
  span-grounding relies on.
- Ingestion does **not** decide what is a requirement — that is Component 2.

## Component 2 — Segmentation

The LLM identifies discrete requirements from the ingested item stream:
**identify** (chunked, LLM-only) → **gate** (a judge drops non-requirements and
refines through a bounded loop) → **assemble** (reassemble requirements split
across chunks by author ID) → **dedup** (reranker-based, with a length guard).
Each `DiscreteRequirement` carries provenance and lineage.

```bash
# ingest + segment one document, print identified requirements
python scripts/segment_doc.py path/to/doc.pdf [--json]
```

## Components 3–5 — Scoring, set-level, review

Per-requirement scoring runs 9 LLM judges (one per individual characteristic
C1–C9) plus deterministic term-list rules from [incose/catalog.json](incose/catalog.json)
(42 rules R1–R42 + 15 characteristics). Set-level (C10–C15) finds overlap
candidates with the reranker, confirms them with the LLM, then runs the set
judge. Defective requirements (any characteristic ≤ 3) go to the Reviewer for
suggested rewrites/advisories.

The INCOSE knowledge base lives in [incose/](incose/): `catalog.json`,
`rules/*.md`, `characteristics/*.md`, and `judges/*.md` (the **static**
per-characteristic judge prompts — no runtime assembly).

### Register the LLM presets (once, idempotent)

```bash
python scripts/register_agents.py          # identify/judge/refine/table/assembler
python scripts/register_incose_judges.py   # incose_c1_necessary … c9, set_judge, reviewer
```

### Produce a full scorecard

Runs the whole pipeline end to end and writes a frontend-ready JSON:

```bash
python scripts/produce_scorecard.py <doc.pdf> frontend/data/scorecard_full.json
```

Env overrides: `INGEST_URL` (`:5601`), `AGENT_SERVER_URL` (`:7701`).

## Component 6 — Frontend dashboard

Dashboard in [frontend/](frontend/) using **Apache ECharts 6.1.0** (vendored),
with light and dark themes. Shows the C1–C9 characteristic radar (fill colored by
the achieved score), most-violated rules, score distribution, set-level bar with
an overlaps side panel, and a sortable requirements table; clicking a row opens a
detail drawer (per-requirement radar, per-characteristic evidence, provenance,
and reviewer suggestions). A **document picker** in the header switches between
scorecards.

### Run it in a container

```bash
docker compose up -d dashboard          # nginx, serves frontend/ on :5602
# open http://localhost:5602
```

The dashboard consumes the producer's `scorecard_full.json` format directly. On
load, `js/app.js` fetches `data/index.json` (the document list), populates the
picker, and fetches the selected scorecard.

**To add a document** to the picker:

```bash
python scripts/produce_scorecard.py <doc.pdf> frontend/data/<name>.json
python scripts/build_dashboard_index.py     # rescan data/*.json -> data/index.json
# refresh the browser (nginx serves data/ with no-cache)
```

### Self-contained build (for sharing / Artifact)

`frontend/preview.html` is a single self-contained file with echarts, one
scorecard, and app.js inlined — no server needed (opens on `file://`). It runs in
single-document mode (picker hidden). Rebuild after frontend changes:

```bash
python scripts/build_preview.py [data/<scorecard>.js]   # default data/scorecard.js
```

The full **lifecycle app** (drag-drop ingest → streamed live progress → review
workflow → document library) is specified in
[specs/requirements_frontend.md](specs/requirements_frontend.md) §8 but not yet
built — it needs an orchestration API (background jobs + SSE).

## Real-time single-requirement assessor

An interactive editor that assesses **one** requirement as you type — distinct
from `produce_scorecard.py`, which batches a whole document. There is no ingest or
segmentation (you write the requirement) and no set-level scoring (that needs the
whole set); it reuses the same deterministic rules, the 9 C1–C9 judge presets, and
the reviewer.

Two tiers, matched to latency measured on the active model (**E4B**, warm):

| Tier | What runs | Latency |
|------|-----------|---------|
| **Instant** (per keystroke) | deterministic term/symbol rules | ~3 ms |
| **Debounced** (on pause) | 9 C1–C9 judges, **fast-lane C3·C4·C5·C7 first**, then the reviewer | ~0.5 s/judge · ~2 s headline · ~4.5 s full · ~5.5 s + review |

Results **stream** as each judge returns (the single GPU serializes them, so
first-score-in-~0.5s beats waiting for a batch), and a new keystroke cancels the
in-flight assessment. Transport is **socket.io**.

> **Model note:** agent_server presets never select a model — they all run on the
> single *active* chat model (E4B today). Faster judging can't come from a smaller
> model per-preset; the only levers are streaming, the fast-lane subset, and
> deferring the reviewer (see `agent_server/documents/how_to.md`).

Core (`src/reqqa/assess.py`) is transport-agnostic: `assess_requirement()` (full,
one shot), `iter_assessment()` (streamed events), `review_requirement()` (deferred
reviewer). The server (`src/reqqa/realtime.py`) serves the editor page and streams
over socket.io.

```bash
PYTHONPATH=src uvicorn reqqa.realtime:asgi --port 7801
# open http://localhost:7801/
```

Requires `agent_server` (`:7701`) with the INCOSE presets registered (see above)
and `llama-server` (`:8500`).

## Repository layout

```
src/reqqa/          ingest/ · segment/ · score/ · llm/ · api.py · assess.py · realtime.py
incose/             catalog.json · rules/ · characteristics/ · judges/
scripts/            register_agents · register_incose_judges · segment_doc · produce_scorecard
frontend/           index.html · js/app.js · editor.html · data/ · vendor/ (echarts, socket.io) · preview.html
specs/              technical_architecture.md · requirements_frontend.md
compose.yaml        ingest service (GPU)
```
