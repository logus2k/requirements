# reqqa — Assessment Notes

Observations from a code walkthrough (2026-07-03). For discussion — nothing here is
a blocking defect; these are seams, scaling limits, and small correctness edges worth
a decision.

## What's working well (keep doing this)

- **Anti-hallucination discipline is the backbone.** Every LLM output is verified
  against source before it's trusted:
  - Traceability gate (`segment/verify.py:traceability`) — a candidate must be a
    substring or ≥60% token-contained in its source block, else dropped as invented.
  - Refined text that can't be re-grounded **escalates** rather than being trusted
    (`segment/gate.py`).
  - Compound-ness is **derived** (multiple model outputs sharing one source index),
    not self-reported (`segment/identify.py`).
  - Deterministic rules are pure regex with cited offsets — never hallucinated
    (`score/deterministic.py`); LLM judges *consume* them.
- **Empirically-driven decisions are documented with their motivation** (batch=1
  scoring, reranker-over-cosine for overlaps, LLM-only identification).
- **Robust LLM plumbing** — three-tier JSON fallback in `llm/client.py`; a failed
  chunk logs and returns `[]` instead of sinking the document.

## Potential issues / points to discuss

1. **`confirm_overlaps` bypasses the preset convention** (`score/setlevel.py`).
   It POSTs `"model": "gemma-4"` with an inline system prompt + `chat_template_kwargs`,
   while everything else calls named agent_server presets via `AgentServerClient`.
   → Register an `incose_overlap_confirmer` preset for consistency, or document why
   this one is intentionally raw.

2. **Overlap detection is O(n²)** (`score/setlevel.py:find_overlaps`) — n rerank
   calls, each over n−1 docs. Fine at 388 reqs; this is the scaling wall. `max_compare`
   only truncates the outer loop, not the comparison set. → Decide if we need
   blocking/bucketing (e.g. embed-then-cluster) before larger docs.

3. **ID-collision suffix runs out of alphabet** (`segment/pipeline.py:unique_id`).
   `chr(ord('a') + suffix - 1)` breaks past 26 collisions of the same base ID.
   Unlikely in practice; would emit non-alnum IDs rather than erroring. → Low
   priority; wrap to `-aa`/`-ab` or a numeric suffix if it ever bites.

4. **Data-file naming seam** — `scripts/build_preview.py` inlines `data/scorecard.js`,
   but `scripts/produce_scorecard.py` writes `scorecard_full.json`. The `data/` dir is
   untracked, so the wiring can't be verified from git. → Confirm the frontend's actual
   data source is consistent end-to-end.

5. **Two different review cutoffs** (`scripts/produce_scorecard.py`) — a requirement
   is *selected* for review when any characteristic ≤3, but the reviewer prompt then
   *bundles* all characteristics <5. Intentional (trigger on serious defects, give the
   reviewer full context) but uncommented. → Add a one-line note so it doesn't read as
   a bug.

6. **No single-requirement / interactive path yet.** `produce_scorecard.py` is a batch
   driver, not a service. The interactive lifecycle app (spec §8) needs an orchestration
   API. See "Real-time assessment page" below — most building blocks already exist.

## Status snapshot

- **Done & validated:** ingest → segment → score → set-level → review batch pipeline;
  results dashboard; ~100% recall / ~94% precision on gold sets; full Annex-A run.
- **Not built:** interactive lifecycle app (drag-drop ingest, streamed live progress,
  single-requirement assessment) — needs an orchestration API.

## Real-time single-requirement assessment page — BUILT & VERIFIED (2026-07-03)

**Verdict: achievable — now built and tested end-to-end on E4B.** Measured live,
not estimated:

| Step | Latency (E4B, warm) |
|------|--------------------|
| Deterministic term rules (per keystroke) | **~3 ms** |
| Per characteristic judge (preset, serialized on 1 GPU) | **~0.5 s** |
| Fast-lane 4 judges (C3·C4·C5·C7) → headline verdict | **~2.0 s** |
| Full 9 judges | **~4.5 s** |
| + Reviewer (rewrites/advisories) | **~5.5 s total** |

**Model note (from agent_server `documents/how_to.md`):** agents never select a
model — every preset runs on the single **active** chat model, which is **E4B
(`gemma-4`)**. There is no per-preset E2B path; E2B isn't even resident. So the
only latency levers that don't require a global model switch are: **stream
results, fast-lane subset first, defer the reviewer** — all three implemented.

**What was built:**
- `src/reqqa/assess.py` — transport-agnostic core: `assess_requirement()` (full)
  + `iter_assessment()` (streams deterministic → 9 judges fast-lane-first →
  review → done) + `review_requirement()` (deferred reviewer).
- `src/reqqa/realtime.py` — socket.io (python-socketio ASGI) server: serves the
  editor page, streams per-event, per-client generation counter cancels a
  superseded stream on new keystrokes.
- `frontend/editor.html` + vendored `frontend/vendor/socket.io.min.js` (v4.7.5).

**Verified live:** page + client JS serve (HTTP 200); socket.io stream delivers
13 events with deterministic at 0.00s, fast-lane first, review last, overall
computed; supersession cancels in-flight streams (gen1 stopped after 2 judges,
gen2 completed 9); too-short text → `idle`.

Run: `PYTHONPATH=src uvicorn reqqa.realtime:asgi --port 7801` → http://localhost:7801/

**Deps added to the dev venv:** `python-socketio`, `uvicorn`, `requests`
(client test), `websocket-client`. Not yet added to `requirements.txt`.

---

### Original two-tier design (as proposed, now implemented)

- **Instant tier (every keystroke):** run the deterministic rules
  (`score/deterministic.check_requirement`). Pure regex, no LLM, sub-millisecond —
  highlights vague terms, escape clauses, oblique symbols, etc. live as the user types.
- **Debounced tier (on ~700ms pause):** fire the 9 C1–C9 judges (batch=1, in parallel)
  plus the Reviewer for rewrite suggestions. Reuses `judge_one` / `review_one` logic
  verbatim. Latency = local-LLM bound (a few seconds), so this is "on pause," not
  per-keystroke.
- **Not applicable to a single requirement:** set-level C10–C15 (needs the whole set)
  and segmentation (user writes one requirement). An optional "is this a requirement?"
  check could reuse the gate judge.

**New work required:** one thin endpoint — `POST /assess {text}` → deterministic +
9 judges (parallel) + reviewer — wrapping functions that already exist, plus the web
page with debounce. No changes to the scoring logic itself.

**Constraint to respect:** keep judges at batch=1 — combining characteristics into one
call to save latency corrupts scores (measured). Parallelize instead; accept a few
seconds on pause.
