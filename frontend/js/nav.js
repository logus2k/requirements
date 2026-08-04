/* Shared top nav for every reqoach page. Projects mode: brand → Projects, a
 * current-project chip (switcher), then the project-scoped pages. Owns the theme
 * (flips `data-theme`, persists to a cookie, calls window.reqoachRedraw() and
 * dispatches "reqoach:theme"). Theme is initialised before this runs by a one-line
 * inline <head> script, so there's no flash.
 *
 * The current project is carried in the URL (?project=<id>) — no client storage — and the
 * project name is fetched for the chip. Theme persistence uses a cookie, not localStorage. */
(function () {
  "use strict";
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Stateless: the project id comes ONLY from the URL (?project=…) — no localStorage. A page
  // opened without one sends the visitor to the project switcher. The name is fetched below.
  const pid = new URLSearchParams(location.search).get("project");
  const q = pid ? "?project=" + encodeURIComponent(pid) : "";

  const cur = location.pathname.split("/").pop() || "index.html";

  // Lifecycle phases (second row) — shown only when a project is selected. Requirements is a
  // section holding several pages; the future SDLC phases are shown but not yet linkable.
  const PHASES = [
    { label: "Overview",     href: "overview.html",     match: ["overview.html"] },
    { label: "Requirements", href: "index.html",        match: ["index.html", "review.html", "coverage.html", "editor.html"] },
    { label: "Architecture", href: "architecture.html", match: ["architecture.html"] },
    { label: "Planning",     href: "planning.html",     match: ["planning.html"],    soon: true },
    { label: "Development",  href: "development.html",   match: ["development.html"],  soon: true },
    { label: "Deployment",   href: "deployment.html",   match: ["deployment.html"],   soon: true },
    { label: "Operation",    href: "operation.html",    match: ["operation.html"],    soon: true },
  ];
  // Sub-tabs inside the Requirements section (third row). "Overlaps" is a VIEW of the Quality
  // page (index.html?view=overlaps); the others are their own pages.
  const urlView = new URLSearchParams(location.search).get("view") || "";
  const REQ_TABS = [
    { label: "Quality",  file: "index.html",    view: "" },
    { label: "Review",   file: "review.html",   view: "" },
    { label: "Overlaps", file: "index.html",    view: "overlaps" },
    { label: "Coverage", file: "coverage.html", view: "" },
    { label: "Editor",   file: "editor.html",   view: "" },
  ];
  const reqHref = t => t.file + (pid ? "?project=" + encodeURIComponent(pid) : "")
    + (t.view ? (pid ? "&" : "?") + "view=" + t.view : "");
  const reqActive = t => t.file === cur && (t.file !== "index.html" || (t.view || "") === urlView);

  // Row 1: brand (left); project selector + auth + theme (right).
  const nav = document.createElement("nav");
  nav.className = "reqoach-nav";
  nav.innerHTML =
    '<a class="brand" href="overview.html">FACTORY</a>' +
    '<span class="spacer"></span>' +
    '<div class="usermenu" id="reqoach-user"></div>';
  document.body.prepend(nav);

  // The active project is chosen from the banner title (#ptitle). The selector works with OR
  // without a project: with none, the title reads "Select a Project" (the home/Overview landing).
  const titleEl = document.getElementById("ptitle");
  if (titleEl) {
    titleEl.classList.add("project-select");
    titleEl.title = pid ? "Switch project" : "Select a project";
    if (!pid) titleEl.textContent = "Select a Project";
    let pop = null;
    const close = () => { if (pop) { pop.remove(); pop = null; } };
    titleEl.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (pop) { close(); return; }
      pop = document.createElement("div"); pop.className = "project-pop";
      pop.innerHTML = '<div class="pp-note">Loading…</div>';
      titleEl.appendChild(pop);
      try {
        const list = await fetch("/analyst/projects").then(r => r.ok ? r.json() : { projects: [] });
        const page = location.pathname.split("/").pop() || "overview.html";
        const rows = (list.projects || []).map(p =>
          `<a class="pp-item${p.id === pid ? " active" : ""}" href="${page}?project=${encodeURIComponent(p.id)}">${esc(p.name || "project")}</a>`).join("");
        pop.innerHTML = (rows || '<div class="pp-note">No projects</div>')
          + '<a class="pp-item pp-all" href="projects.html">Manage projects…</a>';
      } catch (err) { pop.innerHTML = '<div class="pp-note">Failed to load</div>'; }
    });
    document.addEventListener("click", close);
    // With a project, show its NAME in the banner on every page (same as Overview).
    if (pid) {
      fetch("/analyst/projects/" + encodeURIComponent(pid)).then(r => r.ok ? r.json() : null)
        .then(p => { if (p && p.name && !pop) titleEl.textContent = p.name; }).catch(() => {});
    }
  }

  // Row 2: lifecycle phases (only with a project selected).
  let subsEl = null;
  if (pid) {
    const phases = document.createElement("div");
    phases.className = "reqoach-phases";
    phases.innerHTML = PHASES.map(p => {
      if (p.soon) return `<span class="phase soon" title="Coming soon">${p.label}</span>`;
      const active = p.match.indexOf(cur) >= 0 ? " active" : "";
      return `<a class="phase${active}" href="${p.href}${q}">${p.label}</a>`;
    }).join("");
    // The phases row sits BELOW the page header (project title + actions), not directly under
    // the top nav — so the order is: top bar → project title/actions → phases → content.
    const header = document.querySelector("header");
    (header || nav).insertAdjacentElement("afterend", phases);

    // Row 3: Requirements sub-tabs, only on a Requirements page.
    if (REQ_TABS.some(t => t.file === cur)) {
      subsEl = document.createElement("div");
      subsEl.className = "reqoach-subtabs";
      subsEl.innerHTML = REQ_TABS.map(t =>
        `<a class="subtab${reqActive(t) ? " active" : ""}" href="${reqHref(t)}">${t.label}</a>`).join("");
      phases.insertAdjacentElement("afterend", subsEl);
    }
  }

  // --- Google identity (public browse, gated manage) -------------------------------------
  // Browsing needs no login; creating/managing does. Identity comes from oauth2-proxy's
  // /oauth2/userinfo (the session cookie is sent on every same-origin request). The Analyst
  // enforces owner/admin server-side; this object just drives the UI (sign-in state + whether
  // to offer manage actions) and turns a 401/403 into a helpful prompt.
  const ReqoachAuth = {
    ADMIN: "logus2k@gmail.com",
    _me: undefined,
    async me() {
      if (this._me !== undefined) return this._me;
      try {
        const r = await fetch("me", { headers: { Accept: "application/json" } });   // /reqoach/me
        this._me = r.ok ? await r.json() : null;         // {authenticated,email,name,picture} or null
      } catch (e) { this._me = null; }
      return this._me;
    },
    email() { return this._me && this._me.email ? String(this._me.email).toLowerCase() : null; },
    isAdmin() { const e = this.email(); return !!e && e === this.ADMIN; },
    canManage(project) {
      const e = this.email();
      if (!e) return false;
      if (e === this.ADMIN) return true;
      const owner = project && project.owner ? String(project.owner).toLowerCase() : "";
      return !!owner && owner === e;
    },
    signInUrl() { return "/oauth2/sign_in?rd=" + encodeURIComponent(location.href); },
    signOutUrl() { return "/oauth2/sign_out?rd=" + encodeURIComponent(location.origin + location.pathname); },
    // Turn a gated response into a sign-in prompt / message. Returns true if it handled one.
    needAuth(resp) {
      if (!resp) return false;
      if (resp.status === 401) {
        if (confirm("You need to sign in with Google to do that. Go to sign-in now?")) location.href = this.signInUrl();
        return true;
      }
      if (resp.status === 403) { alert("Only the project owner or the administrator can manage this project."); return true; }
      return false;
    },
  };
  window.ReqoachAuth = ReqoachAuth;

  // --- Identity widget: an avatar button that opens a menu (name, theme, sign in/out) ------
  const currentTheme = () => document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const themeLabel = () => currentTheme() === "dark" ? "☀︎  Light theme" : "☾  Dark theme";
  function toggleTheme() {
    const t = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    document.cookie = "reqoach-theme=" + t + ";path=/;max-age=31536000;samesite=lax";
    const ti = document.getElementById("um-theme"); if (ti) ti.textContent = themeLabel();
    if (typeof window.reqoachRedraw === "function") window.reqoachRedraw();
    window.dispatchEvent(new CustomEvent("reqoach:theme", { detail: t }));
  }
  const rd = encodeURIComponent(location.pathname + location.search);
  const box = document.getElementById("reqoach-user");

  function renderUser(me) {
    const authed = !!(me && me.authenticated && me.email);
    const trigger = (authed && me.picture)
      ? `<img class="avatar" src="${esc(me.picture)}" alt="" referrerpolicy="no-referrer">`
      : `<span class="avatar avatar-icon">${authed ? "👤" : "👤"}</span>`;
    const nameBlock = authed
      ? `<div class="um-name">${esc(me.name || me.email)}</div><div class="um-email">${esc(me.email)}</div><div class="um-sep"></div>`
      : "";
    const authItem = authed
      ? `<a class="um-item" href="/oauth2/sign_out?rd=${rd}">Sign out</a>`
      : `<a class="um-item" href="/oauth2/sign_in?rd=${rd}">Sign in</a>`;
    box.innerHTML =
      `<button type="button" class="avatarbtn" id="reqoach-avatar" aria-haspopup="true" ` +
        `title="${esc(authed ? me.email : "Account")}">${trigger}</button>` +
      `<div class="um-pop hidden" id="reqoach-pop">${nameBlock}` +
        `<button type="button" class="um-item" id="um-theme">${themeLabel()}</button>${authItem}</div>`;
    const btn = document.getElementById("reqoach-avatar");
    const pop = document.getElementById("reqoach-pop");
    btn.addEventListener("click", e => { e.stopPropagation(); pop.classList.toggle("hidden"); });
    document.getElementById("um-theme").addEventListener("click", e => { e.stopPropagation(); toggleTheme(); });
  }
  // Close the menu on any outside click (bound once).
  document.addEventListener("click", () => {
    const pop = document.getElementById("reqoach-pop"); if (pop) pop.classList.add("hidden");
  });
  renderUser(null);   // generic icon until identity resolves
  ReqoachAuth.me().then(me => {
    renderUser(me);
    window.dispatchEvent(new CustomEvent("reqoach:auth", { detail: me || null }));
  });

  // If the page has a connection LED (#status), relocate it into the nav so it sits
  // in the SAME position on every page — at the far right, after the Theme button.
  // Connection LED: dock it at the RIGHT of the sub-tab bar when there is one (e.g. Editor);
  // otherwise keep it in the top nav.
  const led = document.getElementById("status");
  if (led) {
    (subsEl || nav).appendChild(led);
    led.removeAttribute("hidden");
    if (subsEl) led.style.marginLeft = "auto";
  }

  // The Quality page (index.html) has a chart-collapse toggle (#chartsToggle) that belongs at
  // the RIGHT of the Requirements sub-tab bar. Dock it here — deterministic, since subsEl was
  // just built above (app.js can't reliably do it: it runs before this script builds the bar).
  const caret = document.getElementById("chartsToggle");
  if (caret && subsEl) {
    subsEl.appendChild(caret);
    caret.style.marginLeft = led ? "12px" : "auto";
  }
})();
