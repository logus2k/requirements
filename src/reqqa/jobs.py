"""Streaming assessment job — the pipeline as an event-emitting generator.

This is the job body behind the orchestration API (spec §8.5/§8.6 step 1). It
runs the same pipeline as `scripts/produce_scorecard.py` — ingest → segment →
gate → score → review → set-level — but instead of a batch `log()` it yields
**structured events** so a UI can fill in live:

  {"type":"stage", "stage":..., "status":"start"|"done", "done":k,"total":n,"message":...}
  {"type":"requirement", "data":{...full record...}}     one per req, the moment
                                                          its 9 judges finish
  {"type":"set_level", "data":{overlaps, set_assessment}}
  {"type":"aggregates", "data":{...}}                     final roll-up
  {"type":"scorecard", "data":{...}}                      the assembled scorecard
  {"type":"error", "stage":..., "message":...}

Scoring keeps the full (req × judge) thread pool for throughput, but tracks a
per-requirement completion counter so each requirement is finalized and emitted
as soon as all 9 of its judges return — no 20-minute blank wait. The assembled
scorecard is byte-for-byte the shape `produce_scorecard.py` wrote, so the
existing dashboard consumes it unchanged.
"""

from __future__ import annotations

import collections
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterator

import httpx

from reqqa.assess import _judge, _review
from reqqa.ingest import ingest_file
from reqqa.ingest.dispatch import MARKDOWN_EXTENSIONS
from reqqa.ingest.model import BlockType, SourceItem
from reqqa.llm.client import AgentServerClient
from reqqa.score import check_requirement
from reqqa.score.characteristics import CHARACTERISTICS
from reqqa.score.setlevel import assess_set
from reqqa.segment.gate import ACCEPTED, gate_requirements
from reqqa.segment.pipeline import segment_items

INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:5601")
REVIEW_IF_MIN_SCORE_AT_MOST = 3
WORKERS = 8


@dataclass
class JobOptions:
    review: bool = True          # run the Reviewer on defective requirements
    set_level: bool = True       # run C10–C15 set analysis
    workers: int = WORKERS


def _ingest(path: str) -> list[SourceItem]:
    # Markdown is structured text — parse it in-process (no Docling container),
    # matching the dispatch split. Binary formats go through the GPU service.
    ext = os.path.splitext(path)[1].lower()
    if ext in MARKDOWN_EXTENSIONS:
        return ingest_file(path, source_file=os.path.basename(path)).items

    with open(path, "rb") as f:
        r = httpx.post(f"{INGEST_URL}/ingest",
                       files={"file": (os.path.basename(path), f)}, timeout=900)
    r.raise_for_status()
    d = r.json()

    def mk(x: dict) -> SourceItem:
        cs = x.get("char_span")
        return SourceItem(
            text=x["text"], block_type=BlockType(x["block_type"]),
            section_path=x["section_path"], source_file=x["source_file"],
            order=x["order"], page=x.get("page"), bbox=x.get("bbox"),
            char_span=tuple(cs) if cs else None, heading_level=x.get("heading_level"))

    return [mk(x) for x in d["items"]]


def _record(req) -> dict:
    """Empty per-requirement record in the scorecard shape."""
    p = req.provenance
    return {
        "req_id": req.req_id, "text": req.text,
        "provenance": {"source_file": p.source_file, "page": p.page, "bbox": p.bbox,
                       "section_path": p.section_path,
                       "char_span": list(p.char_span) if p.char_span else None},
        "lineage": {"origin": req.origin, "was_compound": req.was_compound,
                    "derived_from": req.derived_from, "duplicate_of": req.duplicate_of},
        "characteristics": {}, "deterministic_findings": [],
        "overall": None, "review": None, "_order": p.order,
    }


def _finalize_scores(rec: dict) -> None:
    rec["deterministic_findings"] = [f.to_dict() for f in check_requirement(rec["text"])]
    vs = [rec["characteristics"][c].get("score") for c, _, _ in CHARACTERISTICS
          if rec["characteristics"][c].get("score")]
    rec["overall"] = round(statistics.mean(vs), 2) if vs else None


def _needs_review(rec: dict) -> bool:
    return any((rec["characteristics"][c].get("score") or 5) <= REVIEW_IF_MIN_SCORE_AT_MOST
               for c, _, _ in CHARACTERISTICS)


def _aggregates(records: list[dict]) -> dict:
    per_char = {}
    for c, _, _ in CHARACTERISTICS:
        vs = [r["characteristics"][c]["score"] for r in records
              if r["characteristics"].get(c, {}).get("score")]
        if vs:
            per_char[c] = round(statistics.mean(vs), 2)
    rule_counts: collections.Counter = collections.Counter()
    for r in records:
        rs: set[str] = set()
        for c, _, _ in CHARACTERISTICS:
            rs.update(r["characteristics"].get(c, {}).get("rules_triggered") or [])
        for f in r["deterministic_findings"]:
            rs.add(f["rule_id"])
        for rid in rs:
            rule_counts[rid] += 1
    dist = collections.Counter(round(r["overall"]) for r in records if r["overall"])
    return {"per_characteristic_mean": per_char,
            "per_rule_violation_count": dict(rule_counts.most_common()),
            "score_distribution": dict(sorted(dist.items())),
            "total": len(records)}


