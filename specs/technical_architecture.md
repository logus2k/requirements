# Requirements Quality Analyzer — Technical Architecture

Status: As-built (Components 1–6 implemented)
Date: 2026-07-03

## 1. Purpose

Take a requirements **document** as input, split it into **discrete requirements**,
and **score each requirement** against the INCOSE *Guide for Writing Requirements*
(GtWR) characteristics and rules. Output is a per-requirement scorecard with
actionable, source-anchored findings.

## 2. Scope

In scope (all implemented):
- Ingesting Markdown, PDF, Word (`.docx`), HTML, PowerPoint (`.pptx`) documents.
- Segmenting a document into atomic, singular requirement statements with
  provenance back to the source (LLM identify → gate → assemble → dedup).
- Scoring each requirement against the 9 individual INCOSE characteristics
  (C1–C9), split into a deterministic term-list layer and a semantic layer of
  9 per-characteristic LLM judges (1–5 scale, one requirement per call).
- Set-level INCOSE checks (C10–C15) across the whole set, with reranker-detected
  overlaps confirmed by the LLM.
- A **Reviewer** pass that proposes rewrites/advisories for defective
  requirements (any characteristic ≤ 3).
- A self-contained ECharts frontend that visualizes the scorecard.

Out of scope (for now):
- The full lifecycle app (drag-drop ingest, streamed live progress, review
  workflow, document library) and its orchestration API — designed in
  `requirements_frontend.md` §8, not yet built.
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
4. **Term-list rules are never an ML problem.** The 15 INCOSE rules stated as
   explicit term/symbol lists are detected deterministically (offending token +
   offset) — full consistency and explainability. Grammar/meaning judgments are
   left to the LLM, not brittle syntactic rules.
5. **Decompose LLM work into micro-tasks.** The target model is mid-size
   (7B–34B). It is reliable on small, single-purpose calls and unreliable on
   "do everything at once" prompts.

## 4. High-level pipeline

```
Document (.md / .pdf / .docx / .html / .pptx)
        │
 [1] INGEST  → normalized item stream with provenance
        │        .md            → parse directly (already structured)
        │        .pdf/.docx/... → Docling DocumentConverter → DoclingDocument
        │
 [2] SEGMENT → List[DiscreteRequirement]   (LLM is the sole identifier, no regex)
        │        identify   — span-grounded LLM pass over structure-bounded chunks
        │        gate       — judge drops non-requirements; bounded refine loop
        │        assemble   — reassemble pieces split across chunks (by author ID)
        │        dedup      — reranker marks terse summaries as duplicate_of detail
        │
 [3] SCORE (per requirement) → scorecard
        │        9 LLM judges, C1–C9, 1–5 scale, batch=1  (one req per call)
        │        deterministic term-list engine (15 rules) → offending spans
        │
 [4] SET-LEVEL (whole set) → C10–C15
        │        find overlaps (reranker) → LLM-confirm → holistic set judge
        │
 [5] REVIEW  → for any requirement with a characteristic ≤ 3
        │        Reviewer proposes rewrites + advisories
        ▼
 Scorecard JSON → [6] frontend (ECharts 6.1.0 dashboard)
   per requirement, per characteristic → {score 1–5, rules[], evidence, justification}
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
Tables get a dedicated identifier (`identify_table`) that reads the rendered
Markdown rows. Implemented in `segment/identify.py`, driven by
`segment/pipeline.py`; `chunker.py` builds the structure-bounded chunks.

### 6.3 Gate — judge drops non-requirements, bounded refine loop
A second LLM role (`requirement_judge`) reviews every identified candidate and
returns one of three dispositions (`segment/gate.py`):
- **ACCEPTED** — a genuine requirement; kept.
- **DROPPED** — not a requirement; retained with the judge's justification for
  audit, but excluded from scoring.
- **ESCALATED** — still uncertain after the refine loop; flagged for review.

Uncertain candidates enter a bounded **refine loop** (`requirement_refiner`,
`max_iters`): the refiner may tighten the wording (re-verified as still traceable
to source) or drop it. The gate never *writes* new requirements — it only accepts,
drops, or minimally refines — so identification stays grounded.

### 6.4 Assemble — reassemble split requirements (by author ID)
Chunk boundaries can split one authored requirement across blocks. `assemble.py`
(`reassemble`) merges pieces that share an existing author ID back into a single
`DiscreteRequirement` (`origin="assembled"`, with `component_orders`). Enabled by
the `assemble` flag on `segment_items`.

### 6.5 Dedup — mark overview summaries as duplicates (reranker)
Many SRSs repeat a requirement as a terse overview bullet *and* a detailed
statement. `dedup.py` (`dedup_overview`) uses the reranker to detect these and
marks the terse one `duplicate_of` the detailed one, with a **length guard**
(a candidate shorter than 0.6× the detail is the summary). Marked duplicates are
carried for provenance but excluded from scoring. Enabled by the `dedup` flag.

Anti-hallucination throughout: any candidate whose text is not a substring /
near-match of its source chunk is rejected — the LLM emits spans, never free text.

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
    origin: str                 # "extracted" | "derived" | "assembled"
    derived_from: str | None    # parent req_id if split from a compound
    was_compound: bool          # feeds the Singular score directly
    identification_confidence: float
    component_orders: list[int] | None = None  # source items merged by assemble
    duplicate_of: str | None = None             # set by dedup; excluded from scoring
```

