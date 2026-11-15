#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request

NODE = "sim-field"

def send(url, payload, token="", raw=None, timeout=3):
    data = raw if raw is not None else json.dumps(payload).encode()
    h = {"Content-Type": "application/json"}
    if token:
        h["X-Node-Token"] = token
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)

class Sensor:
    def __init__(self, seed=3, ground=45.2, snow=9.0):
        self.rng, self.t0, self.ground, self.snow, self.seq = random.Random(seed), time.time(), ground, snow, 0

    def packet(self, t=None):
        t = t or time.time()
        self.seq += 1
        x = t - self.t0
        return {"temp_c": round(21.4 + 0.5 * math.sin(x / 140) + self.rng.gauss(0, .08), 2),
                "rh": round(40 + 3 * math.sin(x / 110) + self.rng.gauss(0, .4), 2),
                "dist_cm": round(self.ground - self.snow + self.rng.gauss(0, .25), 2),
                "node": NODE, "seq": self.seq, "t": round(t, 1)}

def steady(url, token, seconds, period):
    s, end, bad = Sensor(), time.time() + seconds, 0
    while time.time() < end:
        code, body = send(url, s.packet(), token)
        print(code, body)
        bad += code != 200
        time.sleep(period)
    return bad == 0

def chaos(url, token, period):
    s, fails = Sensor(), []

    def check(name, got, want):
        ok = got in want if isinstance(want, tuple) else got == want
        print(("ok   " if ok else "FAIL ") + f"{name}: HTTP {got} (want {want})")
        if not ok:
            fails.append(name)

    print("--- 1. healthy live stream")
    for _ in range(3):
        check("live", send(url, s.packet(), token)[0], 200)
        time.sleep(period)
    print("--- 2. exact duplicate (sender timed out and re-sent)")
    p = s.packet()
    check("first copy", send(url, p, token)[0], 200)
    check("duplicate", send(url, p, token)[0], 200)
    print("--- 3. dropout: 12 s of silence, then a backlog burst, newest first (out of order)")
    print("    (sleeping 12 s so the tiles go stale ...)")
    time.sleep(12)
    now = time.time()
    backlog = [s.packet(now - 100 + i * 10) for i in range(5)] + [s.packet(now - 8)]
    for p in reversed(backlog):
        check("backlog", send(url, p, token)[0], 200)
    check("fresh after dropout", send(url, s.packet(), token)[0], 200)
    print("--- 4. wrong clock on the Zero (before 2026, and far in the future)")
    check("clock 1970", send(url, dict(s.packet(), t=1000.0), token)[0], 200)
    check("clock +1 h", send(url, dict(s.packet(), t=time.time() + 3600), token)[0], 200)
    print("--- 5. bad data")
    for name, raw in (("garbage", b"\x00\xffnot json at all"), ("empty", b""), ("array", b"[1,2,3]"), ("no sensor keys", b'{"node":"sim-field","seq":1}')):
        check(name, send(url, None, token, raw=raw)[0], 400)
    for name, payload in (("null/NaN/-1/0", {"temp_c": None, "rh": None, "dist_cm": -1, "node": NODE, "seq": 99, "t": time.time()}),
                          ("DHT11 clamp 0.0", {"temp_c": 0.0, "rh": 0, "dist_cm": 0, "node": NODE, "seq": 100, "t": time.time()})):
        check(name + " (accepted, values dropped)", send(url, payload, token)[0], 200)
    print("--- 6. oversize body")
    check("oversize", send(url, None, token, raw=b'{"temp_c":1,"pad":"' + b"x" * 5000 + b'"}')[0], (413, 0))
    print("--- 7. bad token (only meaningful if node_token is set in config.toml)")
    code = send(url, s.packet(), "definitely-wrong")[0]
    print(f"     bad-token answer: HTTP {code} ({'token is OFF' if code == 200 else 'token enforced'})")
    check("bad token", code, (200, 401))
    print("--- 8. flood: 300 posts as fast as possible; the stream must stay up")
    codes = {}
    t0 = time.time()
    for _ in range(300):
        c = send(url, s.packet(), token, timeout=2)[0]
        codes[c] = codes.get(c, 0) + 1
    print(f"     {codes} in {time.time() - t0:.1f}s (200 = accepted, 429 = rate-limited; both are fine)")
    check("flood only 200/429", all(c in (200, 429) for c in codes), True)
    try:
        base = url.split("/api/node")[0]
        with urllib.request.urlopen(base + "/api/node/info", timeout=2) as r:
            info = json.load(r)
        print("app counters:", info["stats"], "rejected-by-reason:", info["reasons"])
        want = info["stats"]["historical"] >= 5 and info["stats"]["duplicate"] >= 1 and info["stats"]["clock_suspect"] >= 2
        print(("ok   " if want else "FAIL ") + "app saw >=5 historical, >=1 duplicate, >=2 clock_suspect")
        if not want:
            fails.append("counters")
    except Exception:
        print("(counters skipped: run this on the Pi itself to see them)")
    print("\nRESULT:", "PASS" if not fails else "FAIL " + ", ".join(fails))
    return not fails

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/api/node")
    ap.add_argument("--scenario", choices=("steady", "chaos"), default="steady")
    ap.add_argument("--token", default="")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--period", type=float, default=2.0)
    a = ap.parse_args()
    ok = chaos(a.url, a.token, a.period) if a.scenario == "chaos" else steady(a.url, a.token, a.seconds, a.period)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
