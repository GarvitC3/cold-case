from __future__ import annotations

import glob
import json
import logging
import math
import random
import re
import statistics
import threading
import time
from collections import deque
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

log = logging.getLogger("coldcase.node")

DIST_MIN, DIST_MAX, DIST_PRACTICAL = 2.0, 400.0, 200.0
DHT11_MIN, DHT11_MAX = 0.0, 50.0
LIVE_AGE_S, OFFLINE_AGE_S = 6.0, 10.0
CHIP_AMBER_S = 60.0
HIST_AFTER_S = 30.0
MAX_AHEAD_S = 300.0
MAX_HIST_AGE_S = 3 * 86400.0
MIN_VALID_T = 1767225600.0
PROMOTE_S, DWELL_S = 5.0, 5.0
SOURCES = ("wireless", "usb")

@dataclass
class Reading:
    ts: float
    temp_c: Optional[float] = None
    rh: Optional[float] = None
    dist_cm: Optional[float] = None
    temp_src: str = "dht11"
    temp_state: str = "missing"
    dist_state: str = "missing"
    raw: str = ""
    source: str = "usb"
    simulated: bool = False
    node: str = ""
    seq: Optional[int] = None
    t_sent: Optional[float] = None
    flags: List[str] = field(default_factory=list)
    historical: bool = False
    has_keys: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

_BARE = re.compile(r"(?<![\w\"])(-?nan|-?inf|-?infinity)(?![\w\"])", re.I)

def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None

def classify_temp(v: Optional[float], src: str) -> Tuple[Optional[float], str]:
    if v is None:
        return None, "missing"
    if src == "ds18b20":
        if v in (85.0, -127.0) or v < -55.0 or v > 125.0:
            return None, "out_of_range"
        return v, "ok"
    if v <= DHT11_MIN or v >= DHT11_MAX:
        return None, "out_of_range"
    return v, "ok"

def parse_line(line: Any, ts: float) -> Optional[Reading]:
    try:
        if isinstance(line, (bytes, bytearray)):
            line = line.decode("utf-8", errors="ignore")
        s = str(line).strip()
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b <= a:
            return None
        body = _BARE.sub("null", s[a:b + 1])
        obj = json.loads(body)
        if not isinstance(obj, dict):
            return None
    except (ValueError, TypeError, RecursionError):
        return None
    src = str(obj.get("temp_src", "dht11")).lower()
    src = "ds18b20" if src.startswith("ds18") else "dht11"
    temp, tstate = classify_temp(_num(obj.get("temp_c")), src)
    rh = _num(obj.get("rh"))
    if rh is not None and not (0.0 <= rh <= 100.0):
        rh = None
    d = _num(obj.get("dist_cm"))
    if d is None:
        dstate = "missing"
    elif d < DIST_MIN or d > DIST_MAX:
        d, dstate = None, "out_of_range"
    else:
        dstate = "ok"
    meta = {k: obj[k] for k in ("node", "seq", "t") if k in obj}
    has = any(k in obj for k in ("temp_c", "rh", "dist_cm"))
    return Reading(ts, temp, rh, d, src, tstate, dstate, s[:160], has_keys=has, meta=meta)

_NODE_OK = re.compile(r"[^A-Za-z0-9_.\-]")

def classify_time(t: Optional[float], recv: float) -> Tuple[float, str, List[str]]:
    if t is None or not math.isfinite(t):
        return recv, "live", ["no_t"]
    if t < MIN_VALID_T or t > recv + MAX_AHEAD_S:
        return recv, "live", ["clock_suspect"]
    if recv - t > HIST_AFTER_S:
        return t, "historical", []
    return recv, "live", []

def parse_wireless(body: Any, recv: float) -> Tuple[Optional[Reading], str]:
    r = parse_line(body, recv)
    if r is None:
        return None, "garbage"
    if not r.has_keys:
        return None, "no_sensor_keys"
    node = _NODE_OK.sub("", str(r.meta.get("node", "") or ""))[:32] or "unknown"
    seq = _num(r.meta.get("seq"))
    t = _num(r.meta.get("t"))
    eff, kind, flags = classify_time(t, recv)
    r.source, r.node, r.t_sent, r.flags = "wireless", node, t, flags
    r.seq = int(seq) if seq is not None else None
    r.ts, r.historical = eff, kind == "historical"
    r.simulated = node.lower().startswith("sim")
    return r, ""

