"""Drive Component 1 + 2 on a real document.

Ingests a file through the ingest service (HTTP), reconstructs the SourceItem
stream, then runs the segmentation pipeline (LLM identification) and prints the
identified requirements.

    python scripts/segment_doc.py path/to/doc.pdf [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from reqqa.ingest.model import BlockType, SourceItem
from reqqa.segment.pipeline import segment_items
from reqqa.segment.judge import judge_requirements
from reqqa.segment.gate import gate_requirements, ACCEPTED, DROPPED, ESCALATED

INGEST_URL = os.environ.get("INGEST_URL", "http://localhost:5601")


def _item_from_dict(d: dict) -> SourceItem:
    cs = d.get("char_span")
    return SourceItem(
        text=d["text"],
        block_type=BlockType(d["block_type"]),
        section_path=d["section_path"],
        source_file=d["source_file"],
        order=d["order"],
        page=d.get("page"),
        bbox=d.get("bbox"),
        char_span=tuple(cs) if cs else None,
        heading_level=d.get("heading_level"),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true", help="dump full requirement JSON")
    ap.add_argument("--judge", action="store_true", help="run the precision judge over the result")
    ap.add_argument("--gate", action="store_true", help="run the full approval gate (judge + refine loop)")
    args = ap.parse_args()

    t0 = time.time()
    with open(args.path, "rb") as f:
        r = httpx.post(f"{INGEST_URL}/ingest", files={"file": (os.path.basename(args.path), f)}, timeout=600)
    r.raise_for_status()
    ing = r.json()
    items = [_item_from_dict(d) for d in ing["items"]]
    t_ing = time.time() - t0
    print(f"ingest: {ing['format']} | {len(items)} items | {t_ing:.1f}s")

    t1 = time.time()
    reqs = segment_items(items)
    t_seg = time.time() - t1
    print(f"segment: {len(reqs)} requirements | {t_seg:.1f}s")

    compound = sum(1 for x in reqs if x.was_compound)
    with_id = sum(1 for x in reqs if not x.req_id.startswith("REQ-"))
    print(f"  compound-derived: {compound} | with existing IDs: {with_id}")
    print("-" * 72)
    if args.json:
        print(json.dumps([x.to_dict() for x in reqs], indent=2))
    else:
        for x in reqs[:25]:
            p = x.provenance
            print(f"[{x.req_id}] p{p.page} conf={x.identification_confidence} "
                  f"{'(compound)' if x.was_compound else ''}")
            print(f"    {x.text[:95]}")

    if args.judge:
        t2 = time.time()
        verdicts = judge_requirements(reqs)
        t_judge = time.time() - t2
        from collections import Counter
        tally = Counter(v.verdict for v in verdicts)
        n = len(verdicts) or 1
        print("=" * 72)
        print(f"JUDGE ({t_judge:.1f}s): "
              f"requirement={tally['requirement']} "
              f"not_requirement={tally['not_requirement']} "
              f"uncertain={tally['uncertain']}")
        prec = tally["requirement"] / n
        print(f"  precision (confirmed / total) = {prec:.0%}  "
              f"[uncertain excluded from numerator]")
        print("-" * 72)
        print("Non-requirements + uncertain (the interesting calls):")
        for v in verdicts:
            if v.verdict != "requirement":
                print(f"  [{v.req_id}] {v.verdict.upper()}")
                print(f"      req:  {v.text[:85]}")
                print(f"      why:  {v.justification[:160]}")

    if args.gate:
        from collections import Counter
        source_by_order = {it.order: it.text for it in items}
        t3 = time.time()
        gated = gate_requirements(reqs, source_by_order)
        t_gate = time.time() - t3
        tally = Counter(g.disposition for g in gated)
        n = len(gated) or 1
        print("=" * 72)
        print(f"GATE ({t_gate:.1f}s over {len(gated)} candidates): "
              f"accepted={tally[ACCEPTED]} dropped={tally[DROPPED]} escalated={tally[ESCALATED]}")
        print(f"  accepted / total = {tally[ACCEPTED] / n:.0%}")
        looped = [g for g in gated if len(g.rounds) > 1]
        print(f"  entered refine loop: {len(looped)} "
              f"(→ {sum(1 for g in looped if g.disposition == ACCEPTED)} rescued, "
              f"{sum(1 for g in looped if g.disposition == DROPPED)} dropped, "
              f"{sum(1 for g in looped if g.disposition == ESCALATED)} escalated)")
        print("-" * 72)
        print("Refine-loop trajectories:")
        for g in looped:
            print(f"  [{g.requirement.req_id}] → {g.disposition.upper()}: {g.reason[:120]}")
            for r in g.rounds:
                print(f"      {r.role:8} {r.outcome:16} {(r.text_after or '')[:70]!r}")


if __name__ == "__main__":
    main()
