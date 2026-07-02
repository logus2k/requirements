# Requirements Quality Analyzer

Ingest requirements documents, split them into discrete requirements, and score
each against INCOSE guidelines. See [specs/technical_architecture.md](specs/technical_architecture.md).

## Component 1 — Ingestion service

A GPU-enabled FastAPI service that turns a document (`.md`, `.pdf`, `.docx`,
`.html`/`.htm`, `.pptx`) into a normalized stream of `SourceItem`s with
provenance. Markdown is parsed directly; all other formats go through Docling.

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
- Ingestion does **not** decide what is a requirement — that is Component 2
  (segmentation).
