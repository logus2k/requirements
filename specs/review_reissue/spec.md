# Review & Reissue — Technical Spec

Status: DRAFT for approval (2026-07-14). No code until signed off.
Related: [[projects-mode]], `specs/projects_mode/`. Owner surface: reqoach (`reqqa.orchestration_api`, host :7802).

---

## 1. Purpose

Turn reqoach from an **analyzer** ("here is what's wrong with each requirement") into a
**closed-loop remediation tool**: a reviewer walks the requirements one by one, applies or
adapts the suggested fixes with **live re-scoring**, drives the project up to a chosen
**score threshold**, and **reissues a corrected specification** document.

The analysis half already exists (Quality run → per-requirement C1–C9 scores + rule findings
+ `review` rewrites/advisories). This feature adds the **review loop**, **review state**, the
**source-PDF context view**, the **live revised-spec preview**, the **threshold/progress**
readout, and the **export**.

---

## 2. Scope & non-goals

**In scope (v1):**
- A per-(project, quality-run) **review session** with persisted per-requirement state.
- A **Reviewer's View** that reuses the **Live Editor** as the edit + live-rescore surface.
- Two context tabs beside the editor: **Source PDF** (original, current requirement
  highlighted at its bbox) and **Revised Spec** (live Markdown preview of the corrected doc).
