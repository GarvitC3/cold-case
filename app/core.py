from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import __version__
from . import fdd as F
from . import nasa
from .config import CACHE_DIR, SITE_BY_ID, SITES, THRESHOLDS
from .model import IceParams
from .node import NodeHub
from .nowcast import _jsonify, compute_nowcast
from . import trend as TR
from .store import Store

log = logging.getLogger("coldcase.core")
def _build_date() -> str:
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parent
        return date.fromtimestamp(max(p.stat().st_mtime for p in list(root.glob("*.py")) + list((root.parent / "web").rglob("*.js")))).isoformat()
    except (OSError, ValueError):
        return ""

_BUILD = _build_date()
NASA_STALE_DAYS = 10
SYNC_OK_S, SYNC_RETRY_S = 6 * 3600, 5 * 60

class AppCore:
    def __init__(self, cfg: Dict[str, Dict[str, Any]], store: Store, hub: NodeHub,
                 today_override: Optional[date] = None, offline: bool = False, sim: bool = False):
        self.cfg, self.store, self.hub = cfg, store, hub
        self.today_override = today_override
        self.offline = offline or today_override is not None
        self.sim = sim
        self.params = IceParams.from_config(cfg)
        sid = store.get("site") or cfg["site"]["default"]
        self.site_id = sid if sid in SITE_BY_ID else "mississauga"
        self.mode = store.get("mode") or cfg["node"]["mode"]
        hub.mode = self.mode
        self.lock = threading.RLock()
        self._climates: Dict[str, Any] = {}
        self._snap_cache: Optional[tuple] = None
        self._days_cache: Optional[tuple] = None
        self.clock_offset = float(store.get("clock_offset", 0.0) or 0.0)
        self.prefs = store.get("prefs", {}) or {}
        self.sync = {"online": None, "syncing": False, "last_sync": None, "last_attempt": None, "error": None}
        self.stop_flag = threading.Event()
        self.port = int(cfg["server"]["port"])
        self.node_token = str(cfg["node"].get("node_token", "") or "")
        hub.sim_mode = sim

    def node_info(self) -> Dict[str, Any]:
        import socket
        from .netinfo import lan_addresses
        q = f"?token={self.node_token}" if self.node_token else ""
        addrs = [dict(a, url=f"http://{a['ip']}:{self.port}/api/node{q}") for a in lan_addresses()]
        first = addrs[0]["url"] if addrs else f"http://GRAVITY_IP:{self.port}/api/node{q}"
        info = self.hub.info()
        info.update({
            "addresses": addrs, "port": self.port, "hostname": socket.gethostname(),
            "token_required": bool(self.node_token),
            "sender_cmd": f"python3 node_sender.py --url {first}",
            "curl_cmd": ("curl -sS -X POST -H 'Content-Type: application/json' "
                         f"-d '{{\"node\":\"selftest\",\"seq\":1,\"t\":{int(time.time())},\"temp_c\":20}}' '{first}'"),
            "listening": self.cfg["server"]["host"],
        })
        return info

    def node_selftest(self) -> Dict[str, Any]:
        import urllib.request
        from .netinfo import lan_addresses
        targets = [a["ip"] for a in lan_addresses()] + ["127.0.0.1"]
        out = []
        for ip in targets:
            url = f"http://{ip}:{self.port}/api/node" + (f"?token={self.node_token}" if self.node_token else "")
            body = json.dumps({"node": "selftest", "seq": 1, "t": round(time.time(), 1), "temp_c": 20.0}).encode()
            t0 = time.time()
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=2.5) as r:
                    ok = r.status == 200 and json.loads(r.read() or b"{}").get("ok") is True
                out.append({"addr": ip, "ok": ok, "ms": int((time.time() - t0) * 1000), "error": "" if ok else "unexpected reply"})
            except Exception as e:
                out.append({"addr": ip, "ok": False, "ms": int((time.time() - t0) * 1000), "error": str(getattr(e, "reason", e))[:80]})
        return {"ok": all(o["ok"] for o in out), "results": out}

    def _now(self) -> float:
        return time.time() + self.clock_offset

    def today(self) -> date:
        return self.today_override or datetime.fromtimestamp(self._now()).date()

    def day_frac(self) -> float:
        n = datetime.fromtimestamp(self._now())
        return (n.hour * 3600 + n.minute * 60 + n.second) / 86400.0

    def clock_info(self) -> Dict[str, Any]:
        trusted = bool(self.today_override) or bool(self.clock_offset) or datetime.now().year >= 2026
        return {"today": self.today().isoformat(), "trusted": trusted, "dev": bool(self.today_override)}

    def set_clock(self, iso: str) -> bool:
        try:
            d = date.fromisoformat(iso)
        except (TypeError, ValueError):
            return False
        if not (2024 <= d.year <= 2100):
            return False
        self.clock_offset = datetime(d.year, d.month, d.day, 12).timestamp() - time.time()
        self.store.set("clock_offset", self.clock_offset)
        self._days_cache = None
        self._snap_cache = None
        return True

    def set_pref(self, key: str, value: Any) -> bool:
        if key not in ("reduce_motion",):
            return False
        self.prefs[key] = bool(value)
        self.store.set("prefs", self.prefs)
        self._snap_cache = None
        return True

    def reset_season(self) -> None:
        self.store.reset_samples()
        self._days_cache = None
        self._snap_cache = None

    def sync_now(self) -> bool:
        if self.offline or self.sync["syncing"]:
            return False
        threading.Thread(target=self.sync_once, daemon=True, name="sync-now").start()
        return True

    def debug_info(self) -> Dict[str, Any]:
        from .config import LOG_DIR
        tail: list = []
        try:
            tail = (LOG_DIR / "coldcase.log").read_text(errors="ignore").splitlines()[-25:]
        except OSError:
            pass
        return {"raw_tail": list(self.hub.raw_tail)[-30:], "log": tail, "sync": dict(self.sync)}

    def exit_kiosk(self) -> bool:
        import subprocess
        try:
            open("/tmp/coldcase-kiosk.stop", "w").close()
            subprocess.Popen(["pkill", "-f", "coldcase-chrome"])
            return True
        except OSError:
            return False

    def climate(self, site_id: str) -> Optional[F.SiteClimate]:
        p = nasa.cache_path(site_id, CACHE_DIR)
        try:
            key = (p.stat().st_mtime_ns, self.today())
        except OSError:
            key = None
        with self.lock:
            hit = self._climates.get(site_id)
            if hit and hit[0] == key and key is not None:
                return hit[1]
        series = nasa.read_cache(site_id, CACHE_DIR)
        if series is None or series.as_of is None:
            return None
        if self.today_override:
            series = series.truncated(self.today_override - timedelta(days=3))
            if series.as_of is None:
                return None
        try:
            c = F.SiteClimate(site_id, series, self.today())
        except Exception:
            log.exception("climate build failed for %s", site_id)
            return None
        with self.lock:
            self._climates[site_id] = (key, c)
        return c

    def set_site(self, sid: str) -> bool:
        if sid not in SITE_BY_ID:
            return False
        self.site_id = sid
        self.store.set("site", sid)
        self._snap_cache = None
        return True

    def set_mode(self, mode: str) -> bool:
        if mode not in ("indoor_demo", "outdoor"):
            return False
        self.mode = mode
        self.hub.mode = mode
        self.store.set("mode", mode)
        self._days_cache = None
        self._snap_cache = None
        return True

    def _node_days(self, cur_W: Optional[int]):
        if self.mode != "outdoor":
            return {}, None
        now = time.time()
        if self._days_cache and now - self._days_cache[0] < 60:
            return self._days_cache[1], self._days_cache[2]
        since = date(cur_W - 1, 11, 1) if cur_W else self.today()
        days = self.store.outdoor_days(since)
        mins = self.day_frac() * 1440.0
        partial = self.store.today_partial(self.today(), mins)
        self._days_cache = (now, days, partial)
        return days, partial

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        today = self.today()
        site = SITE_BY_ID[self.site_id]
        node = self.hub.snapshot(now)
        clim = self.climate(site.id)

        snow_cm = None
        if node["snow"]["cm"] is not None and node["snow"]["state"] == "ok":
            snow_cm = node["snow"]["cm"]

        if clim is None:
            nowc: Dict[str, Any] = {"phase": "no_data", "today": today.isoformat()}
            nasa_block: Dict[str, Any] = {"has_data": False}
        else:
            days, partial = self._node_days(clim.cur_W)
            nowc = compute_nowcast(clim, today, self.day_frac(), self.mode, days, partial, snow_cm, self.params)
            as_of = clim.as_of
            meta = clim.series.meta or {}
            age = (today - as_of).days if as_of else None
            nasa_block = {
                "has_data": True,
                "as_of": as_of.isoformat() if as_of else None,
                "age_days": age,
                "stale": bool(age is not None and age > NASA_STALE_DAYS),
                "fetched_at": meta.get("fetched_at"),
                "record_start": clim.series.start.isoformat(),
                "n_winters": clim.baseline["n"],
                "parameter": "T2M", "dataset": "NASA POWER daily",
                "api_version": meta.get("api_version"), "sources": meta.get("sources"), "community": meta.get("community"),
            }
        nasa_block.update({
            "online": self.sync["online"], "syncing": self.sync["syncing"],
            "last_sync": self.sync["last_sync"], "offline_flag": self.offline,
        })

        return {
            "v": __version__, "build": _BUILD, "t": round(now, 1),
            "site": {"id": site.id, "name": site.name, "short": site.short, "lat": site.lat, "lon": site.lon},
            "sites": [{"id": s.id, "name": s.name, "short": s.short, "lat": s.lat, "lon": s.lon} for s in SITES],
            "mode": {"deployment": self.mode, "sim": self.sim, "dev_clock": bool(self.today_override)},
            "clock": self.clock_info(),
            "nasa": nasa_block,
            "node": node,
            "now": nowc,
            "thresholds": THRESHOLDS,
            "ice_params": {"alpha": self.params.alpha, "alpha_low": self.params.alpha_low,
                           "alpha_high": self.params.alpha_high, "snow_lambda_cm": self.params.snow_lambda_cm,
                           "snow_floor": self.params.snow_floor},
            "units": self.cfg["display"]["units"],
            "reduce_motion": bool(self.prefs.get("reduce_motion", self.cfg["display"]["reduce_motion"])),
        }

    def snapshot_json(self, max_age: float = 0.4) -> str:
        c = self._snap_cache
        now = time.time()
        if c and now - c[0] < max_age:
            return c[1]
        s = json.dumps(_jsonify(self.snapshot()), separators=(",", ":"), allow_nan=False, default=_default)
        self._snap_cache = (now, s)
        return s

    def season(self) -> Dict[str, Any]:
        clim = self.climate(self.site_id)
        if clim is None:
            return {"has_data": False}
        r1 = lambda a: [None if v != v else round(float(v), 1) for v in a]
        comp = clim.completed
        tot = [w.total for w in comp]
        cur = clim.current
        now = self.snapshot()["now"] if clim.current is not None else {}
        f = (now or {}).get("fdd") or {}
        today_slot = F.slot_of(clim.today)
        asof_slot = F.slot_of(clim.as_of) if clim.as_of and F.winter_of(clim.as_of) == clim.cur_W else None
        out = {
            "has_data": True, "site": self.site_id, "slots": F.SLOTS, "feb29_slot": F.FEB29_SLOT,
            "n": len(comp), "first_W": comp[0].W if comp else None,
            "winters": [{"W": w.W, "label": w.label, "cum": r1(w.cum), "total": round(w.total, 1)} for w in comp],
            "baseline": {k: r1(clim.baseline[k]) for k in ("p10", "p25", "p50", "p75", "p90")},
            "coldest": comp[int(max(range(len(tot)), key=lambda i: tot[i]))].W if comp else None,
            "warmest": comp[int(min(range(len(tot)), key=lambda i: tot[i]))].W if comp else None,
            "latest": comp[-1].W if comp else None,
            "current": None,
            "today_slot": today_slot, "asof_slot": asof_slot,
            "ice": {"alpha": self.params.alpha, "lo": self.params.alpha_low, "hi": self.params.alpha_high},
            "thresholds": THRESHOLDS,
            "as_of": clim.as_of.isoformat() if clim.as_of else None, "today": clim.today.isoformat(),
        }
        if cur is not None:
            out["current"] = {"W": cur.W, "label": cur.label, "cum": r1(cur.cum), "last_slot": cur.last_slot,
                              "verified": f.get("verified"), "now": f.get("now"), "node": f.get("node"),
                              "node_used": bool(f.get("node_used"))}
        return _jsonify(out)

    def trend(self) -> Dict[str, Any]:
        key = []
        for s in SITES:
            try:
                key.append(nasa.cache_path(s.id, CACHE_DIR).stat().st_mtime_ns)
            except OSError:
                key.append(None)
        key = (tuple(key), self.today())
        with self.lock:
            hit = getattr(self, "_trend_cache", None)
            if hit and hit[0] == key:
                return hit[1]
        per = []
        for s in SITES:
            clim = self.climate(s.id)
            if clim is None or len(clim.completed) < TR.MIN_POINTS:
                continue
            a = TR.analyse_site(clim, self.params.alpha)
            a.update({"name": s.name, "short": s.short, "lat": s.lat})
            per.append(a)
        res = _jsonify({"has_data": bool(per), "sites": per, "compare": TR.compare_sites(per) if per else None,
                        "alpha": self.params.alpha, "n_sites": len(per)})
        with self.lock:
            self._trend_cache = (key, res)
        return res

    def raw_nasa(self, n: int = 14) -> Dict[str, Any]:
        clim = self.climate(self.site_id)
        if clim is None:
            return {"rows": []}
        n = max(1, min(int(n), 60))
        rows = []
        for i in range(n):
            day = clim.today - timedelta(days=n - 1 - i)
            t = clim.series.get(day)
            slot = F.slot_of(day)
            w = clim.winters.get(F.winter_of(day)) if F.winter_of(day) else None
            ok = t == t
            cum = float(w.cum[slot]) if (w is not None and slot is not None and ok and w.cum[slot] == w.cum[slot]) else None
            rows.append([day.isoformat(), (round(t, 2) if ok else None), (round(max(0.0, -t), 2) if ok else None),
                         (round(cum, 2) if cum is not None else None)])
        return {"site": self.site_id, "param": "T2M", "source": "NASA POWER daily", "rows": rows}

    def start_background(self) -> None:
        threading.Thread(target=self._housekeeping, daemon=True, name="housekeeping").start()
        threading.Thread(target=self.trend, daemon=True, name="trend-warmup").start()
        if not self.offline:
            threading.Thread(target=self._sync_loop, daemon=True, name="nasa-sync").start()

    def _housekeeping(self) -> None:
        while not self.stop_flag.wait(1.0):
            try:
                self.hub.tick()
            except Exception:
                log.exception("housekeeping tick failed")

    def sync_once(self) -> bool:
        self.sync["syncing"] = True
        self.sync["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ok_all = True
        order = [SITE_BY_ID[self.site_id]] + [s for s in SITES if s.id != self.site_id]
        try:
            for i, site in enumerate(order):
                try:
                    nasa.refresh_site(site, date.today())
                    self._climates.pop(site.id, None)
                except Exception as e:
                    ok_all = False
                    self.sync["error"] = str(e)[:200]
                    log.warning("sync %s failed: %s", site.id, e)
                    break
                if i < len(order) - 1:
                    time.sleep(1.0)
        finally:
            self.sync["syncing"] = False
        self.sync["online"] = ok_all
        if ok_all:
            self.sync["last_sync"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.sync["error"] = None
        self._snap_cache = None
        return ok_all

    def _sync_loop(self) -> None:
        self.stop_flag.wait(2.0)
        while not self.stop_flag.is_set():
            ok = False
            try:
                ok = self.sync_once()
            except Exception:
                log.exception("sync loop crashed once; continuing")
            self.stop_flag.wait(SYNC_OK_S if ok else SYNC_RETRY_S)

def _default(o: Any) -> Any:
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
    except ImportError:
        pass
    raise TypeError(f"not JSON serialisable: {type(o)}")
