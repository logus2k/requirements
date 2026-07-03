# Requirements Quality — Frontend / Results Presentation

Status: Ideas capture (living doc)
Scope: how to present INCOSE quality-assessment results at two levels —
**whole document** and **per requirement**. Charts/UX only; the scoring pipeline
is specified in [technical_architecture.md](technical_architecture.md).

---

## 1. The data the frontend consumes

Everything below is already produced (or planned) by the pipeline. One
`scorecard` per document:

```
document:
  source_file, ingested_at, page_count
  requirements: [ per-requirement records ]           # see §3
  set_level:                                           # INCOSE C10–C15 (whole set)
    C10 Complete, C11 Consistent, C12 Feasible, C13 Comprehensible,
    C14 Able-to-be-validated, C15 Correct  → {score/verdict, findings}
  aggregates:
    per_characteristic_mean[C1..C9]
    per_rule_violation_count[R1..R42]
    score_distribution
    counts: total, by_type(FR/NFR), by_section

per-requirement record:
  req_id, text, provenance{source_file, page, bbox, section_path, char_span}
  origin(extracted|derived|assembled), was_compound, derived_from, duplicate_of
  characteristics[C1..C9]: { score(1–5), rules_triggered[], evidence(span), justification }
  deterministic_findings[]: { rule_id, name, matches[{term, offset}] }
  overall = mean(C1..C9)
  review: { rewrites[{text, addresses[], notes, before→after delta}], advisories[{characteristic, issue, suggestion}] }
```

**Persist ALL reasoning** (every justification, every finding). The document view
surfaces aggregates + failures; the requirement view surfaces everything.

---

## 2. Full-document view

Goal: at a glance, *where is this SRS weak, and which requirements need work?*

### 2.1 Header / health band
- Document name, # requirements, ingestion date, page count.
- **Overall health**: mean of all requirement averages (+ a color band).
- Quick counts: FR vs NFR, # requirements below threshold, # with a proposed rewrite.

### 2.2 Characteristic profile — radar (or bar)
- **Radar** with 9 axes (C1–C9), plotting the per-characteristic mean across the
  set → the document's "quality shape" (e.g. weak on Unambiguous + Verifiable).
- Bar chart is the fallback/alternative (some prefer it for exact reading).

### 2.3 Rule violations — bar / line
- **Bar chart of R1–R42**: how many requirements violate each rule → the most
  common writing problems in this document (e.g. R7 vague terms × 40, R19
  combinators × 55). Line chart if trend across sections is wanted.
- Sortable; click a rule → filtered list of the requirements that violate it (§4).

### 2.4 Requirements × characteristics heatmap
- Rows = requirements (or sections), columns = C1–C9, cell color = score (1–5).
- Reveals patterns: a whole section weak on Complete, a cluster failing Singular.
- Click a cell → that requirement's detail.

### 2.5 Score distribution
- Histogram of per-requirement average scores (how many are "good" vs "poor").

### 2.6 Worst-N table
- Lowest-scoring requirements, sortable, each row: id, snippet, avg, failing
  characteristics, "has rewrite?" → click to detail.

### 2.7 Set-level panel (C10–C15) — separate
- These apply to the **whole set**, not one requirement: Consistent (C11 —
  conflicting/overlapping/duplicate requirements, inconsistent units/terms),
  Complete (C10 — coverage gaps), etc.
- Present as its own section with set-level findings (e.g. "12 duplicate pairs",
  "3 unit inconsistencies"). Fed by the set-level analysis + the `duplicate_of`
  links the pipeline already produces.

### 2.8 Filters / slicing
- By section, by type (FR/NFR), by characteristic, by score threshold, by "has
  proposed rewrite", by origin (assembled/derived) or `duplicate_of`.

---

## 3. Per-requirement view

Goal: *why did this requirement lose points, and how do I fix it?*

### 3.1 The statement, annotated
- Show the requirement text with **inline highlighting of the offending spans**
  (the `evidence` from each judge + deterministic term matches), colored by
  severity / rule. Hover a highlight → which rule/characteristic and why.

### 3.2 This requirement's profile
- Small **radar or bar** of its 9 characteristic scores (1–5).
- Overall average + band.

### 3.3 Per-characteristic cards (all 9, all reasoning)
Each card: **score (1–5)** · rules_triggered · evidence span · **justification**
(the ≤2-sentence reasoning). Failing cards (score < 5) expanded by default;
passing cards collapsed. Never hide the reasoning — persist and show it.

### 3.4 Deterministic findings
- Exact rule/term matches with offsets (e.g. R7 → "appropriately" @ 34). These
  are the auditable, cited lexical hits.

### 3.5 Reviewer panel
- **Proposed rewrites** (one per resulting singular requirement — a compound
  becomes N), with **[specify …] placeholders highlighted** so the human knows
  what to fill. Show `addresses` (which characteristics each rewrite fixes) and
  the **before → after re-score delta**.
- **Advisories** for substance defects (Necessary / Feasible / Correct) that
  can't be auto-fixed — flagged for a human decision.
- Actions: accept a rewrite (creates a proposed revision, original retained),
  dismiss, edit, mark for review.

### 3.6 Provenance & lineage
- Source file, page, section path; **jump-to-source** (bbox highlight in the PDF).
- Lineage: origin (extracted / derived-from-compound / assembled-from-table),
  `was_compound`, `derived_from`, `duplicate_of` (link to the primary).

---

## 4. Navigation / drill-down
- Document → click a requirement (table/heatmap/worst-N) → requirement detail.
- Radar axis (a characteristic) → list of requirements failing it.
- Rule bar → list of requirements violating that rule.
- Requirement detail → jump to source, or to its `duplicate_of` primary.
- Export: CSV of scores, or a formatted quality report (per-rule + per-req).

