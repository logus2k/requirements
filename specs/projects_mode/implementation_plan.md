# Projects Mode — Implementation Plan

Status: Plan (pre-implementation)
Scope: phased, shippable build order for the architecture in
[technical_architecture.md](technical_architecture.md). Each phase is independently
demoable and leaves the app working. Every frontend change = rebuild the `reqoach`
container; every change verified with headless Chromium (0 console errors) as is standard
for this project.

Guiding order: **build the skeleton the analyses plug into first (Project + Documents +
nav), then make Quality explicit, then Problem-Framing, then Coverage A, then Coverage B.**
Coverage math (the hard/novel part) comes only after the workspace and reference plumbing
exist.

---

## Phase 1 — Project entity + project-scoped upload + nav restructure  *(no new analysis)*

The load-bearing skeleton. Nothing analyzes yet.

**Backend**
- `Project` + `Document` models; storage `store/projects/<pid>/…` (§3).
- Endpoints: `POST/GET /projects`, `GET /projects/{pid}`,
  `POST /projects/{pid}/documents` (multipart, **1..n**), `GET …/documents`.
- Ingestion of uploaded docs into requirements is **deferred** — upload only stores source +
  metadata. (Segmentation runs inside a Quality/Coverage run, Phase 2+.)

**Frontend**
- New **Projects** landing/switcher (create + list). Custom dropdown/nav components reused.
- Project context header; **Documents** view: multi-file upload, document list, and two
  disabled-until-implemented buttons **▶ Run Quality** / **▶ Run Coverage**.
- Restructure the top nav to the §7 shape. Retire standalone `overlaps.html`
  (its content returns as a tab in Phase 2).

**Data model changes:** introduce `project`, `document`; requirements gain
`provenance.source_document_id`.

**Done when:** create a project, upload several files into it, see them listed; nav reflects
the new IA; no analysis runs on upload. Verified headless (create → upload N → list; 0 errors).

---

## Phase 2 — Explicit, project-scoped Requirements Quality (+ tabs, + traceability)

Make today's INCOSE pipeline a **user-triggered** run over a project's document set, on its
own page.

**Backend**
- `POST /projects/{pid}/quality:run {document_ids?}` → runs segmentation + INCOSE quality
  **across all selected docs**, producing one `scorecard.json` (existing shape) under
  `quality/<run_id>/`. Set-level (overlaps, C10–C15) computed across the combined set.
- Each requirement carries `source_document_id` (traceability tag) end-to-end.
- Stream via socket.io (`join {run_id}`), reusing `reqqa.jobs`.

**Frontend**
- **Requirements Quality** page with **tabs** (no sliding panels):
  `[ Dashboard | Overlaps | Set-level ]`. Dashboard = today's consolidated master-detail
  (table | detail | suggestions). **Overlaps** = the retired page's content as a tab.
- Requirement rows/detail show their **source document** (from the traceability tag).
- Rule conformance, criticality-colored suggestions, radars, etc. carry over unchanged.

**Done when:** upload N docs → Run Quality → streamed scorecard renders on the Quality page;
Overlaps + Set-level are tabs; each requirement shows its source document. Verified headless.

---

## Phase 3 — Project-Type catalog + Problem Framing (reference plumbing)

Build the reference the Coverage math will consume. Still no coverage verdict yet.

**Backend**
- Seed **ProjectType catalog** (`catalog/project_types/*.json`) with a handful of archetypes
  (e.g., web-app, ML-service, data-pipeline, embedded/edge, internal-tool) — each with
  `matching_signals`, `expected_taxonomy`, `standard_packs`, `typical_capabilities`,
  `thresholds`. `GET /project-types`.
- Seed **standard packs** (`catalog/standards/*.json`): ISO 25010:2023 (+Safety), 29148:2018
  set-characteristics, Volere types, and the reconciled URCF starter; stubs for 25019 /
  ASVS / WCAG.
- **Problem Framing** stage (Collect→Synthesize→Grade→Ratify):
  `POST /projects/{pid}/problem-statement:generate` (streamed draft with provenance grades +
  clarifying questions), `PUT …/problem-statement` (save ratified/edited),
  `GET/PUT …/coverage-profile` (matched types + human overrides).
- Adaptive elaboration + circularity guard per §4.

**Frontend**
- **Requirements Coverage** page, tabs `[ Problem Statement | Profile | … ]` (Matrix/Gaps
  arrive in Phase 4/5).
- **Problem Statement** tab: structured, editable fields with provenance badges
  (stated/inferred/assumed + confidence), clarifying-question list, "Ratify" action.
- **Profile** tab: matched ProjectType(s), the active expected leaves & standard packs,
  editable (add/remove types, mark leaves N/A, adjust thresholds). Versioned.

**Done when:** Run Coverage (or a "Frame problem" action) drafts a structured, provenance-
graded Problem Statement + a matched, editable Profile; human can edit and ratify; both
persist and version. Verified headless (thin input → assumptions flagged; rich input →
extraction-heavy).

---

## Phase 4 — Coverage Layer A (taxonomy coverage + heatmap)

First real coverage verdict — category-level blind spots.

**Backend**
- Requirement **tagging** (faceted, multi-label) against the active Profile's taxonomy, each
  tag carrying its **grounding** standard. Persist on requirements + aggregate.
- Coverage computation Layer A → `coverage.json` `matrix[]` + category `gaps[]`.

**Frontend**
- **Coverage Matrix** tab: heatmap (domains × sub-characteristics; cell = count + status),
  grounding legend, click-through to the covering/absent requirements.
- Honest metrics: covered/expected leaves + open items — **no "coverage %."**

**Done when:** a project's requirements are tagged and the matrix shows thin/empty expected
leaves as gaps, each with its grounding standard. Verified headless.

---

## Phase 5 — Coverage Layer B (goal / obstacle analysis → gaps & questions)

The differentiator — "are they *enough for the problem*."

**Backend**
- From the Problem Statement capabilities, derive a lightweight goal tree; run **obstacle
  analysis** per goal; emit candidate missing requirements + questions with severity +
  grounding + `addressed_capability`. Merge into `coverage.json` `gaps[]` / `questions[]`.

**Frontend**
- **Gaps & Questions** tab: criticality-colored list (reusing `--s1..--s5`), grouped by
  capability/goal, each showing its obstacle and grounding; overall confidence banner
  (explicitly caveated).

**Done when:** coverage surfaces concrete "missing requirement because goal X has unhandled
failure mode Y" items a linter could never produce. Verified headless.

---

## Later (post-MVP)

- **Layer C** (within-requirement completeness: EARS unwanted-behavior, QA scenarios, smells).
- **Layer D** (traceability completeness) when goal→feature→req hierarchies exist.
- Expand standard packs (25019, full ASVS/WCAG/GDPR); UI editor for the ProjectType catalog.
- **Re-import** legacy single-doc scorecards into a project.
- Change-awareness: re-run coverage after edits with a **diff vs the last run**.

---

## Cross-cutting

- **Verification:** headless Chromium per phase (0 console errors); container rebuilt each
  frontend change; endpoints curl-checked.
- **Auth:** create/upload/run gated (existing oauth2 model); browsing public.
- **Reuse:** `reqqa.jobs` streaming, agent_server judges, dashboard/chart/dropdown/nav
  components, single-container deploy.
- **Non-negotiables:** upload never auto-analyzes; Problem Statement/Profile always human-
  ratifiable and versioned; coverage reports gaps+questions+confidence, not a score.
