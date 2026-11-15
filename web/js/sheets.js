import { S, post } from './state.js';
import { traceSpec, srcLabel } from './trace.js';
import { esc, num, isNum, dshort } from './fmt.js';

const root = () => document.getElementById('sheet-root');
let cur = null;

export function closeSheet() { if (cur && cur.onClose) cur.onClose(); cur = null; root().textContent = ''; }

export function openSheet(render, opts) { mount(render, opts); }
function mount(render, { live = false, onAct, onClose } = {}) {
  if (cur && cur.onClose) cur.onClose();
  cur = { render, live, onAct, onClose };
  paint();
}
function paint() {
  if (!cur || !S.state) return;
  const r = root();
  const body = cur.render(S);

  let sheet = r.querySelector('.sheet');
  if (!sheet) {
    r.innerHTML = `<div class="scrim" data-close></div><div class="sheet" role="dialog" aria-modal="true"><div class="grab"></div><button class="close" data-close aria-label="Close">×</button><div class="sbody"></div></div>`;
    r.onclick = (e) => {
      if (e.target.closest('[data-close]')) return closeSheet();
      const a = e.target.closest('[data-act]');
      if (a && cur && cur.onAct) cur.onAct(a.dataset.act, a, e);
    };
    sheet = r.querySelector('.sheet');
  }
  const sb = sheet.querySelector('.sbody');
  if (sb._html !== body) { sb.innerHTML = body; sb._html = body; }
}
export function refreshSheet() { if (cur && cur.live) paint(); }

export function openTrace(kind) {
  let raw = null;
  mount((S) => {
    const t = traceSpec(kind, S);
    const rows = t.inputs.map((i) => `<div class="inp"><span class="src src-${i.src}"><i></i>${esc(srcLabel(i.src))}</span><span>${esc(i.label)}</span><span class="val">${esc(i.value)}</span><span class="when">${esc(i.when)}</span></div>`).join('');
    let rawHtml = '';
    if (t.raw) {
      rawHtml = raw
        ? `<table class="tbl"><thead><tr><th>Day</th><th>T2M °C</th><th>FDD</th><th>Cumulative</th></tr></thead><tbody>${raw.map((r) => `<tr><td>${dshort(r[0])}</td><td>${isNum(r[1]) ? r[1].toFixed(1) : '— <em>not published yet</em>'}</td><td>${isNum(r[2]) ? r[2].toFixed(1) : '—'}</td><td>${isNum(r[3]) ? r[3].toFixed(1) : '—'}</td></tr>`).join('')}</tbody></table>`
        : `<button class="cta ghost" data-act="raw">View the raw NASA days</button>`;
    }
    return `<h2>${esc(t.title)} <span class="src src-${t.src}"><i></i>${esc(srcLabel(t.src))}</span></h2>
      <p class="lead">${esc(t.explain)}</p><div class="formula">${esc(t.formula)}</div>${rows}
      <div class="result">= ${esc(t.result)}</div>${t.note ? `<p class="lead" style="margin-top:.6rem"><b>${esc(t.note)}</b></p>` : ''}
      <div class="row"><span class="k">Code path</span><span class="v">${esc(t.code)}</span></div>${rawHtml}`;
  }, {
    live: true,
    onAct: async (a) => {
      if (a === 'raw') {
        try { raw = (await (await fetch('/api/raw/nasa?n=14', { cache: 'no-store' })).json()).rows || []; } catch (e) { raw = []; }
        refreshSheet();
      }
    },
  });
}

export function openSites() {
  mount((S) => {
    const s = S.state;
    return `<h2>Where is the lake?</h2><p class="lead">The cold record and the baseline come from NASA at this location. The field node’s snow depth applies wherever you choose.</p>
      <div class="opts">${s.sites.map((x) => `<button class="opt ${x.id === s.site.id ? 'on' : ''}" data-act="site" data-id="${x.id}">${esc(x.name)}<small>${num(x.lat, 2)}°N · ${num(Math.abs(x.lon), 2)}°W</small></button>`).join('')}</div>`;
  }, { onAct: async (a, el) => { if (a === 'site') { await post('/api/site', { id: el.dataset.id }); closeSheet(); } } });
}

