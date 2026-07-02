"""FastAPI ingest service — Component 1's HTTP surface.

Endpoints
---------
GET  /health         liveness probe.
POST /ingest         multipart file upload → normalized item stream (JSON).

The service is intentionally thin: it validates the extension, writes the upload
to a temp file, dispatches to the right ingestion path, and returns the
`IngestResult` as JSON. No requirement logic here — that is Component 2.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile

from reqqa.ingest import SUPPORTED_EXTENSIONS, ingest_file
from reqqa.ingest.dispatch import UnsupportedFormatError

app = FastAPI(title="reqqa-ingest", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "supported_extensions": sorted(SUPPORTED_EXTENSIONS)}


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported extension {ext!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    # Persist to a temp file so Docling (which reads from a path) can consume it.
    suffix = ext or ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            result = ingest_file(tmp_path, source_file=filename)
        except UnsupportedFormatError as e:
            raise HTTPException(status_code=415, detail=str(e))
        except Exception as e:  # noqa: BLE001 — surface parse failures as 422
            raise HTTPException(status_code=422, detail=f"ingestion failed: {e}")
        return result.to_dict()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