class SnowFilter:

    def __init__(self, window_s: float = 15.0, agree_cm: float = 1.5, jump_cm: float = 3.0):
        self.window_s, self.agree_cm, self.jump_cm = window_s, agree_cm, jump_cm
        self.buf: Deque[Tuple[float, float]] = deque()

    def reset(self) -> None:
        self.buf.clear()

    def update(self, ts: float, v: float) -> float:
        self.buf.append((ts, v))
        while self.buf and ts - self.buf[0][0] > self.window_s:
            self.buf.popleft()
        med = statistics.median(x for _, x in self.buf)
        if len(self.buf) >= 2:
            a, b = self.buf[-1][1], self.buf[-2][1]
            if abs(a - b) <= self.agree_cm and abs(a - med) > self.jump_cm:
                last2 = list(self.buf)[-2:]
                self.buf.clear()
                self.buf.extend(last2)
                med = (a + b) / 2.0
        return med

def snow_from_dist(dist_cm: Optional[float], ground_cm: Optional[float]) -> Tuple[Optional[float], str]:
    if ground_cm is None:
        return None, "needs_calibration"
    if dist_cm is None:
        return None, "out_of_range"
    raw = ground_cm - dist_cm
    if raw < -4.0:
        return None, "below_ground"
    return max(0.0, raw), "ok"

class Arbiter:

    ALIVE_S = OFFLINE_AGE_S

    def __init__(self) -> None:
        self.last: Dict[str, float] = {}
        self.run_start: Dict[str, float] = {}
        self.active: Optional[str] = None
        self.switched_at = -1e12

    def note(self, src: str, now: float) -> None:
        prev = self.last.get(src)
        if prev is None or now - prev > self.ALIVE_S:
            self.run_start[src] = now
        self.last[src] = max(now, prev or now)

    def alive(self, src: str, now: float) -> bool:
        t = self.last.get(src)
        return t is not None and now - t <= self.ALIVE_S

    def select(self, now: float) -> Optional[str]:
        cur = self.active if (self.active and self.alive(self.active, now)) else None
        want = cur
        if cur is None:
            want = next((s for s in SOURCES if self.alive(s, now)), None)
        elif cur == "usb" and self.alive("wireless", now):
            span = self.last["wireless"] - self.run_start.get("wireless", now)
            if span >= PROMOTE_S and now - self.switched_at >= DWELL_S:
                want = "wireless"
        if want != self.active:
            self.active = want
            self.switched_at = now
        return self.active

class _Link:

    def __init__(self) -> None:
        self.last_ts: Optional[float] = None
        self.node = ""
        self.simulated = False
        self.n_live = 0

