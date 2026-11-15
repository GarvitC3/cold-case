import { rankPhrase, fddFmt } from './copy.js';
import { dshort } from './fmt.js';

const IDLE_MS = 90000;

export function initStory({ show, closeSheet, getState }) {
  const forced = new URLSearchParams(location.search).has('story');
  const el = document.createElement('div');
  el.id = 'story'; el.hidden = true;
  el.innerHTML = '<div class="st-cap"></div><div class="st-bar"><i></i></div>';
  document.body.appendChild(el);
  let running = false, timer = 0, idleSince = Date.now(), step = 0;

  const steps = [
    { id: 'now', ms: 7000, cap: (s) => `Is winter still cold enough to make safe ice \u2014 and how does this winter compare with the last <b>${s.nasa.n_winters || ''}</b>?` },
    { id: 'trend', ms: 9000, cap: (s) => `<b>${s.nasa.n_winters || ''} winters</b> of NASA temperature data, one stripe each. <b style="color:#70b2ec">Blue</b> = colder than that place\u2019s average, <b style="color:#f0a054">amber</b> = milder.` },
    { id: 'season', ms: 8000, cap: (s) => {
      const n = s.now; if (!n || !n.fdd) return 'This winter against every other.';
      return n.delta && n.delta.available ? `This winter is tracking <b>${Math.abs(Math.round(n.delta.pct_of_normal - 100))}% ${n.delta.pct_of_normal < 100 ? 'below' : 'above'} normal</b> \u2014 ${rankPhrase(n)}.`
        : `Winter ${n.winter && n.winter.label} has banked <b>${fddFmt(n.fdd.now)}</b> \u00B0C-days by ${dshort(n.fdd.compare_date)} \u2014 ${rankPhrase(n)}.`; } },
    { id: 'now', ms: 7000, cap: () => 'Snow from the node, cold from NASA, ice from a Stefan model. <b>Tap any number</b> to see exactly where it came from.' },
  ];

  function run() {
    if (!running) return;
    const s = steps[step % steps.length], st = getState();
    if (!st) { timer = setTimeout(run, 500); return; }
    closeSheet(); show(s.id);
    if (s.enter) setTimeout(s.enter, 500);
    el.querySelector('.st-cap').innerHTML = s.cap(st);
    const bar = el.querySelector('.st-bar i');
    bar.style.transition = 'none'; bar.style.width = '0'; void bar.offsetWidth;
    bar.style.transition = `width ${s.ms}ms linear`; bar.style.width = '100%';
    step += 1;
    timer = setTimeout(() => { if (step >= steps.length && !forced) { stop(); } else run(); }, s.ms);
  }
  function start() { if (running) return; running = true; step = 0; el.hidden = false; document.documentElement.classList.add('storying'); run(); }
  function stop() { if (!running) return; running = false; clearTimeout(timer); el.hidden = true; document.documentElement.classList.remove('storying'); idleSince = Date.now(); show('now'); }

  const touch = () => { idleSince = Date.now(); if (running && !forced) stop(); };
  ['pointerdown', 'keydown', 'wheel'].forEach((e) => addEventListener(e, (ev) => { if (ev.key === 's' || ev.key === 'S') return; touch(); }, true));
  addEventListener('keydown', (e) => { if (!e.metaKey && !e.ctrlKey && (e.key === 's' || e.key === 'S')) (running ? stop() : start()); });
  setInterval(() => { if (!running && Date.now() - idleSince > IDLE_MS && !document.querySelector('#sheet-root .sheet')) start(); }, 1000);
  if (forced) {
    document.documentElement.classList.add('story-clean');
    const go = () => (getState() ? start() : setTimeout(go, 300));
    go();
  }
  return { start, stop };
}
