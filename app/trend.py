from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats

import pymannkendall as pmk

ALPHA = 0.05
WINDOW_MIN_FRAC = 0.40
WINDOW_PASS_FRAC = 0.60
LOO_SIG_FRAC = 0.90
MIN_POINTS = 15

def mk_naive(x):
    x = np.asarray(x, float)
    n = len(x)
    diff = x[None, :] - x[:, None]
    s = int(np.sign(diff[np.triu_indices(n, 1)]).sum())
    _, counts = np.unique(x, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    z = 0.0 if (s == 0 or var <= 0) else (s - np.sign(s)) / np.sqrt(var)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return s, float(z), float(p)

def sen(t, x):
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    r = stats.theilslopes(x, t, 0.95)
    return float(r[0]), float(r[2]), float(r[3]), float(r[1])

def lag1(t, x):
    m, _, _, _ = sen(t, x)
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    res = x - (np.median(x - m * t) + m * t)
    res = res - res.mean()
    d = np.dot(res, res)
    return float(np.dot(res[:-1], res[1:]) / d) if d > 0 else 0.0

def hamed_rao_p(x) -> float:
    return float(pmk.hamed_rao_modification_test(np.asarray(x, float)).p)

def loo_test(t, x):
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    base = np.sign(sen(t, x)[0])
    same = sig = 0
    for i in range(len(x)):
        m = np.ones(len(x), bool)
        m[i] = False
        same += np.sign(sen(t[m], x[m])[0]) == base
        sig += mk_naive(x[m])[2] < ALPHA
    n = len(x)
    return {"sign_kept": same / n, "still_sig": sig / n, "pass": bool(same == n and sig / n >= LOO_SIG_FRAC)}

def window_test(t, x):
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    base = np.sign(sen(t, x)[0])
    n = len(x)
    min_len = max(10, int(round(WINDOW_MIN_FRAC * n)))
    ok = opp = total = 0
    for i in range(0, n - min_len + 1):
        for j in range(i + min_len, n + 1):
            m = sen(t[i:j], x[i:j])[0]
            p = mk_naive(x[i:j])[2]
            total += 1
            if p < ALPHA:
                if np.sign(m) == base:
                    ok += 1
                elif np.sign(m) == -base:
                    opp += 1
    frac = ok / total if total else 0.0
    return {"agree_frac": frac, "n_windows": total, "min_len": min_len, "n_opposite": opp,
            "pass": bool(frac >= WINDOW_PASS_FRAC)}

def interrogate(t, x, units: str = "", per: float = 10.0) -> Dict[str, Any]:
    t = np.asarray(t, float)
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    t, x = t[ok], x[ok]
    n = len(x)
    if n < MIN_POINTS:
        return {"verdict": "TOO FEW", "n": int(n), "units": units, "score": 0, "of": 4, "tests": {}}
    if np.ptp(x) == 0:
        return {"n": int(n), "t0": int(t[0]), "t1": int(t[-1]), "slope_per": 0.0, "ci_lo": 0.0, "ci_hi": 0.0,
                "total_change": 0.0, "direction": "flat", "score": 0, "of": 4, "verdict": "NO TREND", "units": units,
                "tests": {"T1_noise": {"pass": False, "p": 1.0}, "T2_memory": {"pass": False, "p": 1.0, "lag1": 0.0},
                          "T3_outlier": {"pass": False, "sign_kept": 0.0, "still_sig": 0.0},
                          "T4_window": {"pass": False, "agree_frac": 0.0, "n_windows": 0, "min_len": 0, "n_opposite": 0}}}
    _, _, p1 = mk_naive(x)
    m, lo, hi, icpt = sen(t, x)
    try:
        p2 = hamed_rao_p(x)
    except Exception:
        p2 = 1.0
    tests = {
        "T1_noise": {"pass": bool(p1 < ALPHA), "p": p1},
        "T2_memory": {"pass": bool(p2 < ALPHA), "p": p2, "lag1": lag1(t, x)},
        "T3_outlier": loo_test(t, x),
        "T4_window": window_test(t, x),
    }
    passed = sum(1 for v in tests.values() if v["pass"])
    verdict = "NO TREND" if not tests["T1_noise"]["pass"] else ("ROBUST" if passed == len(tests) else "FRAGILE")
    return {
        "n": int(n), "t0": int(t[0]), "t1": int(t[-1]),
        "slope_per": m * per, "ci_lo": lo * per, "ci_hi": hi * per,
        "slope": m, "intercept": icpt,
        "total_change": m * (t[-1] - t[0]),
        "direction": "up" if m > 0 else "down" if m < 0 else "flat",
        "tests": tests, "score": passed, "of": len(tests), "verdict": verdict, "units": units,
    }

def explain(r: Dict[str, Any], what: str, where: str) -> str:
    if r.get("verdict") == "TOO FEW":
        return f"{what}, {where}: only {r['n']} usable winters — too few to test for a trend."
    u, span = r["units"], f"{r['t0']}–{r['t1']}"
    ci = f"95% CI {r['ci_lo']:+.1f} to {r['ci_hi']:+.1f}"
    tail = f"Tests passed: {r['score']}/{r['of']}."
    if r["verdict"] == "NO TREND":
        return (f"{what}, {where}, {span}: no detectable trend. Best estimate {r['slope_per']:+.1f} {u} per decade "
                f"({ci}), which cannot be told apart from natural variability. {tail}")
    d = {"up": "rising", "down": "falling", "flat": "flat"}[r["direction"]]
    sig = {"ROBUST": "and the trend survives every test we throw at it.",
           "FRAGILE": "but the trend does NOT survive every test, so treat it with caution."}[r["verdict"]]
    return f"{what}, {where}, {span}: {d} by {abs(r['slope_per']):.1f} {u} per decade ({ci}), {sig} {tail}"

def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"

def test_sentences(r: Dict[str, Any]) -> List[Dict[str, Any]]:
    T = r.get("tests") or {}
    if not T:
        return []
    t1, t2, t3, t4 = T["T1_noise"], T["T2_memory"], T["T3_outlier"], T["T4_window"]
    return [
        {"id": "T1", "name": "Noise", "pass": t1["pass"], "p": t1["p"],
         "q": "Could chance alone produce this?", "a": f"Mann–Kendall p = {_p(t1['p'])} (needs < 0.05)."},
        {"id": "T2", "name": "Memory", "pass": t2["pass"], "p": t2["p"],
         "q": "Does it hold once year-to-year memory is accounted for?", "a": f"Autocorrelation-corrected p = {_p(t2['p'])} (needs < 0.05)."},
        {"id": "T3", "name": "Outlier", "pass": t3["pass"], "p": None,
         "q": "Does one odd winter carry the result?", "a": f"Dropping each winter in turn: sign kept in {t3['sign_kept']:.0%}, still significant in {t3['still_sig']:.0%} of runs."},
        {"id": "T4", "name": "Window", "pass": t4["pass"], "p": None,
         "q": "Is it there in every stretch of the record, or only overall?", "a": f"{t4['agree_frac']:.0%} of {t4['n_windows']} sub-periods (≥ {t4['min_len']} winters) show the same significant trend (needs 60%)."},
    ]

def _lite(r: Dict[str, Any]) -> Dict[str, Any]:
    keep = {k: v for k, v in r.items() if k != "tests"}
    keep["tests"] = test_sentences(r)
    return keep

def analyse_site(climate, alpha_bare: float = 2.7) -> Dict[str, Any]:
    from . import fdd as F

    ws = [w for w in climate.completed]
    years = np.array([w.W for w in ws], float)
    totals = np.array([w.total for w in ws], float)
    mean, std = float(totals.mean()), float(totals.std()) or 1.0
    z = (totals - mean) / std
    from .config import SITE_BY_ID
    name = SITE_BY_ID[climate.site_id].short if climate.site_id in SITE_BY_ID else climate.site_id

    season = interrogate(years, totals, "°C-days", 10.0)
    out: Dict[str, Any] = {
        "site_id": name,
        "years": [int(y) for y in years], "labels": [w.label for w in ws],
        "season_fdd": [round(float(v), 1) for v in totals],
        "z": [round(float(v), 2) for v in z], "mean": mean, "std": std,
        "season": _lite(season),
    }
    if season.get("tests"):
        out["season"]["rel_per_decade"] = [100 * season["slope_per"] / mean, 100 * season["ci_lo"] / mean, 100 * season["ci_hi"] / mean]
    out["iceup"] = {}
    for cm in (20, 30):
        slots = climate.ice_up[cm]["by_winter"]
        pts = [(w.W, slots[w.W]) for w in ws if slots.get(w.W) is not None]
        t = np.array([p[0] for p in pts], float)
        x = np.array([p[1] for p in pts], float)
        r = interrogate(t, x, "days", 10.0)
        out["iceup"][str(cm)] = {
            "cm": cm, "years": [int(v) for v in t], "slot": [int(v) for v in x],
            "n_reached": len(pts), "n_winters": len(ws), "result": _lite(r),
            "text": explain(r, f"Date bare-ice growth reaches {cm} cm", name),
        }
    out["text"] = explain(season, "Freezing degree-days (Nov–Apr)", name)
    if len(ws) >= 20:
        a, b = ws[:10], ws[-10:]
        ice = lambda grp: float(np.mean([alpha_bare * np.sqrt(w.total) for w in grp]))
        lab = lambda g: f"{g[0].W - 1}–{str(g[0].W)[2:]} to {g[-1].W - 1}–{str(g[-1].W)[2:]}"
        out["decades"] = {"first": {"label": lab(a), "ice_cm": ice(a)}, "last": {"label": lab(b), "ice_cm": ice(b)}}
    return out

def compare_sites(per_site: List[Dict[str, Any]]) -> Dict[str, Any]:
    rel = []
    for s in per_site:
        r = s["season"].get("rel_per_decade")
        if r:
            rel.append((s["site_id"], r[0], r[1], r[2]))
    separated = []
    for i in range(len(rel)):
        for j in range(i + 1, len(rel)):
            a, b = rel[i], rel[j]
            if a[3] < b[2] or b[3] < a[2]:
                separated.append((a[0], b[0]))
    return {"rel": rel, "separated_pairs": separated, "gradient_supported": bool(separated)}