export function openCalibration() {
  mount((S) => {
    const n = S.state.node, c = n.cal || { state: 'idle' };
    const g = n.snow.ground_cm;
    if (n.state === 'offline') {
      return `<h2>Set ground level</h2><p class="lead">The field node isn’t connected, so there is nothing to calibrate yet. Plug it in and this will wake up on its own.</p><button class="cta ghost" data-close>OK</button>`;
    }
    if (c.state === 'averaging') {
      return `<h2>Averaging… hold still</h2><p class="lead">Keep the sensor’s view of the ground clear for 5 seconds.</p><div class="progress"><i style="width:${Math.round((c.progress || 0) * 100)}%"></i></div>`;
    }
    if (c.state === 'done') {
      return `<h2>${c.undone ? 'Previous ground level restored' : 'Ground level set'}</h2><div class="bigstate">${num(c.ground_cm, 1)} <span class="unit">cm</span></div><p class="lead">From now on, snow depth = ${num(c.ground_cm, 1)} cm − the distance the sensor reads. Saved; it survives a restart.</p>
        <div class="opts"><button class="cta" data-close>Done</button>${n.snow.can_undo ? '<button class="cta ghost" data-act="undo">Undo</button>' : ''}</div>`;
    }
    if (c.state === 'failed') {
      return `<h2>Couldn’t see the ground</h2><p class="lead">${esc(c.reason || 'No valid distance readings.')}</p><button class="cta" data-act="start">Try again</button>`;
    }
    return `<h2>Set ground level</h2>
      <p class="lead"><b>1.</b> Point the sensor straight down at bare ground, with nothing under it. <b>2.</b> Tap start. It averages for 5 seconds and remembers the result.</p>
      <div class="row"><span class="k">Current ground level</span><span class="v">${isNum(g) ? num(g, 1) + ' cm' : 'not set yet'}</span></div>
      <div class="row"><span class="k">Sensor reads right now</span><span class="v">${isNum(n.dist.cm) ? num(n.dist.cm, 1) + ' cm' : '—'}</span></div>
      <div class="opts" style="margin-top:.8rem"><button class="cta" data-act="start">Start — ground is clear</button>${n.snow.can_undo ? '<button class="cta ghost" data-act="undo">Undo last</button>' : ''}</div>`;
  }, {
    live: true,
    onAct: async (a) => { if (a === 'start') await post('/api/calibrate'); if (a === 'undo') await post('/api/calibrate/undo'); },
  });
}