`Provenance` carries `source_file, section_path, order, page, bbox, char_span`.
This object flows unchanged from segmentation into scoring.

## 8. Scoring

Scoring is the INCOSE knowledge base in `incose/` (GtWR v4, INCOSE-TP-2010-006-04):
`catalog.json` (42 rules R1–R42 + 15 characteristics C1–C15), `rules/*.md`,
`characteristics/*.md`, and `judges/*.md` — the **static, complete** judge
prompts. There is no runtime prompt assembly: each judge is a finished system
prompt registered as an agent preset.

### 8.1 Rule catalog (shared spec)
`incose/catalog.json` holds all 42 rules and 15 characteristics. Each rule that
the GtWR expresses as an explicit term/symbol list is tagged
`detector: "deterministic"` and carries a `terms` list; everything else is judged
by the LLM. The catalog also anchors the scorecard schema.

### 8.2 Deterministic layer (term lists only)
`score/deterministic.py` implements the **15** rules the GtWR states as explicit
term/symbol lists (vague terms, escape clauses, open-ended clauses, oblique `/`,
etc.), read straight from `catalog.json` (`detector == "deterministic"`). Each
finding cites the **offending token and its character offset**, so it is auditable
and never hallucinated. This layer does **no** grammar/NLP parsing — there is no
spaCy passive-voice or modal detector; those judgments belong to the LLM (a
mid-size model reads grammar better than brittle syntactic rules, and the term
lists are exactly where determinism wins).

### 8.3 Semantic layer — 9 per-characteristic judges (1–5, batch=1)
One dedicated judge per individual characteristic C1–C9 (`incose_c1_necessary` …
`incose_c9_conforming`), listed in `score/characteristics.py`. Each judge:
- Scores its characteristic on a **1–5 scale** (5 = no rule triggered / best) and
  returns `{index, score, rules_triggered, evidence, justification}`.
- Runs **batch=1 — one requirement per call.** This is measured, not stylistic:
  at batch=1 the judge is ~96% self-consistent; batching 8+ requirements per call
  drops that to ~54% as the model conflates them. See the `scoring-batch1` memory.
- Is a complete static prompt with the characteristic's rules and few-shot
  anchors baked in.

Binary pass/fail is **derived in code** from the score, not asked of the model.
`normalize_rule_ids` cleans the judges' `rules_triggered` back to canonical
`R##` IDs (the model occasionally emits `R30 Unique Expression` or a stray
`R_C8`).

### 8.4 Set-level layer — C10–C15 (`score/setlevel.py`)
Assessed over the whole set, not per requirement:
- `find_overlaps` — the reranker scores requirement pairs; it cleanly separates
  true overlap (~0.95) from mere topical similarity (<0.05), threshold 0.8. This
  is hard evidence for C11 Consistent / C10 Complete.
