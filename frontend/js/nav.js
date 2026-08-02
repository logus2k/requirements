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
    { href: "overview.html" + q,  label: "Overview",             match: "overview.html" },
    { href: "documents.html" + q, label: "Documents",            match: "documents.html" },
    { href: "index.html" + q,     label: "Requirements Quality",  match: "index.html" },
    { href: "review.html" + q,    label: "Review & Reissue",      match: "review.html" },
    { href: "coverage.html" + q,  label: "Requirements Coverage", match: "coverage.html" },
    { href: "architecture.html" + q, label: "Architecture",       match: "architecture.html" },
    { href: "editor.html",        label: "Live editor",           match: "editor.html" },
  ];
  const cur = location.pathname.split("/").pop() || "index.html";

  const nav = document.createElement("nav");
  nav.className = "reqoach-nav";
  nav.innerHTML =
    '<a class="brand" href="projects.html">reqoach</a>' +
    PAGES.map(p =>
      `<a class="item${p.match === cur ? " active" : ""}" href="${p.href}">${p.label}</a>`
    ).join("") +
    '<span class="spacer"></span>' +
    // Current-project chip lives on the right, just before the theme toggle.
    `<a class="proj${pid ? "" : " none"}" href="projects.html" title="Switch / manage projects">` +
      (pid ? esc(pname || "project") : "Select project…") + "</a>" +
    '<span class="authbox" id="reqoach-auth"></span>' +
    '<button class="tbtn tbtn-icon" id="reqoach-theme" title="Toggle light / dark" aria-label="Toggle light / dark"></button>';
  document.body.prepend(nav);

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
    try { localStorage.setItem("reqoach-theme", t); } catch (e) {}
    setThemeIcon();
    if (typeof window.reqoachRedraw === "function") window.reqoachRedraw();
    window.dispatchEvent(new CustomEvent("reqoach:theme", { detail: t }));
  });

  // If the page has a connection LED (#status), relocate it into the nav so it sits
  // in the SAME position on every page — at the far right, after the Theme button.
  const led = document.getElementById("status");
  if (led) { nav.appendChild(led); led.removeAttribute("hidden"); }
})();
