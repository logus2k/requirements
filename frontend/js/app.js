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
  let drawerChart = null, drawerRuleChart = null, openReq = null, selReqId = null;
  let suggReqChart = null, suggReqRuleChart = null;   // radars for a requirement shown in the sugg column
  let RCATS = [];   // INCOSE rule categories present in the current document (radar axes)
  const charts = {};

  // ---- INCOSE rule metadata (from GET /rules): id -> {name,category,detector,text,terms} ----
  let RULES = {}, ruleBarIds = [];
  const ruleName = id => (RULES[id] && RULES[id].name) || '';
  const ruleCat  = id => (RULES[id] && RULES[id].category) || 'Other';
  const ruleText = id => (RULES[id] && RULES[id].text) || '';
  const uniq = a => [...new Set(a)];
  const CAT_PALETTE = ['#2a78d6','#8a63d2','#0f9d8c','#d98324','#c0507a','#5a7a8c','#b0902a'];
  const _catColor = {};
  const catColor = cat => (_catColor[cat] ||
    (_catColor[cat] = CAT_PALETTE[Object.keys(_catColor).length % CAT_PALETTE.length]));

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
  let docConf = null;                       // document-level rule conformance %
  function paintDocConf() {
    const el = document.getElementById('ruleconf'); if (!el) return;
    if (docConf == null) { el.textContent = '–'; el.style.color = ''; }
    else { el.textContent = docConf + '%'; el.style.color = scoreColor(docConf / 20); }
  }
  const drawer = document.getElementById('drawer');

  // The detail pane is an inline layout component (master–detail), not an overlay.
  // Showing/hiding it reflows the content, so the charts must resize.
  const resizeCharts = () => requestAnimationFrame(() => Object.values(charts).forEach(c => c.resize()));
  function markSel() {
    document.querySelectorAll('#reqrows tr.req').forEach(tr => {
      const r = currentRows[+tr.dataset.i];
      tr.classList.toggle('sel', !!r && r.req_id === selReqId);
    });
  }
  const showDetail = () => { drawer.hidden = false; markSel(); resizeCharts(); };
  const hideDetail = () => { drawer.hidden = true; selReqId = null; markSel(); resizeCharts(); };

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
    const t = T();
    const e = Object.entries(D.aggregates.per_rule_violation_count).slice(0, 10).reverse();
    ruleBarIds = e.map(x => x[0]);
    const label = id => { const n = ruleName(id); return n ? `${id} ${n.length > 13 ? n.slice(0, 12) + '…' : n}` : id; };
    return { backgroundColor: 'transparent', grid: { left: 104, right: 36, top: 6, bottom: 8 },
      tooltip: { trigger: 'item', extraCssText: 'max-width:320px;white-space:normal',
        formatter: p => { const id = ruleBarIds[p.dataIndex];
          return `<b>${id} · ${esc(ruleName(id))}</b><br>${esc(ruleCat(id))} · ${p.value} requirement(s)`
            + (ruleText(id) ? `<br><span style="opacity:.75">${esc(ruleText(id))}</span>` : '')
            + `<br><span style="opacity:.6">click to inspect</span>`; } },
      xAxis: { type: 'value', axisLabel: { show: false }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: 'category', data: e.map(x => label(x[0])), axisLabel: { color: t.ink2, fontSize: 11 },
        axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      series: [{ type: 'bar', barWidth: '62%', cursor: 'pointer',
        data: e.map(x => ({ value: x[1], itemStyle: { color: catColor(ruleCat(x[0])), borderRadius: [0, 4, 4, 0] } })),
        label: { show: true, position: 'right', color: t.ink2 } }] };
  }
  function distOpt() {
    const t = T(), d = D.aggregates.score_distribution;
    const total = [1,2,3,4,5].reduce((a, s) => a + (d[s] || 0), 0);
    return { backgroundColor: 'transparent', grid: { left: 34, right: 14, top: 12, bottom: 24 },
      tooltip: { trigger: 'axis',
        formatter: p => { const v = p[0].value, pct = total ? (v / total * 100).toFixed(1) : '0';
          return `${pct}% · ${v} requirement${v !== 1 ? 's' : ''}`; } },
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
      tooltip: { trigger: 'axis', appendToBody: true, extraCssText: 'max-width:340px;white-space:normal;word-break:break-word',
        formatter: p => {
          const it = a.find(x => x.characteristic === p[0].name);
          return `<b>${esc(it.characteristic)}</b> ${it.score}/5<br>${esc(it.justification || '')}`; } },
      xAxis: { type: 'value', max: 5, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: 'category', data: a.map(x => x.characteristic), axisLabel: { color: t.ink2 },
        axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      series: [{ type: 'bar', barWidth: '58%',
        data: a.map(x => ({ value: x.score, itemStyle: { color: scoreColor(x.score), borderRadius: [0,4,4,0] } })),
        label: { show: true, position: 'right', color: t.ink2, formatter: '{c}' } }] };
  }

  // ---- Rules rolled up to INCOSE categories (3 chart options to compare) ----
  function categoryRollup() {
    const counts = {};
    for (const [rid, n] of Object.entries(D.aggregates.per_rule_violation_count || {}))
      counts[ruleCat(rid)] = (counts[ruleCat(rid)] || 0) + n;
    return Object.entries(counts).map(([cat, count]) => ({ cat, count })).sort((a, b) => b.count - a.count);
  }
  function rcatRadarOpt() {                 // A · conformance (5 = clean; derived from violations)
    const t = T(), d = categoryRollup(); if (!d.length) return { series: [] };
    const max = Math.max(...d.map(x => x.count), 1);
    const conf = d.map(x => +(5 * (1 - x.count / max)).toFixed(2));
    return { backgroundColor: 'transparent',
      tooltip: { trigger: 'item', extraCssText: 'max-width:260px;white-space:normal',
        formatter: () => d.map(x => `${esc(x.cat)}: ${x.count}`).join('<br>') },
      radar: { indicator: d.map(x => ({ name: x.cat, max: 5 })), radius: '60%',
        axisName: { color: t.ink2, fontSize: 10 }, splitNumber: 5,
        splitLine: { lineStyle: { color: t.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: t.grid } } },
      series: [{ type: 'radar', symbolSize: 3, data: [{ value: conf,
        areaStyle: { color: t.accent, opacity: 0.18 }, lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent } }] }] };
  }
  function rcatDonutOpt() {                 // B · composition of violations by category
    const t = T(), d = categoryRollup();
    return { backgroundColor: 'transparent',
      tooltip: { trigger: 'item', formatter: p => `${esc(p.name)}: ${p.value} (${p.percent}%)` },
      series: [{ type: 'pie', radius: ['44%', '70%'], center: ['50%', '52%'],
        itemStyle: { borderColor: cssVar('--surface'), borderWidth: 2 },
        label: { color: t.ink2, fontSize: 10, formatter: '{b}' },
        data: d.map(x => ({ name: x.cat, value: x.count, itemStyle: { color: catColor(x.cat) } })) }] };
  }
  function rcatBarOpt() {                   // C · magnitude per category
    const t = T(), e = [...categoryRollup()].reverse();
    const total = e.reduce((a, x) => a + x.count, 0);
    return { backgroundColor: 'transparent', grid: { left: 96, right: 34, top: 6, bottom: 8 },
      tooltip: { trigger: 'item',
        formatter: p => { const pct = total ? (p.value / total * 100).toFixed(1) : '0';
          return `<b>${esc(p.name)}</b><br>${p.value} violation${p.value !== 1 ? 's' : ''} · ${pct}%`; } },
      xAxis: { type: 'value', axisLabel: { show: false }, splitLine: { lineStyle: { color: t.grid } } },
      yAxis: { type: 'category', data: e.map(x => x.cat), axisLabel: { color: t.ink2, fontSize: 10, width: 84, overflow: 'truncate' },
        axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false } },
      series: [{ type: 'bar', barWidth: '60%',
        data: e.map(x => ({ value: x.count, itemStyle: { color: catColor(x.cat), borderRadius: [0, 4, 4, 0] } })),
        label: { show: true, position: 'right', color: t.ink2 } }] };
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
  // Per-requirement rules radar: conformance per INCOSE category (5 = no findings
  // in that category, 0 = 3+). Same axes for every requirement (RCATS) so shapes
  // are comparable, and pairs beside the characteristics radar.
  const catAbbr = c => (c.split(' ')[0] || c).slice(0, 11);
  function reqRuleRadarOpt(r) {
    const t = T(); if (!RCATS.length) return { series: [] };
    const per = {}, detIds = new Set((r.deterministic_findings || []).map(f => f.rule_id)), seen = new Set();
    for (const f of (r.deterministic_findings || [])) per[ruleCat(f.rule_id)] = (per[ruleCat(f.rule_id)] || 0) + 1;
    for (const c of CHARS) for (const id of (r.characteristics[c].rules_triggered || []))
      if (!detIds.has(id) && !seen.has(id)) { seen.add(id); per[ruleCat(id)] = (per[ruleCat(id)] || 0) + 1; }
    const conf = RCATS.map(cat => Math.max(0, 5 - 2 * (per[cat] || 0)));   // 5 = clean, integer for clean labels
    // Same colour scale as the Characteristics radar: colour by the mean conformance,
    // so green = rule-clean, red = many violations (same 0-5 polarity as the C radar).
    const c0 = scoreColor(conf.length ? conf.reduce((a, b) => a + b, 0) / conf.length : 3);
    return { backgroundColor: 'transparent',
      tooltip: { trigger: 'item', extraCssText: 'max-width:240px;white-space:normal',
        formatter: () => RCATS.map(cat => `${esc(cat)}: ${per[cat] || 0}`).join('<br>') },
      radar: { indicator: RCATS.map(cat => ({ name: catAbbr(cat), max: 5 })), radius: '60%',
        axisName: { color: t.ink2, fontSize: 9 }, splitNumber: 5,
        splitLine: { lineStyle: { color: t.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: t.grid } } },
      series: [{ type: 'radar', symbolSize: 3, data: [{ value: conf,
        areaStyle: { color: c0, opacity: 0.2 }, lineStyle: { color: c0, width: 2 }, itemStyle: { color: c0 },
        label: { show: true, color: t.ink2, fontSize: 9, formatter: p => p.value } }] }] };
  }

  const badge = s => s == null ? '<span class="muted">–</span>'
    : `<span class="badge" style="background:${scoreColor(s)}">${s}</span>`;
  // Average/overall always shows 2 decimals (e.g. 5 -> "5.00") for column consistency.
  const badgeAvg = s => s == null ? '<span class="muted">–</span>'
    : `<span class="badge" style="background:${scoreColor(s)}">${(+s).toFixed(2)}</span>`;

  // ---- Rule conformance: a secondary rules indicator paired with the quality score ----
  // Per-requirement rule violations by INCOSE category (deterministic + judge-flagged, deduped).
  function reqRuleStats(r) {
    const per = {}, detIds = new Set((r.deterministic_findings || []).map(f => f.rule_id)), seen = new Set();
    let viol = 0;
    for (const f of (r.deterministic_findings || [])) { per[ruleCat(f.rule_id)] = (per[ruleCat(f.rule_id)] || 0) + 1; viol++; }
    for (const c of CHARS) for (const id of (r.characteristics[c].rules_triggered || []))
      if (!detIds.has(id) && !seen.has(id)) { seen.add(id); per[ruleCat(id)] = (per[ruleCat(id)] || 0) + 1; viol++; }
    return { per, viol };
  }
  // Conformance % = mean per-category conformance (max(0,5-2*count))/5, over the doc's categories.
  // Mirrors the Rules radar (100% = a full/clean radar), so the badge and radar always agree.
  function confPct(per) {
    if (!RCATS.length) return null;
    const m = RCATS.reduce((a, cat) => a + Math.max(0, 5 - 2 * (per[cat] || 0)), 0) / RCATS.length;
    return Math.round(m / 5 * 100);
  }
  const confBadge = pct => pct == null ? '<span class="muted">–</span>'
    : `<span class="badge" style="background:${scoreColor(pct / 20)}">${pct}%</span>`;

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
      <tr class="req${r.req_id === selReqId ? ' sel' : ''}" data-i="${i}"><td>${r.req_id}</td>
        <td><div class="rtxt" title="${esc(r.text)}">${esc(r.text)}</div></td>
        ${CHARS.map(c => `<td>${badge(r.characteristics[c].score)}</td>`).join('')}
        <td>${badgeAvg(r.overall)}</td></tr>`).join('');
    document.querySelectorAll('th[data-key]').forEach(th => {
      const on = th.dataset.key === sortKey;
      th.classList.toggle('sorted', on);
      th.querySelector('.ind').textContent = on ? (sortDir > 0 ? ' ▲' : ' ▼') : '';
    });
  }

  // ---- detail drawer: requirement text on top, C and R as peer columns ----
  const provStr = r => `${(r.provenance && r.provenance.section_path) || ''}${r.provenance && r.provenance.page ? ' · p.' + r.provenance.page : ''}`;

  // Requirement text with the deterministic rules' offending spans highlighted.
  // Offsets index the RAW text, so we highlight raw (not fmtText) to stay aligned.
  function highlightText(r) {
    const text = r.text || '';
    const marks = [];
    for (const f of (r.deterministic_findings || []))
      for (const m of (f.matches || []))
        if (typeof m.offset === 'number' && m.term) marks.push({ s: m.offset, e: m.offset + m.term.length, rule: f.rule_id });
    if (!marks.length) return esc(text);
    const n = text.length, cover = new Array(n).fill(null);
    for (const mk of marks) for (let i = Math.max(0, mk.s); i < Math.min(n, mk.e); i++) (cover[i] || (cover[i] = new Set())).add(mk.rule);
    const key = i => cover[i] ? [...cover[i]].sort().join(',') : '';
    let out = '', i = 0;
    while (i < n) {
      if (!cover[i]) { let j = i; while (j < n && !cover[j]) j++; out += esc(text.slice(i, j)); i = j; }
      else { const k = key(i); let j = i; while (j < n && cover[j] && key(j) === k) j++;
        const tip = k.split(',').map(x => `${x} ${ruleName(x)}`.trim()).join(' · ');
        out += `<span class="hl" data-rules="${k}" title="${esc(tip)}">${esc(text.slice(i, j))}</span>`; i = j; }
    }
    return out;
  }

  const cCard = (r, c) => { const a = r.characteristics[c]; return `
    <div class="cchar"><div class="top">${badge(a.score)}<span class="name">${names[c]} (${c})</span></div>
      ${a.evidence ? `<div class="ev">“${esc(a.evidence)}”</div>` : ''}
      <div class="just">${esc(a.justification || '')}</div></div>`; };

  // R column: deterministic findings (exact, with term chips) + judge-flagged rules
  // (opinion), grouped by INCOSE category.
  function rColumn(r) {
    const dets = r.deterministic_findings || [];
    const detIds = new Set(dets.map(f => f.rule_id));
    const llm = [];
    for (const c of CHARS) for (const id of (r.characteristics[c].rules_triggered || []))
      if (!detIds.has(id) && !llm.includes(id)) llm.push(id);
    const items = dets.map(f => ({ rule: f.rule_id, det: true, terms: uniq((f.matches || []).map(m => m.term)) }))
      .concat(llm.map(id => ({ rule: id, det: false, terms: [] })));
    if (!items.length) return '<div class="rnone">No rule violations flagged for this requirement.</div>';
    const byCat = {};
    for (const it of items) (byCat[ruleCat(it.rule)] || (byCat[ruleCat(it.rule)] = [])).push(it);
    return Object.entries(byCat).map(([cat, its]) => `
      <div class="rcat" style="color:${catColor(cat)}">${esc(cat)}</div>
      ${its.map(it => `
        <div class="rfind ${it.det ? 'det' : 'llm'} rclick" data-rule="${it.rule}">
          <div class="rtop"><span class="rid">${it.rule}</span><span class="rnm">${esc(ruleName(it.rule))}</span>
            <span class="src">${it.det ? 'deterministic' : 'judge-flagged'}</span></div>
          ${ruleText(it.rule) ? `<div class="guide">${esc(ruleText(it.rule))}</div>` : ''}
          ${it.terms.length ? `<div class="terms">${it.terms.map(t => `<span class="term">${esc(t)}</span>`).join('')}</div>` : ''}
        </div>`).join('')}`).join('');
  }

  const rSummary = r => {
    const cats = {}, detIds = new Set((r.deterministic_findings || []).map(f => f.rule_id)), seen = new Set();
    for (const f of (r.deterministic_findings || [])) cats[ruleCat(f.rule_id)] = (cats[ruleCat(f.rule_id)] || 0) + 1;
    for (const c of CHARS) for (const id of (r.characteristics[c].rules_triggered || []))
      if (!detIds.has(id) && !seen.has(id)) { seen.add(id); cats[ruleCat(id)] = (cats[ruleCat(id)] || 0) + 1; }
    const parts = Object.entries(cats).map(([k, v]) => `${v} ${k}`);
    return parts.length ? parts.join(' · ') : 'none';
  };

  const reviewBlock = r => !r.review ? '' : `
    <h3 style="margin-top:16px">Suggested improvements</h3>
    ${(r.review.rewrites || []).map(w => `<div class="cchar"><b>rewrite</b> → ${esc(w.text)}<div class="muted" style="font-size:12px">${esc(w.notes || '')}</div></div>`).join('')}
    ${(r.review.advisories || []).map(x => `<div class="cchar"><b>${esc(x.characteristic)} advisory</b>: ${esc(x.issue)}<div class="just">${esc(x.suggestion)}</div></div>`).join('')}`;

  function openDrawer(r) {
    openReq = r;
    document.getElementById('drawerBody').innerHTML = `
      <div class="detail-head">
        <h3 style="display:flex;align-items:center;gap:10px;margin-top:0">${r.req_id}<span class="badge" style="background:${scoreColor(r.overall)};margin-left:auto">${(+r.overall).toFixed(2)}</span></h3>
        <div class="muted" style="font-size:12px">${esc(provStr(r))}</div>
        ${(() => { const s = reqRuleStats(r); return `<div class="muted" style="font-size:12px;margin-top:3px">Rule conformance ${confBadge(confPct(s.per))} · ${s.viol} violation${s.viol !== 1 ? 's' : ''}</div>`; })()}
        <div class="rtext" id="rtext">${highlightText(r)}</div>
        <div class="dcharts">
          <div class="col"><h4>Characteristics</h4><div id="reqRadar" style="height:200px;margin:2px 0"></div></div>
          <div class="col"><h4>Rules</h4><div id="reqRuleRadar" style="height:200px;margin:2px 0"></div></div>
        </div>
      </div>
      <div class="detail-scroll">
        <div class="col">${CHARS.map(c => cCard(r, c)).join('')}</div>
        <div class="col">${rColumn(r)}</div>
      </div>`;
    renderSugg(r);                       // suggestions now live in their own right-hand column
    selReqId = r.req_id;
    drawer.hidden = false;              // must be visible BEFORE echarts measures the radars
    markSel();
    if (drawerChart) drawerChart.dispose();
    drawerChart = echarts.init(document.getElementById('reqRadar'));
    drawerChart.setOption(reqRadarOpt(r));
    if (drawerRuleChart) drawerRuleChart.dispose();
    drawerRuleChart = echarts.init(document.getElementById('reqRuleRadar'));
    drawerRuleChart.setOption(reqRuleRadarOpt(r));
    wireRuleLinkage();
  }

  // Criticality colour of a suggestion = worst (lowest) score among the characteristics it
  // addresses — same colour codes as the Live Editor's suggestion borders.
  const critColor = (r, cids) => {
    const s = (cids || []).map(c => { const m = String(c).match(/C\d/); return m && r.characteristics[m[0]] ? r.characteristics[m[0]].score : 0; }).filter(x => x);
    return s.length ? scoreColor(Math.min(...s)) : cssVar('--muted');
  };

  // Suggested improvements for the selected requirement — its own right-hand panel.
  function renderSugg(r) {
    disposeSuggCharts();               // in case a requirement detail was showing here
    const el = document.getElementById('suggBody');
    const rev = r && r.review;
    let h = '<h4 class="suggh">Suggested improvements</h4>';
    const rw = (rev && rev.rewrites) || [], adv = (rev && rev.advisories) || [];
    if (!rw.length && !adv.length) {
      h += '<div class="rnone">' + (r ? 'No suggestions — this requirement scored well.'
                                       : 'Select a requirement to see suggestions.') + '</div>';
    } else {
      h += rw.map(w => `<div class="cchar" style="border-left:3px solid ${critColor(r, w.addresses)}"><b>rewrite</b> → ${esc(w.text)}<div class="muted" style="font-size:12px">${esc(w.notes || '')}</div></div>`).join('');
      h += adv.map(x => `<div class="cchar" style="border-left:3px solid ${critColor(r, [x.characteristic])}"><b>${esc(x.characteristic)} advisory</b>: ${esc(x.issue)}<div class="just">${esc(x.suggestion)}</div></div>`).join('');
    }
    el.innerHTML = h;
  }

  // Full requirement detail rendered into the Suggested Improvements column (stacked to
  // fit the narrow width) — used when a requirement is picked from the rule-centric panel,
  // so the rule panel stays put in the middle. The sugg column scrolls as a whole.
  function disposeSuggCharts() {
    if (suggReqChart) { suggReqChart.dispose(); suggReqChart = null; }
    if (suggReqRuleChart) { suggReqRuleChart.dispose(); suggReqRuleChart = null; }
  }
  function openReqInSugg(r) {
    disposeSuggCharts();
    const el = document.getElementById('suggBody');
    const s = reqRuleStats(r);
    el.innerHTML = `
      <div class="sreq">
        <h3 style="display:flex;align-items:center;gap:10px;margin:0 0 2px">${esc(r.req_id)}<span class="badge" style="background:${scoreColor(r.overall)};margin-left:auto">${(+r.overall).toFixed(2)}</span></h3>
        <div class="muted" style="font-size:12px">${esc(provStr(r))}</div>
        <div class="muted" style="font-size:12px;margin-top:3px">Rule conformance ${confBadge(confPct(s.per))} · ${s.viol} violation${s.viol !== 1 ? 's' : ''}</div>
        <div class="rtext">${highlightText(r)}</div>
        <div class="dcharts stacked">
          <div class="col"><h4>Characteristics</h4><div id="sreqRadar" style="height:200px;margin:2px 0"></div></div>
          <div class="col"><h4>Rules</h4><div id="sreqRuleRadar" style="height:200px;margin:2px 0"></div></div>
        </div>
        <div class="col">${CHARS.map(c => cCard(r, c)).join('')}</div>
        <div class="col">${rColumn(r)}</div>
      </div>`;
    suggReqChart = echarts.init(document.getElementById('sreqRadar'));
    suggReqChart.setOption(reqRadarOpt(r));
    suggReqRuleChart = echarts.init(document.getElementById('sreqRuleRadar'));
    suggReqRuleChart.setOption(reqRuleRadarOpt(r));
    wireRuleLinkage(el);
  }

  // hover a rule finding <-> its highlighted span(s); click a finding -> rule panel
  function wireRuleLinkage(body) {
    body = body || document.getElementById('drawerBody');
    const set = (rid, on) => {
      body.querySelectorAll('.hl').forEach(h => { if (h.dataset.rules.split(',').includes(rid)) h.classList.toggle('active', on); });
      body.querySelectorAll(`.rfind[data-rule="${rid}"]`).forEach(f => f.classList.toggle('active', on));
    };
    body.querySelectorAll('.rfind[data-rule]').forEach(el => {
      const rid = el.dataset.rule;
      el.addEventListener('mouseenter', () => set(rid, true));
      el.addEventListener('mouseleave', () => set(rid, false));
      el.addEventListener('click', () => openRulePanel(rid));
    });
    body.querySelectorAll('.hl[data-rules]').forEach(el => {
      const rids = el.dataset.rules.split(',');
      el.addEventListener('mouseenter', () => rids.forEach(r => set(r, true)));
      el.addEventListener('mouseleave', () => rids.forEach(r => set(r, false)));
    });
  }

  // ---- rule-centric panel: a rule's guidance + every requirement that triggers it ----
  function openRulePanel(ruleId) {
    if (drawerChart) { drawerChart.dispose(); drawerChart = null; }
    if (drawerRuleChart) { drawerRuleChart.dispose(); drawerRuleChart = null; }
    openReq = null;
    const m = RULES[ruleId] || {};
    const detTerms = r => uniq((r.deterministic_findings || []).filter(f => f.rule_id === ruleId).flatMap(f => (f.matches || []).map(x => x.term)));
    const hits = D.requirements.filter(r => (r.deterministic_findings || []).some(f => f.rule_id === ruleId)
      || CHARS.some(c => (r.characteristics[c].rules_triggered || []).includes(ruleId)));
    document.getElementById('drawerBody').innerHTML = `
      <div class="detail-head">
        <h3 style="margin-top:0">${ruleId} · ${esc(m.name || '')}</h3>
        <div class="muted" style="font-size:12px">${esc(m.category || 'Other')}${m.detector ? ' · ' + esc(m.detector) : ''} · ${hits.length} requirement${hits.length !== 1 ? 's' : ''}</div>
        ${m.text ? `<div class="rtext">${esc(m.text)}</div>` : ''}
        ${(m.terms && m.terms.length) ? `<div class="terms" style="margin:8px 0 4px">${m.terms.slice(0, 40).map(t => `<span class="term">${esc(t)}</span>`).join('')}${m.terms.length > 40 ? ' <span class="muted">…</span>' : ''}</div>` : ''}
        <h4 style="margin:14px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)">Requirements (${hits.length})</h4>
      </div>
      <div class="panel-scroll">
      ${hits.map(r => { const ts = detTerms(r); return `
        <div class="cchar rclick" data-req="${esc(r.req_id)}"><div class="top">
          <span class="rid">${esc(r.req_id)}</span>${badgeAvg(r.overall)}</div>
          <div class="just">${esc(r.text.slice(0, 130))}${r.text.length > 130 ? '…' : ''}</div>
          ${ts.length ? `<div class="terms">${ts.map(t => `<span class="term">${esc(t)}</span>`).join('')}</div>` : ''}</div>`; }).join('')}</div>`;
    // Clicking a requirement opens its FULL detail in the Suggested Improvements column,
    // leaving this rule panel in place so you can scan a rule's requirements side by side.
    document.querySelectorAll('#drawerBody .rclick[data-req]').forEach(el =>
      el.addEventListener('click', () => { const r = D.requirements.find(x => x.req_id === el.dataset.req); if (r) openReqInSugg(r); }));
    selReqId = null;
    renderSugg(null);
    showDetail();
  }

  // (Confirmed overlaps now live on their own page — overlaps.html, linked from the nav.)

  function renderAll() {
    charts.radar.setOption(radarOpt(), true);
    charts.rules.setOption(rulesOpt(), true);
    charts.dist.setOption(distOpt(), true);
    charts.setlevel.setOption(setOpt(), true);
    charts.rcat_radar.setOption(rcatRadarOpt(), true);
    charts.rcat_donut.setOption(rcatDonutOpt(), true);
    charts.rcat_bar.setOption(rcatBarOpt(), true);
    if (openReq && drawerChart) drawerChart.setOption(reqRadarOpt(openReq), true);
    if (openReq && drawerRuleChart) drawerRuleChart.setOption(reqRuleRadarOpt(openReq), true);
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
    RCATS = categoryRollup().map(x => x.cat);   // fixed radar axes for per-req rules radar
    const _cs = D.requirements.map(r => confPct(reqRuleStats(r).per)).filter(v => v != null);
    docConf = _cs.length ? Math.round(_cs.reduce((a, b) => a + b, 0) / _cs.length) : null;
    paintDocConf();
    openReq = null;
    renderAll();
    renderTable();
    // The detail pane is always visible; pre-select the first requirement so it's never empty.
    if (currentRows.length) openDrawer(currentRows[0]);
  }

  // ---- one-time wiring (independent of which document is loaded) ----
  ['radar','rules','dist','setlevel','rcat_radar','rcat_donut','rcat_bar'].forEach(id =>
    charts[id] = echarts.init(document.getElementById(id), null, { renderer: 'canvas' }));

  // click a rule bar -> its rule-centric panel (guidance + affected requirements)
  charts.rules.on('click', p => { const id = ruleBarIds[p.dataIndex]; if (id) openRulePanel(id); });

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
  // Arrow keys move the selection up/down the requirements list and auto-open it
  // in the detail panels (ignored while a form control has focus, e.g. the picker).
  document.addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (!currentRows.length) return;
    e.preventDefault();
    let i = currentRows.findIndex(r => r.req_id === selReqId);
    i = i < 0 ? 0 : i + (e.key === 'ArrowDown' ? 1 : -1);
    i = Math.max(0, Math.min(currentRows.length - 1, i));
    openDrawer(currentRows[i]);
    const tr = document.querySelector(`#reqrows tr[data-i="${i}"]`);
    if (tr) tr.scrollIntoView({ block: 'nearest' });
  });
  // Collapse/expand the chart row to give the bottom panels more height.
  document.getElementById('chartsToggle').onclick = () => {
    document.body.classList.toggle('charts-collapsed');   // CSS swaps the up/down-circle icon
    resizeCharts();
  };
  // The shared top nav (js/nav.js) owns the theme toggle; re-render on its event.
  window.addEventListener('reqoach:theme', () => {
    hEl.style.color = scoreColor(health);
    paintDocConf();
    renderAll();
  });
  window.addEventListener('resize', () => {
    Object.values(charts).forEach(c => c.resize());
    if (drawerChart) drawerChart.resize();
    if (drawerRuleChart) drawerRuleChart.resize();
    if (suggReqChart) suggReqChart.resize();
    if (suggReqRuleChart) suggReqRuleChart.resize();
  });

  // ---- document picker: a custom themed dropdown (native <select> popups can't be styled) ----
  const pick = document.getElementById('docpick');
  const pickBtn = document.getElementById('docpickBtn');
  const pickLabel = document.getElementById('docpickLabel');
  const pickMenu = document.getElementById('docpickMenu');
  let docOpts = [], docValue = null, onDocChange = null;
  const splitName = name => { const i = name.lastIndexOf(' · ');
    return i >= 0 ? { main: name.slice(0, i), cnt: name.slice(i + 3) } : { main: name, cnt: '' }; };
  function setLabel() { const o = docOpts.find(x => x.value === docValue); pickLabel.textContent = o ? o.name : ''; }
  function renderMenu() {
    pickMenu.innerHTML = docOpts.map(o => { const s = splitName(o.name);
      return `<div class="docpick-item" role="option" data-val="${esc(o.value)}" aria-selected="${o.value === docValue}">`
        + `<span class="nm">${esc(s.main)}</span>${s.cnt ? `<span class="cnt">${esc(s.cnt)}</span>` : ''}</div>`; }).join('');
  }
  const menuOpen = () => !pickMenu.hidden;
  function openMenu() { if (!docOpts.length) return; renderMenu(); pickMenu.hidden = false; pick.dataset.open = 'true'; pickBtn.setAttribute('aria-expanded', 'true'); }
  function closeMenu() { pickMenu.hidden = true; pick.dataset.open = 'false'; pickBtn.setAttribute('aria-expanded', 'false'); }
  pickBtn.addEventListener('click', e => { e.stopPropagation(); menuOpen() ? closeMenu() : openMenu(); });
  pickMenu.addEventListener('click', e => { const it = e.target.closest('.docpick-item'); if (!it) return;
    const v = it.dataset.val; closeMenu(); if (v !== docValue) { docValue = v; setLabel(); if (onDocChange) onDocChange(v); } });
  document.addEventListener('click', () => { if (menuOpen()) closeMenu(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menuOpen()) closeMenu(); });
  // Boot API (mirrors the old <select>'s role): populate options / show a bare label.
  function setDocOptions(opts, startVal, onChange) { docOpts = opts; docValue = startVal; onDocChange = onChange; setLabel(); }
  const showOnly = txt => { docOpts = []; docValue = null; onDocChange = null; pickLabel.textContent = txt; };

  // Rule metadata (names, categories, guidance) for the R findings + chart.
  // Best-effort: a static-only deploy without the API just falls back to bare ids.
  const rulesP = fetch('rules').then(r => r.ok ? r.json() : {}).catch(() => ({}));

  // ---- boot: pick data mode ----
  if (window.SCORECARD) {                      // single-document inlined build
    rulesP.then(m => { RULES = m || {}; showOnly(window.SCORECARD.source_file); loadScorecard(window.SCORECARD); });
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

    Promise.all([staticP, apiP, rulesP]).then(([statics, apis, rmeta]) => {
      RULES = rmeta || {};
      const opts = statics.map(d => ({ value: 'static:' + d.file, name: d.name }));
      for (const d of apis) {
        if (!d.total) continue;                // skip empty/failed jobs
        opts.push({ value: 'api:' + d.doc_id, name: d.source_file + ' · ' + d.total });
      }
      if (!opts.length) { showOnly('no documents'); return; }
      // Deep-link: ?doc=<doc_id> (from the monitor's "open full report") pre-selects
      // that assessed document; otherwise show the first.
      const want = new URLSearchParams(location.search).get('doc');
      const startVal = (want && opts.find(o => o.value === 'api:' + want) || opts[0]).value;
      setDocOptions(opts, startVal, loadDoc);
      loadDoc(startVal);
    });
  }
})();
