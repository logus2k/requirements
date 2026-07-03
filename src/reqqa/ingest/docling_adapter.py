"""Docling ingestion path for binary/structured formats (.pdf/.docx/.html/.pptx).

We deliberately do NOT use Docling's `HybridChunker`: it is a retrieval chunker
(`merge_peers=True` bags whole lists into one chunk), which is the opposite of
what segmentation needs. Instead we walk the `DoclingDocument` tree item by item
with `iterate_items()`, map each `DocItemLabel` to our normalized `BlockType`,
and carry page/bbox provenance.

Docling and its heavy models are imported lazily so this module (and the
Markdown path) import cleanly in environments where Docling isn't installed.
"""

from __future__ import annotations

import logging
import os

from reqqa.ingest.model import BlockType, IngestResult, SourceItem

logger = logging.getLogger(__name__)

_converter = None


def _normalize_text(s: str) -> str:
    """Normalize symbol-font artifacts. Docling emits Word/PDF symbol-font bullets
    as private-use glyphs in the U+F000–U+F0FF remap block (e.g. U+F0B7, which
    renders blank downstream and reads as stray spaces). Map that whole block to a
    real bullet '•' so the ingested text is clean for scoring, review, and display."""
    if not s:
        return s
    return "".join("•" if 0xF000 <= ord(c) <= 0xF0FF else c for c in s)


def _label_to_block_type(label) -> BlockType:
    """Map a Docling `DocItemLabel` to our normalized vocabulary."""
    # Imported here so module import doesn't require docling_core.
    from docling_core.types.doc import DocItemLabel

    name = getattr(label, "value", None) or str(label)
    mapping = {
        DocItemLabel.TITLE: BlockType.HEADING,
        DocItemLabel.SECTION_HEADER: BlockType.HEADING,
        DocItemLabel.LIST_ITEM: BlockType.LIST_ITEM,
        DocItemLabel.TABLE: BlockType.TABLE,
        DocItemLabel.PICTURE: BlockType.PICTURE,
        DocItemLabel.CAPTION: BlockType.CAPTION,
        DocItemLabel.CODE: BlockType.CODE,
        DocItemLabel.FORMULA: BlockType.CODE,
        DocItemLabel.DOCUMENT_INDEX: BlockType.TOC,
        DocItemLabel.TEXT: BlockType.PARAGRAPH,
        DocItemLabel.PARAGRAPH: BlockType.PARAGRAPH,
        DocItemLabel.FOOTNOTE: BlockType.PARAGRAPH,
        DocItemLabel.REFERENCE: BlockType.PARAGRAPH,
    }
    return mapping.get(label, BlockType.OTHER)


def _first_prov(item) -> tuple[int | None, list[float] | None]:
    """Extract (page_no, bbox) from a Docling item's first provenance entry."""
    provs = getattr(item, "prov", None) or []
    if not provs:
        return None, None
    p = provs[0]
    page_no = getattr(p, "page_no", None)
    bb = getattr(p, "bbox", None)
    bbox = None
    if bb is not None:
        try:
            bbox = [float(v) for v in bb.as_tuple()]
        except Exception:
            bbox = None
    return (int(page_no) if page_no is not None else None), bbox


def _build_converter():
    """Lazily construct a Docling `DocumentConverter` for all supported formats.

    Honors two env vars, matching the pattern proven in the noted graph service:
      DOCLING_ARTIFACTS_PATH  local model-cache dir (avoids re-downloading
                              layout/TableFormer weights on every rebuild)
      DOCLING_OCR             "1"/"true" to enable OCR (default off)
    """
    global _converter
    if _converter is not None:
        return _converter

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    artifacts_path = os.environ.get("DOCLING_ARTIFACTS_PATH") or None
    if artifacts_path and not os.path.isdir(artifacts_path):
        logger.warning("DOCLING_ARTIFACTS_PATH %s not a dir; ignoring", artifacts_path)
        artifacts_path = None
    do_ocr = os.environ.get("DOCLING_OCR", "").lower() in ("1", "true", "yes")

    pdf_opts = PdfPipelineOptions(do_ocr=do_ocr, artifacts_path=artifacts_path)

    _converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.PPTX,
            InputFormat.HTML,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
        },
    )
    logger.info("Docling converter built (ocr=%s artifacts=%s)", do_ocr, artifacts_path)
    return _converter


def parse_with_docling(abs_path: str, source_file: str) -> IngestResult:
    """Convert a binary/structured document into normalized `SourceItem`s."""
    from docling_core.types.doc import DocItemLabel

    converter = _build_converter()
    result = converter.convert(abs_path)
    doc = result.document  # DoclingDocument

    items: list[SourceItem] = []
    heading_stack: list[tuple[int, str]] = []  # (tree level, title)
    order = 0

    def section_path() -> str:
        return " > ".join(t for _, t in heading_stack) or "(root)"

    for node, level in doc.iterate_items():
        label = getattr(node, "label", None)
        if label is None:
            continue
        block_type = _label_to_block_type(label)

        # Extract text: tables render to markdown to preserve structure.
        if label == DocItemLabel.TABLE:
            try:
                text = node.export_to_markdown(doc)
            except Exception as e:
                logger.warning("table export failed: %s", e)
                text = ""
        else:
            text = (getattr(node, "text", None) or "")
        text = _normalize_text(text).strip()

        # Maintain the heading stack for section_path. `level` is the item's
        # depth in the doc tree; Docling's PDF backend sometimes flattens
        # heading levels (a known limitation — ancestry reconstruction from
        # positional cues is a planned enhancement, see spec §5).
        if block_type == BlockType.HEADING and text:
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))

        if not text:
            continue

        page_no, bbox = _first_prov(node)
        items.append(SourceItem(
            text=text,
            block_type=block_type,
            section_path=section_path(),
            source_file=source_file,
            order=order,
            page=page_no,
            bbox=bbox,
            char_span=None,  # binary source: char offset not meaningful
            heading_level=level if block_type == BlockType.HEADING else None,
        ))
        order += 1

    return IngestResult(source_file=source_file, format="docling", items=items)
