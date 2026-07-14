/* pdf-viewer.js — minimal, single-page-on-demand PDF.js viewer for reqoach.
 *
 * Adapted from ~/env/assets/cv/widget/cv-pdf-viewer.js. Requirements come from
 * large SRS PDFs, so instead of rendering every page (as the CV viewer does for
 * a 2-page CV) we render ONLY the page a requirement lives on and draw its
 * bounding box — the bbox is the same Docling PDF-user-space rect reqoach stores
 * in `provenance.bbox` ([x0,y0,x1,y1], origin bottom-left). PDF.js's
 * `viewport.convertToViewportRectangle` handles the y-flip + scale, so no manual
 * coordinate remapping is needed.
 *
 * Public API on window.reqoachPdf:
 *   init({ src, host }) -> Promise<numPages>   load (cached per src)
 *   showPage(pageNo, regions)                  render one page + highlight bboxes
 *   clear()                                    empty the host
 *   regions: [{ page_no, bbox: [x0,y0,x1,y1] }, ...]
 */
import * as pdfjs from "../vendor/pdfjs/pdf.min.mjs";

// Resolve the worker relative to THIS module so it works under /reqoach/ too.
pdfjs.GlobalWorkerOptions.workerSrc =
  new URL("../vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).toString();

const HIGHLIGHT_CLASS = "cv-pdf-highlight";
let _doc = null, _src = null, _host = null;

async function init({ src, host }) {
  _host = (typeof host === "string") ? document.querySelector(host) : host;
  if (!_host) throw new Error("reqoach-pdf: host not found");
  if (_src !== src || !_doc) {          // reuse the loaded document across pages of the same doc
    _src = src;
    _doc = await pdfjs.getDocument({ url: src }).promise;
  }
  return _doc.numPages;
}

// Fit the page to the host's column width (the host's parent is the scroll column).
function _scaleFor(viewport) {
  const stage = _host.parentElement || _host;
  const availW = Math.max(140, (stage.clientWidth || 320) - 22);
  return Math.min(2.0, Math.max(0.4, availW / viewport.width));
}

async function showPage(pageNo, regions) {
  if (!_doc || !_host) return false;
  _host.innerHTML = "";
  const page = await _doc.getPage(Number(pageNo));
  const scale = _scaleFor(page.getViewport({ scale: 1 }));
  const viewport = page.getViewport({ scale });

  const wrapper = document.createElement("div");
  wrapper.className = "cv-pdf-page";
  wrapper.style.width = viewport.width + "px";
  wrapper.style.height = viewport.height + "px";

  const canvas = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * dpr);
  canvas.height = Math.floor(viewport.height * dpr);
  canvas.style.width = viewport.width + "px";
  canvas.style.height = viewport.height + "px";

  const overlay = document.createElement("div");
  overlay.className = "cv-pdf-overlay";

  wrapper.appendChild(canvas);
  wrapper.appendChild(overlay);
  _host.appendChild(wrapper);

  const ctx = canvas.getContext("2d");
  const transform = dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null;
  await page.render({ canvasContext: ctx, viewport, transform }).promise;

  let first = null;
  for (const r of (regions || [])) {
    if (!r || !r.bbox) continue;
    if (r.page_no != null && Number(r.page_no) !== Number(pageNo)) continue;
    const [x0, y0, x1, y1] = r.bbox.map(Number);
    const [vx0, vy0, vx1, vy1] = viewport.convertToViewportRectangle([x0, y0, x1, y1]);
    const el = document.createElement("div");
    el.className = HIGHLIGHT_CLASS;
    el.style.left = Math.min(vx0, vx1) + "px";
    el.style.top = Math.min(vy0, vy1) + "px";
    el.style.width = Math.abs(vx1 - vx0) + "px";
    el.style.height = Math.abs(vy1 - vy0) + "px";
    overlay.appendChild(el);
    if (!first) first = el;
  }
  (first || wrapper).scrollIntoView({ behavior: "smooth", block: "center" });
  return true;
}

function clear() { if (_host) _host.innerHTML = ""; }

window.reqoachPdf = { init, showPage, clear };
