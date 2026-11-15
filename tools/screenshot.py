#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = {
    "live":   (["--sim", "--sim-snow", "9"], True, None, None),
    "uncal":  (["--sim", "--sim-snow", "9"], False, None, None),
    "nonode": ([], False, None, None),
    "mid":    (["--sim", "--sim-snow", "9", "--today", "2026-01-20"], True, None, None),
    "winter": (["--sim", "--sim-snow", "14", "--today", "2026-02-10"], True, "sudbury", None),
}

def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def post(url: str, path: str, body: str = "{}") -> None:
    req = urllib.request.Request(url + path, data=body.encode(), headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=5).read()

def wait_up(url: str) -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/state", timeout=1).read(); return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("server did not start")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="live", choices=sorted(SCENARIOS))
    ap.add_argument("--sizes", default="1280x720,1024x600,800x480,720x1280")
    ap.add_argument("--screens", default="now")
    ap.add_argument("--sheet", default=None, help="trace:ice | trace:cold | trace:snow | cal | sites | settings")
    ap.add_argument("--out", default=str(ROOT / "docs" / "screens"))
    ap.add_argument("--tag", default=None)
    ap.add_argument("--wait", type=float, default=2.2, help="seconds to let animations settle")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    flags, cal, site, _ = SCENARIOS[a.scenario]
    port = free_port(); url = f"http://127.0.0.1:{port}"
    db = tempfile.mktemp(suffix=".db")
    proc = subprocess.Popen([sys.executable, "-m", "app", "--port", str(port), "--db", db, "--offline", *flags],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    try:
        wait_up(url)
        if site:
            post(url, "/api/site", f'{{"id":"{site}"}}')
        if cal:
            time.sleep(2.5); post(url, "/api/calibrate"); time.sleep(8.5)
        time.sleep(1.5)
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True)
            for size in a.sizes.split(","):
                w, h = (int(x) for x in size.split("x"))
                ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                for scr in a.screens.split(","):
                    page.goto(f"{url}/#{scr}")
                    page.wait_for_function("window.__state && window.__state.now", timeout=8000)
                    page.evaluate(f"window.__show('{scr}')")
                    if a.sheet:
                        kind, _, arg = a.sheet.partition(":")
                        js = {"trace": f"window.__openTrace('{arg}')", "cal": "window.__openCal()", "sites": "window.__openSites()", "settings": "window.__openSettings()"}[kind]
                        page.evaluate(js)
                    page.wait_for_timeout(int(a.wait * 1000))
                    name = f"{a.tag or a.scenario}_{scr}{'_' + a.sheet.replace(':', '-') if a.sheet else ''}_{size}.png"
                    page.screenshot(path=str(out / name))
                    txt = page.evaluate("document.body.innerText")
                    import re
                    bad = re.findall(r"\b(NaN|undefined|null|Infinity|Traceback|TypeError)\b", txt)
                    over = page.evaluate("document.documentElement.scrollWidth > innerWidth + 1 || document.body.scrollHeight > innerHeight + 1")
                    flag = ("  !! BAD TEXT: " + ",".join(sorted(set(bad)))) if bad else ""
                    flag += "  !! PAGE OVERFLOWS" if over else ""
                    print("saved", out / name, flag or "  ok")
                if errors:
                    print("  JS errors at", size, errors[:5])
                ctx.close()
            br.close()
    finally:
        proc.send_signal(signal.SIGTERM)
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
        for ext in ("", "-wal", "-shm"):
            try: os.remove(db + ext)
            except OSError: pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
