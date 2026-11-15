#!/usr/bin/env python3
import os, subprocess, sys, time, tempfile, signal, urllib.request, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _server import ROOT, free_port, post
from playwright.sync_api import sync_playwright

MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 30
port = free_port(); url = f"http://127.0.0.1:{port}"
logdir = tempfile.mkdtemp(); env = dict(os.environ, COLDCASE_LOGDIR=logdir)
proc = subprocess.Popen([sys.executable, "-m", "app", "--port", str(port), "--db", tempfile.mktemp(suffix=".db"), "--offline", "--sim", "--sim-wireless", "--sim-period", "0.05"],
                        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try: urllib.request.urlopen(url + "/api/state", timeout=1).read(); break
    except Exception: time.sleep(0.25)
time.sleep(1); post(url, "/api/calibrate"); time.sleep(8)
rss = lambda: int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(proc.pid)]).split()[0]) / 1024
rows, t_end, errs = [], time.time() + MIN * 60, []
SCR = ["now", "season", "trend"]
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    pg = br.new_page(viewport={"width": 800, "height": 480}, has_touch=True)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(url + "/#now"); pg.wait_for_function("window.__state && window.__state.now")
    cdp = pg.context.new_cdp_session(pg); cdp.send("Performance.enable")
    heap = lambda: next(m["value"] for m in cdp.send("Performance.getMetrics")["metrics"] if m["name"] == "JSHeapUsedSize") / 1048576
    i, last_sample = 0, 0
    while time.time() < t_end:
        scr = SCR[i % 3]; i += 1
        pg.evaluate(f"window.__show('{scr}')"); pg.wait_for_timeout(1500)
        if i % 3 == 0: pg.evaluate("window.__openTrace('ice')"); pg.wait_for_timeout(500); pg.evaluate("window.__closeSheet()")
        if i % 7 == 0: post(url, "/api/site", json.dumps({"id": ["mississauga", "sudbury", "timmins"][i % 3]}))
        pg.wait_for_timeout(2500)
        if time.time() - last_sample > 60:
            last_sample = time.time()
            pg.evaluate("window.gc && window.gc()")
            rows.append((round((time.time() - (t_end - MIN * 60)) / 60, 1), round(rss(), 1), round(heap(), 1)))
            print(f"t={rows[-1][0]:5.1f} min  server RSS {rows[-1][1]:6.1f} MB  browser JS heap {rows[-1][2]:6.1f} MB  samples ingested ~{int(rows[-1][0]*60/0.05):,}", flush=True)
    br.close()
proc.send_signal(signal.SIGTERM); proc.wait(timeout=10)
log = (Path(logdir) / "coldcase.log")
text = log.read_text(errors="ignore") if log.exists() else ""
bad = [l for l in text.splitlines() if re.search(r"ERROR|Traceback|CRITICAL", l)]
early, late = rows[len(rows) // 4], rows[-1]
g_rss, g_heap = 100 * (late[1] - early[1]) / early[1], 100 * (late[2] - early[2]) / max(early[2], 0.1)
verdict = g_rss < 10 and g_heap < 25 and not bad and not errs
summary = (f"SOAK {MIN:.0f} min (sim accelerated 40x ~ {int(MIN*60/0.05):,} node samples = {MIN*60/0.05*2/3600:.0f} h of real-rate data)\n"
           f"server RSS  {early[1]} -> {late[1]} MB ({g_rss:+.1f}% from minute {early[0]})\n"
           f"browser heap {early[2]} -> {late[2]} MB ({g_heap:+.1f}%)\n"
           f"backend log ERROR/Traceback lines: {len(bad)}   page JS errors: {len(errs)}\n"
           f"VERDICT: {'PASS' if verdict else 'FAIL'}\n" + "".join(f"  {l}\n" for l in bad[:5]) + "".join(f"  js: {e[:120]}\n" for e in errs[:3]))
print(summary); (ROOT / "docs" / "SOAK.txt").write_text(summary + "\nsamples (min, serverMB, heapMB): " + json.dumps(rows) + "\n")
sys.exit(0 if verdict else 1)
