/* Requirements Quality dashboard — Apache ECharts 6.1.0, light/dark themes.
 *
 * Two data modes:
 *   - multi-document (container): fetch data/index.json, populate the document
 *     picker, then fetch the selected scorecard JSON.
 *   - single-document (self-contained build / Artifact): window.SCORECARD is
 *     inlined; the picker is hidden.
 *
 * Consumes the producer's scorecard_full.json format directly: overall_health
 * and the per-characteristic `rules` alias are derived here if absent. */
(function () {
  const CHARS = ["C1","C2","C3","C4","C5","C6","C7","C8","C9"];
  let D, names, health, byId;                 // current scorecard + derived
  let sortKey = 'overall', sortDir = 1, currentRows = [];
  let drawerChart = null, openReq = null;
  const charts = {};

  const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const T = () => ({ ink: cssVar('--ink'), ink2: cssVar('--ink2'), muted: cssVar('--muted'),
                     grid: cssVar('--grid'), axis: cssVar('--axis'), accent: cssVar('--accent') });
  const scoreColor = s => cssVar('--s' + Math.max(1, Math.min(5, Math.round(s))));
  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
  // Requirement text lost its list structure at ingestion: Docling emits bullets
  // as the private-use glyph U+F0B7 (renders blank -> looks like spaces) or other
  // bullet chars. Restore readable line breaks + a bullet marker.
  const fmtText = s => esc(s)
    .replace(/\s*[•●▪‣⁃∙]\s*/g, '<br>• ')
    .replace(/ {2,}/g, '<br>')
    .replace(/^(?:\s*<br>\s*•?\s*)+/, '');

  const hEl = document.getElementById('health');
  const drawer = document.getElementById('drawer');

  // ---- chart option builders (read current D / names / health / byId) ----
  function radarOpt() {
    const t = T(), m = D.aggregates.per_characteristic_mean, c0 = scoreColor(health);
    return { backgroundColor: 'transparent',
      radar: { indicator: CHARS.map(c => ({ name: `${names[c]} (${c})`, max: 5 })),
        axisName: { color: t.ink2, fontSize: 11 }, splitNumber: 5,
        splitLine: { lineStyle: { color: t.grid } }, splitArea: { show: false },
        axisLine: { lineStyle: { color: t.grid } } },
      series: [{ type: 'radar', symbolSize: 4,
        data: [{ value: CHARS.map(c => m[c]),
          lineStyle: { color: c0, width: 2 }, itemStyle: { color: c0 },
          areaStyle: { color: c0, opacity: 0.18 },
          label: { show: true, color: t.ink2, fontSize: 10, formatter: p => (+p.value).toFixed(1) } }] }] };
  }
  function rulesOpt() {
    const t = T(), e = Object.entries(D.aggregates.per_rule_violation_count).slice(0, 14).reverse();
    return { backgroundColor: 'transparent', grid: { left: 46, right: 30, top: 6, bottom: 22 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'value', axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: 'category', data: e.map(x => x[0]), axisLabel: { color: t.ink2 },
        axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      series: [{ type: 'bar', data: e.map(x => x[1]), barWidth: '62%',
        itemStyle: { color: t.accent, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right', color: t.ink2 } }] };
  }
  function distOpt() {
    const t = T(), d = D.aggregates.score_distribution;
    return { backgroundColor: 'transparent', grid: { left: 34, right: 14, top: 12, bottom: 24 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: ['1','2','3','4','5'], name: 'score',
        nameTextStyle: { color: t.muted }, axisLabel: { color: t.ink2 }, axisLine: { lineStyle: { color: t.axis } } },
      yAxis: { type: 'value', axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      series: [{ type: 'bar', barWidth: '56%',
        data: [1,2,3,4,5].map(s => ({ value: d[s] || 0, itemStyle: { color: scoreColor(s), borderRadius: [4,4,0,0] } })),
        label: { show: true, position: 'top', color: t.ink2 } }] };
  }
  function setOpt() {
    const t = T(), a = D.set_level.set_assessment;
    return { backgroundColor: 'transparent', grid: { left: 40, right: 26, top: 6, bottom: 18 },
      tooltip: { trigger: 'axis', formatter: p => {
        const it = a.find(x => x.characteristic === p[0].name);
        return `<b>${it.characteristic}</b> ${it.score}/5<br>${it.justification}`; } },
      xAxis: { type: 'value', max: 5, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: 'category', data: a.map(x => x.characteristic), axisLabel: { color: t.ink2 },
        axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      series: [{ type: 'bar', barWidth: '58%',
        data: a.map(x => ({ value: x.score, itemStyle: { color: scoreColor(x.score), borderRadius: [0,4,4,0] } })),
        label: { show: true, position: 'right', color: t.ink2, formatter: '{c}' } }] };
  }
  function reqRadarOpt(r) {
    const t = T(), c0 = scoreColor(r.overall);
    return { backgroundColor: 'transparent',
      radar: { indicator: CHARS.map(c => ({ name: c, max: 5 })), radius: '62%',
        axisName: { color: t.ink2, fontSize: 10 }, splitNumber: 5,
        splitLine: { lineStyle: { color: t.grid } }, splitArea: { show: false },
        axisLine: { lineStyle: { color: t.grid } } },
      series: [{ type: 'radar', symbolSize: 3,
        data: [{ value: CHARS.map(c => r.characteristics[c].score || 0),
          lineStyle: { color: c0, width: 2 }, itemStyle: { color: c0 },
          areaStyle: { color: c0, opacity: 0.22 },
          label: { show: true, color: t.ink2, fontSize: 9, formatter: p => p.value } }] }] };
  }

  const badge = s => s == null ? '<span class="muted">–</span>'
    : `<span class="badge" style="background:${scoreColor(s)}">${s}</span>`;

  // ---- sortable requirements table ----
  const sortVal = (r, k) =>
    k === 'req_id' ? r.req_id :
    k === 'text' ? r.text.toLowerCase() :
    k === 'overall' ? (r.overall == null ? -1 : r.overall) :
    (r.characteristics[k] && r.characteristics[k].score != null ? r.characteristics[k].score : -1);
  function renderTable() {
    currentRows = [...D.requirements].sort((a, b) => {
      const va = sortVal(a, sortKey), vb = sortVal(b, sortKey);
      return va < vb ? -sortDir : va > vb ? sortDir : 0;
    });
    document.getElementById('reqrows').innerHTML = currentRows.map((r, i) => `
      <tr class="req" data-i="${i}"><td>${r.req_id}</td>
        <td>${esc(r.text.slice(0, 70))}${r.text.length > 70 ? '…' : ''}</td>
        ${CHARS.map(c => `<td>${badge(r.characteristics[c].score)}</td>`).join('')}
        <td>${badge(r.overall)}</td></tr>`).join('');
    document.querySelectorAll('th[data-key]').forEach(th => {
      const on = th.dataset.key === sortKey;
      th.classList.toggle('sorted', on);
      th.querySelector('.ind').textContent = on ? (sortDir > 0 ? ' ▲' : ' ▼') : '';
    });
  }

  // ---- detail drawer (with per-requirement radar) ----
  function openDrawer(r) {
    openReq = r;
    document.getElementById('drawerBody').innerHTML = `
      <h3>${r.req_id} <span class="badge" style="background:${scoreColor(r.overall)}">${r.overall}</span></h3>
      <div class="muted" style="font-size:12px">${(r.provenance && r.provenance.section_path) || ''}${r.provenance && r.provenance.page ? ' · p.' + r.provenance.page : ''}</div>
      <div id="reqRadar" style="height:236px;margin:6px 0 2px"></div>
      <div class="rtext">${fmtText(r.text)}</div>
      ${CHARS.map(c => { const a = r.characteristics[c]; return `
        <div class="cchar"><div class="top">
          ${badge(a.score)}<span class="name">${names[c]} (${c})</span>
          <span class="rules">${(a.rules || a.rules_triggered || []).join(', ')}</span></div>
          ${a.evidence ? `<div class="ev">“${a.evidence}”</div>` : ''}
          <div class="just">${a.justification || ''}</div></div>`; }).join('')}
      ${r.review ? `<h3 style="margin-top:14px">Suggested improvements</h3>
        ${(r.review.rewrites || []).map(w => `<div class="cchar"><b>rewrite</b> → ${w.text}<div class="muted" style="font-size:12px">${w.notes || ''}</div></div>`).join('')}
        ${(r.review.advisories || []).map(x => `<div class="cchar"><b>${x.characteristic} advisory</b>: ${x.issue}<div class="just">${x.suggestion}</div></div>`).join('')}` : ''}`;
    if (drawerChart) drawerChart.dispose();
    drawerChart = echarts.init(document.getElementById('reqRadar'));
    drawerChart.setOption(reqRadarOpt(r));
    drawer.classList.add('open');
  }

  // ---- overlaps side panel ----
  function openOverlaps() {
    if (drawerChart) { drawerChart.dispose(); drawerChart = null; }
    openReq = null;
    const ov = D.set_level.overlaps || [];
    document.getElementById('drawerBody').innerHTML = `
      <h3>Confirmed overlaps <span class="muted">(${ov.length})</span></h3>
      <div class="muted" style="font-size:12px;margin-bottom:8px">Requirement pairs judged to duplicate or substantially overlap.</div>
      ${ov.map(o => { const a = byId[o.a_id], b = byId[o.b_id]; return `
        <div class="cchar ovpair"><div class="top">
          <span class="name">${o.a_id} ~ ${o.b_id}</span><span class="sc">${o.score}</span></div>
          <div class="just">${a ? esc(a.text.slice(0, 96)) : o.a_id}</div>
          <div class="just">${b ? esc(b.text.slice(0, 96)) : o.b_id}</div></div>`; }).join('')}`;
    drawer.classList.add('open');
  }

  function renderAll() {
    charts.radar.setOption(radarOpt(), true);
    charts.rules.setOption(rulesOpt(), true);
    charts.dist.setOption(distOpt(), true);
    charts.setlevel.setOption(setOpt(), true);
    if (openReq && drawerChart) drawerChart.setOption(reqRadarOpt(openReq), true);
  }

  // ---- load a scorecard (producer format) and (re)render everything ----
  function loadScorecard(sc) {
    D = sc;
    names = D.characteristic_names;
    const m = D.aggregates.per_characteristic_mean;
    health = (D.aggregates.overall_health != null)
      ? D.aggregates.overall_health
      : Math.round(mean(CHARS.map(c => m[c])) * 100) / 100;
    byId = Object.fromEntries(D.requirements.map(r => [r.req_id, r]));
    hEl.textContent = health.toFixed(2); hEl.style.color = scoreColor(health);
    document.getElementById('ovcount').textContent = (D.set_level.overlaps || []).length;
    drawer.classList.remove('open'); openReq = null;
    renderAll();
    renderTable();
  }

  // ---- one-time wiring (independent of which document is loaded) ----
  ['radar','rules','dist','setlevel'].forEach(id =>
    charts[id] = echarts.init(document.getElementById(id), null, { renderer: 'canvas' }));

  document.querySelectorAll('th[data-key]').forEach(th =>
    th.addEventListener('click', () => {
      const k = th.dataset.key;
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
      renderTable();
    }));
  document.getElementById('reqrows').addEventListener('click', e => {
    const tr = e.target.closest('tr.req'); if (!tr) return;
    openDrawer(currentRows[+tr.dataset.i]);
  });
  document.getElementById('ovBtn').addEventListener('click', openOverlaps);
  document.getElementById('drawerClose').onclick = () => drawer.classList.remove('open');
  document.getElementById('themeBtn').onclick = () => {
    const h = document.documentElement;
    h.dataset.theme = h.dataset.theme === 'dark' ? 'light' : 'dark';
    hEl.style.color = scoreColor(health);
    renderAll();
  };
  window.addEventListener('resize', () => {
    Object.values(charts).forEach(c => c.resize());
    if (drawerChart) drawerChart.resize();
  });

  // ---- document picker (the subtitle select) ----
  const sel = document.getElementById('docsel');
  const measureCtx = document.createElement('canvas').getContext('2d');
  // Size the select to its selected option so the caret sits right after the
  // current document's title (a native select otherwise sizes to the widest
  // option). +24px leaves room for the caret and a little slack.
  function fitDocSel() {
    const opt = sel.options[sel.selectedIndex];
    if (!opt) return;
    const cs = getComputedStyle(sel);
    measureCtx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    sel.style.width = Math.ceil(measureCtx.measureText(opt.text).width) + 24 + 'px';
  }
  const showOnly = txt => { sel.innerHTML = `<option>${esc(txt)}</option>`; fitDocSel(); };

  // ---- boot: pick data mode ----
  if (window.SCORECARD) {                      // single-document inlined build
    showOnly(window.SCORECARD.source_file);
    loadScorecard(window.SCORECARD);
  } else {                                     // multi-document mode
    // The picker merges two sources: curated static scorecards under data/, and
    // documents assessed live through the orchestration API (GET documents ->
    // GET documents/{id}/scorecard). Option values are tagged "static:<file>" or
    // "api:<doc_id>" so the loader knows where to fetch from. Either source may
    // be absent (e.g. a static-only deploy, or the API unreachable) — we merge
    // whatever loads.
    const loadDoc = value => {
      const i = value.indexOf(':'), src = value.slice(0, i), id = value.slice(i + 1);
      const url = src === 'api' ? 'documents/' + id + '/scorecard' : 'data/' + id;
      return fetch(url)
        .then(r => { if (!r.ok) throw new Error(r.status + ' ' + id); return r.json(); })
        .then(loadScorecard)
        .catch(e => { showOnly('failed to load ' + id); console.error(e); });
    };

    const staticP = fetch('data/index.json')
      .then(r => r.ok ? r.json() : [])
      .then(d => Array.isArray(d) ? d : []).catch(() => []);
    const apiP = fetch('documents')
      .then(r => r.ok ? r.json() : { documents: [] })
      .then(d => (d && d.documents) || []).catch(() => []);

    Promise.all([staticP, apiP]).then(([statics, apis]) => {
      const opts = statics.map(d => ({ value: 'static:' + d.file, name: d.name }));
      for (const d of apis) {
        if (!d.total) continue;                // skip empty/failed jobs
        opts.push({ value: 'api:' + d.doc_id, name: d.source_file + ' · ' + d.total });
      }
      if (!opts.length) { showOnly('no documents'); return; }
      sel.innerHTML = opts.map(o => `<option value="${esc(o.value)}">${esc(o.name)}</option>`).join('');
      // Deep-link: ?doc=<doc_id> (from the monitor's "open full report") pre-selects
      // that assessed document; otherwise show the first.
      const want = new URLSearchParams(location.search).get('doc');
      const startVal = (want && opts.find(o => o.value === 'api:' + want) || opts[0]).value;
      sel.value = startVal;
      fitDocSel();
      sel.onchange = () => { fitDocSel(); loadDoc(sel.value); };
      loadDoc(startVal);
    });
  }
})();
