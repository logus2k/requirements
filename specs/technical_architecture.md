# Requirements Quality Analyzer — Technical Architecture

Status: Draft
Date: 2026-07-02

## 1. Purpose

Take a requirements **document** as input, split it into **discrete requirements**,
and **score each requirement** against the INCOSE *Guide for Writing Requirements*
(GtWR) characteristics and rules. Output is a per-requirement scorecard with
actionable, source-anchored findings.

## 2. Scope

In scope:
- Ingesting Markdown, PDF, Word (`.docx`), HTML (and similar) documents.
- Segmenting a document into atomic, singular requirement statements with
  provenance back to the source.
- Scoring each requirement against INCOSE characteristics, split into a
  deterministic layer (mechanical/lexical/syntactic rules) and a semantic layer
  (judgment characteristics via a local LLM).

Out of scope (for now):
- Set-level INCOSE checks (Consistency, Completeness across the whole set) —
  deferred; noted as a later phase.
- Auto-rewriting requirements — deferred; scoring first.
- Training a bespoke classifier — deferred. Start LLM-first, distill later only
  if scale/cost/consistency demands it (see §9).

## 3. Design principles

1. **Structure-first, LLM only where structure runs out, deterministic
   verification at the end.** Do as much as possible by parsing document
   structure; use the mid-size local LLM narrowly and in a *grounded* way; then
   validate everything deterministically so a stochastic model cannot inject
   unverifiable output.
2. **Span-grounding over free text.** The LLM never emits requirement *text*; it
   emits character offsets into the text it was given, and the pipeline slices
   the real source. Eliminates hallucination, yields exact provenance.
3. **Provenance is non-negotiable.** Every discrete requirement carries a
   back-pointer to its source location. Without it, a score is not actionable.
4. **Mechanical rules are never an ML problem.** Roughly half the INCOSE rules
   are deterministic lexical/syntactic checks; a rule engine handles them with
   full consistency and explainability.
5. **Decompose LLM work into micro-tasks.** The target model is mid-size
   (7B–34B). It is reliable on small, single-purpose calls and unreliable on
   "do everything at once" prompts.

## 4. High-level pipeline

```
Document (.md / .pdf / .docx / .html / ...)
        │
 [1] INGEST  → normalized item stream with provenance
        │        .md            → parse directly (already structured)
        │        .pdf/.docx/... → Docling DocumentConverter → DoclingDocument
        │
 [2] SEGMENT → List[DiscreteRequirement]
        │        router → structured lane (deterministic)
        │                 prose lane      (span-grounded LLM)
        │        normalize granularity (split compound / merge qualifiers)
        │        deterministic verify & reconcile
        │
 [3] SCORE   → per-requirement scorecard
        │        deterministic INCOSE rule engine  (mechanical characteristics)
        │        semantic LLM judge                (judgment characteristics)
        ▼
 Scorecard: per requirement, per characteristic → {verdict, severity, rule_id, evidence span}
```

## 5. Ingestion

Extension dispatch, mirroring the proven pattern in the `noted` graph service
(`graph/app/scanners/`):

- `.md` → parse directly. Already structured text; no Docling needed.
- `.pdf`, `.docx`, `.pptx`, `.html`, `.htm` → **Docling** `DocumentConverter`
  → `DoclingDocument` tree.

