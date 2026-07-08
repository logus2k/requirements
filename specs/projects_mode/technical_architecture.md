# Projects Mode — Technical Architecture

Status: Design (pre-implementation, living doc)
Scope: reshapes reqoach from a single-document analyzer into a **project workspace**
with two independent, user-triggered analyses — **Requirements Quality** (existing
INCOSE pipeline) and **Requirements Coverage** (new). Covers the domain model, storage,
the Coverage pipeline (incl. the Problem-Framing stage and the Project-Type catalog),
the standards stack, the information architecture, and the API. The build order lives in
[implementation_plan.md](implementation_plan.md).

Companion baseline (today's single-doc quality pipeline): [../baseline/technical_architecture.md](../baseline/technical_architecture.md).

---

## 1. Why this exists

reqoach today answers **"is each requirement well-written?"** — INCOSE GtWR quality,
per requirement + set level. It says nothing about whether the requirements we have are
**adequate / enough for the problem**. That second question — *coverage* — is
**reference-relative**: you cannot detect a missing requirement by inspecting the
requirements you have; you need a model of *what should exist* to compare against.

Two consequences drive the whole design:

1. **The reference must be produced and owned.** The Coverage pipeline's first job is to
   build that reference (a **Problem Statement** + a matched **Project Type**), make its
   assumptions transparent, and let a human ratify/edit it at any time.
2. **Completeness is not provable.** The output is **prioritized gaps and questions with a
   stated confidence, never a "100% covered" score.** We reduce unknown-unknowns; we do
   not certify done.

---

## 2. Domain model

> **BUILT (2026-07-08):** the catalog exists on disk at `catalog/` (bind-mounted like
> `store/`): `domains.json` (16 coverage domains), `project_types/*.json` (20 archetypes),
> `standards/*.json` (6 packs). See `catalog/README.md`. The model below reflects the
> **compose** design (archetype = per-domain knowledge, not a match label).

```
Domain                 (catalog/domains.json — 16 fixed coverage domains; one judge each)
  id, name, standards[], concerns[], questions[]     # the generic baseline per domain

Archetype              (catalog/project_types/*.json — REUSABLE domain KNOWLEDGE, not a label)
  id, name, class, aliases[], summary, matching_signals[], salient_domains[], grounding[]
  domains{ <domain-id>: { emphasis, concerns[], typical_requirements[], questions[] } }
  # a system-type × domain matrix; composed (not matched) — judges pull relevant slices

StandardPack           (catalog/standards/*.json)
  id, name, source, leaves[{ id, name, domain, description, signals[] }]

Project                (a concrete engagement — the new top-level entity)
  id, name, created_at
  documents[]               # 1..n uploaded docs
  problem_statement@ver     # §4 (versioned, human-ratified)
  coverage_profile@ver      # candidate archetypes (w/ confidence) + human overrides
  quality_runs[]            # explicit Quality analyses (history)
  coverage_runs[]           # explicit Coverage analyses (history)

Document               (belongs to exactly one Project)
  id, project_id, filename, ingested_at, page_count, source_ref

Requirement            (produced by segmentation; the atom both analyses share)
  req_id, text, provenance{ source_document_id, section_path, page, char_span, order }
  tags[]                    # faceted, multi-label — §5
  quality{}                 # C1..C9 + rules + review   (from a Quality run)
  coverage{}                # matched leaves + grounding (from a Coverage run)
```

**Key relationships**
- A **Project** owns many **Documents**; requirements are gathered across *all* of them
  and each requirement is traceable to its `source_document_id` (a tag — §5).
- An **Archetype** is reusable per-domain knowledge in the catalog. A **Project** is not
  *matched* to one — the Problem-Framing agent proposes **candidate archetypes with
  confidence** (a project is naturally hybrid), which *weight* how the domain judges
  **compose** knowledge from several archetypes. The human-editable **Coverage Profile**
  records those candidates + overrides.
- **Quality run** and **Coverage run** are explicit, versioned jobs. Uploading documents
  triggers **neither**.

---

## 3. Storage layout

Greenfield — **no migration** from the current `store/<doc_id>/…`. Legacy scorecards may be
re-imported later into a project.

```
store/projects/<project_id>/
  meta.json                      # name, created_at, document index
  problem_statement.json         # current + version history (or versions/ subdir)
  coverage_profile.json          # resolved reference (matched types + overrides)
  documents/<document_id>/
    source.<ext>                 # original upload
    meta.json                    # filename, ingested_at, page_count
  quality/<run_id>/
    scorecard.json               # SAME shape as today's scorecard (per-req + set-level + aggregates)
    meta.json                    # run params, doc set, started/finished
  coverage/<run_id>/
    coverage.json                # §7 output (matrix, gaps, questions, grounding)
    meta.json

catalog/project_types/<id>.json        # the archetype catalog (BUILT — 20 archetypes)
catalog/standards/<pack_id>.json       # reference packs (§6)
```

`store/` and `catalog/` writable dirs are bind-mounted into the single `reqoach`
container (as `store/` is today). Catalog is read-mostly; editable via API later.

---

## 4. The Coverage pipeline

Coverage is an explicit run over a project. Stages:

### Stage 0 — Problem Framing  *(the linchpin — always runs first)*

Builds the reference the rest of coverage depends on. **Collect → Synthesize → Grade → Ratify.**

- **Collect** every intent signal across the full input spectrum: explicit
  problem/scope/vision prose, titles & headings, an optional free-text sentence from the
  user, and — as *weak* signal only — the requirements themselves.
- **Synthesize** a **structured** Problem Statement (not a blob):
  ```
  problem_statement:
    purpose            # the goal / why
    stakeholders[]     # who
    context            # operating environment
    scope{ in[], out[] }
    capabilities[]     # key things the system must do  (goal seeds for obstacle analysis)
    constraints[]
    success_criteria[]
    each field: { value, provenance: stated|inferred|assumed, confidence, source_quote? }
  ```
- **Grade** every field by provenance (`stated` w/ source quote · `inferred` w/ confidence ·
  `assumed/missing`). Non-negotiable: the coverage verdict inherits these assumptions, so
  they must be visible.
- **Ratify** — present the draft + assumptions + clarifying questions; the human confirms/
  edits before Coverage computes. Versioned; editable at any later time.

**Adaptive elaboration ladder.** The stage first classifies *how much input it has* and
shifts mode: a rich spec is mostly **extracted**; a bare sentence ("build me X") is
**elaborated** from domain priors with every expansion flagged as an assumption and the
sharpest clarifying questions surfaced. The same stage serves "500-page SRS" and one
sentence — its honesty about the extraction:inference ratio *is* the feature.

**Circularity guard.** If the Problem Statement is inferred largely *from the requirements
themselves*, grading those reqs against it is partly circular. Mitigations, all built in:
(1) derive primarily from **non-requirement narrative**; (2) lean on references
**independent** of this req set — standards taxonomies, domain checklists, and especially
**goal/obstacle analysis** (which generates goals the reqs never mention); (3) the human
ratification injects outside judgment. When the statement is ~entirely inferred, Coverage
**lowers its confidence** rather than presenting a confident gap list.

### Stage 1 — Archetype relevance (compose, don't match)

> **Architecture change (2026-07-08): compose, not match.** Archetypes are domain
> *knowledge*, not labels. We do NOT force the project into N discrete types and union a
> checklist. Instead the Problem-Framing agent proposes **candidate archetypes with
> confidence** (a project is naturally hybrid — see the `candidate_archetypes` field), and
> that becomes *relevance weighting* over the catalog, not a hard filter. Each domain judge
> (Stage 3) pulls the relevant per-domain slices from several archetypes. The human can
> still add/remove archetypes and mark domains N/A; versioned as the **Coverage Profile**.

### Stage 2 — Requirement tagging  (faceted, multi-label)

For every requirement across all project docs, assign **multi-label tags** (§5) —
coverage-domain, NFR-type, capability/goal, **standard grounding**, and **source-document**.
A transversal requirement carries several tags across facets. No forced 1:1 classification.

### Stage 3 — Domain-judge panel (the coverage engine)

A **panel of ~16 specialized coverage judges — one per domain** (`catalog/domains.json`) —
the set-level analog of the per-requirement INCOSE C1–C9 judge fan-out. Each judge, in
parallel, for its domain:
1. **Decomposes** the input — what the requirement set actually *says* in this domain
   (grounds first, so it doesn't flood the user with generic best-practice).
2. **Consults archetype knowledge** — the domain's slice of the relevant archetypes
   (`catalog/project_types/*` weighted by Stage-1 relevance) + the domain's standard-pack
   leaves.
3. **Emits** (a) domain **coverage** (which expected concerns are addressed vs missing),
   (b) **gaps + pointed questions** with grounding, and (c) **enrichments** to the problem
   statement (domain concerns the user never stated — this is how a one-sentence brief gets
   built out).
Then a **synthesis/dedup pass** (like the existing reviewer step) merges overlapping /
contradictory candidates across judges, resolves cross-domain overlap, prioritizes by
severity, and keeps the **questions + confidence, human-ratified** contract.

- **Later:** within-requirement completeness (EARS unwanted-behavior, QA scenarios, smells)
  and traceability completeness (orphans / childless parents) layer on as extra judges.

### Output shape (`coverage.json`)

```
coverage:
  profile_ref{ types[], version }
  problem_statement_ref{ version, overall_confidence }
  matrix[]        # per expected leaf: { facet, leaf, standard_pack, expected, found, status, req_ids[] }
  gaps[]          # { title, severity, layer:A|B, grounding[], addressed_capability?, question, source_obstacle? }
  questions[]     # ranked clarifying / interrogation questions
  confidence      # overall, explicitly caveated
```

Gaps/questions render **criticality-colored** (reuse the `--s1..--s5` scale) and carry
their **grounding** tags, so every finding is auditable ("why is this flagged?").

---

## 5. Tag model (faceted, multi-label)

A requirement is transversal by carrying tags across facets simultaneously:

| Facet | Example values | Source |
|---|---|---|
| `quality` | `iso-25010:2023/Security/Confidentiality` | ISO 25010:2023 |
| `nfr` | `volere/Operational` | Volere |
| `capability` | `goal:checkout-flow` | Problem Statement goals |
| `grounding` | `owasp-asvs:V3`, `29148:set-complete` | the standard that justified the tag |
| `source_document` | `doc:<document_id>` | provenance (traceability) |
| `stakeholder` / `lifecycle` | `stakeholder:operator`, `phase:runtime` | optional |

Coverage math is per-facet: *for each expected tag in the Profile, is the count ≥ its
threshold?* The **`grounding`** facet is what makes findings filterable/auditable and lets
standards be swapped as **pluggable packs**.

---

## 6. Standards stack (current editions) — pluggable reference packs

Each pack is a catalog file mapping a standard to coverage leaves + matching heuristics;
the active Profile switches packs on/off.

- **ISO/IEC 25010:2023** — product quality, **9** characteristics. Note the renames
  (Usability→**Interaction Capability**, Portability→**Flexibility**) and the **new
  Safety** characteristic (operational constraint, risk identification, fail-safe, hazard
  warning, safe integration) — a real blind spot in the original URCF draft.
- **ISO/IEC 25019:2023** — Quality-in-use (effectiveness, efficiency, satisfaction,
  freedom-from-risk): the "adequate *for users/context*" axis.
- **ISO/IEC 25012 / 25024** — data quality (makes the Functional & Data Integrity domain rigorous).
- **ISO/IEC/IEEE 29148:2018** — requirements *set* characteristics (complete-as-a-set,
  consistent, feasible, comprehensible, validatable) + SRS section skeleton as a structural
  checklist.
- **Volere** — operational / legal / cultural / mandated-constraint types ISO under-covers.
- **Domain oracles** — OWASP ASVS (security), WCAG 2.2 (accessibility), GDPR/HIPAA (privacy).

The seed **URCF** taxonomy (`data/coverage/unified_method.md`) becomes one starter pack,
reconciled to 25010:2023 (+Safety).

---

## 7. Information architecture / navigation

```
Projects ▾                      # landing / switcher; create project
  └─ (current project)
       Documents                # upload 1..n; NO auto-analysis; ▶ Run Quality / ▶ Run Coverage
       Requirements Quality     # own page + menu — TABS, no sliding panels:
                                #   [ Dashboard | Overlaps | Set-level ]
       Requirements Coverage    # own page + menu — TABS:
                                #   [ Problem Statement | Profile | Coverage Matrix | Gaps & Questions ]
Live editor                     # single-req quality tool, project-independent (unchanged)
```

- **Overlaps** returns under **Requirements Quality** as a **tab** in the same page — the
  standalone `overlaps.html` and any sliding/overlay panels are retired.
- Upload is **project-scoped** and multi-file; it stages material only.
- **Auth** unchanged model: create project / upload / run = gated active surface; browsing
  results public.

---

## 8. API surface (additions)

```
# Projects
POST   /projects                      {name}                       -> project
GET    /projects                                                   -> [projects]
GET    /projects/{pid}                                             -> project (+ docs, refs)
# Documents (project-scoped, multi-file, no auto-analysis)
POST   /projects/{pid}/documents      multipart 1..n               -> [documents]
GET    /projects/{pid}/documents
# Problem framing / profile
POST   /projects/{pid}/problem-statement:generate                 -> draft (streamed)
PUT    /projects/{pid}/problem-statement                           -> save edited/ratified version
GET/PUT /projects/{pid}/coverage-profile                          -> resolved reference (+ overrides)
# Project-type catalog
GET    /project-types                                              -> catalog
# Explicit analyses
POST   /projects/{pid}/quality:run     {document_ids?}            -> quality_run (streamed)
POST   /projects/{pid}/coverage:run                               -> coverage_run (streamed)
GET    /projects/{pid}/quality/{run}    /coverage/{run}           -> results
```

Streaming reuses the existing socket.io job model (`join {run_id}`; `stage`,
`requirement`, `problem_statement`, `coverage`, `done` events). The Live-editor `assess`
event is unchanged.

---

## 9. Reuse & constraints

- **Reuse:** `reqqa.jobs` streaming core, INCOSE judges on agent_server (:7701), the
  dashboard chart/master-detail + criticality-color patterns, the custom dropdown & nav
  components, the single-container deploy (`reqqa.orchestration_api`, host :7802).
- **Constraint:** every frontend change still requires a container rebuild (frontend is
  COPYed into the image; only writable data dirs are bind-mounted). `Cache-Control:
  no-cache` on html/js/css is already in place.
- **Honesty principle (repeated):** coverage surfaces **gaps + questions with confidence**,
  not a completeness score. The human owns the Problem Statement and Profile and can revise
  them — and re-run — at any time.

---

## 10. Non-goals (now) / future

- Automatic acceptance of inferred problem statements (always human-ratified).
- Coverage Layers C/D (within-req completeness, traceability) — after A/B prove out.
- Editing the archetype catalog via UI (authored via files first).
- Re-import of legacy single-doc scorecards into projects (a later utility).
