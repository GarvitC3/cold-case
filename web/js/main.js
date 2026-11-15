import { S, subscribe, startStream } from './state.js';
import { startPerf } from './perf.js';
import { svgIcon } from './icons.js';
import { dshort, esc } from './fmt.js';
import { openSites, openSettings, openCalibration, openTrace, openNode, closeSheet, refreshSheet } from './sheets.js';
import { mountNow } from './screens/now.js';
import { mountSeason } from './screens/season.js';
import { mountTrend } from './screens/trend.js';
import { initStory } from './story.js';
import { mountPlaceholder } from './screens/placeholder.js';

const SCREENS = [
  { id: 'now', label: 'Now', icon: 'now', mount: mountNow },
  { id: 'season', label: 'Season', icon: 'season', mount: mountSeason },
  { id: 'trend', label: 'Trend', icon: 'trend', mount: mountTrend },
];
const $ = (id) => document.getElementById(id);
const mounted = {};
let active = null;

$('nav').innerHTML = SCREENS.map((s) => `<button data-s="${s.id}" aria-label="${s.label}">${svgIcon(s.icon)}<span>${s.label}</span></button>`).join('');
const stage = $('stage');
SCREENS.forEach((s) => { const sec = document.createElement('section'); sec.className = `screen ${s.id}`; sec.id = `screen-${s.id}`; stage.appendChild(sec); });

export function show(id) {
  const sc = SCREENS.find((s) => s.id === id) || SCREENS[0];
  active = sc.id;
  $('app').dataset.screen = sc.id;
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.s === sc.id));
  document.querySelectorAll('.screen').forEach((n) => n.classList.toggle('on', n.id === `screen-${sc.id}`));
  if (!mounted[sc.id]) mounted[sc.id] = sc.mount($(`screen-${sc.id}`));
  if (S.state && mounted[sc.id].update) mounted[sc.id].update(S);
  if (mounted[sc.id].resize) requestAnimationFrame(() => mounted[sc.id].resize());
  if (location.hash.slice(1) !== sc.id) history.replaceState(null, '', `#${sc.id}`);
}
$('nav').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { closeSheet(); show(b.dataset.s); } });
addEventListener('hashchange', () => show(location.hash.slice(1)));
addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const i = '123'.indexOf(e.key);
  if (i >= 0) { closeSheet(); show(SCREENS[i].id); }
  if (e.key === 'Escape') closeSheet();
});

let sx = null, sy = null;
stage.addEventListener('pointerdown', (e) => { if (!e.target.closest('[data-noswipe]')) { sx = e.clientX; sy = e.clientY; } else sx = null; });
stage.addEventListener('pointerup', (e) => {
  if (sx === null) return;
  const dx = e.clientX - sx, dy = e.clientY - sy; sx = null;
  if (Math.abs(dx) > 90 && Math.abs(dy) < 60) { const i = SCREENS.findIndex((s) => s.id === active); const n = SCREENS[i + (dx < 0 ? 1 : -1)]; if (n) show(n.id); }
});

let lp = null;
const wm = $('wordmark');
wm.addEventListener('pointerdown', () => { wm.classList.add('pressing'); lp = setTimeout(() => { lp = null; wm.classList.remove('pressing'); openSettings(); }, 1000); });
['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => wm.addEventListener(ev, () => { wm.classList.remove('pressing'); if (lp) { clearTimeout(lp); lp = null; } }));
addEventListener('contextmenu', (e) => e.preventDefault());
$('sitechip').addEventListener('click', openSites);

const age = (s) => (s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min`);
export function linkChipHtml(node) {
  const c = node.link.chip, via = c.via === 'wireless' ? 'Wi-Fi' : c.via === 'usb' ? 'USB' : null;
  let wide, compact, tone = c.tone;
  if (!via) { tone = 'grey'; wide = 'Field node · no signal yet'; compact = 'No node'; }
  else if (tone === 'grey') { wide = `Field node · offline · ${age(c.age_s)} ago`; compact = `Offline · ${age(c.age_s)}`; }
  else { wide = `Field node · ${via} · ${age(c.age_s)} ago`; compact = `${via} · ${age(c.age_s)}`; }
  return `<button class="chipbtn linkchip t-${tone}" id="linkchip" aria-label="Field node link: ${esc(wide)}. Tap for details"><i></i><span class="w">${esc(wide)}</span><span class="c">${esc(compact)}</span></button>`;
}
function chrome(S) {
  const st = S.state;
  if (!st) return;
  $('sitechip').innerHTML = `${esc(st.site.short)} <small>${st.site.lat.toFixed(2)}°N</small>`;
  const n = st.nasa, node = st.node, indoor = st.mode.deployment === 'indoor_demo', pills = [];
  if (n.has_data) pills.push(`<span class="pill ${n.stale ? 'warn' : 'nasa'}"><i></i><span>NASA <span class="w">· as of </span>${dshort(n.as_of)}${n.stale ? ' · stale' : ''}</span></span>`);
  else pills.push(`<span class="pill warn"><i></i>No NASA data yet</span>`);
  pills.push(linkChipHtml(node));
  const tag = [];
  if (node.simulated) tag.push(['SIMULATED', 'SIM']);
  if (indoor) tag.push(['INDOOR DEMO', 'INDOOR']);
  if (tag.length) pills.push(`<span class="pill ${node.simulated ? 'sim' : 'model'}"><i></i><span><span class="w">${tag.map((t) => t[0]).join(' · ')}</span><span class="c">${tag.map((t) => t[1]).join(' · ')}</span></span></span>`);
  if (st.mode.dev_clock) pills.push(`<span class="pill warn"><i></i><span>DEV<span class="w"> CLOCK ${esc(st.clock.today)}</span></span></span>`);
  const html = pills.join('');
  if ($('pills')._h !== html) { $('pills').innerHTML = html; $('pills')._h = html; }
  const b = $('banner');
  let msg = '';
  if (S.stale) msg = 'Reconnecting to the instrument…';
  else if (!st.clock.trusted) msg = 'Clock unverified — the date may be wrong. Hold the COLD CASE title to set it.';
  b.hidden = !msg; b.textContent = msg;
  document.documentElement.dataset.reduceMotion = st.reduce_motion ? '1' : '0';
}
$('pills').addEventListener('click', (e) => { if (e.target.closest('#linkchip')) openNode(); });

subscribe((S) => {
  chrome(S);
  const m = mounted[active];
  if (m && m.update) m.update(S);
  refreshSheet();
});

const params = new URLSearchParams(location.search);
if (params.has('kiosk')) document.documentElement.classList.add('kiosk');
startPerf();
startStream();
initStory({ show, closeSheet, getState: () => S.state });
show(location.hash.slice(1) || 'now');

Object.assign(window, { __show: show, __openSettings: openSettings, __openCal: openCalibration, __openSites: openSites, __openTrace: openTrace, __openNode: openNode, __closeSheet: closeSheet });
