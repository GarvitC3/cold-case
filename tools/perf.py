#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _server import backend
from playwright.sync_api import sync_playwright

SECS = 12

def run(url, br, screen, rate, w=1280, h=720, act=None):
    pg = br.new_page(viewport={"width": w, "height": h})
    cdp = pg.context.new_cdp_session(pg)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    pg.goto(url + f"/#{screen}"); pg.wait_for_function("window.__state && window.__state.now")
    if act: act(pg)
    trace = []
    for _ in range(SECS):
        pg.wait_for_timeout(1000)
        trace.append((pg.evaluate("window.__fps || 0"), pg.evaluate("document.documentElement.dataset.quality || 'high'")))
    pg.close()
    return trace

def main():
    rows = []
    with backend("--sim-snow", "12", "--today", "2026-02-10") as (url, proc, _), sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for name, screen, act in [("NOW", "now", None), ("SEASON", "season", None), ("TREND", "trend", None)]:
            for rate in (1, 4, 6, 12):
                t = run(url, br, screen, rate, act=act)
                fps = [f for f, _ in t]; flip = next((i + 1 for i, (_, q) in enumerate(t) if q == "low"), None)
                first3 = sum(fps[:3]) / 3; last = sum(fps[-4:]) / 4
                rows.append((name, rate, first3, last, flip))
                print(f"{name:30} cpu x{rate:<3} first-3s {first3:5.1f} fps | settled {last:5.1f} fps | auto-degrade to LOW at {('t=%ds' % flip) if flip else 'never (not needed)'}")
        br.close()
    return rows

if __name__ == "__main__":
    main()
