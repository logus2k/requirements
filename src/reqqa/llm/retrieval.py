"""Embedding + reranking access via the local llama-server.

Embeddings (bge-m3) and reranking (bge-reranker) are served by llama-server
(NOT agent_server) at LLAMA_SERVER_URL, OpenAI-style `/v1/embeddings` and the
llama.cpp `/v1/rerank` endpoint. Mirrors noted-rag's rag_service.

For overview-dedup we only need the reranker: raw cosine similarity does not
separate a summary from a merely-related requirement in an SRS (everything is
topically similar), whereas the reranker scores true subsumption ~0.95 vs <0.05.
"""

from __future__ import annotations

import math
import os

import httpx

LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "http://localhost:8500")
EMBED_MODEL = os.environ.get("EMBED_MODEL_NAME", "bge-m3")
RERANK_MODEL = os.environ.get("RERANK_MODEL_NAME", "bge-reranker")


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def rerank(query: str, documents: list[str], timeout: float = 60.0) -> list[float]:
    """Return one 0-1 relevance score per document, in INPUT order.

    llama-server returns raw logits with an `index` per result; we sigmoid them
    (same as noted-rag) so a fixed threshold is meaningful.
    """
    if not documents:
        return []
    r = httpx.post(
        f"{LLAMA_SERVER_URL}/v1/rerank",
        json={"model": RERANK_MODEL, "query": query, "documents": documents},
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    results = body.get("results") or body.get("data") or []
    scored = [0.0] * len(documents)
    for item in results:
        idx = int(item.get("index", 0))
        raw = item.get("relevance_score", item.get("score", 0.0))
        if 0 <= idx < len(scored):
            scored[idx] = _sigmoid(float(raw))
    return scored


def embed(texts: list[str], timeout: float = 120.0) -> list[list[float]]:
    """L2-normalized dense embeddings (bge-m3). Kept for future cross-document
    work; overview-dedup uses rerank(), not this."""
    if not texts:
        return []
    r = httpx.post(
        f"{LLAMA_SERVER_URL}/v1/embeddings",
        json={"model": EMBED_MODEL, "input": list(texts)},
        timeout=timeout,
    )
    r.raise_for_status()
    entries = sorted(r.json().get("data", []), key=lambda e: int(e.get("index", 0)))
    out: list[list[float]] = []
    for e in entries:
        v = e["embedding"]
        if v and isinstance(v[0], (list, tuple)):
            v = v[0]
        n = math.sqrt(sum(x * x for x in v))
        out.append([x / n for x in v] if n > 0 else list(v))
    return out
