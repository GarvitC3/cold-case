import { clamp, isNum } from './fmt.js';

export class Snowfall {
  constructor(canvas) {
    this.cv = canvas; this.ctx = canvas.getContext('2d');
    this.w = 0; this.h = 0; this.skyH = 0; this.target = 8; this.running = false;
    this.p = Array.from({ length: 60 }, () => ({ x: Math.random(), y: Math.random(), r: 0.7 + Math.random() * 1.5, v: 10 + Math.random() * 26, ph: Math.random() * 6.28 }));
    this.t0 = performance.now();
  }
  resize(w, h, skyH) {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    this.w = w; this.h = h; this.skyH = skyH;
    this.cv.width = Math.round(w * dpr); this.cv.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  setSnow(cm) { this.target = isNum(cm) ? clamp(Math.round(6 + cm * 2.4), 6, 60) : 6; }
  start() { if (!this.running) { this.running = true; this.last = performance.now(); requestAnimationFrame((t) => this.frame(t)); } }
  frame(t) {
    if (!this.running) return;
    requestAnimationFrame((n) => this.frame(n));
    const root = document.documentElement;
    const off = root.dataset.quality === 'low' || root.dataset.reduceMotion === '1' || document.hidden;
    const dt = Math.min(0.05, (t - this.last) / 1000); this.last = t;
    const { ctx, w, skyH } = this;
    ctx.clearRect(0, 0, w, this.h);
    if (off || !w) return;
    ctx.fillStyle = '#e6f0ff';
    for (let i = 0; i < this.target; i++) {
      const p = this.p[i];
      p.y += (p.v * dt) / Math.max(skyH, 1);
      p.ph += dt * 0.9;
      if (p.y > 1) { p.y = -0.02; p.x = Math.random(); }
      const x = p.x * w + Math.sin(p.ph) * 6, y = p.y * skyH;
      ctx.globalAlpha = 0.22 + p.r * 0.25;
      ctx.beginPath(); ctx.arc(x, y, p.r, 0, 6.2832); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
}
