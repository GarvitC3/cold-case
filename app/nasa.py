from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import CACHE_DIR, Site

log = logging.getLogger("coldcase.nasa")

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
RECORD_START = date(1981, 11, 1)
FILL = -999.0
USER_AGENT = "cold-case/2.0 (NASA Space Apps Challenge prototype)"

def build_url(lat: float, lon: float, start: date, end: date) -> str:
    return (
        f"{POWER_URL}?parameters=T2M&community=AG&longitude={lon}&latitude={lat}"
        f"&start={start:%Y%m%d}&end={end:%Y%m%d}&format=JSON"
    )

def _ymd(s: str) -> date:
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))

@dataclass
class DailySeries:

    start: date
    values: np.ndarray
    meta: Dict[str, Any]

    @property
    def end(self) -> date:
        return self.start + timedelta(days=len(self.values) - 1)

    @property
    def as_of(self) -> Optional[date]:
        idx = np.flatnonzero(~np.isnan(self.values))
        return (self.start + timedelta(days=int(idx[-1]))) if len(idx) else None

    def get(self, d: date) -> float:
        i = (d - self.start).days
        if 0 <= i < len(self.values):
            return float(self.values[i])
        return float("nan")

    def truncated(self, last_day: date) -> "DailySeries":
        n = (last_day - self.start).days + 1
        n = max(0, min(n, len(self.values)))
        meta = dict(self.meta)
        meta["truncated_for_dev_clock"] = True
        return DailySeries(self.start, self.values[:n].copy(), meta)

def parse_power_json(payload: Dict[str, Any]) -> Dict[str, float]:
    try:
        t2m = payload["properties"]["parameter"]["T2M"]
    except (KeyError, TypeError) as e:
        raise ValueError(f"unexpected POWER response shape: {e}")
    if not isinstance(t2m, dict) or not t2m:
        raise ValueError("POWER response had no T2M values")
    return t2m

def series_from_map(t2m: Dict[str, float], start: date) -> np.ndarray:
    keys = sorted(t2m)
    end = _ymd(keys[-1])
    n = (end - start).days + 1
    arr = np.full(n, np.nan)
    for k in keys:
        try:
            i = (_ymd(k) - start).days
            v = float(t2m[k])
        except (ValueError, TypeError):
            continue
        if 0 <= i < n and np.isfinite(v) and v > -900:
            arr[i] = v
    return arr

def fetch_power(lat: float, lon: float, start: date, end: date,
                timeout: float = 60.0, retries: int = 4) -> Dict[str, Any]:
    url = build_url(lat, lon, start, end)
    delay = 2.0
    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.load(r)
            parse_power_json(payload)
            payload["_source_url"] = url
            return payload
        except urllib.error.HTTPError as e:
            last = e
            retryable = e.code in (408, 425, 429) or e.code >= 500
            log.warning("POWER HTTP %s (attempt %d/%d)", e.code, attempt, retries)
            if not retryable:
                break
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            last = e
            log.warning("POWER fetch failed: %s (attempt %d/%d)", e, attempt, retries)
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"POWER fetch failed after {retries} attempts: {last}")

def cache_path(site_id: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"power_{site_id}.json"

def _atomic_write(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        try:
            os.replace(path, path.with_suffix(".json.bak"))
        except OSError:
            pass
    os.replace(tmp, path)

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict) and isinstance(obj.get("t2m"), list) and obj.get("start"):
            return obj
    except (OSError, ValueError):
        pass
    return None

def read_cache(site_id: str, cache_dir: Path = CACHE_DIR) -> Optional[DailySeries]:
    p = cache_path(site_id, cache_dir)
    obj = _load_json(p)
    if obj is None:
        obj = _load_json(p.with_suffix(".json.bak"))
        if obj is not None:
            log.warning("cache for %s was corrupt; using last-good backup", site_id)
    if obj is None:
        return None
    start = _ymd(obj["start"])
    vals = np.array([np.nan if v is None else float(v) for v in obj["t2m"]], dtype=float)
    meta = {k: obj.get(k) for k in
            ("site", "lat", "lon", "fetched_at", "source_url", "as_of_date", "missing_count",
             "api_version", "sources", "param", "community")}
    return DailySeries(start, vals, meta)

def write_cache(site: Site, series: DailySeries, source_url: str, api_meta: Dict[str, Any],
                cache_dir: Path = CACHE_DIR) -> Dict[str, Any]:
    as_of = series.as_of
    miss = int(np.isnan(series.values).sum())
    obj = {
        "site": site.id, "lat": site.lat, "lon": site.lon,
        "param": "T2M", "community": "AG",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": source_url,
        "api_version": (api_meta.get("api") or {}).get("version"),
        "sources": api_meta.get("sources"),
        "start": f"{series.start:%Y%m%d}",
        "as_of_date": as_of.isoformat() if as_of else None,
        "missing_count": miss,
        "t2m": [None if np.isnan(v) else round(float(v), 2) for v in series.values],
    }
    _atomic_write(cache_path(site.id, cache_dir), obj)
    return obj

def refresh_site(site: Site, today: Optional[date] = None, cache_dir: Path = CACHE_DIR,
                 full: bool = False) -> DailySeries:
    today = today or date.today()
    existing = None if full else read_cache(site.id, cache_dir)
    if existing is None or existing.as_of is None:
        payload = fetch_power(site.lat, site.lon, RECORD_START, today)
        t2m = parse_power_json(payload)
        arr = series_from_map(t2m, RECORD_START)
        series = DailySeries(RECORD_START, arr, {})
    else:
        start = max(RECORD_START, existing.as_of - timedelta(days=21))
        payload = fetch_power(site.lat, site.lon, start, today)
        t2m = parse_power_json(payload)
        new = series_from_map(t2m, start)
        n_total = max(len(existing.values), (start - existing.start).days + len(new))
        merged = np.full(n_total, np.nan)
        merged[: len(existing.values)] = existing.values
        off = (start - existing.start).days
        seg = merged[off: off + len(new)]
        ok = ~np.isnan(new)
        seg[ok] = new[ok]
        merged[off: off + len(new)] = seg
        series = DailySeries(existing.start, merged, {})
    write_cache(site, series, payload["_source_url"], payload.get("header", {}), cache_dir)
    return read_cache(site.id, cache_dir) or series
