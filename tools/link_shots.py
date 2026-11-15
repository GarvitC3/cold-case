#!/usr/bin/env python3
import argparse
import json
import math
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _server import ROOT, backend, post as spost
from playwright.sync_api import sync_playwright

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="800x480,1024x600")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screens"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with backend(calibrate=False, sim=False, flags_=("--today", "2026-02-10")) as (url, proc, _):
        stop = threading.Event()
        state = {"dist": 45.2, "seq": 0}

        def zero():
            n = 0
            while not stop.is_set():
                n += 1; state["seq"] += 1
                body = {"temp_c": round(21.3 + 0.2 * math.sin(n / 7), 2), "rh": 41.0, "dist_cm": state["dist"],
                        "node": "sim-field", "seq": state["seq"], "t": round(time.time(), 1)}
                try:
                    urllib.request.urlopen(urllib.request.Request(url + "/api/node", data=json.dumps(body).encode(),
                                           headers={"Content-Type": "application/json"}), timeout=2).read()
                except Exception:
                    pass
                stop.wait(1.0)
        th = threading.Thread(target=zero, daemon=True); th.start()
        time.sleep(12)
        spost(url, "/api/calibrate"); time.sleep(8.5)
        state["dist"] = 36.2
        time.sleep(4)
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True)
            pages = []
            for size in a.sizes.split(","):
                w, h = (int(x) for x in size.split("x"))
                pg = br.new_context(viewport={"width": w, "height": h}).new_page()
                pg.goto(url + "/#now"); pg.wait_for_function("window.__state && window.__state.now"); pg.wait_for_timeout(2500)
                pages.append((size, pg))
            def shot(tag, sheet=None):
                for size, pg in pages:
                    pg.evaluate("window.__closeSheet(); dispatchEvent(new PointerEvent('pointerdown')); window.__show('now')")
                    if sheet == "node": pg.evaluate("window.__openNode()")
                    if sheet == "settings": pg.evaluate("window.__openSettings()")
                    pg.wait_for_timeout(1800)
                    f = out / f"link_{tag}_{size}.png"; pg.screenshot(path=str(f)); print("saved", f)
            shot("green"); shot("node_sheet", "node"); shot("settings", "settings")
            stop.set(); t_stop = time.time()
            time.sleep(max(0, 25 - (time.time() - t_stop)))
            shot("amber")
            time.sleep(max(0, 80 - (time.time() - t_stop)))
            shot("offline"); shot("offline_node_sheet", "node")
            br.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
