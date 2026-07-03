"""Complete scorecard producer: ingest -> segment -> per-requirement scoring
(9 judges + deterministic) -> reviewer (on defects) -> set-level, assembled into
one frontend-ready scorecard JSON.

Usage: python scripts/produce_scorecard.py <doc.pdf> <out.json>
"""
from __future__ import annotations

import json, os, sys, time, statistics, collections
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from reqqa.ingest.model import BlockType, SourceItem
from reqqa.segment.pipeline import segment_items
from reqqa.segment.gate import gate_requirements, ACCEPTED
from reqqa.score import check_requirement
from reqqa.score.characteristics import CHARACTERISTICS, normalize_rule_ids
from reqqa.score.setlevel import assess_set

INGEST = os.environ.get("INGEST_URL", "http://localhost:5601")
AGENT = os.environ.get("AGENT_SERVER_URL", "http://localhost:7701")
REVIEW_IF_MIN_SCORE_AT_MOST = 3      # run Reviewer when any characteristic <= this
WORKERS = 8


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _chat(model, content, timeout=90):
    r = httpx.post(f"{AGENT}/v1/chat/completions", timeout=timeout, json={
        "model": model, "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"}})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def ingest(path):
    with open(path, "rb") as f:
        r = httpx.post(f"{INGEST}/ingest", files={"file": (os.path.basename(path), f)}, timeout=900)
    r.raise_for_status()
    d = r.json()
    def mk(x):
        cs = x.get("char_span")
        return SourceItem(text=x["text"], block_type=BlockType(x["block_type"]),
                          section_path=x["section_path"], source_file=x["source_file"], order=x["order"],
                          page=x.get("page"), bbox=x.get("bbox"),
                          char_span=tuple(cs) if cs else None, heading_level=x.get("heading_level"))
    return [mk(x) for x in d["items"]]


def judge_one(args):
    """Score one requirement on one characteristic (batch=1)."""
    idx, cid, suffix, text = args
    try:
        a = _chat(f"incose_{suffix}", f"[0] {text}")["assessments"][0]
        return idx, cid, {"score": a.get("score"),
                          "rules_triggered": normalize_rule_ids(a.get("rules_triggered")),
                          "evidence": a.get("evidence", ""),
                          "justification": a.get("justification", "")}
    except Exception as e:
        return idx, cid, {"score": None, "error": str(e)}


def review_one(args):
    idx, req, ctx = args
    bundle = [f"REQUIREMENT: {req['text']}", f"\nSOURCE CONTEXT: {ctx}", "\nASSESSMENT:"]
    for cid, _, name in CHARACTERISTICS:
        a = req["characteristics"][cid]
        if a.get("score") and a["score"] < 5:
            bundle.append(f"  {cid} {name} score={a['score']} rules={a.get('rules_triggered')} :: {a.get('justification','')}")
    bundle.append("\nDETERMINISTIC FINDINGS:")
    for f in req["deterministic_findings"]:
        bundle.append(f"  {f['rule_id']} {f['name']}: {[m['term'] for m in f['matches']]}")
    try:
        r = _chat("incose_reviewer", "\n".join(bundle), timeout=120)
        return idx, {"rewrites": r.get("rewrites", []), "advisories": r.get("advisories", [])}
    except Exception as e:
        return idx, {"error": str(e)}


def main():
    path, out = sys.argv[1], sys.argv[2]
    t0 = time.time()
    log(f"ingesting {path}")
    items = ingest(path)
    log(f"ingested {len(items)} items; segmenting")
    reqs_all = segment_items(items)
    primaries = [r for r in reqs_all if r.duplicate_of is None]
    log(f"segment: {len(reqs_all)} ({len(primaries)} primary); gating")
    gated = gate_requirements(primaries, {it.order: it.text for it in items})
    accepted = [g.requirement for g in gated if g.disposition == ACCEPTED]
    src_by_order = {it.order: it.text for it in items}
    log(f"accepted {len(accepted)} requirements; scoring 9 judges (batch=1)")

    records = []
    for r in accepted:
        records.append({
            "req_id": r.req_id, "text": r.text,
            "provenance": {"source_file": r.provenance.source_file, "page": r.provenance.page,
                           "bbox": r.provenance.bbox, "section_path": r.provenance.section_path,
                           "char_span": list(r.provenance.char_span) if r.provenance.char_span else None},
            "lineage": {"origin": r.origin, "was_compound": r.was_compound,
                        "derived_from": r.derived_from, "duplicate_of": r.duplicate_of},
            "characteristics": {}, "deterministic_findings": [], "overall": None, "review": None,
            "_order": r.provenance.order,
        })

    tasks = [(i, cid, suffix, records[i]["text"]) for i in range(len(records))
             for cid, suffix, _ in CHARACTERISTICS]
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, cid, a in ex.map(judge_one, tasks):
            records[i]["characteristics"][cid] = a
            done += 1
            if done % 200 == 0: log(f"  judged {done}/{len(tasks)}")

    # deterministic + overall
    for rec in records:
        rec["deterministic_findings"] = [f.to_dict() for f in check_requirement(rec["text"])]
        vs = [rec["characteristics"][c].get("score") for c, _, _ in CHARACTERISTICS
              if rec["characteristics"][c].get("score")]
        rec["overall"] = round(statistics.mean(vs), 2) if vs else None

    # reviewer on defective requirements
    to_review = [i for i, rec in enumerate(records)
                 if any((rec["characteristics"][c].get("score") or 5) <= REVIEW_IF_MIN_SCORE_AT_MOST
                        for c, _, _ in CHARACTERISTICS)]
    log(f"reviewing {len(to_review)} defective requirements")
    rtasks = [(i, records[i], src_by_order.get(records[i]["_order"], records[i]["text"])) for i in to_review]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, rev in ex.map(review_one, rtasks):
            records[i]["review"] = rev

    log("set-level analysis")
    set_block = assess_set([{"id": r["req_id"], "text": r["text"]} for r in records])

    # aggregates
    per_char = {c: round(statistics.mean([r["characteristics"][c]["score"] for r in records
                if r["characteristics"][c].get("score")]), 2) for c, _, _ in CHARACTERISTICS}
    rule_counts = collections.Counter()
    for r in records:
        rs = set()
        for c, _, _ in CHARACTERISTICS: rs.update(r["characteristics"][c].get("rules_triggered") or [])
        for f in r["deterministic_findings"]: rs.add(f["rule_id"])
        for rid in rs: rule_counts[rid] += 1
    dist = collections.Counter(round(r["overall"]) for r in records if r["overall"])

    scorecard = {
        "source_file": os.path.basename(path),
        "produced_in_s": round(time.time() - t0),
        "requirements": [{k: v for k, v in r.items() if k != "_order"} for r in records],
        "set_level": set_block,
        "aggregates": {"per_characteristic_mean": per_char,
                       "per_rule_violation_count": dict(rule_counts.most_common()),
                       "score_distribution": dict(sorted(dist.items())),
                       "total": len(records)},
        "characteristic_names": {c: n for c, _, n in CHARACTERISTICS},
    }
    json.dump(scorecard, open(out, "w"), indent=1)
    log(f"DONE in {time.time()-t0:.0f}s -> {out}  ({len(records)} reqs, {len(to_review)} reviewed)")
    log(f"per-characteristic means: {per_char}")


if __name__ == "__main__":
    main()
