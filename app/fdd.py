from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np

from .nasa import DailySeries

SLOTS = 182
FEB29_SLOT = 120
LAST_SLOT = SLOTS - 1
_REF0 = date(2023, 11, 1)
MAX_INTERP_GAP = 3
ALPHA_ICEUP = 2.7

def is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)

def winter_of(d: date) -> Optional[int]:
    if d.month >= 11:
        return d.year + 1
    if d.month <= 4:
        return d.year
    return None

def slot_of(d: date) -> Optional[int]:
    if winter_of(d) is None:
        return None
    ref_year = 2023 if d.month >= 11 else 2024
    return (date(ref_year, d.month, d.day) - _REF0).days

def date_of_slot(W: int, slot: int) -> Optional[date]:
    ref = _REF0 + timedelta(days=int(slot))
    if ref.month == 2 and ref.day == 29 and not is_leap(W):
        return None
    year = (W - 1) if ref.month >= 11 else W
    return date(year, ref.month, ref.day)

def winter_label(W: int) -> str:
    return f"{W - 1}–{W % 100:02d}"

def fdd_threshold_for_ice(cm: float, alpha: float = ALPHA_ICEUP) -> float:
    return (cm / alpha) ** 2

def interpolate_short_gaps(values: np.ndarray, max_gap: int = MAX_INTERP_GAP) -> np.ndarray:
    v = values.astype(float).copy()
    n = len(v)
    i = 0
    while i < n:
        if np.isnan(v[i]):
            j = i
            while j < n and np.isnan(v[j]):
                j += 1
            if i > 0 and j < n and (j - i) <= max_gap:
                v[i:j] = np.linspace(v[i - 1], v[j], j - i + 2)[1:-1]
            i = j
        else:
            i += 1
    return v

@dataclass
class Winter:
    W: int
    label: str
    tmean: np.ndarray
    fdd: np.ndarray
    cum: np.ndarray
    placeholder: np.ndarray
    last_slot: int
    n_missing: int

    @property
    def complete(self) -> bool:
        return self.last_slot >= LAST_SLOT and self.n_missing == 0

    @property
    def total(self) -> float:
        return float(self.cum[self.last_slot]) if self.last_slot >= 0 else 0.0

def _build_winter(vals: np.ndarray, series_start: date, W: int) -> Winter:
    d0 = date(W - 1, 11, 1)
    i0 = (d0 - series_start).days
    ndays = 182 if is_leap(W) else 181
    seg = np.full(ndays, np.nan)
    for k in range(ndays):
        idx = i0 + k
        if 0 <= idx < len(vals):
            seg[k] = vals[idx]
    t = np.full(SLOTS, np.nan)
    placeholder = np.zeros(SLOTS, dtype=bool)
    if ndays == 182:
        t[:] = seg
    else:
        t[:FEB29_SLOT] = seg[:FEB29_SLOT]
        t[FEB29_SLOT + 1:] = seg[FEB29_SLOT:]
        placeholder[FEB29_SLOT] = True
    real = ~placeholder
    have = ~np.isnan(t)
    last = int(np.flatnonzero(have)[-1]) if have.any() else -1
    n_missing = int((real & ~have & (np.arange(SLOTS) <= last)).sum()) if last >= 0 else 0
    fdd = np.where(have, np.maximum(0.0, -np.nan_to_num(t)), 0.0)
    cum = np.cumsum(fdd)
    if last >= 0:
        cum[last + 1:] = np.nan
    else:
        cum[:] = np.nan
    return Winter(W, winter_label(W), t, fdd, cum, placeholder, last, n_missing)

def build_winters(series: DailySeries) -> Dict[int, Winter]:
    vals = interpolate_short_gaps(series.values)
    out: Dict[int, Winter] = {}
    W = series.start.year + 1 if series.start <= date(series.start.year, 11, 1) else series.start.year + 2
    while date(W - 1, 11, 1) <= series.end:
        out[W] = _build_winter(vals, series.start, W)
        W += 1
    return out

def baseline_bands(winters: List[Winter]) -> Dict[str, np.ndarray]:
    if not winters:
        z = np.full(SLOTS, np.nan)
        return {"n": 0, "p10": z, "p25": z, "p50": z, "p75": z, "p90": z, "mean": z}
    M = np.vstack([w.cum for w in winters])
    p10, p25, p50, p75, p90 = np.percentile(M, [10, 25, 50, 75, 90], axis=0)
    return {"n": len(winters), "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90, "mean": M.mean(axis=0)}

def percentile_rank(value: float, samples: np.ndarray) -> float:
    s = np.asarray(samples, float)
    s = s[~np.isnan(s)]
    if len(s) == 0 or not np.isfinite(value):
        return float("nan")
    less = float((s < value).sum())
    eq = float((s == value).sum())
    return 100.0 * (less + 0.5 * eq) / len(s)

def first_slot_reaching(cum: np.ndarray, threshold: float) -> Optional[int]:
    idx = np.flatnonzero(cum >= threshold)
    return int(idx[0]) if len(idx) else None

class SiteClimate:

    def __init__(self, site_id: str, series: DailySeries, today: date):
        self.site_id = site_id
        self.series = series
        self.today = today
        self.as_of: Optional[date] = series.as_of
        self.winters = build_winters(series)
        self.cur_W: Optional[int] = winter_of(today)
        self.completed: List[Winter] = [w for W, w in sorted(self.winters.items())
                                        if w.complete and W != self.cur_W]
        self.baseline = baseline_bands(self.completed)
        self.current: Optional[Winter] = self.winters.get(self.cur_W) if self.cur_W else None
        self.ice_up: Dict[int, Dict[str, object]] = {}
        for cm in (10, 20, 30):
            thr = fdd_threshold_for_ice(cm)
            slots = [first_slot_reaching(w.cum, thr) for w in self.completed]
            reached = [s for s in slots if s is not None]
            if reached:
                q = np.percentile(reached, [10, 50, 90])
                stat = {"p10": float(q[0]), "median": float(q[1]), "p90": float(q[2])}
            else:
                stat = {"p10": None, "median": None, "p90": None}
            stat["n_reached"] = len(reached)
            stat["n_winters"] = len(self.completed)
            stat["by_winter"] = {w.W: s for w, s in zip(self.completed, slots)}
            self.ice_up[cm] = stat
