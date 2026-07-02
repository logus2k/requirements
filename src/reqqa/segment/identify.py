"""The LLM identification pass (spec §6.2).

For each chunk, ask the `requirement_identifier` preset which blocks are
requirements (splitting compounds), then map the returned local indices back to
their SourceItems. Compound detection is DERIVED here (multiple outputs sharing
one index) rather than trusted from the model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from reqqa.ingest.model import SourceItem
from reqqa.llm.client import AgentServerClient, LLMError
from reqqa.segment.chunker import Chunk
from reqqa.segment.prompts import IDENTIFIER_AGENT_NAME

logger = logging.getLogger(__name__)


@dataclass
class RawIdentification:
    """One requirement the LLM returned, mapped back to its source block."""

    source_item: SourceItem
    text: str
    was_compound: bool


def identify_chunk(client: AgentServerClient, chunk: Chunk) -> list[RawIdentification]:
    """Identify requirements in one chunk. Returns [] on LLM/parse failure
    (logged) so one bad chunk doesn't sink the whole document."""
    try:
        result = client.complete_json(IDENTIFIER_AGENT_NAME, chunk.render())
    except LLMError as e:
        logger.warning("identify_chunk failed: %s", e)
        return []

    reqs = result.get("requirements")
    if not isinstance(reqs, list):
        logger.warning("identify_chunk: 'requirements' missing/not a list: %r", result)
        return []

    # Group by source index to derive compound-ness (>1 output per index).
    by_index: dict[int, list[str]] = {}
    for r in reqs:
        if not isinstance(r, dict):
            continue
        idx = r.get("index")
        text = r.get("text")
        if not isinstance(idx, int) or not isinstance(text, str) or not text.strip():
            continue
        if 0 <= idx < len(chunk.items):
            by_index.setdefault(idx, []).append(text.strip())

    out: list[RawIdentification] = []
    for idx, texts in by_index.items():
        compound = len(texts) > 1
        for t in texts:
            out.append(RawIdentification(
                source_item=chunk.items[idx],
                text=t,
                was_compound=compound,
            ))
    return out
