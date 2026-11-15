export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const lerp = (a, b, t) => a + (b - a) * t;

export function num(v, dp = 0, fallback = '—') {
  return isNum(v) ? v.toFixed(dp) : fallback;
}

export function ice(v) { return isNum(v) ? (Math.abs(v) < 0.05 ? '0' : v < 10 ? v.toFixed(1) : String(Math.round(v))) : '—'; }

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function parseISO(s) {
  if (typeof s !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}

export function dshort(s) { const d = parseISO(s); return d ? `${d.getDate()} ${MON[d.getMonth()]}` : '—'; }

export function dlong(s) { const d = parseISO(s); return d ? `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}` : '—'; }
export function ago(sec) {
  if (!isNum(sec)) return '—';
  if (sec < 90) return `${Math.round(sec)} s ago`;
  if (sec < 5400) return `${Math.round(sec / 60)} min ago`;
  return `${Math.round(sec / 3600)} h ago`;
}
export const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;

export function spct(v) { return isNum(v) ? `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v))}%` : '—'; }

const tweens = new WeakMap();
export function countTo(el, to, fmt, ms = 450) {
  const reduce = document.documentElement.dataset.reduceMotion === '1';
  if (!isNum(to) || reduce) { el.textContent = fmt(to); el._v = isNum(to) ? to : undefined; return; }
  const from = isNum(el._v) ? el._v : to;
  if (from === to) { el.textContent = fmt(to); return; }
  cancelAnimationFrame(tweens.get(el) || 0);
  const t0 = performance.now();
  const step = (t) => {
    const k = clamp((t - t0) / ms, 0, 1), e = 1 - Math.pow(1 - k, 3);
    const v = from + (to - from) * e;
    el.textContent = fmt(v); el._v = v;
    if (k < 1) tweens.set(el, requestAnimationFrame(step)); else { el._v = to; el.textContent = fmt(to); }
  };
  tweens.set(el, requestAnimationFrame(step));
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function slotLabel(slot) {
  const d = new Date(2023, 10, 1 + Math.round(slot));
  return `${d.getDate()} ${MON[d.getMonth()]}`;
}
