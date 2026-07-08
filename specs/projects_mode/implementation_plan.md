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

## Phase 3 — Catalog + Problem Framing (reference plumbing) — compose model

Build the reference the Coverage engine consumes. Still no coverage verdict yet.

**Backend**
- **Catalog — BUILT (2026-07-08)** at `catalog/`: `domains.json` (16 coverage domains),
  `project_types/*.json` (20 archetypes as system-type × domain knowledge), `standards/*.json`
  (6 packs). See `catalog/README.md`. Add `GET /catalog/{domains,archetypes,standards}`.
- **Problem-Framing agent — BUILT (2026-07-08)** as the `problem_framing` preset on
  agent_server (structured, provenance-graded Problem Statement + `candidate_archetypes` +
  clarifying questions; adaptive extract-vs-elaborate; verified on rich + one-sentence input).
  Remaining: `reqqa` integration (gather project doc text → call preset), endpoints
  `POST /projects/{pid}/problem-statement:generate`, `PUT …/problem-statement`,
  `GET/PUT …/coverage-profile` (candidate archetypes + overrides), persistence + versioning.

**Frontend**
- **Requirements Coverage** page, tabs `[ Problem Statement | Profile | … ]`.
- **Problem Statement** tab: structured, editable fields with provenance badges
  (stated/inferred/assumed + confidence), clarifying-question list, "Ratify" action.
- **Profile** tab: the candidate archetypes (with confidence) + active standard packs,
  editable (add/remove archetypes, mark domains N/A, adjust emphasis). Versioned.

**Done when:** Frame-problem drafts a structured, provenance-graded Problem Statement +
editable Profile; human edits/ratifies; both persist and version. Verified (thin → assumptions
flagged; rich → extraction-heavy) — the preset already demonstrates this.

---

## Phase 4 — Domain-judge panel (the coverage engine)

The real coverage verdict — a fan-out of ~16 domain-expert judges (one per `domains.json`
domain), the set-level analog of the C1–C9 judges.

**Backend**
- One coverage judge per domain (agent_server presets), run in parallel over the project's
  requirement set + Problem Statement. Each: **decompose** input in its domain → **consult**
  the domain's slice of the relevant archetypes (weighted by `candidate_archetypes`) + the
  domain's standard-pack leaves → emit domain **coverage + gaps + questions + enrichments**,
  each with **grounding**. Then a **synthesis/dedup** pass across judges.
- `POST /projects/{pid}/coverage:run` (streamed, per-domain progress) → `coverage.json`.

**Frontend**
- **Coverage** tab: domain heatmap (16 domains × status), grounding legend, click-through to
  covering/absent requirements. Honest metrics: covered/expected + open items — **no "%."**

**Done when:** a coverage run produces per-domain coverage + a deduped, grounded gap/question
list. Verified with a real run.

---

## Phase 5 — Synthesis, obstacle depth & problem-statement enrichment

Deepen the panel's output.

**Backend**
- Goal/**obstacle analysis** per capability folded into the relevant domain judges (unmitigated
  obstacle → candidate missing requirement + question). Judges also **enrich the Problem
  Statement** (domain concerns the user never stated) — the one-sentence-input build-out.
- Synthesis prioritizes by severity, resolves cross-domain overlap, sets overall confidence.

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
- Expand standard packs (25019, full ASVS/WCAG/GDPR); UI editor for the archetype catalog.
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