- `confirm_overlaps` — an LLM pass keeps only genuine duplicates/overlaps and
  drops the reranker's merely-related false positives (measured: 98 candidates →
  ~3 confirmed on a sample).
- `assess_set` — a holistic set judge (`incose_set_judge`) rates C10–C15 from a
  set summary plus the confirmed overlaps, with justifications and findings.

### 8.5 Review layer (`incose/judges/reviewer.md`)
Any requirement with a characteristic score ≤ 3 is sent to the **Reviewer**
(`incose_reviewer`) with the bundle of failing judgments; it returns suggested
**rewrites** and **advisories**. It assesses and improves an already-written
document — it does not author requirements from scratch.

### 8.6 Scorecard output
`scripts/produce_scorecard.py` assembles everything into one frontend-ready JSON:
per requirement, per characteristic `{score, rules, evidence, justification}`;
the reviewer block on defective requirements; set-level C10–C15; and aggregates
(per-characteristic means, per-rule violation counts, score distribution,
overall health). Never a single opaque score without its backing findings.

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
- Embeddings + rerank run on **llama-server** (`:8500`, bge-m3 + bge-reranker),
  used by set-level overlap detection and segmentation dedup.
- Every LLM call is narrow, grounded (spans), and structured. Division of labor:
  identification (§6) is LLM-only, while *scoring* (§8) offloads the 15 explicit
  term-list rules to `deterministic.py` — "no regex for identification" does not
  mean "no deterministic scoring rules"; those are different stages.
- Growth path: LLM-first now; use the running pipeline to bootstrap a labeled
  set; **distill** into a trained classifier only if scale/cost/consistency
  demands it (this is the mature form of an ensemble — LLM teaches the
  classifier, not a weak classifier anchoring the LLM).

## 10. Proposed module layout

```
requirements/
  specs/technical_architecture.md      # this file
  incose/                              # KB: catalog.json, rules/, characteristics/, judges/
  src/reqqa/
    ingest/                            # dispatch.py, docling_adapter.py, markdown.py, model.py
    segment/
      identify.py                      # LLM identification pass (sole identifier, span-grounded)
      chunker.py                       # structure-bounded chunking + context for the LLM
      gate.py                          # judge: accept / drop / refine loop
      assemble.py                      # reassemble requirements split across chunks
      dedup.py                         # reranker overview-vs-detail dedup (length guard)
      pipeline.py, model.py, prompts.py, judge.py, verify.py
    score/
      deterministic.py                 # 15 term-list detectors (from catalog.json)
      characteristics.py               # C1–C9 list + normalize_rule_ids
      setlevel.py                      # C10–C15: find/confirm overlaps + set judge
    llm/
      client.py                        # agent_server preset client
      retrieval.py                     # embeddings + rerank (llama-server :8500)
  scripts/                             # register_agents, register_incose_judges,
                                       #   segment_doc, produce_scorecard
  frontend/                            # ECharts 6.1.0 dashboard (index.html, js/app.js, …)
```

## 11. Open questions

- Rule→characteristic aggregation matrix is still `pending` verification (only
  needed to roll rule violations up per characteristic).
- Confidence thresholds for routing ESCALATED / low-confidence extractions to
  human review.
- Gold-set evaluation is done on ReqView + Annex-A SRS (recall ~100%, true
  precision ~94%); broaden to more labeled sets.

## 12. Build order

1. Ingestion → normalized item stream with provenance. **Done — Component 1.**
2. Segmentation: LLM identify → gate → assemble → dedup. **Done — Component 2.**
3. Scoring: 9 judges (C1–C9, 1–5, batch=1) + deterministic term lists.
   **Done — Component 3.**
4. Set-level C10–C15 (reranker overlaps + LLM confirm + set judge). **Done.**
5. Reviewer pass on defective requirements + full scorecard producer. **Done.**
6. Frontend dashboard (ECharts 6.1.0, light/dark). **Done — Component 6.**
7. Full lifecycle app + orchestration API — **planned** (`requirements_frontend.md` §8).
```
