// SEASON — "This winter vs every other". One big chart; direct labels; scrub to read any day.
import { isNum, clamp, slotLabel, dshort, esc } from '../fmt.js';
import { rankPhrase, fddFmt } from '../copy.js';

const NS = 'http://www.w3.org/2000/svg';
const MONTHS = [[0, 'Nov'], [30, 'Dec'], [61, 'Jan'], [92, 'Feb'], [121, 'Mar']];
const XMAX = 151;   // chart runs 1 Nov -> 31 Mar

export function mountSeason(root) {
  root.innerHTML = `<div class="card season">
    <div class="s-head"><p class="s-headline"></p>
      <div class="s-ctl" data-noswipe>
        <div class="seg"><button data-mode="ice" class="on">Ice</button><button data-mode="cold">Cold</button></div>
        <div class="chips2"><button data-hl="coldest">Coldest</button><button data-hl="warmest">Warmest</button><button data-hl="latest">Latest</button></div>
      </div></div>
    <div class="s-chart" data-noswipe><svg></svg><div class="s-readout"></div></div>
    <p class="s-foot"></p></div>`;
  const q = (s) => root.querySelector(s);
  const svg = q('svg'), box = q('.s-chart'), ro = q('.s-readout');
  let data = null, snap = null, mode = 'ice', hl = new Set(), cursor = null, W = 0, H = 0, geo = null, lastKey = '';

  const val = (cum) => (mode === 'ice' && isNum(cum) ? data.ice.alpha * Math.sqrt(Math.max(0, cum)) : cum);
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };

  async function load() {
    try { const r = await fetch('/api/season', { cache: 'no-store' }); data = await r.json(); } catch (e) { data = null; }
    draw();
  }

  function path(arr, X, Y, from = 0, to = XMAX) {
    let d = '', pen = false;
    for (let i = from; i <= to && i < arr.length; i++) {
      const v = arr[i];
      if (!isNum(v)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)},${Y(val(v)).toFixed(1)}`; pen = true;
    }
    return d;
  }

  function draw() {
    if (!W || !H) return;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.textContent = '';
    if (!data || !data.has_data) { q('.s-headline').textContent = 'No NASA history cached yet — run prefetch.py once with internet.'; return; }
    const compact = W < 560;
    const L = compact ? 34 : 44, R = compact ? 52 : 86, T = 20, B = 22;
    const pw = W - L - R, ph = H - T - B;
    // y domain: the thickest thing on the chart
    let max = 0;
    for (const w of data.winters) for (let i = 0; i <= XMAX; i++) if (isNum(w.cum[i])) max = Math.max(max, val(w.cum[i]));
    const step = mode === 'ice' ? 10 : 100;
    const top = Math.max(mode === 'ice' ? 40 : 200, Math.ceil(max / step) * step);
    const X = (i) => L + (i / XMAX) * pw, Y = (v) => T + ph - (v / top) * ph;
    geo = { L, pw, T, ph, X, Y, top };

    // grid + axes
    const g0 = el('g', {}, svg);
    const ts = [10, 20, 25, 50, 100, 200, 250, 500].find((x) => top / x <= 5) || 500;
    for (let v = 0; v <= top + 1e-6; v += ts) {
      el('line', { x1: L, x2: L + pw, y1: Y(v), y2: Y(v), stroke: 'rgba(150,185,230,.10)' }, g0);
      const t = el('text', { x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', fill: '#70849f', 'font-size': 12 }, g0); t.textContent = Math.round(v);
    }
    const u = el('text', { x: L - 6, y: T - 9, 'text-anchor': 'end', fill: '#70849f', 'font-size': 12, 'font-weight': 700 }, g0);
    u.textContent = mode === 'ice' ? 'cm' : '°C-d';
    for (const [i, m] of MONTHS) {
      el('line', { x1: X(i), x2: X(i), y1: T, y2: T + ph, stroke: 'rgba(150,185,230,.07)' }, g0);
      const t = el('text', { x: X(i) + 4, y: H - 6, fill: '#a3b5ce', 'font-size': 12, 'font-weight': 600 }, g0); t.textContent = m;
    }
    // safety thresholds (ice mode): quiet bands, labelled at the left edge of the plot
    if (mode === 'ice') {
      for (const th of data.thresholds) {
        const y1 = Y(th.hi || th.cm), y2 = Y(th.cm);
        if (th.cm > top) continue;
        if (th.hi) el('rect', { x: L, y: y1, width: pw, height: y2 - y1, fill: 'rgba(191,239,255,.06)' }, g0);
        el('line', { x1: L, x2: L + pw, y1: y2, y2: y2, stroke: 'rgba(191,239,255,.28)', 'stroke-dasharray': '2 5' }, g0);
        if (th.id !== 'snowmobile') {   // 10 and 12 cm sit too close to label both; the dashed line still marks 12
          const t = el('text', { x: L + pw - 4, y: y2 - 3, 'text-anchor': 'end', fill: 'rgba(191,239,255,.6)', 'font-size': 12, 'font-weight': 700 }, g0);
          t.textContent = `${th.label.split(' /')[0].toUpperCase()} ${th.cm}`;
        }
      }
    }
    // spaghetti: every past winter
    const sp = el('g', { fill: 'none', 'stroke-linejoin': 'round' }, svg);
    for (const w of data.winters) el('path', { d: path(w.cum, X, Y), stroke: 'rgba(132,151,179,.2)', 'stroke-width': 1 }, sp);
    // ribbon + median
    const b = data.baseline;
    let rib = '';
    for (let i = 0; i <= XMAX; i++) rib += `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(val(b.p90[i])).toFixed(1)}`;
    for (let i = XMAX; i >= 0; i--) rib += `L${X(i).toFixed(1)},${Y(val(b.p10[i])).toFixed(1)}`;
    el('path', { d: rib + 'Z', fill: 'rgba(132,151,179,.2)' }, svg);
    el('path', { d: path(b.p50, X, Y), fill: 'none', stroke: '#9fb0c9', 'stroke-width': 2 }, svg);
    // highlighted winters (direct labels)
    const hlDefs = { coldest: data.coldest, warmest: data.warmest, latest: data.latest };
    for (const key of hl) {
      const w = data.winters.find((x) => x.W === hlDefs[key]); if (!w) continue;
      el('path', { d: path(w.cum, X, Y), fill: 'none', stroke: '#eaf9ff', 'stroke-width': 2, 'stroke-dasharray': key === 'latest' ? '1 0' : '5 3' }, svg);
      const i = XMAX, v = val(w.cum[i]);
      if (isNum(v)) { const t = el('text', { x: X(i) + 5, y: Y(v) + 4, fill: '#eaf9ff', 'font-size': 12, 'font-weight': 700 }, svg); t.textContent = `${w.label}`; }
    }
    // direct labels for the baseline (no legend lookup)
    const lab = (txt, i, v, dy, fill) => { const t = el('text', { x: X(XMAX) + 5, y: Y(val(v[i])) + dy, fill, 'font-size': 12, 'font-weight': 700 }, svg); t.textContent = txt; };
    lab(compact ? 'median' : 'normal', XMAX, b.p50, 4, '#9fb0c9');
    if (!compact) { lab('90%', XMAX, b.p90, 3, '#70849f'); lab('10%', XMAX, b.p10, 4, '#70849f'); }

    // this winter: NASA solid, node dashed, NASA-lag strip, today marker
    const c = data.current;
    if (c) {
      const lastN = data.asof_slot !== null && data.asof_slot !== undefined ? data.asof_slot : -1;
      if (data.today_slot !== null && lastN >= 0 && data.today_slot > lastN) {
        el('rect', { x: X(lastN), y: T, width: Math.max(2, X(data.today_slot) - X(lastN)), height: ph, fill: 'rgba(255,181,71,.07)' }, svg);
      }
      el('path', { d: path(c.cum, X, Y, 0, Math.max(0, lastN)), fill: 'none', stroke: '#5b9bff', 'stroke-width': 3.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, svg);
      let endSlot = lastN, endV = lastN >= 0 ? c.cum[lastN] : null;
      if (c.node_used && lastN >= 0 && data.today_slot > lastN && isNum(c.now)) {
        el('path', { d: `M${X(lastN)},${Y(val(c.cum[lastN]))} L${X(data.today_slot)},${Y(val(c.now))}`, stroke: '#ffb547', 'stroke-width': 3.2, 'stroke-dasharray': '6 4', fill: 'none' }, svg);
        endSlot = data.today_slot; endV = c.now;
      }
      if (data.today_slot !== null && data.today_slot <= XMAX) {
        el('line', { x1: X(data.today_slot), x2: X(data.today_slot), y1: T, y2: T + ph, stroke: 'rgba(255,255,255,.35)', 'stroke-dasharray': '2 4' }, svg);
        const lt = el('text', { x: X(data.today_slot) + 4, y: T + 11, fill: '#eaf1fb', 'font-size': 12, 'font-weight': 800, 'letter-spacing': '.1em' }, svg); lt.textContent = 'TODAY';
      }
      if (endSlot >= 0 && isNum(endV) && endSlot <= XMAX) {
        el('circle', { cx: X(endSlot), cy: Y(val(endV)), r: 5, fill: c.node_used && endSlot === data.today_slot ? '#ffb547' : '#5b9bff', stroke: '#050a12', 'stroke-width': 2 }, svg);
        const t = el('text', { x: X(endSlot) + 9, y: Y(val(endV)) - 8, fill: '#8db9ff', 'font-size': 12, 'font-weight': 800 }, svg);
        t.textContent = 'THIS WINTER';
      }
    }
    // scrub cursor
    geo.cur = el('line', { y1: T, y2: T + ph, stroke: '#eaf1fb', 'stroke-width': 1.2 }, svg);
    geo.dot = el('circle', { r: 4.5, fill: '#5b9bff', stroke: '#050a12', 'stroke-width': 2 }, svg);
    const dflt = data.asof_slot !== null && data.asof_slot !== undefined ? data.asof_slot : (data.today_slot !== null ? data.today_slot : XMAX);
    placeCursor(cursor !== null ? cursor : clamp(dflt, 0, XMAX));
  }

  function placeCursor(slot) {
    if (!geo || !data) return;
    cursor = clamp(Math.round(slot), 0, XMAX);
    const x = geo.X(cursor);
    geo.cur.setAttribute('x1', x); geo.cur.setAttribute('x2', x);
    const c = data.current, here = c && isNum(c.cum[cursor]) ? c.cum[cursor] : null;
    if (here !== null) { geo.dot.setAttribute('cx', x); geo.dot.setAttribute('cy', geo.Y(val(here))); geo.dot.setAttribute('opacity', 1); } else geo.dot.setAttribute('opacity', 0);
    const b = data.baseline, f = (v) => (mode === 'ice' ? `${val(v).toFixed(val(v) < 10 ? 1 : 0)} cm` : `${fddFmt(v)} °C-d`);
    const samples = data.winters.map((w) => w.cum[cursor]).filter(isNum);
    let rank = '';
    if (here !== null && samples.length) {
      const less = samples.filter((v) => v < here - 1e-9).length, eq = samples.filter((v) => Math.abs(v - here) < 1e-9).length;
      rank = eq / samples.length >= 0.25 ? `tied with ${eq} of ${samples.length} winters` : (100 * (less + eq / 2) / samples.length >= 50 ? `colder than ${Math.round(100 * (less + eq / 2) / samples.length)}% of winters` : `milder than ${Math.round(100 - 100 * (less + eq / 2) / samples.length)}% of winters`);
    }
    ro.innerHTML = `<b>${slotLabel(cursor)}</b>`
      + (here !== null ? `<span class="rd" style="color:var(--nasa)">This winter ${f(here)}</span>` : `<span class="rd faint">${c ? 'not yet' : 'no current winter'}</span>`)
      + `<span class="rd" style="color:#9fb0c9">Normal ${f(b.p50[cursor])} <small>(${f(b.p10[cursor])}–${f(b.p90[cursor])})</small></span>`
      + (rank ? `<span class="rd faint">${rank}</span>` : '');
  }

  function scrub(e) {
    if (!geo) return;
    const r = svg.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W;
    placeCursor(((x - geo.L) / geo.pw) * XMAX);
  }
  let dragging = false;
  svg.addEventListener('pointerdown', (e) => { dragging = true; svg.setPointerCapture(e.pointerId); scrub(e); });
  svg.addEventListener('pointermove', (e) => { if (dragging) scrub(e); });
  ['pointerup', 'pointercancel'].forEach((n) => svg.addEventListener(n, () => { dragging = false; }));

  root.addEventListener('click', (e) => {
    const m = e.target.closest('[data-mode]'), h = e.target.closest('[data-hl]');
    if (m) { mode = m.dataset.mode; root.querySelectorAll('[data-mode]').forEach((b) => b.classList.toggle('on', b === m)); draw(); }
    if (h) { const k = h.dataset.hl; hl.has(k) ? hl.delete(k) : hl.add(k); h.classList.toggle('on', hl.has(k)); draw(); }
  });

  function resize() {
    const r = box.getBoundingClientRect();
    if (Math.abs(r.width - W) > 1 || Math.abs(r.height - H) > 1) { W = Math.round(r.width); H = Math.round(r.height); draw(); }
  }
  new ResizeObserver(resize).observe(box);

  function headline() {
    const now = snap && snap.now;
    if (!now || now.phase === 'no_data') return '';
    if (now.phase === 'offseason') return `Every winter since ${data && data.first_W ? data.first_W - 1 : '1981'}, side by side. The next one starts on 1 Nov.`;
    const name = now.winter.label, n = now.rank ? now.rank.n : (data ? data.n : 0);
    if (now.delta && now.delta.available) {
      const p = Math.round(now.delta.pct_of_normal - 100);
      return `This winter (${name}) is tracking <b>${Math.abs(p)}% ${p < 0 ? 'below' : 'above'} normal</b> — ${rankPhrase(now)}.`;
    }
    return `Winter ${name} has banked <b>${fddFmt(now.fdd.now)}</b> °C-days by ${dshort(now.fdd.compare_date)} — a normal winter has <b>${fddFmt(now.normal.p50)}</b> by now (${rankPhrase(now)}).`;
  }

  let loadedKey = '';
  function update(S) {
    snap = S.state;
    q('.s-headline').innerHTML = headline();
    const key = [snap.site.id, snap.clock.today, snap.now && snap.now.as_of, snap.now && snap.now.fdd && Math.round(snap.now.fdd.now)].join('|');
    if (key !== loadedKey) { loadedKey = key; load(); }
    q('.s-foot').innerHTML = `${esc(snap.site.name)} · <span class="nasa-t">NASA POWER daily T2M</span> · ${data ? data.n : '—'} winters since ${data && data.first_W ? data.first_W - 1 : '—'} · bare-ice model, snow ignored so winters compare like for like`;
  }
  return { update, resize };
}
