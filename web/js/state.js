export const S = { state: null, connected: false, lastMsg: 0, stale: false };
const subs = new Set();
export const subscribe = (fn) => { subs.add(fn); if (S.state) fn(S); return () => subs.delete(fn); };
const emit = () => subs.forEach((fn) => { try { fn(S); } catch (e) { console.error('subscriber failed', e); } });

let es = null, backoff = 1000;
function accept(obj) { S.state = obj; S.lastMsg = Date.now(); S.stale = false; S.connected = true; window.__state = obj; emit(); }

export function startStream() {
  const open = () => {
    try { es = new EventSource('/api/stream'); } catch (e) { setTimeout(open, backoff); return; }
    es.addEventListener('state', (ev) => { try { accept(JSON.parse(ev.data)); backoff = 1000; } catch (e) {  } });
    es.onerror = () => { S.connected = false; emit(); es.close(); setTimeout(open, backoff); backoff = Math.min(backoff * 2, 10000); };
  };
  open();
  setInterval(async () => {
    const quiet = Date.now() - S.lastMsg;
    if (quiet > 6000) {
      S.stale = true;
      try { const r = await fetch('/api/state', { cache: 'no-store' }); if (r.ok) accept(await r.json()); else emit(); } catch (e) { emit(); }
    }
  }, 3000);
}

export async function post(path, body) {
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return await r.json();
  } catch (e) { return { ok: false }; }
}