- A **threshold** definition + a **progress gauge** (projected project score, # below target).
- **Export** the revised spec: Markdown first, then **Markdown → PDF** via headless Chromium
  with a clean house template.

**Non-goals (v1):**
- **No in-place editing of the original PDF.** In-place PDF text editing (reflow, fonts,
  layout) is fragile; we never mutate the source. It stays the reference.
- **No reproduction of the original document's exact visual layout/branding.** Ingest kept
  *content + logical structure* (text, `section_path`, order, tables/headings, page/bbox), not
  the presentation template. The reissued PDF matches the original in **structure and content**,
  in our (or a supplied) template — not pixel-for-pixel. (See §11.)
- **Single reviewer.** No concurrent multi-user review/locking in v1.

---

## 3. User workflow (the loop)

1. From a project's **Quality** run, the reviewer clicks **Review this run** → enters the
   Reviewer's View (bound to that `project_id` + `run_id`).
2. **Requirements navigator** (left): every requirement with a **status chip** + current score;
   sortable/filterable (e.g. "show only below threshold", "only unreviewed"). Keyboard nav
   (↑/↓, "next unreviewed").
3. For the **current requirement**:
   - See original text, C1–C9 scores, rule findings, and the fix **suggestions** (rewrites +
     advisories).
   - **Edit via the embedded Live Editor**: one click applies a suggested rewrite, or the
     reviewer adapts the text freely; the score **re-computes live** (fast-lane judges + instant
     rule flags).
   - Context tabs: **Source PDF** (page + bbox highlight) and **Revised Spec** (live preview).
   - Set a **status**: *Accept original* / *Accept fix* / *Edited* / *Skip*.
4. **Progress gauge** updates continuously: reviewed N/M, project score **original → projected**,
   # still below threshold, threshold met?.
5. When ready (threshold met or on demand): **Export** the revised spec → Markdown and/or PDF.

---

## 4. UX / layout

```
┌ Reviewer's View — <Project> · run <id> ───────────────────────── [Export ▼] ┐
│ threshold: every req ≥ 3.0   ·   project 3.4 → 4.1 (proj.)  ·  12/386 · 31 below │
├───────────────┬──────────────────────────────┬──────────────────────────────┤
│ REQUIREMENTS  │  REQUIREMENT (Live Editor)    │  CONTEXT                     │
│ (navigator)   │  ┌ text (editable) ─────────┐ │  [ Source PDF | Revised Spec]│
│ ▸REQ-0005 ✎3.1│  │ The system shall ...      │ │                              │
│  REQ-0006 ✓4.2│  └───────────────────────────┘ │  ┌ pdf page, bbox highlighted┐│
│  REQ-0008 •—  │  Characteristics radar / bars  │  │  ....[ HIGHLIGHT ]....     ││
│  ...          │  Rules radar / findings        │  │                           ││
│               │  Suggestions (click to apply)  │  └───────────────────────────┘│
│ filter: below │  [Accept orig][Accept fix][Save edit][Skip]  [‹ Prev][Next ›] │
└───────────────┴──────────────────────────────┴──────────────────────────────┘
```

- **Status chips:** `•` unreviewed, `✎` edited, `✓` accepted (orig or fix), `⤼` skipped.
- **Center = the Live Editor**, seeded with the current requirement and reporting back its
  final text + overall score. See §7 for the embed strategy.
- **Right = context tabs** (§8, §9). The *Source PDF* tab is hidden/disabled for requirements
  whose source isn't a PDF or that lack `page`/`bbox`.

---

## 5. Data model

Per (project, run) review state, stored under the project (bind-mounted `store/`, so no rebuild
to change data):

```
store/projects/<pid>/reviews/<run_id>/review.json
{
  "run_id": "...", "project_id": "...",
  "threshold": { "mode": "each_ge" | "avg_ge" | "pct_ge", "value": 3.0, "pct": 90 },
  "updated_at": "<iso>",
  "requirements": {
    "REQ-0005": {
      "status": "unreviewed|accepted_original|accepted_fix|edited|skipped",
      "original_text": "…",         // snapshot from the scorecard at session start
      "final_text": "…",            // == original unless changed
      "note": "",                   // optional reviewer note
      "overall_before": 3.1,        // from the scorecard
      "overall_after": 4.3,         // last live re-score of final_text (null if not re-scored)
      "reviewed_at": "<iso|null>"
    }, ...
  }
}
```

- Keyed by `req_id` (stable within a run; note the ingest `#n` de-dupe suffix keeps ids unique).
- `original_text` is snapshotted so the session is stable even if the run is re-produced.
- `projects.py` additions: `get_review(pid, run)`, `save_review(pid, run, doc)`,
  `upsert_req_review(pid, run, req_id, patch)`, `get_threshold`/`set_threshold`.

---

## 6. Reusing the Live Editor / realtime assessor

The realtime assessor is already the review engine. `reqqa.assess.iter_assessment(text, review=True)`
streams, over socket.io (event `assess`):
- `{type:"deterministic", findings:[…]}` (~instant),
- `{type:"characteristic", data:{…}, i, n:9}` (fast-lane C3·C4·C5·C7 first),
- `{type:"review", data:{rewrites:[…], advisories:[…]}}` (for defective reqs),
- `{type:"done", overall:<float|null>}`.

`editor.html` already: renders the text field + Characteristics/Rules radars + rule findings +
a **Suggestions** panel where **clicking a rewrite applies it and re-assesses**. That is the
per-requirement remediation loop verbatim.

**Reuse strategy (DECIDED — backend only):** The Reviewer's View reuses **only the backend
assessor** — the `assess` socket event + `iter_assessment` — which already streams
deterministic/characteristic/review/done for any text, model E4B, project-independent. The
review page has its **own bespoke frontend** (§4's 3-pane layout) with its **own** editor pane
(text field + radars + rule findings + suggestions + apply-rewrite) implemented against that
socket protocol. We do **not** reuse or port editor.html's UI, and we do **not** extract its JS
into a shared module — the frontend is new and different. (editor.html stays as the standalone
scratchpad editor; only the server-side assessor is shared.)

---

## 7. Source PDF context tab  *(foundation already built)*

- Viewer: `frontend/js/pdf-viewer.js` — single-page, on-demand (renders only the requirement's
  page; SRS PDFs are large). API `init({src,host}) → numPages`, `showPage(pageNo, regions)`,
  `clear()`. Reuses the CV example's coordinate math (`convertToViewportRectangle`, Docling
  bbox = same space reqoach stores).
- Source bytes: `GET /projects/{pid}/documents/{did}/source` (**built + verified**: 200,
  `application/pdf`).
- On requirement change: `showPage(prov.page, [{page_no: prov.page, bbox: prov.bbox}])` using
  `provenance.source_document_id` for the URL. Hidden when source isn't a PDF / lacks page+bbox.
- Still TODO: CSS (`frontend/css/pdf-viewer.css` — `.cv-pdf-page/.cv-pdf-overlay/.cv-pdf-highlight`)
  + the include + the tab wiring. Viewer is **written but unwired/unverified**.

---

## 8. Revised Spec (Markdown) tab — the live preview + export source

**DECIDED: reissue = requirements + original context** (not requirements-only). The reissued doc
**reconstructs the original document's flow** — its headings, narrative/intro prose, and tables in
order — and **substitutes the corrected `final_text` wherever a block is a requirement**.

This requires data we don't persist today (the pipeline keeps only *accepted requirements*, not the
full document). New requirement:
- **Persist the full ingested item stream** per document at quality-run time →
  `store/projects/<pid>/quality/<run>/ingest.json` = ordered `SourceItem`s (text, `block_type`,
  `section_path`, `page`, `order`, `char_span`). This is the document "skeleton." (Alternative:
  re-ingest at export — slower, needs the Docling service; **persisting at run-time is recommended**.)
