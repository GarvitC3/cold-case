#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _server import backend
from playwright.sync_api import sync_playwright

TARGET, GAP, MIN_TEXT = 44, 8, 12
JS = """([TARGET, GAP, MIN_TEXT]) => {
  const vis = (el) => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && cs.visibility !== 'hidden' && cs.display !== 'none' && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; };
  const label = (el) => (el.getAttribute('aria-label') || el.innerText || el.className.baseVal || el.className || el.tagName).toString().trim().replace(/\\s+/g, ' ').slice(0, 28);
  const sel = 'button, a[href], [role=button], .tm-strip, .tm-trace';
  const sheet = document.querySelector('#sheet-root .sheet');
  const top = (el) => { const r = el.getBoundingClientRect(), t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!t && (t === el || el.contains(t) || t.contains(el)); };
  const els = [...document.querySelectorAll(sel)].filter(vis).filter((e) => (sheet ? sheet.contains(e) : true) && (e.matches('.tm-strip,.tm-trace') || top(e)));
  const small = [], gaps = [], text = [];
  for (const el of els) { const r = el.getBoundingClientRect(); const m = Math.min(r.width, r.height);
    if (m < TARGET - 0.5) small.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`); }
  const btns = els.filter((e) => e.matches('button, a[href]') && !e.closest('#nav, .seg'));   // tabs / segmented controls are contiguous by design
  for (let i = 0; i < btns.length; i++) for (let j = i + 1; j < btns.length; j++) {
    const a = btns[i].getBoundingClientRect(), b = btns[j].getBoundingClientRect();
    if (btns[i].contains(btns[j]) || btns[j].contains(btns[i])) continue;
    const dx = Math.max(a.left - b.right, b.left - a.right), dy = Math.max(a.top - b.bottom, b.top - a.bottom);
    const d = Math.max(dx, dy);                       // both overlap on one axis -> gap is the other axis
    if (dx < 0 && dy < 0) gaps.push(`overlap: ${label(btns[i])} / ${label(btns[j])}`);
    else if (d >= 0 && d < GAP - 0.5 && (dx < 0 || dy < 0)) gaps.push(`${Math.round(d)}px: ${label(btns[i])} / ${label(btns[j])}`);
  }
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (w.nextNode()) { const n = w.currentNode, t = n.nodeValue.trim(); if (!t) continue;
    const p = n.parentElement; if (!p || !vis(p) || p.closest('script,style,#story[hidden]')) continue;
    let fs = parseFloat(getComputedStyle(p).fontSize); const svg = p.closest('svg');
    if (svg) { const vb = svg.viewBox && svg.viewBox.baseVal; const r = svg.getBoundingClientRect(); if (vb && vb.width) fs *= Math.min(r.width / vb.width, r.height / vb.height); }
    if (fs < MIN_TEXT - 0.2) { const k = t.slice(0, 22) + Math.round(fs); if (!seen.has(k)) { seen.add(k); text.push(`${fs.toFixed(1)}px "${t.slice(0, 24)}"`); } } }
  return { small: [...new Set(small)], gaps: [...new Set(gaps)], text };
}"""

def main():
    sizes = [tuple(map(int, s.split("x"))) for s in (sys.argv[1] if len(sys.argv) > 1 else "800x480,720x1280").split(",")]
    total = 0
    with backend("--sim-snow", "12", "--today", "2026-02-10") as (url, proc, _), sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for (w, h) in sizes:
            pg = br.new_page(viewport={"width": w, "height": h}, has_touch=True)
            pg.goto(url + "/#now"); pg.wait_for_function("window.__state && window.__state.now")
            views = [("now", None), ("season", None), ("trend", None), 
                     ("now", "trace:ice"), ("now", "settings"), ("now", "node"), ("now", "cal"), ("now", "sites"), ("trend", "detail")]
            for scr, extra in views:
                pg.evaluate("window.__closeSheet && window.__closeSheet()"); pg.evaluate(f"window.__show('{scr}')"); pg.wait_for_timeout(900)
                if extra and extra.startswith("trace"): pg.evaluate("window.__openTrace('ice')")
                if extra == "settings": pg.evaluate("window.__openSettings()")
                if extra == "node": pg.evaluate("window.__openNode()")
                if extra == "cal": pg.evaluate("window.__openCal()")
                if extra == "sites": pg.evaluate("window.__openSites()")
                if extra == "detail": pg.click(".t-row[data-i='0']")
                pg.wait_for_timeout(700)
                r = pg.evaluate(JS, [TARGET, GAP, MIN_TEXT])
                n = len(r["small"]) + len(r["gaps"]) + len(r["text"]); total += n
                print(f"[{w}x{h}] {scr}{':' + extra if extra else ''}: targets<{TARGET}: {len(r['small'])}  gaps<{GAP}: {len(r['gaps'])}  text<{MIN_TEXT}px: {len(r['text'])}")
                for k in ("small", "gaps", "text"):
                    for x in r[k][:7]: print(f"      {k}: {x}")
            pg.close()
        br.close()
    print("TOTAL issues:", total)
    return 0 if total == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
