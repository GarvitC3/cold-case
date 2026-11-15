// TREND — "Winter is losing days". Winter stripes (inspired by Ed Hawkins' warming stripes) + the trial verdicts.
import { isNum, esc, slotLabel } from '../fmt.js';
import { openSheet } from '../sheets.js';

const MINUS = '−';
const sg = (v, dp = 0) => (isNum(v) ? `${v < 0 ? MINUS : v > 0 ? '+' : ''}${Math.abs(v).toFixed(dp)}` : '—');
// diverging, colour-blind-safe (blue <-> orange): colder than the site's own average = blue, milder = amber
const STOPS = [[-2.2, [196, 96, 18]], [-1, [240, 160, 84]], [0, [225, 232, 242]], [1, [112, 178, 236]], [2.2, [30, 98, 200]]];
export function stripeColor(z) {
  const v = Math.max(-2.2, Math.min(2.2, z));
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [a, ca] = STOPS[i], [b, cb] = STOPS[i + 1];
    if (v <= b) { const k = (v - a) / (b - a); return `rgb(${ca.map((c, j) => Math.round(c + (cb[j] - c) * k)).join(',')})`; }
  }
  return 'rgb(30,98,200)';
}
const GLYPH = { ROBUST: '✓', FRAGILE: '!', 'NO TREND': '–', 'TOO FEW': '?' };
export const verdictChip = (r) => `<span class="vchip v-${r.verdict.replace(' ', '')}"><b>${GLYPH[r.verdict] || ''}</b>${esc(r.verdict)}${r.of ? ` <small>${r.score}/${r.of}</small>` : ''}</span>`;

let lastNote = '';
export function mountTrend(root) {
  root.innerHTML = `<div class="card trend"><div class="t-head"><p class="t-headline"></p></div><div class="t-grid" data-noswipe></div><div class="t-axis"><span class="t-y0"></span><span class="t-y1"></span></div><p class="t-foot"></p></div>`;
  const q = (s) => root.querySelector(s);
  let data = null, snap = null, key = '';

  async function load() {
    try { data = await (await fetch('/api/trend', { cache: 'no-store' })).json(); } catch (e) { data = null; }
    render();
  }

  function headline() {
    if (!snap) return '';
    if (!data || !data.has_data) return 'Trend analysis needs the NASA history — run prefetch.py once with internet.';
    const id = snap.site.id;
    const s = data.sites.find((x) => x.site_id === id) || data.sites[0];
    const dec = s.decades, ice = s.iceup['30'], ir = ice.result;
    let l1 = '';
    if (dec) l1 = `Typical peak ice at <b>${esc(s.short)}</b>: <b>${Math.round(dec.first.ice_cm)} cm</b> in the first decade of record → <b>${Math.round(dec.last.ice_cm)} cm</b> in the latest.`;
    let l2 = '';
    if (ir.verdict === 'NO TREND') l2 = ` The 30 cm ice date shows <b>no detectable shift</b> (${sg(ir.slope_per, 1)} days per decade, CI ${sg(ir.ci_lo, 1)} to ${sg(ir.ci_hi, 1)}).`;
    else if (ir.verdict === 'TOO FEW') l2 = '';
    else l2 = ` 30 cm of ice arrives about <b>${Math.abs(ir.slope_per).toFixed(1)} days ${ir.slope_per > 0 ? 'later' : 'earlier'} per decade</b> — ${ir.verdict === 'ROBUST' ? 'robust' : 'fragile: it does not survive every test'}.`;
    return l1 + l2;
  }

  function render() {
    const grid = q('.t-grid');
    q('.t-headline').innerHTML = headline();
    if (!data || !data.has_data) { grid.innerHTML = ''; return; }
    const sites = data.sites, n = sites[0].years.length;
    grid.innerHTML = sites.map((s, i) => {
      const r = s.season;
      const rects = s.z.map((z, k) => `<rect x="${k}" y="0" width="1.02" height="1" fill="${stripeColor(z)}"/>`).join('');
      return `<button class="t-row ${snap && snap.site.id === s.site_id ? 'sel' : ''}" data-i="${i}" aria-label="${esc(s.name)} details">
        <span class="t-name">${esc(s.short)}</span>
        <svg class="t-stripes" viewBox="0 0 ${n} 1" preserveAspectRatio="none" shape-rendering="crispEdges">${rects}</svg>
        <span class="t-info"><span class="t-slope">${sg(r.slope_per)} <small>°C-d/decade</small> <em>${sg(r.ci_lo)} to ${sg(r.ci_hi)}</em></span>${verdictChip(r)}</span></button>`;
    }).join('');
    q('.t-y0').textContent = sites[0].years[0] - 1 + '–' + String(sites[0].years[0]).slice(2);
    q('.t-y1').textContent = sites[0].years[n - 1] - 1 + '–' + String(sites[0].years[n - 1]).slice(2);
    const c = data.compare;
    let note = 'The differences between sites are within the uncertainty \u2014 no north\u2013south claim is made.';
    if (c && c.gradient_supported) {
      const cnt = {}; c.separated_pairs.forEach((p) => { cnt[p[0]] = (cnt[p[0]] || 0) + 1; });
      const lead = Object.keys(cnt).sort((x, y) => cnt[y] - cnt[x])[0];
      const others = c.separated_pairs.filter((p) => p[0] === lead).map((p) => p[1]);
      const rel = Object.fromEntries(c.rel.map((r) => [r[0], r[1]]));
      const nm = (id) => (sites.find((x) => x.site_id === id) || {}).short || id;
      const ov = others.map((id) => rel[id]);
      note = `In relative terms <b>${esc(nm(lead))}</b> is losing cold fastest (${sg(rel[lead], 0)}% per decade vs ${sg(Math.max(...ov), 0)}% to ${sg(Math.min(...ov), 0)}% at ${others.map(nm).map(esc).join(', ')}) \u2014 their 95% intervals do not overlap.`;
    }
    lastNote = note;
    q('.t-foot').innerHTML = `<b style="color:#70b2ec">Blue</b> = colder than the site’s own average, <b style="color:#f0a054">amber</b> = milder · tap a row for the tests · after Ed Hawkins’ warming stripes`;
    q('.t-headline').innerHTML = headline() + ` <span class="t-claim">${note}</span>`;
  }

  root.addEventListener('click', (e) => {
    const row = e.target.closest('.t-row');
    if (row && data) openDetail(data.sites[+row.dataset.i]);
  });

  function update(S) {
    snap = S.state;
    const k = snap.site.id + '|' + snap.clock.today;
    if (k !== key) { key = k; if (data) render(); else load(); }
    root.querySelectorAll('.t-row').forEach((b, i) => b.classList.toggle('sel', data && data.sites[i] && data.sites[i].site_id === snap.site.id));
    q('.t-headline').innerHTML = headline() + (lastNote ? ` <span class="t-claim">${lastNote}</span>` : '');
  }
  load();
  return { update, resize() {} };
}

