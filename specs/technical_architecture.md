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

1. **The LLM identifies requirements; deterministic code validates its output.**
   Requirement identification is done entirely by the LLM (no regex/modal
   detector — see §6), in a *grounded* way; the pipeline then validates every
   result deterministically so a stochastic model cannot inject unverifiable
   output. Structure is context and provenance for the LLM, never a gate.
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
        │        LLM identification pass (span-grounded) — sole identifier,
        │            no regex/modal gate; structure passed in as context
        │        normalize granularity (split compound / merge qualifiers)
        │        deterministic verify (output validation only, no re-judging)
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
  `LIST_ITEM`, `DOCUMENT_INDEX`, `TEXT`, …) carried as context/provenance for the
  LLM identifier (not as an identification gate).
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

Segmentation is a *semantic* decision at **statement granularity**, and the
**LLM is the sole requirement identifier**. There is no regex/modal-verb
detector and no structural gate that decides what is or isn't a requirement.

**Rationale (evidence-based).** Requirements are written in an unbounded variety
of forms — `shall / must / will / should / needs to / is required to`, bare
imperatives, table rows, and multi-sentence bullets — and the ambiguous modals
("should", "will") appear constantly in non-normative prose. A regex/lexical
detector therefore both misses requirements and fires on non-requirements.
Measured on the five real SRS PDFs in `data/examples/`: two documents contain
**zero** "shall" statements (one uses "will/must" in numbered list items; another
uses 135 "should" / 81 "will" across bullets). Any phrasing-based detector would
miss those documents entirely. The regex approach is error-prone by nature and is
not used for identification.

### 6.1 Structure is context and provenance — never a gate
Ingestion's structural output (`block_type`, `section_path`, table Markdown,
page/bbox) is still produced and used, but only as:
- **provenance** carried through to each requirement, and
- **context passed INTO the LLM** to help it judge (e.g. "this block is a table
  row under section 3.2", the rendered table, the heading trail).

Structure never *decides* identification and never short-circuits the LLM. An
explicit ID or a requirements-table row is a strong hint handed to the model, not
an accept-without-checking rule. The LLM judges all of it, uniformly, so one
document's idiosyncratic conventions can't slip past a structural assumption.

### 6.2 LLM identification pass (span-grounded)
Feed the ingested `SourceItem` stream to the LLM in **structure-bounded chunks**
(a section or a table at a time — not raw character windows), with generous
surrounding context (the model's ~64K ceiling is headroom, not a target to fill).
For each chunk the LLM:
- **Classifies** each candidate span: `requirement | rationale | background |
  definition | heading | other`.
- **Bounds** each requirement by returning character/offset spans into the
  provided text; the pipeline slices the real source. The model never emits
  requirement text, so it cannot invent one — and provenance is exact.

This single pass replaces the former "structured vs prose lane" split: every
block flows through the same LLM identifier regardless of format or phrasing.

### 6.3 Normalize granularity (LLM, one requirement at a time)
- **Split** compound statements into singular requirements (real bullets in the
  example docs pack several normative sentences each). Flag the original as a
  `Singular` defect; keep a `derived_from` link on each child.
- **Merge** qualifiers / sub-conditions that belong to one requirement (e.g. a
  stem with `(a)…(b)…` conditions is one requirement, not many).

### 6.4 Verify & reconcile (deterministic — output validation only)
This step validates the LLM's output; it does **not** re-judge whether something
is a requirement (no modal/shape gate — that would smuggle the regex approach
back in).
- Reject any candidate whose text is not traceable to source (not a substring /
  near-match of the provided chunk) — anti-hallucination.
- Deduplicate on provenance + normalized text.
- Enforce a minimum length (drop empty/degenerate spans).
- Assign IDs (existing or generated); attach full provenance.
- Low-confidence identifications are flagged for review, not silently trusted.

### 6.5 Topic segmentation (complement only)
Topic/semantic segmentation (embedding-similarity, TextTiling) is not the
splitter: it only (a) bounds LLM chunks when a block has no structural headings,
and (b) clusters final requirements for later set-level checks. Its topic
granularity is too coarse to separate two adjacent same-topic requirements — that
separation is the LLM's job.

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

- Model: **Gemma 4 E4B**, served locally via `agent_server` (`:7701`,
  OpenAI-compatible; call by agent-preset name). See the `local-llm-agent-server`
  memory and `agent_server/documents/how_to.md`.
- Context: **64K configured, 128K model ceiling** — the configured window is
  headroom for context/anchors, and can be raised toward 128K if chunks + context
  ever need it.
- No grammar-constrained decoding (removed) — structured/JSON output relies on
  prompt + robust parsing; silence the thinking channel with
  `chat_template_kwargs={"enable_thinking": false}`.
- Every LLM call is narrow, grounded (spans), and structured. Division of labor:
  identification (§6) is LLM-only, while *scoring* (§8) still offloads mechanical
  INCOSE checks to the deterministic rule engine — "no regex for identification"
  does not mean "no deterministic scoring rules"; those are different stages.
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
      identify.py                      # LLM identification pass (sole identifier, span-grounded)
      chunker.py                       # structure-bounded chunking + context assembly for the LLM
      normalize.py                     # split/merge to singular
      verify.py                        # deterministic output validation (no re-judging)
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
   without a model). **Done — Component 1.**
2. LLM identification pass (span-grounded, structure as context) + verify.
3. Normalize granularity (split compound / merge qualifiers).
4. Deterministic INCOSE rule engine + catalog.
5. Semantic LLM judge + scorecard.
```