- **Map requirement → its source block(s)** via `order`/`char_span` + lineage (`origin`,
  `was_compound`, `derived_from`). Where a requirement was **assembled/split** (compound sentence,
  table-row + label), reinsertion is **best-effort**: replace the primary source span with
  `final_text`; non-requirement blocks pass through unchanged.
- **Live update**: the preview re-renders as review state changes; Markdown→HTML for preview.
- Preview and export consume the **same** assembled artifact.

**Goal (user, DECIDED):** the export is a **content-complete replacement** of the original — it can
stand in for the previous document **in terms of content** — accepting that **formatting/layout is
not replicated** (restyled in our template).

**Fidelity boundary (reaffirmed):** we reconstruct all **textual content** — headings, narrative
prose, requirements (corrected), and **tables** (Docling → Markdown tables) — in original order. We
do **NOT** reproduce the original's **visual layout/template**. The **one content nuance to settle
(§14.7):** **figures/images** — either **extract & embed** them from the source PDF (Docling can emit
figure crops; adds work + weight) or represent them as **captioned placeholders / references**
("[Figure 3: …]"). Text-content completeness is unaffected either way.

---

## 9. Threshold & progress

- **Modes:** `avg_ge` (project average ≥ value — the dashboard's "AVG QUALITY / 5"),
  `each_ge` (every requirement ≥ value), `pct_ge` (≥ pct% of requirements ≥ value).
- **Default (DECIDED):** `avg_ge`, value **4.3**, **configurable per project** (a project-level
  setting inherited by its review sessions; overridable per session). Interpreting "project score
  threshold" as the project average; switch mode to `each_ge` if a per-requirement floor is wanted.
- **Projected project score:** recompute aggregates using `overall_after` for reviewed reqs,
  `overall_before` otherwise (the **live** basis). Gauge shows: reviewed N/M, current→projected
  average, # below threshold, met? / how many remain.
- **"Re-score all" (optional):** a button that re-runs full scoring over every `final_text` for
  an **authoritative** scorecard (progress + abort, reuses the pipeline). Not required — export
  works on the live basis at any time.

---

## 10. Export (reissue)

- **Assemble** the revised Markdown (title block + sections from `section_path` + numbered
  requirements with IDs + optional metadata).
- **Pipeline (DECIDED — server-side quality PDF):** Markdown → HTML (+ house **CSS template**) →
  **PDF generated server-side** and offered as a **download**. No browser print. This requires
  adding a **PDF engine to the reqoach image** (verified 2026-07-14: none present today).
  **Engine choice is the one open sub-decision (§14.6):**
  - **WeasyPrint (recommended):** HTML+CSS → PDF in-process; strong **paged-media** support
    (`@page` margins, running headers/footers, CSS-counter page numbers, TOC). Adds system libs
    (pango/cairo/gdk-pixbuf/harfbuzz) to the image — moderate weight. Deterministic, template-driven.
  - **Bundled Chromium (Playwright):** best CSS fidelity, but heavy (~400 MB) in the image.
  - **Pandoc + LaTeX / Typst:** great typography, different (non-HTML/CSS) templating path.
  Markdown/HTML remain available as lighter export formats alongside the PDF.
- **Endpoint:** `POST /projects/{pid}/reviews/{run}/export?format=md|pdf` → returns the file.
- **Templates (DECIDED):** v1 ships **one clean built-in SRS template** (title page, numbered
  sections from `section_path`, requirement blocks with IDs, TOC, page numbers). **No
  customization in v1** — custom CSS/branding is deferred to a later milestone (M5).
- **Layout-fidelity caveat (explicit):** the output matches the original in **structure and
  content**, not its exact visual design/branding (see §2 non-goals, §11).

---

## 11. On "same layout as the original" (recorded decision)

Not achievable from ingested data: Docling captured content + logical structure, **not** the
presentation layer (fonts, margins, headers/footers, corporate template), and revised text
repaginates anyway. We therefore **regenerate a clean, consistently-styled** spec that mirrors
the original's **organization** (sections, ordering, IDs, tables). If a specific look is required,
the supported path is a **user-supplied template/CSS**, not reverse-engineering the source PDF.

---

## 12. Backend endpoints (new unless noted)

| Method | Path | Purpose |
|---|---|---|
| GET | `/projects/{pid}/reviews/{run}` | full review state (creates an empty one seeded from the scorecard on first GET) |
| PUT | `/projects/{pid}/reviews/{run}/requirements/{req_id}` | upsert one requirement's review (status/final_text/note/overall_after) |
| GET/PUT | `/projects/{pid}/reviews/{run}/threshold` | read/set threshold |
| GET | `/projects/{pid}/reviews/{run}/markdown` | assembled revised Markdown (preview + export source) |
| POST | `/projects/{pid}/reviews/{run}/export?format=md\|pdf` | generate & return the reissued doc |
| GET | `/projects/{pid}/documents/{did}/source` | raw source bytes — **built + verified** |
| (socket) | `assess` | live single-requirement scoring — **exists** |

---

## 13. Frontend

- New **`frontend/review.html`** (or a **Review** tab within the project) — the workspace of §4.
- Reuse: `pdf-viewer.js` (+ new `css/pdf-viewer.css`), the extracted `req-editor.js` core, a
  small Markdown renderer.
- Entry point: a **"Review this run"** button on the Quality dashboard, and/or a nav item.
- The pipeline **Overview** could show a 5th stage/among actions: *Review & Reissue*.

---

## 14. Open decisions (need your call before/at build)

1. **Live-editor reuse:** ✅ DECIDED — **reuse the BACKEND assessor only** (`assess` socket +
   `iter_assessment`, already project-independent). The Reviewer's View has its **own bespoke
   frontend** (the 3-pane layout) that talks to that same socket — it does **not** reuse or port
   editor.html's UI. No frontend module extraction; the review page implements its own editor pane.
4. **Review location:** ✅ DECIDED — **dedicated page** (`review.html`) launched via a
   **"Review this run"** button on the Quality dashboard (also from the pipeline Overview).
2. **Default threshold:** ✅ DECIDED — **4.3, configurable per project**; interpreted as
   `avg_ge` (project average). Confirm if a per-requirement floor (`each_ge`) was intended instead.
3. **Export template:** ✅ DECIDED — v1 ships **one clean built-in SRS template**, no
   customization; custom CSS/branding deferred to M5.
4. **Where Review lives:** new top-level page launched from a Quality run (recommended) vs a
   tab inside the existing dashboard.
5. **Re-score:** ✅ DECIDED — **live scores are the working basis** (export proceeds anytime on
   the `overall_after`/`overall_before` mix captured so far). A **"Re-score all"** pass is
   **available but optional** — re-runs full scoring over every `final_text` for an authoritative
   scorecard (progress + abort, reusing the pipeline). Never mandatory to export.

---

6. **PDF export mechanism:** ✅ DECIDED — **server-side quality PDF download** (NOT browser print).
   Requires adding a PDF engine to the image. **Open sub-decision:** which engine — **WeasyPrint**
   (recommended: HTML+CSS, paged-media, moderate weight) vs bundled Chromium (heavy) vs Pandoc/Typst.
   Decide by **M4**; not M1-blocking.
7. **Reissue scope:** ✅ DECIDED — **requirements + original context**, a **content-complete
   replacement** of the original (formatting not replicated). Requires persisting the full ingest
   stream + reconstruction (§8). **Open sub-decision (M4):** **figures/images** — extract & embed vs
   captioned placeholders.
8. **Review scope:** ✅ DECIDED — this **Review & Reissue = the QUALITY / correction loop**
   (per-requirement C1–C9 + rules → fix → reissue). **Coverage is a SEPARATE page/feature** — a
   distinct *completion*-oriented UI (add missing requirements to fill gaps), its own future spec.
   Framing: **quality = correction, coverage = completion.** (Set-level overlaps: out of v1 here.)
9. **Auth timing:** ✅ DECIDED — **build M1 now**, then gate **all** write endpoints (existing +
   new review) in **one pass before go-live**. (Prod writes remain ungated meanwhile — already
   the case today.)

### Resolved-by-verification (no longer open)
- **Score-formula consistency:** ✅ the live assessor's `_overall` = `round(mean(C1–C9), 2)`,
  identical to the pipeline's `_finalize_scores` — projected aggregate is consistent.
- **`section_path` is a flat string** (e.g. `"1) User Registration and Profile Management"`), not
  a nested hierarchy → Markdown assembly groups requirements under flat section headings.
- **Requirement ordering:** the scorecard's `requirements[]` is already in source order; `_order`
  is stripped from the emitted objects, so assembly uses **array order** (no separate sort key).
- **Save/edit semantics (M1 default, unless you object):** the status buttons (Accept original /
  Accept fix / Save edit / Skip) are the explicit save. An in-progress edit is **auto-saved as an
  `edited` draft** on navigation so nothing is lost; `final_text` is always the source of truth.
- **Session vs re-run:** a review session is bound to one `run_id`; re-running Quality creates a
  new run → a fresh review session (the prior one is preserved).

## 15. Risks / caveats

- **Re-score latency** (E4B) per edit — mitigated by fast-lane ordering (already) and running the
  costly reviewer only on pause / on demand (`review=False` fast path exists).
- **Score volatility:** LLM scores can vary run-to-run; we store `overall_after` at review time
  and treat it as the record. Projected aggregate is indicative, not a re-run of the full pipeline.
- **Non-PDF / missing bbox:** the Source-PDF tab degrades gracefully (hidden with a note).
- **Auth:** the Reviewer's View is all writes (review state, export) — folds into the **existing
  open write-endpoint issue**; gate together with the other project writes.

---

## 16. Milestones

- **M1 — Review core:** state model + endpoints; requirements navigator + statuses; embed the
  live editor; accept/apply/edit/skip + persistence + Prev/Next.
- **M2 — Context tabs:** wire the staged Source-PDF viewer (+ css); Revised-Spec live preview.
- **M3 — Threshold & progress:** threshold config + projected-score gauge + filters.
- **M4 — Reissue:** assemble + export Markdown; then Markdown→PDF with the default template.
- **M5 — Later:** custom export template, DOCX, batch re-score, multi-reviewer.