class NodeHub:

    def __init__(self, store, mode: str = "indoor_demo", snow_filter_s: float = 15.0):
        self.store = store
        self.mode = mode
        self.lock = threading.RLock()
        self.snow_filter = SnowFilter(snow_filter_s)
        self.arb = Arbiter()
        self.links: Dict[str, _Link] = {s: _Link() for s in SOURCES}
        self.last: Optional[Reading] = None
        self.last_seen: Optional[float] = None
        self.active: Optional[str] = None
        self._last_active: Optional[str] = None
        self.usb_port: Optional[str] = None
        self.sim_mode = False
        self.raw_tail: Deque[str] = deque(maxlen=60)
        self.snow_cm: Optional[float] = None
        self.snow_state = "offline"
        g = store.get("grounds")
        if not isinstance(g, dict):
            g = {"usb": {"g": store.get("ground_cm"), "h": store.get("ground_history", []) or []}} if store.get("ground_cm") is not None else {}
        self._grounds: Dict[str, Dict[str, Any]] = g
        self.cal: Dict[str, Any] = {"state": "idle"}
        self._cal_samples: List[float] = []
        self.on_calibration: Optional[Callable[[bool], None]] = None
        self.hist: Deque[Tuple[float, float]] = deque(maxlen=360)
        self._bucket: Dict[str, Any] = {}
        self.dev_snow_override: Optional[float] = None
        self._seen: "OrderedDict[Tuple[str, int], None]" = OrderedDict()
        self._seen_new: List[Tuple[str, int]] = []
        self._hist_pending: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self.packets: Deque[Dict[str, Any]] = deque(maxlen=20)
        self._accepted: Deque[float] = deque(maxlen=600)
        self.stats = {"accepted": 0, "live": 0, "standby": 0, "historical": 0, "duplicate": 0, "rejected": 0,
                      "too_old": 0, "clock_suspect": 0}
        self.reject_reasons: Dict[str, int] = {}
        self._load_history()
        for k in self.store.seen_load():
            self._seen[(k[0], int(k[1]))] = None

    def _gkey(self) -> str:
        return self.active or self._last_active or "usb"

    @property
    def ground_cm(self) -> Optional[float]:
        return (self._grounds.get(self._gkey()) or {}).get("g")

    @ground_cm.setter
    def ground_cm(self, v: Optional[float]) -> None:
        self._grounds.setdefault(self._gkey(), {"g": None, "h": []})["g"] = v

    @property
    def ground_history(self) -> List[float]:
        return (self._grounds.get(self._gkey()) or {}).get("h", [])

    @ground_history.setter
    def ground_history(self, v: List[float]) -> None:
        self._grounds.setdefault(self._gkey(), {"g": None, "h": []})["h"] = v

    def _persist_ground(self) -> None:
        self.store.set("grounds", self._grounds)

    def _load_history(self) -> None:
        for ts, t, _s in self.store.recent(time.time() - 6 * 3600):
            if t is not None:
                self.hist.append((float(ts), float(t)))

    def mark_connection(self, source: Optional[str], port: Optional[str]) -> None:
        with self.lock:
            self.usb_port = port if source else None

    def _select(self, now: float) -> Optional[str]:
        act = self.arb.select(now)
        if act != self.active:
            self._flush_bucket()
            self.snow_filter.reset()
            self.snow_cm, self.snow_state = None, "offline"
            self.last, self.last_seen = None, None
            if self.active:
                self._last_active = self.active
            self.active = act
            if act:
                self._last_active = act
        return act

    def ingest(self, r: Reading) -> bool:
        with self.lock:
            src = r.source
            link = self.links.setdefault(src, _Link())
            link.last_ts, link.node, link.simulated = r.ts, r.node, r.simulated
            link.n_live += 1
            self.raw_tail.append(r.raw)
            self.arb.note(src, r.ts)
            if self._select(r.ts) != src:
                return False
            self._feed(r)
            return True

    def _feed(self, r: Reading) -> None:
        self.last_seen = r.ts
        self.last = r
        if self.cal.get("state") == "averaging":
            if r.dist_cm is not None:
                self._cal_samples.append(r.dist_cm)
            self._advance_calibration(r.ts)
        snow, state = snow_from_dist(r.dist_cm, self.ground_cm)
        if snow is not None:
            self.snow_cm = round(self.snow_filter.update(r.ts, snow), 2)
        elif state != "ok":
            self.snow_cm = None
        self.snow_state = state
        self._bucket_add(r)

    def receive(self, r: Reading, now: Optional[float] = None) -> str:
        now = now or time.time()
        with self.lock:
            if r.t_sent is not None:
                key = (r.node, int(round(r.t_sent * 10)))
                if key in self._seen:
                    self.stats["duplicate"] += 1
                    return "duplicate"
                self._seen[key] = None
                self._seen_new.append(key)
                if len(self._seen) > 20000:
                    self._seen.popitem(last=False)
            if r.historical and now - r.ts > MAX_HIST_AGE_S:
                self.stats["too_old"] += 1
                return "too_old"
            self.stats["accepted"] += 1
            self._accepted.append(now)
            if "clock_suspect" in r.flags:
                self.stats["clock_suspect"] += 1
            if r.historical:
                self._hist_add(r)
                self.stats["historical"] += 1
                return "historical"
            if self.ingest(r):
                self.stats["live"] += 1
                return "live"
            self.stats["standby"] += 1
            return "standby"

    def note_packet(self, ip: str, status: int, nbytes: int, raw: str, note: str = "") -> None:
        clean = "".join(c if 32 <= ord(c) < 127 else "·" for c in raw[:160])
        with self.lock:
            self.packets.append({"at": time.time(), "ip": ip, "status": status, "bytes": nbytes, "raw": clean, "note": note})
            if status >= 400:
                self.stats["rejected"] += 1
                self.reject_reasons[note or str(status)] = self.reject_reasons.get(note or str(status), 0) + 1

    def _hist_add(self, r: Reading) -> None:
        minute = int(r.ts // 60 * 60)
        if len(self._hist_pending) > 2000 and (minute, r.source) not in self._hist_pending:
            return
        ground = (self._grounds.get(r.source) or {}).get("g")
        snow, _ = snow_from_dist(r.dist_cm, ground)
        b = self._hist_pending.setdefault((minute, r.source), {"t": [], "rh": [], "d": [], "s": [], "sim": r.simulated})
        for k, v in (("t", r.temp_c), ("rh", r.rh), ("d", r.dist_cm), ("s", snow)):
            if v is not None:
                b[k].append(v)

    def _flush_hist(self) -> None:
        pend, self._hist_pending = self._hist_pending, {}
        for (minute, src), b in pend.items():
            mean = lambda xs: (sum(xs) / len(xs)) if xs else None
            self.store.add_sample(minute, mean(b["t"]), mean(b["rh"]), mean(b["d"]), mean(b["s"]),
                                  temp_ok=bool(b["t"]), mode=self.mode, src=("sim-" if b["sim"] else "") + src,
                                  counts=(len(b["t"]), len(b["rh"]), len(b["d"]), len(b["s"])))
        if self._seen_new:
            keys, self._seen_new = self._seen_new, []
            self.store.seen_add(keys)

    def _bucket_add(self, r: Reading) -> None:
        minute = int(r.ts // 60 * 60)
        b = self._bucket
        if b and (b["minute"] != minute or b["src"] != r.source):
            self._flush_bucket()
            b = self._bucket
        if not b:
            b.update(minute=minute, src=r.source, sim=r.simulated, t=[], rh=[], d=[], s=[])
        if r.temp_c is not None:
            b["t"].append(r.temp_c)
        if r.rh is not None:
            b["rh"].append(r.rh)
        if r.dist_cm is not None:
            b["d"].append(r.dist_cm)
        if self.snow_cm is not None:
            b["s"].append(self.snow_cm)

    def _flush_bucket(self) -> None:
        b = self._bucket
        if not b:
            return
        mean = lambda xs: (sum(xs) / len(xs)) if xs else None
        t = mean(b["t"])
        self.store.add_sample(b["minute"], t, mean(b["rh"]), mean(b["d"]), mean(b["s"]),
                              temp_ok=bool(b["t"]), mode=self.mode, src=("sim-" if b["sim"] else "") + b["src"],
                              counts=(len(b["t"]), len(b["rh"]), len(b["d"]), len(b["s"])))
        if t is not None:
            self.hist.append((float(b["minute"]), t))
        self._bucket = {}

    def flush(self) -> None:
        with self.lock:
            self._flush_bucket()
            self._flush_hist()

    def start_calibration(self, seconds: float = 5.0) -> Dict[str, Any]:
        with self.lock:
            if self.cal.get("state") == "averaging":
                return dict(self.cal)
            self._cal_samples = []
            self.cal = {"state": "averaging", "t0": time.time(), "seconds": seconds}
        if self.on_calibration:
            self.on_calibration(True)
        return dict(self.cal)

    def _advance_calibration(self, now: float) -> None:
        c = self.cal
        if c.get("state") != "averaging":
            return
        elapsed = time.time() - c["t0"]
        if elapsed < c["seconds"]:
            return
        if len(self._cal_samples) < 2 and elapsed < c["seconds"] + 6.0:
            return
        if self.on_calibration:
            self.on_calibration(False)
        if len(self._cal_samples) >= 2:
            ground = round(statistics.median(self._cal_samples), 1)
            if self.ground_cm is not None:
                self.ground_history = (self.ground_history + [self.ground_cm])[-5:]
            self.ground_cm = ground
            self.snow_filter.reset()
            self._persist_ground()
            self.cal = {"state": "done", "ground_cm": ground, "n": len(self._cal_samples), "at": time.time()}
        else:
            self.cal = {"state": "failed", "at": time.time(),
                        "reason": "The sensor could not see the ground. Check it points straight down, 2–400 cm away."}

    def tick(self) -> None:
        with self.lock:
            self._select(time.time())
            if self.cal.get("state") == "averaging":
                self._advance_calibration(time.time())
            elif self.cal.get("state") in ("done", "failed") and time.time() - self.cal.get("at", 0) > 12:
                self.cal = {"state": "idle"}
            if self._hist_pending or self._seen_new:
                self._flush_hist()

    def undo_calibration(self) -> bool:
        with self.lock:
            if not self.ground_history:
                return False
            hist = list(self.ground_history)
            self.ground_cm = hist.pop()
            self.ground_history = hist
            self.snow_filter.reset()
            self._persist_ground()
            self.cal = {"state": "done", "ground_cm": self.ground_cm, "undone": True, "at": time.time()}
            return True

    def clear_calibration(self) -> None:
        with self.lock:
            self.ground_cm = None
            self.ground_history = []
            self.snow_cm = None
            self.snow_filter.reset()
            self._persist_ground()
            self.cal = {"state": "idle"}

    def state(self, now: Optional[float] = None) -> str:
        now = now or time.time()
        if self.last_seen is None:
            return "offline"
        age = now - self.last_seen
        return "live" if age <= LIVE_AGE_S else ("dropout" if age <= OFFLINE_AGE_S else "offline")

    def packets_per_min(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        return sum(1 for t in self._accepted if now - t <= 60.0)

    @staticmethod
    def _tone(age: Optional[float]) -> str:
        if age is None:
            return "grey"
        return "green" if age <= OFFLINE_AGE_S else ("amber" if age <= CHIP_AMBER_S else "grey")

    def link_view(self, now: float) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for s, l in self.links.items():
            age = (now - l.last_ts) if l.last_ts is not None else None
            out[s] = {"age_s": round(age, 1) if age is not None else None, "tone": self._tone(age), "node": l.node,
                      "simulated": l.simulated, "seen": l.last_ts is not None, "active": self.active == s}
        out["usb"]["connected"] = self.usb_port is not None
        out["usb"]["port"] = self.usb_port
        out["wireless"]["ppm"] = self.packets_per_min(now)
        seen = [(s, out[s]["age_s"]) for s in SOURCES if out[s]["seen"]]
        if self.active:
            via = self.active
        elif seen:
            via = min(seen, key=lambda x: x[1])[0]
        else:
            via = None
        chip = {"via": via, "age_s": out[via]["age_s"] if via else None, "tone": out[via]["tone"] if via else "grey",
                "node": out[via]["node"] if via else "", "simulated": out[via]["simulated"] if via else False}
        out["chip"] = chip
        return out

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        with self.lock:
            self._select(now)
            st = self.state(now)
            r = self.last
            age = (now - self.last_seen) if self.last_seen else None
            live = st in ("live", "dropout")
            snow_cm = self.dev_snow_override if self.dev_snow_override is not None else self.snow_cm
            link = self.link_view(now)
            if r is not None:
                simulated = bool(r.simulated)
            else:
                seen = [l for l in self.links.values() if l.last_ts is not None]
                simulated = max(seen, key=lambda l: l.last_ts).simulated if seen else self.sim_mode
            return {
                "state": st,
                "source": self.active,
                "via": self.active,
                "name": (r.node if r else "") or "",
                "port": self.usb_port if self.active == "usb" else None,
                "simulated": simulated,
                "last_seen_age_s": round(age, 1) if age is not None else None,
                "link": link,
                "temp": {
                    "c": round(r.temp_c, 1) if (r and live and r.temp_c is not None) else None,
                    "state": (r.temp_state if (r and live) else "missing"),
                    "src": (r.temp_src if r else "dht11"),
                },
                "rh": round(r.rh) if (r and live and r.rh is not None) else None,
                "dist": {"cm": r.dist_cm if (r and live) else None,
                         "state": (r.dist_state if (r and live) else "missing"),
                         "practical_max": DIST_PRACTICAL},
                "snow": {
                    "cm": snow_cm if (live or self.dev_snow_override is not None) else None,
                    "state": self.snow_state if live else "offline",
                    "ground_cm": self.ground_cm,
                    "can_undo": bool(self.ground_history),
                },
                "cal": self._cal_view(),
                "spark": self._spark(now),
            }

    def info(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        with self.lock:
            return {"packets": [dict(p, age_s=round(now - p["at"], 1)) for p in list(self.packets)[::-1]],
                    "ppm": self.packets_per_min(now), "stats": dict(self.stats), "reasons": dict(self.reject_reasons)}

    def _cal_view(self) -> Dict[str, Any]:
        c = dict(self.cal)
        if c.get("state") == "averaging":
            c["progress"] = max(0.0, min(1.0, (time.time() - c["t0"]) / c["seconds"]))
        c.pop("t0", None)
        return c

    def _spark(self, now: float) -> List[List[float]]:
        pts = [p for p in self.hist if now - p[0] <= 6 * 3600]
        bins: Dict[int, List[float]] = {}
        for ts, t in pts:
            bins.setdefault(int(ts // 300), []).append(t)
        return [[k * 300.0, round(sum(v) / len(v), 2)] for k, v in sorted(bins.items())]

class SimNode(threading.Thread):

    GROUND_TRUE_CM = 45.2

    def __init__(self, hub: NodeHub, period: float = 2.0, snow_fixed: Optional[float] = None, seed: int = 7,
                 via: str = "usb", url: str = ""):
        super().__init__(daemon=True, name=f"sim-node-{via}")
        self.hub, self.period, self.snow_fixed, self.via, self.url = hub, period, snow_fixed, via, url
        self.rng = random.Random(seed)
        self.t0 = time.time()
        self.seq = 0
        self.clear_view = False
        self.stop_flag = threading.Event()
        self.next_dropout = self.t0 + self.rng.uniform(300, 600)
        self.dropout_until = 0.0
        prev = hub.on_calibration
        hub.on_calibration = (lambda a: (prev(a) if prev else None, self._cal_hook(a))[1])
        if via == "usb":
            hub.mark_connection("usb", "simulated")

    def _cal_hook(self, active: bool) -> None:
        self.clear_view = active

    def true_snow(self, t: float) -> float:
        if self.clear_view:
            return 0.0
        if self.snow_fixed is not None:
            return self.snow_fixed
        x = t - self.t0
        return max(0.0, 8.5 + 6.0 * math.sin(2 * math.pi * x / 160.0) + 2.0 * math.sin(2 * math.pi * x / 41.0))

    def line(self, t: float) -> str:
        x = t - self.t0
        temp = 21.4 + 0.6 * math.sin(2 * math.pi * x / 900.0) + self.rng.gauss(0, 0.08)
        rh = 40.0 + 3.0 * math.sin(2 * math.pi * x / 700.0) + self.rng.gauss(0, 0.4)
        dist = self.GROUND_TRUE_CM - self.true_snow(t) + self.rng.gauss(0, 0.25)
        return json.dumps({"temp_c": round(temp, 2), "rh": round(rh, 2), "dist_cm": round(dist, 2)})

    def reading(self, t: float) -> Reading:
        r = parse_line(self.line(t), t)
        assert r is not None
        r.simulated = True
        return r

    def _post(self, t: float) -> None:
        import urllib.request
        self.seq += 1
        obj = json.loads(self.line(t))
        obj.update({"node": "sim-field", "seq": self.seq, "t": round(t, 1)})
        req = urllib.request.Request(self.url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()

    def run(self) -> None:
        while not self.stop_flag.is_set():
            t = time.time()
            if t >= self.next_dropout:
                self.dropout_until = t + 8.0
                self.next_dropout = t + self.rng.uniform(480, 720)
            if t >= self.dropout_until:
                try:
                    if self.via == "wireless":
                        self._post(t)
                    else:
                        self.hub.ingest(self.reading(t))
                except Exception:
                    log.debug("sim %s send failed", self.via, exc_info=True)
            self.stop_flag.wait(self.period)

    def stop(self) -> None:
        self.stop_flag.set()

def find_ports(override: str = "") -> List[str]:
    if override:
        return [override]
    pats = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/cu.wchusbserial*"]
    out: List[str] = []
    for p in pats:
        out.extend(sorted(glob.glob(p)))
    return out

class SerialManager(threading.Thread):

    def __init__(self, hub: NodeHub, baud: int = 115200, port_override: str = ""):
        super().__init__(daemon=True, name="serial-node")
        self.hub, self.baud, self.override = hub, baud, port_override
        self.stop_flag = threading.Event()
        self.last_error: Optional[str] = None

    def run(self) -> None:
        try:
            import serial
        except ImportError:
            log.warning("pyserial not installed — node stays offline (apt install python3-serial)")
            return
        while not self.stop_flag.is_set():
            ports = find_ports(self.override)
            if not ports:
                self.hub.mark_connection(None, None)
                self.stop_flag.wait(2.0)
                continue
            port = ports[0]
            try:
                with serial.Serial(port, self.baud, timeout=3) as s:
                    log.info("node connected on %s", port)
                    self.hub.mark_connection("serial", port)
                    self.last_error = None
                    while not self.stop_flag.is_set():
                        line = s.readline()
                        if not line:
                            continue
                        r = parse_line(line, time.time())
                        if r is not None:
                            self.hub.ingest(r)
                        else:
                            self.hub.raw_tail.append("? " + line.decode("utf-8", errors="ignore").strip()[:100])
            except Exception as e:
                if str(e) != self.last_error:
                    log.warning("serial %s: %s — will retry", port, e)
                self.last_error = str(e)
            self.hub.mark_connection(None, None)
            self.stop_flag.wait(1.5)

    def stop(self) -> None:
        self.stop_flag.set()
