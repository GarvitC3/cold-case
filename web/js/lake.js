import { ICONS } from './icons.js';
import { clamp, lerp, isNum } from './fmt.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
};
const mix = (a, b, t) => a.map((v, i) => Math.round(lerp(v, b[i], t)));
const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;

function skyStops(t) {

  const k = isNum(t) ? clamp((6 - t) / 26, 0, 1) : 0.3;
  return [rgb(mix([10, 17, 33], [8, 11, 34], k)), rgb(mix([30, 56, 86], [26, 38, 88], k))];
}

const DEFAULT = { snow: 0, ice: 0, lo: 0, hi: 0, normal: 0, domain: 45, airT: null };

export class Lake {
  constructor(svg) {
    this.svg = svg;
    this.w = 0; this.h = 0;
    this.avoidTop = 130;
    this.bottomReserve = 56;
    this.c = { ...DEFAULT };
    this.t = { ...DEFAULT };
    this.meta = { thresholds: [], hasNode: false, nodeLive: false, snowKnown: false, simulated: false,
                  cold: 0, normalLabel: 'normal', needsCal: false, reduce: false, hasIce: false };
    this._raf = 0; this._last = 0; this._litKey = '';
    this.build();
  }

  build() {
    const s = this.svg;
    s.textContent = '';
    const defs = el('defs', {}, s);
    const lg = (id, stops, x1 = 0, y1 = 0, x2 = 0, y2 = 1) => {
      const g = el('linearGradient', { id, x1, y1, x2, y2 }, defs);
      stops.forEach(([o, c, a]) => el('stop', { offset: o, 'stop-color': c, 'stop-opacity': a ?? 1 }, g));
      return g;
    };
    this.skyG = lg('g-sky', [[0, '#0a1121'], [1, '#1e3856']]);
    lg('g-water', [[0, '#12486c'], [0.35, '#0a2e4d'], [1, '#050f20']]);
    lg('g-ice', [[0, '#f1fbff'], [0.35, '#a6e2f2'], [1, '#2b9bb3']]);
    lg('g-snow', [[0, '#f6f9fe'], [1, '#c3d3ea']]);
    lg('g-earth', [[0, '#1c2b41'], [1, '#09111e']]);
    lg('g-beam', [[0, '#ffb547', 0.55], [1, '#ffb547', 0.06]]);
    const sw = lg('g-sweep', [[0, '#fff', 0], [0.5, '#fff', 0.55], [1, '#fff', 0]], 0, 0, 1, 0);
    const pat = el('pattern', { id: 'p-band', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
    el('rect', { width: 6, height: 6, fill: 'rgba(212,205,255,.10)' }, pat);
    el('line', { x1: 0, y1: 0, x2: 0, y2: 6, stroke: 'rgba(160,140,255,.5)', 'stroke-width': 1.6 }, pat);
    this.bandClip = el('clipPath', { id: 'c-band' }, defs);
    this.bandClipRect = el('rect', {}, this.bandClip);
    this.iceClip = el('clipPath', { id: 'c-ice' }, defs);
    this.iceClipRect = el('rect', {}, this.iceClip);
    this.waterClip = el('clipPath', { id: 'c-water' }, defs);
    this.waterClipRect = el('rect', {}, this.waterClip);

    this.sky = el('rect', { fill: 'url(#g-sky)' }, s);
    this.stars = el('g', { opacity: 0.0 }, s);
    this.water = el('rect', { fill: 'url(#g-water)' }, s);
    this.waves = el('g', { class: 'waves', 'clip-path': 'url(#c-water)' }, s);
    for (let i = 0; i < 3; i++) el('path', { fill: 'none', stroke: 'rgba(150,210,240,.2)', 'stroke-width': 1.4, class: `wave w${i}` }, this.waves);
    this.shore = el('path', { fill: 'url(#g-earth)' }, s);
    this.shoreLine = el('path', { fill: 'none', stroke: 'rgba(160,190,225,.28)', 'stroke-width': 1.2 }, s);

    this.ice = el('rect', { fill: 'url(#g-ice)' }, s);
    this.iceTop = el('line', { stroke: 'rgba(255,255,255,.85)', 'stroke-width': 1.5 }, s);
    this.band = el('g', { 'clip-path': 'url(#c-band)' }, s);
    this.iceBottom = el('line', { stroke: '#f4fcff', 'stroke-width': 2.2, 'stroke-linecap': 'round' }, s);
    this.bandFill = el('rect', { fill: 'url(#p-band)' }, this.band);
    this.sweep = el('rect', { fill: 'url(#g-sweep)', class: 'sweep', opacity: 0.55 }, this.band);
    this.bandEdgeLo = el('line', { stroke: 'rgba(212,205,255,.9)', 'stroke-width': 1.2, 'stroke-dasharray': '3 3' }, s);
    this.bandEdgeHi = el('line', { stroke: 'rgba(212,205,255,.9)', 'stroke-width': 1.2, 'stroke-dasharray': '3 3' }, s);
    this.iceLabel = el('text', { fill: '#06202c', 'font-size': 12, 'font-weight': 800, 'letter-spacing': '.12em' }, s);

    this.ghost = el('line', { stroke: '#b9c8de', 'stroke-width': 2, 'stroke-dasharray': '7 5' }, s);
    this.ghostBg = el('rect', { rx: 4, fill: 'rgba(5,10,18,.82)' }, s);
    this.ghostLabel = el('text', { fill: '#a9b9d1', 'font-size': 12, 'font-weight': 700, 'letter-spacing': '.08em', 'text-anchor': 'end' }, s);

    this.snowLake = el('path', { fill: 'url(#g-snow)' }, s);
    this.snowShore = el('path', { fill: 'url(#g-snow)' }, s);
    this.arrows = el('g', { class: 'arrows' }, s);

    this.sensor = el('g', { class: 'sensor' }, s);
    this.beam = el('path', { fill: 'url(#g-beam)' }, this.sensor);
    this.beamL = el('line', { stroke: '#ffb547', 'stroke-width': 1, 'stroke-dasharray': '3 4', opacity: 0.9 }, this.sensor);
    this.beamR = el('line', { stroke: '#ffb547', 'stroke-width': 1, 'stroke-dasharray': '3 4', opacity: 0.9 }, this.sensor);
    this.post = el('line', { stroke: '#5b6f8c', 'stroke-width': 3, 'stroke-linecap': 'round' }, this.sensor);
    this.head = el('rect', { rx: 4, fill: '#16233a', stroke: '#ffb547', 'stroke-width': 1.6 }, this.sensor);
    this.eyeL = el('circle', { fill: '#0b1220', stroke: '#ffb547', 'stroke-width': 1.5 }, this.sensor);
    this.eyeR = el('circle', { fill: '#0b1220', stroke: '#ffb547', 'stroke-width': 1.5 }, this.sensor);
    this.dim = el('g', { class: 'dim' }, this.sensor);
    this.dimLine = el('line', { stroke: '#ffb547', 'stroke-width': 1.6 }, this.dim);
    this.dimTop = el('line', { stroke: '#ffb547', 'stroke-width': 1.6 }, this.dim);
    this.dimBot = el('line', { stroke: '#ffb547', 'stroke-width': 1.6 }, this.dim);
    this.dimBg = el('rect', { rx: 5, fill: 'rgba(5,10,18,.86)', stroke: 'rgba(255,181,71,.5)', 'stroke-width': 1 }, this.dim);
    this.dimText = el('text', { fill: '#ffb547', 'font-size': 13, 'font-weight': 800 }, this.dim);
    this.nodeTag = el('text', { fill: '#ffb547', 'font-size': 12, 'font-weight': 800, 'letter-spacing': '.08em', 'text-anchor': 'middle' }, this.sensor);

    this.ruler = el('g', { class: 'ruler' }, s);
    this.waterTag = el('text', { fill: 'rgba(150,190,230,.45)', 'font-size': 12, 'font-weight': 700, 'letter-spacing': '.2em' }, s);
    this.waterTag.textContent = 'WATER';

    const suf = `-${(Lake._n = (Lake._n || 0) + 1)}`;
    s.querySelectorAll('[id]').forEach((n) => { n.id += suf; });
    s.querySelectorAll('*').forEach((n) => {
      for (const at of ['fill', 'stroke', 'clip-path']) {
        const v = n.getAttribute(at);
        if (v && v.includes('url(#')) n.setAttribute(at, v.replace(/url\(#([\w-]+)\)/, `url(#$1${suf})`));
      }
    });
  }

  resize(w, h, avoidTop, bottomReserve) {
    if (!(w > 0 && h > 0)) return;
    this.w = w; this.h = h;
    if (isNum(avoidTop)) this.avoidTop = avoidTop;
    if (isNum(bottomReserve)) this.bottomReserve = bottomReserve;
    this.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    this.geom();
    this._rulerKey = '';
    this.kick();
  }

  set(target, meta) {
    Object.assign(this.t, target);
    if (meta) Object.assign(this.meta, meta);

    const need = Math.max(this.t.hi || 0, this.t.normal || 0, 12) * 1.18;
    this.t.domain = Math.max(45, Math.ceil(need / 15) * 15);
    this.kick();
  }

  kick() { if (!this._raf && this.w) this._raf = requestAnimationFrame((t) => this.frame(t)); }

  frame(now) {
    this._raf = 0;
    const dt = Math.min(0.1, Math.max(0.001, (now - (this._last || now)) / 1000));
    this._last = now;
    const k = this.meta.reduce ? 1 : 1 - Math.exp(-dt / 0.3);
    let moving = false;
    for (const key of ['snow', 'ice', 'lo', 'hi', 'normal', 'domain']) {
      const d = this.t[key] - this.c[key];
      if (Math.abs(d) > 0.004) { this.c[key] += d * k; moving = true; } else this.c[key] = this.t[key];
    }
    if (isNum(this.t.airT)) {
      this.c.airT = isNum(this.c.airT) ? this.c.airT + (this.t.airT - this.c.airT) * k : this.t.airT;
      if (Math.abs(this.t.airT - this.c.airT) > 0.02) moving = true;
    } else this.c.airT = null;
    this.draw();
    if (moving) { this._last = now; this._raf = requestAnimationFrame((t) => this.frame(t)); } else this._last = 0;
  }

  geom() {
    const { w, h } = this;
    const compact = w < 560;
    this.rulerW = clamp(w * 0.2, 70, 138);
    this.plotW = w - this.rulerW;
    this.shoreW = clamp(this.plotW * 0.24, 106, 150);
    this.lakeX0 = this.rulerW;
    this.shoreX0 = w - this.shoreW;
    const sentH = this.bottomReserve;
    const minSurf = this.avoidTop + 26;
    this.ySurf = clamp(Math.max(h * 0.4, minSurf), h * 0.3, h - sentH - 8 - h * 0.34);
    this.iceZone = h - this.ySurf - sentH - 8;
    this.compact = compact;
    this.sz = clamp(w / 640, 0.82, 1.3);
    this.sky.setAttribute('x', 0); this.sky.setAttribute('y', 0); this.sky.setAttribute('width', w); this.sky.setAttribute('height', this.ySurf + 1);
    this.skyG.setAttribute('gradientUnits', 'userSpaceOnUse'); this.skyG.setAttribute('x1', 0); this.skyG.setAttribute('x2', 0);
    this.skyG.setAttribute('y1', 0); this.skyG.setAttribute('y2', this.ySurf);
    this.water.setAttribute('x', 0); this.water.setAttribute('y', this.ySurf);
    this.water.setAttribute('width', this.shoreX0 + 6); this.water.setAttribute('height', h - this.ySurf);
    for (const [k, v] of [['x', 0], ['y', this.ySurf], ['width', this.shoreX0], ['height', h - this.ySurf]]) this.waterClipRect.setAttribute(k, v);

    const bank = Math.min(46, (h - this.ySurf) * 0.12);
    const sx = this.shoreX0;
    this.shore.setAttribute('d', `M${sx},${this.ySurf} L${w},${this.ySurf} L${w},${h} L${sx - bank},${h} Q${sx - bank * 0.2},${this.ySurf + (h - this.ySurf) * 0.55} ${sx},${this.ySurf} Z`);
    this.shoreLine.setAttribute('d', `M${sx},${this.ySurf} L${w},${this.ySurf}`);

    const ww = this.shoreX0 - this.lakeX0;
    this.waves.querySelectorAll('.wave').forEach((p, i) => {
      const y = this.ySurf + (h - this.ySurf) * (0.55 + i * 0.14);
      let d = `M-60,${y}`;
      for (let x = 0; x <= this.shoreX0 + 120; x += 30) d += ` q7,${i % 2 ? -3 : 3} 15,0 t15,0`;
      p.setAttribute('d', d);
    });
    this.waterTag.setAttribute('x', this.lakeX0 + 10);
    this.waterTag.setAttribute('y', h - this.bottomReserve + 2 > this.ySurf + 30 ? this.ySurf + this.iceZone + 2 : h - 8);
    this.iceClipRect.setAttribute('x', this.lakeX0); this.iceClipRect.setAttribute('width', this.shoreX0 - this.lakeX0 + 4);

    this.stars.textContent = '';
    let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 26; i++) el('circle', { cx: rnd() * w, cy: rnd() * this.ySurf * 0.8, r: 0.6 + rnd() * 0.9, fill: '#cfe0ff', opacity: 0.15 + rnd() * 0.35 }, this.stars);
    this.stars.setAttribute('opacity', 1);
  }

  pill(t, bg, text, x, y, anchor) {
    if (t._txt !== text) { t.textContent = text; t._txt = text; t._w = text ? t.getComputedTextLength() : 0; }
    t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('text-anchor', anchor);
    bg.setAttribute('x', anchor === 'end' ? x - t._w - 6 : x - 6); bg.setAttribute('y', y - 14);
    bg.setAttribute('width', t._w ? t._w + 12 : 0); bg.setAttribute('height', 21);
  }

  yOfIce(cm) { return this.ySurf + cm * this.ppc; }

  snowPx(cm) {

    const avail = Math.max(24, this.ySurf - this.avoidTop - 18);
    const lin = cm * this.ppc;
    return avail * (1 - Math.exp(-lin / avail));
  }

  draw() {
    const { w, h, c, meta } = this;
    if (!w) return;
    this.ppc = this.iceZone / c.domain;
    const ppc = this.ppc, ys = this.ySurf, x0 = this.lakeX0, x1 = this.shoreX0, sz = this.sz;
    const [top, bot] = skyStops(c.airT);
    const stops = this.skyG.querySelectorAll('stop');
    stops[0].setAttribute('stop-color', top); stops[1].setAttribute('stop-color', bot);

    const hasIce = c.ice >= 0.15;
    const iceH = c.ice * ppc, loY = ys + c.lo * ppc, hiY = ys + c.hi * ppc;
    this.ice.setAttribute('x', x0); this.ice.setAttribute('width', x1 - x0 + 4);
    this.ice.setAttribute('y', ys); this.ice.setAttribute('height', Math.max(0, iceH));
    this.ice.setAttribute('opacity', hasIce ? 1 : 0);
    this.iceTop.setAttribute('x1', x0); this.iceTop.setAttribute('x2', x1 + 4); this.iceTop.setAttribute('y1', ys); this.iceTop.setAttribute('y2', ys);
    this.iceTop.setAttribute('opacity', hasIce ? 1 : 0.35);
    const bandOn = hasIce && c.hi - c.lo > 0.15;
    this.band.setAttribute('opacity', bandOn ? 1 : 0);
    this.bandClipRect.setAttribute('x', x0); this.bandClipRect.setAttribute('width', x1 - x0 + 4);
    this.bandClipRect.setAttribute('y', loY); this.bandClipRect.setAttribute('height', Math.max(0, hiY - loY));
    this.bandFill.setAttribute('x', x0); this.bandFill.setAttribute('width', x1 - x0 + 4); this.bandFill.setAttribute('y', loY); this.bandFill.setAttribute('height', Math.max(0, hiY - loY));
    this.sweep.setAttribute('x', x0 - 120); this.sweep.setAttribute('width', 120); this.sweep.setAttribute('y', loY); this.sweep.setAttribute('height', Math.max(0, hiY - loY));
    this.sweep.style.setProperty('--sweep', `${x1 - x0 + 240}px`);
    for (const [ln, y] of [[this.bandEdgeLo, loY], [this.bandEdgeHi, hiY]]) {
      ln.setAttribute('x1', x0); ln.setAttribute('x2', x1); ln.setAttribute('y1', y); ln.setAttribute('y2', y); ln.setAttribute('opacity', bandOn ? 1 : 0);
    }
    this.iceBottom.setAttribute('x1', x0); this.iceBottom.setAttribute('x2', x1); this.iceBottom.setAttribute('y1', ys + iceH); this.iceBottom.setAttribute('y2', ys + iceH);
    this.iceBottom.setAttribute('opacity', hasIce ? 0.95 : 0);
    const showIceLabel = hasIce && iceH > 22 * sz && loY - ys > 22 * sz;
    this.iceLabel.textContent = showIceLabel ? 'ICE' : '';
    this.iceLabel.setAttribute('x', x0 + 10); this.iceLabel.setAttribute('y', ys + 15 * sz);

    const gy = ys + c.normal * ppc;
    this.ghost.setAttribute('x1', x0); this.ghost.setAttribute('x2', x1); this.ghost.setAttribute('y1', gy); this.ghost.setAttribute('y2', gy);
    const below = c.normal * ppc < 16;
    this.pill(this.ghostLabel, this.ghostBg, meta.normalLabel, x1 - 8, below ? gy + 15 : gy - 7, 'end');

    const snowOn = isNum(this.t.snow) && meta.snowKnown;
    const sp = snowOn ? this.snowPx(c.snow) : 0;
    const bumpy = (xa, xb, base, hgt, seed) => {
      if (hgt < 1.2) return '';
      let d = `M${xa},${base} L${xa},${base - hgt}`;
      const n = Math.max(2, Math.round((xb - xa) / 28));
      for (let i = 1; i <= n; i++) {
        const x = xa + (xb - xa) * i / n, bump = Math.sin(i * 1.7 + seed) * Math.min(2.2, hgt * 0.12);
        d += ` L${x},${base - hgt + bump}`;
      }
      return d + ` L${xb},${base} Z`;
    };
    const lakeSnowVis = clamp((c.ice - 0.2) / 1.2, 0, 1);
    this.snowLake.setAttribute('d', bumpy(x0, x1 + 4, ys, sp, 0.6));
    this.snowLake.setAttribute('opacity', lakeSnowVis);
    this.snowShore.setAttribute('d', bumpy(x1 + 4, w, ys, sp, 2.1));

    const live = meta.nodeLive;
    const postX = x1 + this.shoreW * 0.5;
    const headW = 34 * sz, headH = 15 * sz;
    const snowTopY = ys - sp;
    const headY = Math.min(ys - Math.max(46 * sz, ys * 0.34), snowTopY - 38 * sz);
    this.post.setAttribute('x1', postX); this.post.setAttribute('x2', postX); this.post.setAttribute('y1', headY + headH); this.post.setAttribute('y2', ys + 2);
    this.head.setAttribute('x', postX - headW / 2); this.head.setAttribute('y', headY); this.head.setAttribute('width', headW); this.head.setAttribute('height', headH);
    const ex = headW * 0.25, ey = headY + headH / 2;
    for (const [n, dx] of [[this.eyeL, -ex], [this.eyeR, ex]]) { n.setAttribute('cx', postX + dx); n.setAttribute('cy', ey); n.setAttribute('r', 4.2 * sz); }
    const beamOn = live && snowOn && meta.snowKnown;
    const spread = 15 * sz, by = headY + headH, ty = snowOn ? snowTopY : ys;
    this.beam.setAttribute('d', `M${postX - ex},${by} L${postX + ex},${by} L${postX + spread},${ty} L${postX - spread},${ty} Z`);
    this.beamL.setAttribute('x1', postX - ex); this.beamL.setAttribute('y1', by); this.beamL.setAttribute('x2', postX - spread); this.beamL.setAttribute('y2', ty);
    this.beamR.setAttribute('x1', postX + ex); this.beamR.setAttribute('y1', by); this.beamR.setAttribute('x2', postX + spread); this.beamR.setAttribute('y2', ty);
    for (const n of [this.beam, this.beamL, this.beamR]) n.setAttribute('opacity', beamOn ? 1 : 0);
    this.sensor.setAttribute('opacity', live ? 1 : 0.42);

    const dx = postX - spread - 9 * sz;
    const dimOn = beamOn && sp > 3;
    this.dim.setAttribute('opacity', dimOn ? 1 : 0);
    this.dimLine.setAttribute('x1', dx); this.dimLine.setAttribute('x2', dx); this.dimLine.setAttribute('y1', snowTopY); this.dimLine.setAttribute('y2', ys);
    this.dimTop.setAttribute('x1', dx - 4); this.dimTop.setAttribute('x2', dx + 4); this.dimTop.setAttribute('y1', snowTopY); this.dimTop.setAttribute('y2', snowTopY);
    this.dimBot.setAttribute('x1', dx - 4); this.dimBot.setAttribute('x2', dx + 4); this.dimBot.setAttribute('y1', ys); this.dimBot.setAttribute('y2', ys);
    this.dimText.setAttribute('x', dx - 11); this.dimText.setAttribute('text-anchor', 'end'); this.dimText.setAttribute('y', (snowTopY + ys) / 2 + 4);
    const dtxt = dimOn ? `${c.snow < 10 ? c.snow.toFixed(1) : Math.round(c.snow)} cm` : '';
    this.pill(this.dimText, this.dimBg, dtxt, dx - 11, (snowTopY + ys) / 2 + 4, 'end');
    this.nodeTag.setAttribute('x', postX); this.nodeTag.setAttribute('y', headY - 7);
    this.nodeTag.textContent = meta.simulated ? 'SIM NODE' : (live ? 'FIELD NODE' : (meta.needsCal ? 'SET GROUND' : 'NO NODE'));
    this.nodeTag.setAttribute('fill', meta.simulated ? '#ffb547' : (live ? '#ffb547' : '#8497b3'));

    this.drawRuler();
    this.drawArrows();
  }

  drawRuler() {
    const { c, meta } = this;
    const th = meta.thresholds || [];
    const key = [Math.round(c.domain * 10), this.w, this.h, Math.round(this.ySurf), th.map((x) => x.cm).join(',')].join('|');
    if (key !== this._rulerKey) {
      this._rulerKey = key; this._litKey = '';
      const g = this.ruler; g.textContent = '';
      const ppc = this.ppc, ys = this.ySurf, sx = this.rulerW - 8, sz = this.sz;
      el('line', { x1: sx, x2: sx, y1: ys, y2: ys + this.iceZone, stroke: 'rgba(160,190,225,.35)', 'stroke-width': 1.2 }, g);
      for (let cm = 0; cm <= c.domain; cm += 5) {
        const major = cm % 10 === 0, y = ys + cm * ppc;
        el('line', { x1: sx - (major ? 7 : 4), x2: sx, y1: y, y2: y, stroke: 'rgba(160,190,225,.45)', 'stroke-width': 1 }, g);
      }

      const iconS = 20 * sz, gap = iconS + 11;
      const rungs = th.map((t, i) => ({ t, i, want: ys + t.cm * ppc, y: ys + t.cm * ppc }));
      rungs.sort((a, b) => a.want - b.want);
      for (let i = 1; i < rungs.length; i++) if (rungs[i].y - rungs[i - 1].y < gap) rungs[i].y = rungs[i - 1].y + gap;
      const maxY = ys + this.iceZone;
      for (let i = rungs.length - 1; i >= 0; i--) { if (rungs[i].y > maxY) rungs[i].y = maxY; if (i && rungs[i].y - rungs[i - 1].y < gap) rungs[i - 1].y = rungs[i].y - gap; }
      this.rungEls = [];
      for (const r of rungs) {
        el('line', { x1: sx, x2: this.shoreX0, y1: r.want, y2: r.want, stroke: 'rgba(200,225,255,.13)', 'stroke-width': 1, 'stroke-dasharray': '2 6' }, g);
      }
      for (const r of rungs) {
        const rg = el('g', { class: 'rung' }, g);
        el('path', { d: `M${sx},${r.want} L${sx - 9},${r.want} L${sx - 14},${r.y}`, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.2, class: 'lead' }, rg);
        el('circle', { cx: sx - 14 - iconS / 2 - 2, cy: r.y, r: iconS / 2 + 3, class: 'badge' }, rg);
        const ic = el('g', { transform: `translate(${sx - 14 - iconS - 2 + 0},${r.y - iconS / 2}) scale(${iconS / 24})`, class: 'ico' }, rg);
        ic.innerHTML = ICONS[r.t.icon] || '';
        const range = r.t.hi ? `${r.t.cm}–${r.t.hi}` : `${r.t.cm}`;
        const tx = el('text', { x: sx - 14 - iconS - 8, y: r.y + 4, 'text-anchor': 'end', 'font-size': Math.max(12, 12.5 * Math.min(1.1, sz)), 'font-weight': 800, class: 'rtxt' }, rg);
        tx.textContent = this.rulerW > 110 ? `${range} cm` : range;
        const gbg = el('rect', { rx: 4, fill: 'rgba(5,10,18,.82)' }, rg);
        const gap2 = el('text', { 'font-size': 12, 'font-weight': 700, 'letter-spacing': '.05em', class: 'rgap' }, rg);
        this.rungEls.push({ t: r.t, g: rg, gap: gap2, gbg, gx: sx + 12, gy: r.want - 7 });
      }
    }

    const lit = (this.rungEls || []).map((r) => (c.lo >= r.t.cm ? 2 : (c.hi >= r.t.cm ? 1 : 0)));
    const nextIdx = lit.findIndex((v) => v < 2);
    const k = lit.join('') + '|' + nextIdx + '|' + (isNum(c.ice) ? Math.round(c.ice * 10) : 'x');
    if (k !== this._litKey) {
      this._litKey = k;
      (this.rungEls || []).forEach((r, i) => {
        r.g.setAttribute('class', `rung s${lit[i]}${i === nextIdx ? ' next' : ''}`);
        const need = r.t.cm - c.ice;
        this.pill(r.gap, r.gbg, i !== nextIdx ? '' : (need > 0.4 ? `NEEDS +${need < 10 ? need.toFixed(1) : Math.round(need)} CM` : 'IN THE BAND'), r.gx, r.gy, 'start');
      });
    }
  }

  drawArrows() {
    const cold = clamp(this.meta.cold || 0, 0, 1);
    const n = this.meta.reduce || document.documentElement.dataset.quality === 'low' ? 0 : Math.round(cold * 7);
    const key = `${n}|${Math.round(this.ySurf)}|${Math.round(this.c.ice * this.ppc / 8)}|${this.w}`;
    if (key === this._arrowKey) return;
    this._arrowKey = key;
    const g = this.arrows; g.textContent = '';
    if (!n) return;
    const x0 = this.lakeX0 + 24, x1 = this.shoreX0 - 24;
    const y0 = this.ySurf + Math.max(this.c.ice * this.ppc, 10) + 16;
    const rise = -(y0 - (this.ySurf - Math.min(40, this.snowPx(this.c.snow) + 8)));
    for (let i = 0; i < n; i++) {
      const x = x0 + (x1 - x0) * ((i + 0.5) / n);

      const gg = el('g', { transform: `translate(${x},${y0})` }, g);
      const a = el('path', { d: 'M-6,3 L0,-5 L6,3', fill: 'none', stroke: '#2bb4da', 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: 'arrow' }, gg);
      a.style.setProperty('--rise', `${rise}px`);
      a.style.animationDuration = `${lerp(5.2, 2.6, cold)}s`;
      a.style.animationDelay = `${-(i * 0.73) % 3}s`;
    }
  }
}
