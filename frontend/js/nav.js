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
  // Sub-tabs inside the Requirements section (third row).
  const REQ_TABS = [
    { label: "Quality",  href: "index.html",    match: "index.html" },
    { label: "Review",   href: "review.html",   match: "review.html" },
    { label: "Coverage", href: "coverage.html", match: "coverage.html" },
    { label: "Editor",   href: "editor.html",   match: "editor.html" },
  ];

  // Row 1: brand (left); project selector + auth + theme (right).
  const nav = document.createElement("nav");
  nav.className = "reqoach-nav";
  nav.innerHTML =
    '<a class="brand" href="projects.html">reqoach</a>' +
    '<span class="spacer"></span>' +
    `<a class="proj${pid ? "" : " none"}" id="reqoach-proj" href="projects.html" title="Switch / manage projects">` +
      (pid ? "…" : "Select project…") + "</a>" +
    '<span class="authbox" id="reqoach-auth"></span>' +
    '<button class="tbtn tbtn-icon" id="reqoach-theme" title="Toggle light / dark" aria-label="Toggle light / dark"></button>';
  document.body.prepend(nav);

  // Fill the project chip with the project's name — fetched, not stored.
  if (pid) {
    fetch("/analyst/projects/" + encodeURIComponent(pid)).then(r => r.ok ? r.json() : null)
      .then(p => { const el = document.getElementById("reqoach-proj"); if (el && p && p.name) el.textContent = p.name; })
      .catch(() => {});
  }

  // Row 2: lifecycle phases (only with a project selected).
  if (pid) {
    const phases = document.createElement("div");
    phases.className = "reqoach-phases";
    phases.innerHTML = PHASES.map(p => {
      if (p.soon) return `<span class="phase soon" title="Coming soon">${p.label}</span>`;
      const active = p.match.indexOf(cur) >= 0 ? " active" : "";
      return `<a class="phase${active}" href="${p.href}${q}">${p.label}</a>`;
    }).join("");
    nav.insertAdjacentElement("afterend", phases);

    // Row 3: Requirements sub-tabs, only on a Requirements page.
    if (REQ_TABS.some(t => t.match === cur)) {
      const subs = document.createElement("div");
      subs.className = "reqoach-subtabs";
      subs.innerHTML = REQ_TABS.map(t =>
        `<a class="subtab${t.match === cur ? " active" : ""}" href="${t.href}${q}">${t.label}</a>`).join("");
      phases.insertAdjacentElement("afterend", subs);
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
        const r = await fetch("/oauth2/userinfo", { headers: { Accept: "application/json" } });
        this._me = r.ok ? await r.json() : null;         // {email,user,…} or null when anonymous
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

  const authEl = document.getElementById("reqoach-auth");
  ReqoachAuth.me().then(me => {
    if (me && me.email) {
      authEl.innerHTML = `<span class="who" title="${esc(me.email)}">${esc(me.email)}</span>`
        + `<a class="authlink" href="${ReqoachAuth.signOutUrl()}">Sign out</a>`;
    } else {
      authEl.innerHTML = `<a class="authlink signin" href="${ReqoachAuth.signInUrl()}">Sign in</a>`;
    }
    window.dispatchEvent(new CustomEvent("reqoach:auth", { detail: me || null }));
  });

  const themeBtn = document.getElementById("reqoach-theme");
  // Show the icon of the theme you'd switch TO: moon on light (go dark), sun on dark (go light).
  const setThemeIcon = () => {
    themeBtn.textContent = document.documentElement.dataset.theme === "dark" ? "☀︎" : "☾";
  };
  setThemeIcon();
  themeBtn.addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    document.cookie = "reqoach-theme=" + t + ";path=/;max-age=31536000;samesite=lax";
    setThemeIcon();
    if (typeof window.reqoachRedraw === "function") window.reqoachRedraw();
    window.dispatchEvent(new CustomEvent("reqoach:theme", { detail: t }));
  });

  // If the page has a connection LED (#status), relocate it into the nav so it sits
  // in the SAME position on every page — at the far right, after the Theme button.
  const led = document.getElementById("status");
  if (led) { nav.appendChild(led); led.removeAttribute("hidden"); }
})();
