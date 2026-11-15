// NOW — "The lake, cut open". The signature screen.
import { Lake } from '../lake.js';
import { Snowfall } from '../snow.js';
import { isNum, num, ice as iceFmt, countTo, dshort, ago, esc, clamp } from '../fmt.js';
import { heroSentence, deltaChip, rankPhrase, sgn, fddFmt } from '../copy.js';
import { openTrace, openCalibration } from '../sheets.js';

const chip = (k, label, short) => `<span class="src src-${k}"><i></i><span class="w">${label}</span><span class="c">${short || label}</span></span>`;
const WC = (long, short) => `<span class="w">${long}</span><span class="c">${short}</span>`;   // wide / compact copy
const setHTML = (el, html) => { if (el._h !== html) { el.innerHTML = html; el._h = html; } };
const heroFmt = (v) => (isNum(v) ? (v < 0.05 ? '0' : iceFmt(v)) : '—');

export function mountNow(root) {
  root.innerHTML = `
  <div class="hero card" id="hero">
    <svg class="lake" role="img" aria-label="Cross-section of a frozen lake"></svg>
    <canvas class="snowfall"></canvas>
    <div class="hero-top">
      <div class="eyebrow">Ice thickness now ${chip('model', 'Model')}</div>
      <div class="hero-num trace" role="button" tabindex="0" data-trace="ice" aria-label="Where does this number come from?"><span class="n">—</span><span class="u">cm</span><span class="band"></span></div>
      <div class="delta" hidden></div>
    </div>
    <p class="sentence hero-bottom"></p>
  </div>
  <aside class="rail">
    <div class="card tile" data-trace="temp" role="button" tabindex="0">
      <div class="top"><span class="eyebrow">Air temp</span><span class="chips"></span></div>
      <div class="val"><span class="v">—</span><span class="unit">°C</span></div>
      <div class="grow"><svg class="spark" preserveAspectRatio="none"></svg><div class="sub"></div></div>
    </div>
    <div class="card tile" data-trace="snow" role="button" tabindex="0">
      <div class="top"><span class="eyebrow">Snow depth</span><span class="chips"></span></div>
      <div class="val"><span class="v">—</span><span class="unit">cm</span></div>
      <div class="grow"><div class="sub"></div><div class="cta-slot"></div></div>
    </div>
    <div class="card tile" data-trace="cold" role="button" tabindex="0">
      <div class="top"><span class="eyebrow">Cold banked</span><span class="chips"></span></div>
      <div class="val"><span class="v">—</span><span class="unit">°C-days</span></div>
      <div class="grow"><div class="barslot"></div><div class="legend"></div><div class="sub"></div></div>
    </div>
  </aside>`;
  const q = (s) => root.querySelector(s);
  const hero = q('#hero'), lake = new Lake(q('svg.lake')), snow = new Snowfall(q('canvas.snowfall'));
  const el = {
    n: q('.hero-num .n'), band: q('.hero-num .band'), delta: q('.delta'), sent: q('.sentence'), top: q('.hero-top'),
    tv: q('[data-trace=temp] .v'), tsub: q('[data-trace=temp] .sub'), tchips: q('[data-trace=temp] .chips'), spark: q('svg.spark'),
    sv: q('[data-trace=snow] .v'), ssub: q('[data-trace=snow] .sub'), schips: q('[data-trace=snow] .chips'), scta: q('[data-trace=snow] .cta-slot'),
    cv: q('[data-trace=cold] .v'), cbar: q('.barslot'), cleg: q('.legend'), csub: q('[data-trace=cold] .sub'), cchips: q('[data-trace=cold] .chips'),
  };
  snow.start();
  window.__lake = lake;

  // ---------------- interaction: tap any number -> Trace drawer
  const act = (e) => {
    const cta = e.target.closest('[data-act]');
    if (cta) { e.stopPropagation(); if (cta.dataset.act === 'cal') openCalibration(); return; }
    const t = e.target.closest('[data-trace]');
    if (t) openTrace(t.dataset.trace);
  };
  root.addEventListener('click', act);
  root.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { const t = e.target.closest('[data-trace]'); if (t) { e.preventDefault(); openTrace(t.dataset.trace); } } });

  // ---------------- layout: tell the lake where the text lives
  let lastKey = '';
  function layout() {
    const r = hero.getBoundingClientRect();
    if (!r.width) return;
    const avoidTop = el.top.offsetTop + el.top.offsetHeight;
    const bot = el.sent.offsetHeight + parseFloat(getComputedStyle(el.sent).bottom || 0) + 10;
    const key = [Math.round(r.width), Math.round(r.height), avoidTop, bot].join('|');
    if (key === lastKey) return;
    lastKey = key;
    lake.resize(r.width, r.height, avoidTop, bot);
    snow.resize(r.width, r.height, lake.ySurf);
  }
  new ResizeObserver(layout).observe(hero);

  // ---------------- sparkline
  function drawSpark(points, ok) {
    const w = 200, h = 34;
    el.spark.setAttribute('viewBox', `0 0 ${w} ${h}`);
    if (!ok || !points || points.length < 2) {
      el.spark.innerHTML = `<line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="rgba(255,181,71,.3)" stroke-dasharray="3 5" stroke-width="1.5"/>`; return;
    }
    const ys = points.map((p) => p[1]);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (hi - lo < 2) { const m = (hi + lo) / 2; lo = m - 1; hi = m + 1; }   // a flat room should look flat
    const X = (i) => (i / (points.length - 1)) * (w - 6) + 3, Y = (v) => h - 4 - ((v - lo) / (hi - lo)) * (h - 10);
    const d = points.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ');
    const last = points[points.length - 1];
    el.spark.innerHTML = `<path d="${d} L${X(points.length - 1)},${h} L${X(0)},${h} Z" fill="rgba(255,181,71,.10)"/><path d="${d}" fill="none" stroke="#ffb547" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/><circle cx="${X(points.length - 1)}" cy="${Y(last[1])}" r="2.6" fill="#ffb547"/>`;
  }

  // ---------------- main update
  function update(S) {
    const st = S.state, now = st.now, node = st.node, nasa = st.nasa;
    if (!now) return;
    const indoor = st.mode.deployment === 'indoor_demo';
    const nodeLive = node.state === 'live' || node.state === 'dropout';
    const iceE = now.ice || { cm: 0, lo: 0, hi: 0, factor: 1 };
    const has = now.phase && now.phase !== 'no_data' && now.phase !== 'offseason';

    // ---- hero numeral, band, delta, sentence
    countTo(el.n, has ? iceE.cm : null, heroFmt);
    const half = has ? (iceE.hi - iceE.lo) / 2 : 0;
    // symmetric band -> "± 3"; lopsided (no snow reading: the low end drops to the deep-snow floor) -> the honest range "20–49"
    const lopsided = has && Math.abs((iceE.cm - iceE.lo) - (iceE.hi - iceE.cm)) > 0.2 * Math.max(half, 1);
    el.band.textContent = half >= 0.5 && iceE.cm >= 0.5 ? (lopsided ? `${iceFmt(iceE.lo)}–${iceFmt(iceE.hi)}` : `± ${iceFmt(half)}`) : '';
    const dc = deltaChip(S);
    el.delta.hidden = !dc; if (dc) { el.delta.className = 'delta ' + dc.cls; el.delta.textContent = dc.text; }
    setHTML(el.sent, heroSentence(S));

    // ---- lake
    const nasaT = now.nasa_t && isNum(now.nasa_t.c) ? now.nasa_t.c : null;
    const nodeT = !indoor && node.temp.c !== null ? node.temp.c : null;
    const airT = nodeT !== null ? nodeT : nasaT;
    lake.set({
      snow: now.snow && now.snow.known ? now.snow.cm : 0,
      ice: has ? iceE.cm : 0, lo: has ? iceE.lo : 0, hi: has ? iceE.hi : 0,
      normal: has && now.ice_normal ? now.ice_normal.cm : 0, airT,
    }, {
      thresholds: st.thresholds, nodeLive, snowKnown: !!(now.snow && now.snow.known), simulated: node.simulated,
      cold: isNum(airT) && airT < 0 ? clamp(-airT / 20, 0, 1) : 0, needsCal: node.snow.state === 'needs_calibration',
      normalLabel: has ? `NORMAL ${dshort(now.fdd.compare_date).toUpperCase()}` : '',
      reduce: document.documentElement.dataset.reduceMotion === '1',
    });
    snow.setSnow(now.snow && now.snow.known ? now.snow.cm : null);
    layout();

    // ---- tile: air temperature (field node)
    const nodeChip = node.simulated ? chip('sim', 'Simulated node', 'Sim') : chip('node', 'Field node', 'Node');
    setHTML(el.tchips, nodeChip);
    const tok = nodeLive && node.temp.c !== null;
    countTo(el.tv, tok ? node.temp.c : null, (v) => sgn(v, 1));
    let tsub;
    if (!nodeLive) tsub = WC(`Node offline${nasaT !== null ? ` · NASA <span style="color:var(--nasa)">${dshort(now.as_of)}: ${sgn(nasaT)}°C</span>` : ''}`, 'Node offline');
    else if (node.temp.state === 'out_of_range') tsub = WC('Below the sensor’s range — the DHT11 only reads 0–50°C', 'Below sensor range (0–50°C)');
    else if (node.temp.state !== 'ok') tsub = 'No valid temperature reading';
    else tsub = indoor ? WC('Room temperature · indoor demo, <b>not climate data</b>', 'Indoor · <b>not climate data</b>') : 'Outdoors · last 6 hours';
    setHTML(el.tsub, tsub);
    drawSpark(node.spark, tok);

    // ---- tile: snow depth (field node)
    setHTML(el.schips, nodeChip);
    const ss = node.snow.state, sok = nodeLive && ss === 'ok' && node.snow.cm !== null;
    countTo(el.sv, sok ? node.snow.cm : null, (v) => (isNum(v) ? (v < 10 ? v.toFixed(1) : String(Math.round(v))) : '—'));
    let ssub = '', cta = '';
    if (!nodeLive) ssub = WC('Node offline — this wakes up on its own when readings resume.', 'Node offline');
    else if (ss === 'needs_calibration') { ssub = WC('Point the sensor at bare ground, then set the ground level.', 'Point it at bare ground.'); cta = '<button class="cta" data-act="cal">Set ground level</button>'; }
    else if (ss === 'out_of_range') ssub = 'Out of range — the sensor reads 2–400 cm.';
    else if (ss === 'below_ground') { ssub = 'Reads below the ground level — recalibrate?'; cta = '<button class="cta ghost" data-act="cal">Set ground level</button>'; }
    else ssub = indoor ? WC('<b>Try it:</b> slide a book under the sensor.', '<b>Try it:</b> slide a book under it') : `Ground level ${num(node.snow.ground_cm, 1)} cm`;
    setHTML(el.ssub, ssub); setHTML(el.scta, cta);
    el.sv.parentElement.classList.toggle('na', !sok);
    el.tv.parentElement.classList.toggle('na', !tok);
    q('[data-trace=snow]').classList.toggle('has-cta', !!cta);

    // ---- tile: cold banked (NASA verified solid + node dashed)
    const f = now.fdd, nrm = now.normal;
    setHTML(el.cchips, chip('nasa', 'NASA POWER', 'NASA') + (f && f.node_used ? chip('node', 'Node') : ''));
    countTo(el.cv, has && f ? f.now : null, (v) => fddFmt(v));
    if (has && f && nrm) {
      const scale = Math.max(nrm.p90 * 1.15, f.now * 1.12, 4), pc = (x) => clamp((x / scale) * 100, 0, 100);
      const rw = Math.max(1.6, pc(nrm.p90) - pc(nrm.p10));
      setHTML(el.cbar, `<div class="cbar"><div class="rng" style="left:${pc(nrm.p10)}%;width:${rw}%"></div><div class="seg v" style="width:${pc(f.verified)}%"></div>${f.node_used ? `<div class="seg n" style="left:${pc(f.verified)}%;width:${Math.max(0.8, pc(f.node))}%"></div>` : ''}<div class="tick" style="left:${pc(nrm.p50)}%"></div></div>`);
      setHTML(el.cleg, `<span><i style="background:var(--nasa)"></i>${WC('NASA to ' + dshort(now.as_of), 'NASA')}</span><span><i style="background:repeating-linear-gradient(135deg,var(--node) 0 3px,rgba(255,181,71,.3) 3px 6px)"></i>${WC(f.node_used ? 'Node since' : (indoor ? 'Node: excluded' : 'Node: none yet'), 'Node')}</span><span><i style="background:var(--normal)"></i>Normal</span>`);
      setHTML(el.csub, WC(esc(rankPhrase(now)).replace(/^./, (c) => c.toUpperCase()), esc(rankPhrase(now)).replace(/ (of \d+ winters) (by|on) .*$/, ' $1').replace(/^./, (c) => c.toUpperCase())));
    } else {
      setHTML(el.cbar, ''); setHTML(el.cleg, ''); setHTML(el.csub, nasa && nasa.has_data === false ? 'Waiting for NASA history' : 'Off-season');
    }
  }

  return { update, resize: layout };
}