const hhmmss = (at) => { const d = new Date(at * 1000); return [d.getHours(), d.getMinutes(), d.getSeconds()].map((x) => String(x).padStart(2, '0')).join(':'); };
const ageTxt = (s) => (!isNum(s) ? 'never' : s < 60 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`);
const TONE = { green: 'live', amber: 'recent', grey: 'offline' };

export function openNode() {
  let info = null, showPk = false, showLog = false, log = null, test = null, copied = false, timer = null;
  const load = async () => {
    try { const r = await fetch('/api/node/info', { cache: 'no-store' }); info = r.ok ? await r.json() : { denied: true }; } catch (e) { info = { denied: true }; }
    refreshSheet();
  };
  load(); timer = setInterval(load, 2500);
  mount((S) => {
    const nd = S.state.node, L = nd.link, w = L.wireless, u = L.usb, sim = nd.simulated;
    const via = nd.via === 'wireless' ? `Wi-Fi from node \u2018${esc(nd.name || 'field')}\u2019` : nd.via === 'usb' ? `USB${nd.port && !sim ? ' (' + esc(nd.port) + ')' : ''}` : null;
    const head = nd.state !== 'offline' && via
      ? `Reading arrived over ${via} ${ageTxt(nd.last_seen_age_s)}${sim ? ' \u00B7 <b>SIMULATED</b>' : ''}.`
      : (w.seen || u.seen ? `No reading for a while \u2014 the tiles are empty on purpose. It recovers by itself when packets resume.` : 'No node has reported yet. Plug in the Arduino, or point the Zero at this Pi (below).');
    const src = (name, l, detail) => `<div class="lrow"><i class="dot t-${l.tone}"></i><span class="k">${name}</span><span class="v">${detail}</span>${l.active ? '<span class="tag">feeding the tiles</span>' : ''}</div>`;
    const wDetail = w.seen ? `${TONE[w.tone]} \u00B7 ${ageTxt(w.age_s)} \u00B7 ${w.ppm}/min` : 'nothing received yet';
    const uDetail = u.seen ? `${TONE[u.tone]} \u00B7 ${ageTxt(u.age_s)}` : (u.connected ? 'plugged in, no data yet' : 'not plugged in');
    let connect;
    if (!info) connect = '<p class="lead">Loading\u2026</p>';
    else if (info.denied) connect = '<p class="lead">Addresses, packets and the self-test are shown on the Pi\u2019s own screen only.</p>';
    else {
      const addrs = info.addresses.length ? info.addresses.map((a) => `<div class="big-ip">${esc(a.ip)}<span>:${info.port}</span><small>${esc(a.iface)}</small></div>`).join('') : '<p class="lead"><b>No network address found.</b> Connect this Pi to Wi-Fi or Ethernet first.</p>';
      const tr = test ? `<div class="testres">${test.running ? 'Testing\u2026' : test.results.map((x) => `<div class="${x.ok ? 'ok' : 'bad'}">${x.ok ? '\u2713' : '\u2717'} ${esc(x.addr)} \u2014 ${x.ok ? 'answered in ' + x.ms + ' ms' : esc(x.error || 'no answer')}</div>`).join('')}${!test.running && !test.ok ? '<p class="lead" style="margin-top:.4rem">A failing LAN address usually means <b>host</b> in config.toml is 127.0.0.1 (set 0.0.0.0) or a firewall is blocking the port. This test runs on the Pi, so it cannot check the Zero\u2019s Wi-Fi.</p>' : ''}</div>` : '';
      connect = `${addrs}
        <div class="cmd"><code>${esc(info.sender_cmd)}</code><button class="cta ghost" data-act="copy">${copied ? 'Copied' : 'Copy'}</button></div>
        <p class="lead">Run this on the Zero, or put the same URL in <code>node-sender.service</code>. ${info.token_required ? 'A token is required and is already in the URL.' : 'No token is set (any device on your private network may post).'} Wi-Fi must be <b>2.4 GHz</b>.</p>
        <div class="opts"><button class="cta" data-act="test">${test && test.running ? 'Testing\u2026' : 'Test link'}</button><button class="cta ghost" data-act="pk">${showPk ? 'Hide' : 'Show'} last 20 packets</button></div>${tr}`;
    }
    const st = info && !info.denied ? info.stats : null;
    const traffic = st ? `<div class="eyebrow" style="margin:1rem 0 .3rem">Traffic</div>
      <div class="row"><span class="k">Packets per minute</span><span class="v">${info.ppm}</span></div>
      <div class="row"><span class="k">Accepted \u00B7 duplicates \u00B7 rejected</span><span class="v">${st.accepted} \u00B7 ${st.duplicate} \u00B7 ${st.rejected}</span></div>
      <div class="row"><span class="k">Late (stored, never shown live)</span><span class="v">${st.historical}</span></div>
      ${st.clock_suspect ? `<div class="row"><span class="k">Sender clock wrong (receipt time used)</span><span class="v">${st.clock_suspect}</span></div>` : ''}` : '';
    const pk = showPk && info && info.packets ? `<div class="pktbox">${info.packets.length ? info.packets.map((p) => `<div class="pk ${p.status >= 400 ? 'bad' : ''}"><b>${hhmmss(p.at)}</b> ${p.status} \u00B7 ${p.bytes} B \u00B7 ${esc(p.ip)}${p.note ? ' \u00B7 ' + esc(p.note) : ''}<br><span>${esc(p.raw || '(empty)')}</span></div>`).join('') : '<div class="pk">No packets yet.</div>'}</div>` : '';
    const lg = showLog ? `<pre class="logbox">${esc((log ? log.raw_tail.concat(['\u2014 backend log \u2014'], log.log) : ['loading\u2026']).join('\n'))}</pre>` : '';
    return `<h2>Field node</h2><p class="lead">${head}</p>
      <div class="eyebrow" style="margin:.2rem 0 .3rem">Links</div>
      ${src('Wi-Fi \u00B7 Pi Zero', w, wDetail)}${src('USB \u00B7 Arduino', u, uDetail)}
      <div class="eyebrow" style="margin:1rem 0 .4rem">Connect the Zero</div>${connect}${pk}${traffic}
      <div class="opts" style="margin-top:.9rem"><button class="cta ghost" data-act="log">${showLog ? 'Hide' : 'Show'} backend log</button><a class="cta ghost" href="/api/export.csv" download>Export CSV</a></div>${lg}
      <p class="lead" style="margin-top:.8rem">The DHT11 reads 0\u201350 \u00B0C only, so below freezing the temperature stays empty. The wireless node has no battery readout.</p>`;
  }, {
    live: true,
    onClose: () => { if (timer) clearInterval(timer); },
    onAct: async (a) => {
      if (a === 'pk') { showPk = !showPk; refreshSheet(); }
      if (a === 'copy' && info && info.sender_cmd) {
        try { await navigator.clipboard.writeText(info.sender_cmd); copied = true; } catch (e) { copied = false; }
        refreshSheet(); setTimeout(() => { copied = false; refreshSheet(); }, 1800);
      }
      if (a === 'test') {
        test = { running: true }; refreshSheet();
        try { test = await post('/api/node/selftest'); } catch (e) { test = { ok: false, results: [{ addr: 'this Pi', ok: false, ms: 0, error: 'test failed to run' }] }; }
        if (!test.results) test = { ok: false, results: [{ addr: 'this Pi', ok: false, ms: 0, error: 'test failed to run' }] };
        refreshSheet();
      }
      if (a === 'log') { showLog = !showLog; if (showLog) { try { log = await (await fetch('/api/debug', { cache: 'no-store' })).json(); } catch (e) { log = { raw_tail: ['unavailable'], log: [] }; } } refreshSheet(); }
    },
  });
}

export function openSettings() {
  let armed = '';
  const shift = (iso, days, months) => {
    const d = new Date(iso + 'T12:00:00');
    if (months) d.setMonth(d.getMonth() + months);
    if (days) d.setDate(d.getDate() + days);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  mount((S) => {
    const s = S.state, indoor = s.mode.deployment === 'indoor_demo', c = s.clock, chip = s.node.link.chip;
    const via = chip.via === 'wireless' ? 'Wi-Fi' : chip.via === 'usb' ? 'USB' : null;
    const linkTxt = !via ? 'no signal yet' : `${via} \u00B7 ${chip.tone === 'grey' ? 'offline, ' : ''}${ageTxt(chip.age_s)}`;
    return `<h2>Settings</h2>
      <div class="eyebrow" style="margin:.5rem 0 .4rem">Node</div>
      <div class="opts">
        <button class="opt ${indoor ? 'on' : ''}" data-act="mode" data-m="indoor_demo">Indoor demo<small>Never used as climate data</small></button>
        <button class="opt ${!indoor ? 'on' : ''}" data-act="mode" data-m="outdoor">Outdoor<small>Feeds the cold total</small></button>
      </div>
      <div class="row" style="margin-top:.4rem"><span class="k">Field node<br><small class="faint">${esc(linkTxt)}</small></span><button class="cta ghost" data-act="node">Link &amp; setup</button></div>
      <div class="row"><span class="k">Ground level</span><button class="cta ghost" data-act="cal">${isNum(s.node.snow.ground_cm) ? num(s.node.snow.ground_cm, 1) + ' cm \u00B7 change' : 'Set ground level'}</button></div>
      <div class="eyebrow" style="margin:1rem 0 .3rem">Location &amp; data</div>
      <div class="row"><span class="k">Site</span><button class="cta ghost" data-act="sites">${esc(s.site.name)}</button></div>
      <div class="row"><span class="k">NASA data<br><small class="faint">as of ${s.nasa.as_of ? dshort(s.nasa.as_of) : '\u2014'} \u00B7 synced ${s.nasa.last_sync ? dshort(s.nasa.last_sync) : 'never'}${s.nasa.offline_flag ? ' \u00B7 offline mode' : ''}</small></span><button class="cta ghost" data-act="sync">${s.nasa.syncing ? 'Syncing\u2026' : 'Sync now'}</button></div>
      <div class="eyebrow" style="margin:1rem 0 .3rem">Display &amp; clock</div>
      <div class="row"><span class="k">Date ${c.trusted ? '' : '<b style="color:var(--warn)">\u2014 unverified</b>'}<br><small class="faint">${dshort(c.today)} ${c.today.slice(0, 4)}</small></span>
        <span class="opts" style="grid-template-columns:repeat(4,auto)"><button class="cta ghost" data-act="d" data-d="-1">\u22121 d</button><button class="cta ghost" data-act="d" data-d="1">+1 d</button><button class="cta ghost" data-act="d" data-m="-1">\u22121 mo</button><button class="cta ghost" data-act="d" data-m="1">+1 mo</button></span></div>
      <div class="row"><span class="k">Reduce motion</span><button class="cta ghost" data-act="rm">${s.reduce_motion ? 'On' : 'Off'}</button></div>
      <div class="eyebrow" style="margin:1rem 0 .3rem">Danger zone</div>
      <div class="row"><span class="k">Erase or leave</span><span class="opts" style="grid-template-columns:repeat(2,auto)"><button class="cta ghost" data-act="reset">${armed === 'reset' ? 'Tap again: erase' : 'Reset season data'}</button><button class="cta ghost" data-act="exit">${armed === 'exit' ? 'Tap again: leave' : 'Exit kiosk'}</button></span></div>
      <p class="lead" style="margin:.6rem 0 0"><small class="faint">Cold Case ${esc(s.v)} \u00B7 ${esc(s.build || '')}</small></p>`;
  }, {
    live: true,
    onAct: async (a, el) => {
      const st = S.state;
      if (a !== 'reset' && a !== 'exit') armed = '';
      if (a === 'mode') await post('/api/mode', { mode: el.dataset.m });
      if (a === 'sites') openSites();
      if (a === 'cal') openCalibration();
      if (a === 'node') openNode();
      if (a === 'd') await post('/api/clock', { date: shift(st.clock.today, +(el.dataset.d || 0), +(el.dataset.m || 0)) });
      if (a === 'rm') await post('/api/pref', { key: 'reduce_motion', value: !st.reduce_motion });
      if (a === 'sync') await post('/api/sync');
      if (a === 'reset' || a === 'exit') {
        if (armed !== a) { armed = a; refreshSheet(); setTimeout(() => { if (armed === a) { armed = ''; refreshSheet(); } }, 4000); return; }
        armed = ''; await post(a === 'reset' ? '/api/reset-season' : '/api/exit-kiosk'); refreshSheet();
      }
    },
  });
}