// ------------------------------------------------------------------ detail sheet: the data, the Theil-Sen line, the tests in words
function lineChart(years, ys, res, fmtY) {
  const W = 640, H = 210, L = 46, R = 12, T = 10, B = 24;
  const x0 = years[0], x1 = years[years.length - 1];
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R), Y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const tm = (x0 + x1) / 2, ym = res.slope * tm + res.intercept;
  const line = (m) => `M${X(x0)},${Y(ym + m * (x0 - tm))} L${X(x1)},${Y(ym + m * (x1 - tm))}`;
  const slo = res.ci_lo / 10, shi = res.ci_hi / 10;
  const band = `M${X(x0)},${Y(ym + slo * (x0 - tm))} L${X(x1)},${Y(ym + slo * (x1 - tm))} L${X(x1)},${Y(ym + shi * (x1 - tm))} L${X(x0)},${Y(ym + shi * (x0 - tm))}Z`;
  const ticks = [0, 1, 2, 3].map((i) => lo + ((hi - lo) * i) / 3);
  return `<svg viewBox="0 0 ${W} ${H}" class="dchart">
    ${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgba(150,185,230,.12)"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end" fill="#70849f" font-size="15">${fmtY(v)}</text>`).join('')}
    ${[0, 0.25, 0.5, 0.75, 1].map((f) => { const t = Math.round(x0 + f * (x1 - x0)); return `<text x="${X(t)}" y="${H - 6}" text-anchor="middle" fill="#a3b5ce" font-size="15">${t}</text>`; }).join('')}
    <path d="${band}" fill="rgba(212,205,255,.16)"/>
    <path d="${line(res.slope)}" stroke="#d4cdff" stroke-width="2.2" fill="none"/>
    ${years.map((t, i) => `<circle cx="${X(t)}" cy="${Y(ys[i])}" r="3.2" fill="#5b9bff"/>`).join('')}</svg>`;
}

function openDetail(s) {
  let metric = 'season';
  openSheet(() => {
    const m = metric === 'season' ? { res: s.season, years: s.years, ys: s.season_fdd, fmt: (v) => Math.round(v), text: s.text, unit: '°C-days of cold per winter', foot: '' }
      : (() => { const d = s.iceup[metric]; return { res: d.result, years: d.years, ys: d.slot, fmt: (v) => slotLabel(v), text: d.text, unit: `date bare ice reaches ${metric} cm`,
        foot: d.n_reached < d.n_winters ? `${d.n_winters - d.n_reached} winter${d.n_winters - d.n_reached > 1 ? 's' : ''} never reached ${metric} cm and ${d.n_winters - d.n_reached > 1 ? 'are' : 'is'} left out — which can hide a real shift in the warmest winters.` : '' }; })();
    const r = m.res;
    const body = r.verdict === 'TOO FEW' ? `<p class="lead">${esc(m.text)}</p>` : `${lineChart(m.years, m.ys, r, m.fmt)}
      <p class="lead" style="margin-top:.5rem">${esc(m.text)}</p>${m.foot ? `<p class="lead faint">${esc(m.foot)}</p>` : ''}
      <div class="tests">${(r.tests || []).map((t) => `<div class="tcard ${t.pass ? 'ok' : 'no'}"><b>${t.pass ? '✓ PASS' : '✗ FAIL'}</b> <span>${esc(t.name)}</span><small>${esc(t.q)}</small><em>${esc(t.a)}</em></div>`).join('')}</div>`;
    return `<h2>${esc(s.name)} ${verdictChip(r)}</h2>
      <div class="seg" data-noswipe style="margin:.4rem 0 .6rem"><button data-m="season" class="${metric === 'season' ? 'on' : ''}" data-act="m">Season cold</button><button data-m="20" class="${metric === '20' ? 'on' : ''}" data-act="m">20 cm ice-up</button><button data-m="30" class="${metric === '30' ? 'on' : ''}" data-act="m">30 cm ice-up</button></div>
      ${lastNote ? `<p class="lead">${lastNote}</p>` : ''}<p class="eyebrow" style="margin-bottom:.2rem">${esc(m.unit)} · Theil–Sen line with 95% interval</p>${body}`;
  }, { live: true, onAct: (a, el) => { if (a === 'm') { metric = el.dataset.m; /* re-render through the live refresh */ import('../sheets.js').then((m) => m.refreshSheet()); } } });
}
