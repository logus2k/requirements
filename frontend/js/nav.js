/* Shared top nav for every reqoach page. Injects a consistent menu bar (brand +
 * page links + theme toggle), highlights the current page, and owns the theme:
 * it flips `data-theme`, persists to localStorage ("reqoach-theme"), and both
 * calls window.reqoachRedraw() (charts that read CSS vars) and dispatches a
 * "reqoach:theme" event (so pages can re-render on their own).
 *
 * Theme is initialized *before* this runs by a one-line inline script in each
 * page's <head>, so there's no flash and charts render in the right theme.
 *
 * Monitor is intentionally not a top-level link — it is per-job (needs ?job=)
 * and is reached from the ingestion flow. */
(function () {
  "use strict";
  const PAGES = [
    { href: "index.html",    label: "Dashboard" },
    { href: "overlaps.html", label: "Overlaps" },
    { href: "ingest.html",   label: "Assess a document" },
    { href: "editor.html",   label: "Live editor" },
  ];
  const cur = location.pathname.split("/").pop() || "index.html";

  const nav = document.createElement("nav");
  nav.className = "reqoach-nav";
  nav.innerHTML =
    '<a class="brand" href="index.html">reqoach</a>' +
    PAGES.map(p =>
      `<a class="item${p.href === cur ? " active" : ""}" href="${p.href}">${p.label}</a>`
    ).join("") +
    '<span class="spacer"></span>' +
    '<button class="tbtn" id="reqoach-theme" title="Toggle light / dark">◐ Theme</button>';
  document.body.prepend(nav);

  document.getElementById("reqoach-theme").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("reqoach-theme", t); } catch (e) {}
    if (typeof window.reqoachRedraw === "function") window.reqoachRedraw();
    window.dispatchEvent(new CustomEvent("reqoach:theme", { detail: t }));
  });

  // If the page has a connection LED (#status), relocate it into the nav so it sits
  // in the SAME position on every page — at the far right, after the Theme button.
  const led = document.getElementById("status");
  if (led) { nav.appendChild(led); led.removeAttribute("hidden"); }
})();
