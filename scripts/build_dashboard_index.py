"""Build frontend/data/index.json — the document list the dashboard's picker
reads. Scans every scorecard JSON in frontend/data/ (the producer's
scorecard_full.json format) and emits a compact index:

    [ { "file": "scorecard_full.json", "name": "<source_file>",
        "count": <#requirements>, "health": <overall mean> }, ... ]

Run after adding/replacing a scorecard:

    python scripts/build_dashboard_index.py
"""
from __future__ import annotations

import glob
import json
import os

DATA = os.path.join(os.path.dirname(__file__), "..", "frontend", "data")


def _summarize(path: str) -> dict | None:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    reqs = d.get("requirements")
    if not isinstance(reqs, list):
        return None  # not a scorecard
    agg = d.get("aggregates", {})
    health = agg.get("overall_health")
    if health is None:
        m = agg.get("per_characteristic_mean") or {}
        health = round(sum(m.values()) / len(m), 2) if m else None
    return {
        "file": os.path.basename(path),
        "name": d.get("source_file") or os.path.basename(path),
        "count": len(reqs),
        "health": health,
    }


def main() -> None:
    out = os.path.join(DATA, "index.json")
    docs = []
    for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        if os.path.basename(path) == "index.json":
            continue
        try:
            summary = _summarize(path)
        except (json.JSONDecodeError, OSError) as e:
            print(f"skip {os.path.basename(path)}: {e}")
            continue
        if summary:
            docs.append(summary)
            print(f"  + {summary['file']}  {summary['name']}  ({summary['count']} reqs, health {summary['health']})")
    # Best document first.
    docs.sort(key=lambda x: (x["health"] is None, -(x["health"] or 0)))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=1)
    print(f"wrote {out} ({len(docs)} document(s))")


if __name__ == "__main__":
    main()
