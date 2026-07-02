"""Component 2 pipeline: SourceItem stream → List[DiscreteRequirement].

chunk → LLM identify → deterministic verify → assign IDs + provenance.
"""

from __future__ import annotations

import logging
import re

from reqqa.ingest.model import SourceItem
from reqqa.llm.client import AgentServerClient
from reqqa.segment.chunker import chunk_items
from reqqa.segment.identify import identify_chunk
from reqqa.segment.model import DiscreteRequirement, Provenance
from reqqa.segment import verify

logger = logging.getLogger(__name__)

# Explicit requirement IDs authors use, e.g. [DEMO-SRS-53], REQ-001, PERF-002.
_ID_RE = re.compile(r"\[?\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b\]?")


def _extract_existing_id(text: str) -> str | None:
    m = _ID_RE.match(text.strip())
    if m:
        return m.group(1)
    # Also catch a bracketed id anywhere near the start.
    m2 = _ID_RE.search(text[:40])
    return m2.group(1) if m2 else None


def segment_items(
    items: list[SourceItem],
    client: AgentServerClient | None = None,
) -> list[DiscreteRequirement]:
    """Identify discrete requirements in an ingested item stream."""
    client = client or AgentServerClient()
    chunks = chunk_items(items)
    logger.info("segmenting %d items in %d chunks", len(items), len(chunks))

    requirements: list[DiscreteRequirement] = []
    seen: set[tuple[int, str]] = set()
    used_ids: set[str] = set()
    gen_counter = 0
    n_dropped_untraceable = 0

    def unique_id(base: str | None) -> str:
        nonlocal gen_counter
        if base:
            cand = base
            suffix = 0
            while cand in used_ids:
                suffix += 1
                cand = f"{base}-{chr(ord('a') + suffix - 1)}"
            used_ids.add(cand)
            return cand
        gen_counter += 1
        cand = f"REQ-{gen_counter:04d}"
        while cand in used_ids:
            gen_counter += 1
            cand = f"REQ-{gen_counter:04d}"
        used_ids.add(cand)
        return cand

    for chunk in chunks:
        for raw in identify_chunk(client, chunk):
            text = raw.text.strip()
            if not verify.is_valid_length(text):
                continue
            traceable, conf = verify.traceability(text, raw.source_item.text)
            if not traceable:
                n_dropped_untraceable += 1
                logger.debug("dropped untraceable: %r (src %r)", text[:60], raw.source_item.text[:60])
                continue
            key = verify.dedup_key(raw.source_item.order, text)
            if key in seen:
                continue
            seen.add(key)

            existing = _extract_existing_id(raw.source_item.text)
            req_id = unique_id(existing)
            src = raw.source_item
            requirements.append(DiscreteRequirement(
                req_id=req_id,
                text=text,
                provenance=Provenance(
                    source_file=src.source_file,
                    section_path=src.section_path,
                    order=src.order,
                    page=src.page,
                    bbox=src.bbox,
                    char_span=src.char_span,
                ),
                origin="derived" if raw.was_compound else "extracted",
                derived_from=existing if raw.was_compound else None,
                was_compound=raw.was_compound,
                identification_confidence=round(conf, 3),
            ))

    logger.info("identified %d requirements (dropped %d untraceable)",
                len(requirements), n_dropped_untraceable)
    return requirements