def iter_job(path: str, options: JobOptions | None = None,
             client: AgentServerClient | None = None) -> Iterator[dict]:
    """Run the full pipeline for one document, yielding events as it goes."""
    opts = options or JobOptions()
    client = client or AgentServerClient()
    t0 = time.time()
    source_file = os.path.basename(path)

    # 1. Ingest
    yield {"type": "stage", "stage": "ingest", "status": "start"}
    items = _ingest(path)
    yield {"type": "stage", "stage": "ingest", "status": "done",
           "done": len(items), "total": len(items), "message": f"{len(items)} items"}

    # 2. Segment
    yield {"type": "stage", "stage": "segment", "status": "start"}
    reqs_all = segment_items(items, client=client)
    primaries = [r for r in reqs_all if r.duplicate_of is None]
    yield {"type": "stage", "stage": "segment", "status": "done",
           "done": len(primaries), "total": len(reqs_all),
           "message": f"{len(reqs_all)} identified, {len(primaries)} primary"}

    # 3. Gate
    yield {"type": "stage", "stage": "gate", "status": "start"}
    src_by_order = {it.order: it.text for it in items}
    gated = gate_requirements(primaries, src_by_order, client=client)
    accepted = [g.requirement for g in gated if g.disposition == ACCEPTED]
    yield {"type": "stage", "stage": "gate", "status": "done",
           "done": len(accepted), "total": len(primaries),
           "message": f"{len(accepted)} accepted"}

    # 4. Score — full (req × judge) pool, but emit each requirement the moment
    #    all 9 of its judges have returned.
    records = [_record(r) for r in accepted]
    n = len(records)
    total_tasks = n * len(CHARACTERISTICS)
    remaining = [len(CHARACTERISTICS)] * n
    yield {"type": "stage", "stage": "score", "status": "start",
           "done": 0, "total": total_tasks}

    completed_reqs = 0
    done_tasks = 0
    with ThreadPoolExecutor(max_workers=opts.workers) as ex:
        fut_meta = {ex.submit(_judge, client, cid, suffix, records[i]["text"]): (i, cid)
                    for i in range(n)
                    for cid, suffix, _ in CHARACTERISTICS}
        for fut in as_completed(fut_meta):
            i, cid = fut_meta[fut]
            records[i]["characteristics"][cid] = fut.result()
            done_tasks += 1
            remaining[i] -= 1
            if remaining[i] == 0:
                _finalize_scores(records[i])
                completed_reqs += 1
                rec = {k: v for k, v in records[i].items() if k != "_order"}
                yield {"type": "requirement", "data": rec,
                       "scored": completed_reqs, "total": n}
    yield {"type": "stage", "stage": "score", "status": "done",
           "done": total_tasks, "total": total_tasks,
           "message": f"{n} requirements scored"}

    # 5. Review (defective only)
    if opts.review:
        to_review = [i for i in range(n) if _needs_review(records[i])]
        yield {"type": "stage", "stage": "review", "status": "start",
               "done": 0, "total": len(to_review)}
        reviewed = 0
        with ThreadPoolExecutor(max_workers=opts.workers) as ex:
            fut_i = {ex.submit(_review, client, records[i]["text"],
                               [records[i]["characteristics"][c] for c, _, _ in CHARACTERISTICS],
                               records[i]["deterministic_findings"]): i
                     for i in to_review}
            for fut in as_completed(fut_i):
                i = fut_i[fut]
                records[i]["review"] = fut.result()
                reviewed += 1
                yield {"type": "review_result", "req_id": records[i]["req_id"],
                       "data": records[i]["review"], "done": reviewed, "total": len(to_review)}
        yield {"type": "stage", "stage": "review", "status": "done",
               "done": len(to_review), "total": len(to_review)}

    # 6. Set-level (needs the whole set)
    set_block = {"overlaps": [], "set_assessment": []}
    if opts.set_level:
        yield {"type": "stage", "stage": "set_level", "status": "start"}
        set_block = assess_set([{"id": r["req_id"], "text": r["text"]} for r in records],
                               client=client)
        yield {"type": "set_level", "data": set_block}
        yield {"type": "stage", "stage": "set_level", "status": "done",
               "message": f"{len(set_block.get('overlaps', []))} overlaps"}

    # 7. Assemble the scorecard (same shape produce_scorecard.py writes)
    aggregates = _aggregates(records)
    yield {"type": "aggregates", "data": aggregates}
    scorecard = {
        "source_file": source_file,
        "produced_in_s": round(time.time() - t0),
        "requirements": [{k: v for k, v in r.items() if k != "_order"} for r in records],
        "set_level": set_block,
        "aggregates": aggregates,
        "characteristic_names": {c: name for c, _, name in CHARACTERISTICS},
    }
    yield {"type": "scorecard", "data": scorecard}


def run_job(path: str, emit: Callable[[dict], None] | None = None,
            options: JobOptions | None = None,
            client: AgentServerClient | None = None) -> dict:
    """Run the job to completion, forwarding each event to `emit`, and return
    the assembled scorecard. Convenience wrapper over `iter_job` for callers
    that want a callback + final result rather than a generator."""
    scorecard: dict = {}
    for event in iter_job(path, options=options, client=client):
        if event.get("type") == "scorecard":
            scorecard = event["data"]
        if emit is not None:
            emit(event)
    return scorecard
