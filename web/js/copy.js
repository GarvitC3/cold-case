import { isNum, dshort, num, ice, spct, plural } from './fmt.js';

const MINUS = '−';
export const sgn = (v, dp = 1) => (isNum(v) ? `${v < 0 ? MINUS : ''}${Math.abs(v).toFixed(dp)}` : '—');
const fdd = (v) => (isNum(v) ? (Math.abs(v) < 0.05 ? '0' : v < 10 ? v.toFixed(1) : String(Math.round(v))) : '—');
export const fddFmt = fdd;

export function rankPhrase(now) {
  const r = now.rank;
  if (!r || !isNum(r.pct)) return '';
  const when = dshort(now.fdd && now.fdd.compare_date);
  if (r.tied / r.n >= 0.25) return `tied with ${r.tied} of ${r.n} winters on ${when}`;
  if (r.pct >= 50) return `colder than ${Math.round(r.pct)}% of ${r.n} winters by ${when}`;
  return `milder than ${Math.round(100 - r.pct)}% of ${r.n} winters by ${when}`;
}

export function heroSentence(S) {
  const s = S.state, now = s.now, site = s.site.short;
  const t = (x) => `<span class="m">${x}</span>`;
  if (!now || now.phase === 'no_data') return 'No NASA history cached yet. Run <b>prefetch.py</b> once with internet.';
  if (now.phase === 'offseason') return `Off-season. The next winter begins on 1 Nov; the lake model wakes up when NASA's daily record shows the first freezing days.`;
  const fi = now.first_ice && now.first_ice['10'];
  const typical = fi && fi.median ? `${dshort(fi.median)}` : null;
  const spread = fi && fi.p10 && fi.p90 ? ` (middle 80%: ${dshort(fi.p10)} – ${dshort(fi.p90)})` : '';
  const nasaDay = `<span class="nasa">${dshort(now.as_of)}</span>`;
  const T = now.nasa_t && isNum(now.nasa_t.c) ? now.nasa_t.c : null;
  const cmp = now.fdd.compare_date;
  if (now.phase === 'none') {
    const cold = T !== null && T <= 0;
    const lead = `<b>${site}</b> is still open water.`;
    const day = T === null ? '' : ` NASA’s latest day (${nasaDay}) averaged <b>${sgn(T)}°C</b>${cold ? ', so freezing has begun but almost no cold is banked yet' : ''}.`;
    const tip = typical ? ` In a typical winter the model reaches 10 cm of ice around ${t(typical)}${spread}.` : '';
    return lead + day + tip;
  }
  if (now.phase === 'forming') {
    return `Thin ice is forming — about ${t(ice(now.ice.cm) + ' cm')}, too thin to stand on. `
      + (typical ? `In a typical winter the model reaches 10 cm around ${t(typical)}. ` : '')
      + `This winter has banked <b>${fdd(now.fdd.now)}</b> °C-days against a normal <b>${fdd(now.normal.p50)}</b> by ${dshort(cmp)}.`;
  }
  const d = now.delta;
  const vs = d && d.available
    ? (d.pct_of_normal < 100 ? `${Math.round(100 - d.pct_of_normal)}% below` : `${Math.round(d.pct_of_normal - 100)}% above`) + ' normal for the date'
    : null;
  const th = (s.thresholds || []).find((x) => now.ice.lo < x.cm);

  const next = th
    ? (th.cm - now.ice.cm > 0.4 ? ` Next: ${th.label.toLowerCase()} needs +${ice(th.cm - now.ice.cm)} cm.` : ` Next: ${th.label.toLowerCase()} is within the band, not yet certain.`)
    : ' Every rung on the ladder is passed — but no ice is safe ice.';

  const noSnow = now.snow && now.snow.known === false ? ' No snow reading, so this assumes bare ice.' : '';
  return `Modelled ice is ${t(ice(now.ice.cm) + ' cm')} (${ice(now.ice.lo)}–${ice(now.ice.hi)}).`
    + (vs ? ` That is <b>${vs}</b>.` : '') + next + noSnow;
}

export function deltaChip(S) {
  const now = S.state.now;
  if (!now || !now.delta || now.phase === 'offseason' || now.phase === 'no_data') return null;
  if (now.delta.available) {
    const p = now.delta.pct_of_normal - 100;
    return { cls: p < 0 ? 'neg' : 'pos', text: `${p < 0 ? '▼' : '▲'} ${spct(p)} vs normal ${dshort(now.fdd.compare_date)}` };
  }
  return { cls: '', text: `Normal by ${dshort(now.fdd.compare_date)}: ${fdd(now.normal.p50)} °C-days` };
}