---

## 5. Visual conventions
- **Score → color**: 1–2 red, 3 amber, 4–5 green (finalize against the `dataviz`
  skill palette for light/dark + accessibility). Consistent everywhere.
- Severity of a highlight follows the triggering characteristic's score.
- Radar for *profiles* (9 axes), bar for *rules* (many bars) and for exact reads,
  heatmap for *requirements × characteristics*, histogram for *distribution*.
- When building any chart, load the `dataviz` skill first.

---

## 6. Open questions / decisions
- **Binary vs 1–5 surfacing**: we persist 1–5; a derived binary (pass = score 5,
  or ≥4) can drive filters/counts. Which threshold for "pass" in the UI?
- **Radar readability** at 9 axes vs. a horizontal bar of 9 — offer both?
- **Set-level (C10–C15) depth**: how much whole-set analysis to build first
  (consistency/duplication is the highest-value; comprehension/validation later).
- **Rewrite acceptance workflow**: does accepting a rewrite re-run identification
  + scoring on the new text (close the loop), and how is the revision versioned?
- **Scale of the heatmap** for 300+ requirements (group by section, virtualize).

---

## 8. The full lifecycle (from results-viewer to application)

The document/requirement views (§2–§3) are the *results* half. The app also owns
the workflow that produces them: **ingest → monitor → results → review → manage**.
This turns a static viewer into an application with a backend.

### 8.1 Ingestion view
- Drag-and-drop / file picker for `.pdf .docx .html .pptx .md`.
- Options: chunking/segmentation on by default; which characteristics to score;
  run reviews now vs on-demand; run set-level (yes/no).
- "Assess" → creates a **job** and jumps to the monitor.

### 8.2 Progress / monitoring view (streamed) — AND live results
Two kinds of events stream over **SSE / WebSocket**, and the view is not a bare
progress bar — the **dashboard fills in as requirements complete**:

1. **Stage events** — `{stage, done, total, message}`: Ingest (items) → Segment
   (`440 → 403 primary`) → Gate (`388 accepted`) → Score (`1800/3492`, bar + rate
   + ETA) → Review → Set-level. Cancellable; errors surfaced inline.
2. **Per-requirement result events** — `{type:"requirement", data:{req_id,
   characteristics, deterministic_findings, overall, provenance, lineage}}`,
   emitted the moment a requirement's 9 characteristics + deterministic pass are
   done. The frontend **appends the table row and updates the charts as running
   aggregates** (means, rule counts, distribution recomputed incrementally;
   worst-first re-sorts). No 20-minute blank wait — results flow in.
3. **Finalization events** — set-level (C10–C15, needs the whole set) and any
   review results arrive near the end; final aggregates replace the running ones.

Implementation note: the producer must complete requirements incrementally — keep
the parallel (req × judge) pool but emit a requirement event once all 9 of its
judges have returned. Aggregates shown live are partial ("214 / 388 scored") and
finalize when the run ends. This is the producer's stage log + per-record output
formalized into structured events.

### 8.3 Review workflow view
- Per requirement: **run Reviewer on demand** (button), see proposed rewrites
  (placeholders highlighted) + advisories + the before→after re-score delta.
- Actions: **accept** a rewrite → creates a *proposed revision* (original
  retained, versioned), **edit**, **dismiss**, **mark for human review**.
- Accepting a rewrite optionally **re-runs identification + scoring** on the new
  text to close the loop and record the quality delta.
- A queue/worklist of requirements needing attention (lowest scores first,
  `escalated` items, unresolved advisories).

### 8.4 Document library
- List of assessed documents: name, date, overall health, # requirements,
  status (processing / done / failed). Open, re-run, **compare two runs** (did
  quality improve after edits?), delete, export report.

### 8.5 Backend orchestration API (the new dependency)
A service (FastAPI, sibling to the ingest service) that the frontend talks to:

| Endpoint | Purpose |
|---|---|
| `POST /documents` | upload → store → create job |
| `GET /jobs/{id}/events` | **SSE/WS** stream of stage progress |
| `GET /jobs/{id}` | job status snapshot |
| `GET /documents/{id}/scorecard` | the assembled scorecard JSON (§1) |
| `POST /requirements/{id}/review` | run Reviewer on demand |
| `POST /requirements/{id}/revisions` | accept/edit a rewrite → new revision |
| `POST /requirements/{id}/rescore` | re-score (a revision or after edit) |
| `GET /documents` | library listing |

Responsibilities: run the pipeline as an **async job** (background worker),
**emit progress events**, **persist** documents / scorecards / revisions
(SQLite or files), and reuse the existing ingest service + agent_server presets +
llama-server. The current `scripts/produce_scorecard.py` becomes the job body,
its `log()` calls becoming emitted events.

### 8.6 Build order (lifecycle)
1. Wrap the producer as a **job with structured progress events** (refactor the
   stage logs).
2. **Orchestration API** — upload, job, SSE progress, scorecard serving.
3. **Monitor view** wired to the SSE stream (highest-value: live processing).
4. **Ingestion view** (upload → job).
5. **Review workflow** (on-demand reviewer, accept/re-score) + revisions store.
6. **Library** + run comparison.

---

## 7. Grounding notes (so the UI stays honest)
- Scores are the model's assessment; **surface the justification** so a reviewer
  can judge the judge. Don't present a bare number as ground truth.
- Rewrites are **proposals with placeholders** — never silently applied, values
  never invented.
- Deterministic findings are exact/auditable; LLM characteristic scores are
  judgments — the UI may visually distinguish the two sources.