Reused patterns (lift, don't reinvent):
- Converter setup with a local, bind-mounted model cache (avoid re-downloading
  layout/TableFormer weights).
- Provenance extraction: `page_no` + `bbox` from `doc_items[].prov[].bbox`.
- Structural labels via `DocItemLabel` (`SECTION_HEADER`, `TITLE`, `TABLE`,
  `LIST_ITEM`, `DOCUMENT_INDEX`, `TEXT`, …) as the router's signal source.
- Table → Markdown via `TableItem.export_to_markdown(doc)`.
- Heading-ancestry reconstruction: Docling's PDF backend flattens heading
  levels (every header at `level=1`); ancestry must be rebuilt from positional
  cues (the graph service's `_build_heading_hierarchy` is a starting point).

**Explicit non-reuse:** Docling's `HybridChunker` is NOT used as the
segmentation unit. It is a *retrieval* chunker — `merge_peers=True` deliberately
merges adjacent items and bags whole lists into one chunk. That is the opposite
of what segmentation needs (split to atomic requirements). We walk the document
items ourselves.

Ingestion emits a normalized item stream: for each item, `{text, block_type
(from DocItemLabel), section_path, provenance}`.

## 6. Segmentation

Segmentation is a *semantic* decision at **statement granularity**. Document
structure is a cheap, reliable *proxy* used where present; where absent, the
decision is made semantically by the LLM.

### 6.1 Router (deterministic)
Classify each item/region using structural signals:
- explicit requirement ID pattern (`REQ-\d+`, `\d+\.\d+`, etc.)
- table with a requirements-like schema (ID column / "shall" column)
- list item under a "Requirements" heading
- modal-verb presence (`shall` / `must` / `will`)

Routes each item into one of two lanes.

### 6.2 Structured lane (deterministic — no LLM)
Each ID'd item / table row / list item becomes one candidate requirement,
parsed directly. No model involved.

### 6.3 Prose lane (span-grounded LLM)
For narrative prose (no reliable structure), feed a **structure-bounded chunk**
(a section, a table — not a raw character window) to the LLM, with generous
surrounding context (the model's ~64K ceiling is headroom, not a target to fill).
Two micro-tasks:
- **Classify** each sentence/clause: `requirement | rationale | background |
  definition | heading`.
- **Bound** each requirement: return character spans; the pipeline slices the
  real text.

Topic/semantic segmentation (embedding-similarity, TextTiling) is a *complement*,
not the core splitter: it only (a) bounds prose-lane chunks when structural
headings are absent, and (b) clusters final requirements for later set-level
checks. It operates at topic granularity, which is too coarse to separate two
adjacent same-topic requirements — that separation is the LLM's job.

### 6.4 Normalize granularity (LLM, one requirement at a time)
- **Split** compound statements into singular requirements. Flag the original as
  a `Singular` defect; keep a `derived_from` link on each child.
- **Merge** qualifiers / sub-conditions that belong to one requirement (e.g. a
  stem with `(a)…(b)…` conditions is one requirement, not many).

### 6.5 Verify & reconcile (deterministic)
- Reject any candidate whose text is not traceable to source (not a substring /
  near-match of the provided chunk).
- Assert each unit has subject + modal + predicate; enforce a minimum length.
- Deduplicate on provenance + normalized text.
- Assign IDs (existing or generated); attach full provenance.
- Anything failing is dropped or flagged low-confidence for review — never
  silently trusted.

## 7. Data model

```python
@dataclass
class Provenance:
    source_file: str
    page: int | None          # for paginated sources (PDF)
    section_path: str         # ' > '-joined heading trail
    char_span: tuple[int, int] | None
    bbox: list[float] | None  # for PDF highlight

@dataclass
class DiscreteRequirement:
    req_id: str                 # existing ID, or generated (DOC-0007)
    text: str                   # clean, singular requirement statement
    provenance: Provenance
    origin: str                 # "extracted" | "derived"
    derived_from: str | None    # original req_id if split from a compound
    was_compound: bool          # feeds the Singular score directly
    extraction_confidence: float
```

This object flows unchanged from segmentation into scoring.

## 8. Scoring

### 8.1 Rule catalog (shared spec)
A single catalog tags each INCOSE rule/characteristic with its lane and
reference:

```
{ rule_id, incose_ref, characteristic, lane: "deterministic"|"semantic"|"hybrid",
  severity_default, description }
```

Both the deterministic engine and the LLM judge implement against this catalog;
it also defines the scorecard schema.

### 8.2 Deterministic layer (Python)
A rule registry, one detector per rule. Each detector returns the **offending
span**, not just a boolean.
- Regex for lexical rules: vague terms (*user-friendly, robust, minimize*),
  escape clauses (*if possible, as appropriate*), open-ended clauses (*including
  but not limited to*), `and`/`or` combinators, missing units/tolerances.
- spaCy for syntactic rules: passive voice, pronoun/ambiguous referent, modal
  ("shall") presence.

Covers the mechanical INCOSE characteristics with full consistency and
explainability.

### 8.3 Semantic layer (local LLM judge)
For judgment characteristics (Necessary, Appropriate, Complete, Correct,
Feasible, and the semantic aspects of Unambiguous / Verifiable):
- **One characteristic per call** (or tightly grouped), structured JSON out:
  `{verdict, severity, evidence, rationale}`.
- Few-shot anchors per characteristic.
- Pass the section neighborhood as context for characteristics that need it
  (Complete, Necessary), not the lone sentence.
- **Self-consistency** on borderline cases: sample N, take majority — cheap
  insurance against mid-size-model flakiness.

### 8.4 Scorecard output
Per requirement, per characteristic:
`{characteristic, verdict, severity, rule_id, evidence_span, rationale}` — plus a
roll-up. Never a single opaque score without its backing findings.

## 9. Local LLM constraints

- Target: mid-size open-weight model (7B–34B), served locally.
- ~64K context ceiling — treated as headroom for context/anchors, not a chunk
  target.
- Because the model is mid-size, the deterministic layer carries as much as
  possible, and every LLM call is narrow, grounded (spans), and structured.
- Growth path: LLM-first now; use the running pipeline to bootstrap a labeled
  set; **distill** into a trained classifier only if scale/cost/consistency
  demands it (this is the mature form of an ensemble — LLM teaches the
  classifier, not a weak classifier anchoring the LLM).

## 10. Proposed module layout

```
requirements/
  specs/technical_architecture.md      # this file
  src/reqqa/
    ingest/                            # extension dispatch, Docling adapter, .md parser
    segment/
      router.py                        # deterministic lane routing
      structured.py                    # structured-lane extraction
      prose.py                         # span-grounded LLM extraction
      normalize.py                     # split/merge to singular
      verify.py                        # deterministic reconcile
    model/                             # DiscreteRequirement, Provenance
    rules/
      catalog.py                       # INCOSE rule catalog (shared spec)
      deterministic.py                 # regex + spaCy detectors
    score/
      semantic.py                      # LLM judge (one characteristic per call)
      scorecard.py                     # assembly + roll-up
    llm/                               # local model client, structured-output helpers
```

## 11. Open questions

- Exact INCOSE rule set to implement first (which characteristics in the MVP).
- Local model choice and serving runtime.
- Confidence thresholds for routing low-confidence extractions to human review.
- Evaluation method for the scorer once the rule catalog is fixed.

## 12. Build order

1. Ingestion → normalized item stream with provenance (deterministic, testable
   without a model).
2. Router + structured lane.
3. Prose lane (span-grounded LLM) + normalize + verify.
4. Deterministic INCOSE rule engine + catalog.
5. Semantic LLM judge + scorecard.
```
