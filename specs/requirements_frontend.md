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

## 7. Grounding notes (so the UI stays honest)
- Scores are the model's assessment; **surface the justification** so a reviewer
  can judge the judge. Don't present a bare number as ground truth.
- Rewrites are **proposals with placeholders** — never silently applied, values
  never invented.
- Deterministic findings are exact/auditable; LLM characteristic scores are
  judgments — the UI may visually distinguish the two sources.
