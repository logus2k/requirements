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

## Component 6 — Frontend

Self-contained dashboard in [frontend/](frontend/) using **Apache ECharts 6.1.0**
(vendored), with light and dark themes. Shows the C1–C9 characteristic radar,
most-violated rules, score distribution, set-level bar with an overlaps side
panel, and a sortable requirements table; clicking a row opens a detail drawer
(per-requirement radar, per-characteristic evidence, provenance, and reviewer
suggestions).

Open `frontend/index.html` (reads `frontend/data/scorecard.js`), or the inlined
single-file build `frontend/preview.html`.

The full **lifecycle app** (drag-drop ingest → streamed live progress → review
workflow → document library) is specified in
[specs/requirements_frontend.md](specs/requirements_frontend.md) §8 but not yet
built — it needs an orchestration API (background jobs + SSE).

## Repository layout

```
src/reqqa/          ingest/ · segment/ · score/ · llm/ · api.py
incose/             catalog.json · rules/ · characteristics/ · judges/
scripts/            register_agents · register_incose_judges · segment_doc · produce_scorecard
frontend/           index.html · js/app.js · data/ · vendor/echarts.min.js · preview.html
specs/              technical_architecture.md · requirements_frontend.md
compose.yaml        ingest service (GPU)
```
