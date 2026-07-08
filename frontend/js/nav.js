/* Shared top nav for every reqoach page. Projects mode: brand → Projects, a
 * current-project chip (switcher), then the project-scoped pages. Owns the theme
 * (flips `data-theme`, persists to localStorage, calls window.reqoachRedraw() and
 * dispatches "reqoach:theme"). Theme is initialised before this runs by a one-line
 * inline <head> script, so there's no flash.
 *
 * Current project lives in localStorage: reqoach-project (id) + reqoach-project-name.
 * Project-scoped links carry ?project=<id> so a page always knows its project. */
(function () {
  "use strict";
  const ls = k => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const pid = ls("reqoach-project");
  const pname = ls("reqoach-project-name");
  const q = pid ? "?project=" + encodeURIComponent(pid) : "";

  // Project-scoped pages carry the current project; Live editor is project-independent.
  const PAGES = [
    { href: "documents.html" + q, label: "Documents",            match: "documents.html" },
    { href: "index.html" + q,     label: "Requirements Quality",  match: "index.html" },
    { href: "coverage.html" + q,  label: "Requirements Coverage", match: "coverage.html" },
    { href: "editor.html",        label: "Live editor",           match: "editor.html" },
  ];
  const cur = location.pathname.split("/").pop() || "index.html";

  const nav = document.createElement("nav");
  nav.className = "reqoach-nav";
  nav.innerHTML =
    '<a class="brand" href="projects.html">reqoach</a>' +
    `<a class="proj${pid ? "" : " none"}" href="projects.html" title="Switch / manage projects">` +
      (pid ? esc(pname || "project") : "Select project…") + "</a>" +
    PAGES.map(p =>
      `<a class="item${p.match === cur ? " active" : ""}" href="${p.href}">${p.label}</a>`
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
