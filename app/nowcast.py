from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Optional

import numpy as np

from . import fdd as F
from .model import IceParams, ice_cm, ice_estimate

MIN_COVERAGE = 0.80
MIN_BIAS_DAYS = 3

@dataclass
class NodeDay:
    day: date
    mean_c: float
    coverage: float

def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None

def _interp(arr: np.ndarray, pos: float) -> float:
    if pos <= 0:
        return float(arr[0]) if len(arr) else float("nan")
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(arr) - 1)
    lo = min(lo, len(arr) - 1)
    frac = pos - math.floor(pos)
    return float(arr[lo] + frac * (arr[hi] - arr[lo]))

def _slot_date(climate: F.SiteClimate, slot: Optional[float], W_ref: int) -> Optional[str]:
    if slot is None or not math.isfinite(slot):
        return None
    d = F.date_of_slot(W_ref, int(round(slot)))
    if d is None:
        d = F.date_of_slot(W_ref, int(round(slot)) - 1)
    return d.isoformat() if d else None

def compute_nowcast(
    climate: F.SiteClimate,
    today: date,
    day_frac: float,
    mode: str,
    node_days: Optional[Dict[date, NodeDay]],
    today_partial: Optional[NodeDay],
    snow_cm: Optional[float],
    params: IceParams,
) -> Dict[str, Any]:
    as_of = climate.as_of
    cur = climate.current
    W_ref = climate.cur_W or (today.year + 1)
    outdoor = (mode == "outdoor")
    node_days = node_days or {}

    out: Dict[str, Any] = {
        "today": today.isoformat(),
        "as_of": as_of.isoformat() if as_of else None,
        "gap_days": ((today - as_of).days if as_of else None),
        "mode": mode,
    }

    first_ice = {}
    for cm in (10, 20, 30):
        st = climate.ice_up[cm]
        first_ice[str(cm)] = {
            "median": _slot_date(climate, st["median"], W_ref),
            "p10": _slot_date(climate, st["p10"], W_ref),
            "p90": _slot_date(climate, st["p90"], W_ref),
            "n_reached": st["n_reached"], "n_winters": st["n_winters"],
        }
    out["first_ice"] = first_ice
    out["n_winters"] = climate.baseline["n"]

    if cur is None or as_of is None:
        out.update({
            "phase": "offseason", "winter": {"W": None, "label": None, "slot": None},
            "fdd": {"verified": 0.0, "node": 0.0, "now": 0.0, "node_used": False,
                    "node_days_used": 0, "node_days_excluded": 0, "lower_bound": False},
            "normal": None, "rank": None, "ice": ice_estimate(0.0, snow_cm, params),
            "ice_normal": None, "delta": {"available": False, "cm": None, "pct_of_normal": None},
            "bias": _bias(climate, as_of, node_days, outdoor),
        })
        _jsonify(out)
        return out

    today_slot = F.slot_of(today)
    as_of_slot = F.slot_of(as_of)
    out["winter"] = {"W": cur.W, "label": cur.label, "slot": today_slot}

    if as_of_slot is None or F.winter_of(as_of) != cur.W:
        verified = 0.0
        as_of_slot = -1
    else:
        verified = float(cur.cum[as_of_slot]) if np.isfinite(cur.cum[as_of_slot]) else 0.0

    node_fdd, used, excluded = 0.0, 0, 0
    if outdoor:
        d = as_of + timedelta(days=1)
        while d < today:
            nd = node_days.get(d)
            if nd is not None and nd.coverage >= MIN_COVERAGE and math.isfinite(nd.mean_c):
                node_fdd += max(0.0, -nd.mean_c)
                used += 1
            else:
                excluded += 1
            d += timedelta(days=1)
        tp = today_partial
        if tp is not None and tp.coverage >= MIN_COVERAGE and math.isfinite(tp.mean_c):
            node_fdd += max(0.0, -tp.mean_c) * max(0.0, min(1.0, day_frac))
    node_used = outdoor and (used > 0 or today_partial is not None)
    fdd_now = verified + node_fdd

    if node_used and today_slot is not None:
        pos = max(0.0, (today_slot - 1) + max(0.0, min(1.0, day_frac)))
        cmp_date = today
    else:
        pos = float(as_of_slot)
        cmp_date = as_of
    b = climate.baseline
    if pos < 0 or b["n"] == 0:
        normal = {"p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "n": b["n"]}
        rank_pct, tied_n, less_n = None, 0, 0
    else:
        normal = {k: _interp(b[k], pos) for k in ("p10", "p25", "p50", "p75", "p90")}
        normal["n"] = b["n"]
        lo = int(math.floor(pos))
        samples = np.array([w.cum[min(lo, F.LAST_SLOT)] for w in climate.completed])
        rank_pct = F.percentile_rank(fdd_now, samples)
        tied_n = int((np.abs(samples - fdd_now) < 1e-9).sum())
        less_n = int((samples < fdd_now - 1e-9).sum())

    snow_known = snow_cm is not None and math.isfinite(snow_cm)
    snow_used = float(snow_cm) if snow_known else 0.0
    ice = ice_estimate(fdd_now, snow_used, params)
    ice_norm = ice_estimate(normal["p50"], snow_used, params)
    if not snow_known:
        for est, f in ((ice, fdd_now), (ice_norm, normal["p50"])):
            if f is not None and math.isfinite(f):
                est["lo"] = ice_cm(f, 1.0e6, params.alpha_low, params)
    ice_cm_v = ice["cm"]
    norm_cm = ice_norm["cm"]
    pct = (100.0 * ice_cm_v / norm_cm) if norm_cm >= 3.0 else None
    if ice_cm_v < 0.5:
        phase = "none"
    elif ice_cm_v < 10.0:
        phase = "forming"
    else:
        phase = "season"

    nasa_t = cur.tmean[as_of_slot] if as_of_slot >= 0 and np.isfinite(cur.tmean[as_of_slot]) else None

    out.update({
        "phase": phase,
        "fdd": {
            "verified": verified, "node": node_fdd, "now": fdd_now,
            "node_used": node_used, "node_days_used": used, "node_days_excluded": excluded,
            "lower_bound": bool(outdoor and excluded > 0),
            "compare_date": cmp_date.isoformat(), "compare_pos": pos,
        },
        "normal": normal,
        "rank": ({"pct": rank_pct, "n": b["n"], "tied": tied_n, "less": less_n} if rank_pct is not None else None),
        "snow": {"cm": snow_used if snow_known else None, "known": snow_known},
        "ice": ice,
        "ice_normal": ice_norm,
        "delta": {"available": pct is not None,
                  "cm": ice_cm_v - norm_cm,
                  "pct_of_normal": pct},
        "nasa_t": {"c": nasa_t, "date": as_of.isoformat()},
        "bias": _bias(climate, as_of, node_days, outdoor),
    })
    _jsonify(out)
    return out

def _bias(climate: F.SiteClimate, as_of: Optional[date], node_days: Dict[date, NodeDay], outdoor: bool) -> Dict[str, Any]:
    if not outdoor:
        return {"status": "indoor_demo", "n": 0, "bias_c": None}
    if as_of is None:
        return {"status": "collecting", "n": 0, "bias_c": None}
    diffs = []
    for d, nd in node_days.items():
        if d > as_of or nd.coverage < MIN_COVERAGE or not math.isfinite(nd.mean_c):
            continue
        nasa_v = climate.series.get(d)
        if math.isfinite(nasa_v):
            diffs.append(nd.mean_c - nasa_v)
    if len(diffs) < MIN_BIAS_DAYS:
        return {"status": "collecting", "n": len(diffs), "bias_c": None, "needed": MIN_BIAS_DAYS}
    return {"status": "ok", "n": len(diffs), "bias_c": float(np.mean(diffs)),
            "needed": MIN_BIAS_DAYS}

def _jsonify(o: Any) -> Any:
    if isinstance(o, dict):
        for k, v in list(o.items()):
            o[k] = _jsonify(v)
        return o
    if isinstance(o, (list, tuple)):
        return [_jsonify(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o
