#!/usr/bin/env python3
import signal, subprocess, sys, time, tempfile, os, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _server import ROOT, free_port, post
from playwright.sync_api import sync_playwright

out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screens"
port = free_port(); url = f"http://127.0.0.1:{port}"
db = tempfile.mktemp(suffix=".db"); env = dict(os.environ, COLDCASE_LOGDIR=tempfile.mkdtemp())
def boot():
    p = subprocess.Popen([sys.executable, "-m", "app", "--port", str(port), "--db", db, "--offline", "--sim", "--sim-snow", "9"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try: urllib.request.urlopen(url + "/api/state", timeout=1).read(); return p
        except Exception: time.sleep(0.25)
    raise SystemExit("backend did not start")
srv = boot(); time.sleep(2.5); post(url, "/api/calibrate"); time.sleep(8.5)
ok = True
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_page(viewport={"width": 1280, "height": 720}); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url + "/#now"); pg.wait_for_function("window.__state && window.__state.now"); pg.wait_for_timeout(1500)
    srv.send_signal(signal.SIGKILL); srv.wait()
    t0 = time.time()
    while time.time() - t0 < 25 and pg.evaluate("document.getElementById('banner').hidden"): pg.wait_for_timeout(500)
    shown = not pg.evaluate("document.getElementById('banner').hidden")
    txt = pg.evaluate("document.body.innerText")
    pg.screenshot(path=str(out / "resilience_backend_down_1280x720.png"))
    print("banner shown after backend death:", shown, f"({time.time() - t0:.1f}s)", "| raw error text on screen:", any(w in txt for w in ("NaN", "undefined", "Traceback", "Failed to fetch")))
    ok &= shown
    srv = boot()
    t0 = time.time()
    while time.time() - t0 < 30 and not pg.evaluate("document.getElementById('banner').hidden"): pg.wait_for_timeout(500)
    rec = pg.evaluate("document.getElementById('banner').hidden")
    print("recovered by itself after restart:", rec, f"({time.time() - t0:.1f}s)", "| page errors:", errs[:3])
    ok &= rec
    br.close()
srv.send_signal(signal.SIGTERM)
sys.exit(0 if ok else 1)
