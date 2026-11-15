from __future__ import annotations
import numpy as np
from scipy import stats
import pymannkendall as pmk

ALPHA = 0.05
WINDOW_MIN_FRAC = 0.40
WINDOW_PASS_FRAC = 0.60
LOO_SIG_FRAC = 0.90

def mk_naive(x):
    x = np.asarray(x, float)
    n = len(x)
    diff = x[None, :] - x[:, None]
    s = int(np.sign(diff[np.triu_indices(n, 1)]).sum())
    _, counts = np.unique(x, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    z = 0.0 if s == 0 else (s - np.sign(s)) / np.sqrt(var)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return s, float(z), float(p)

def sen(t, x):
    r = stats.theilslopes(np.asarray(x, float), np.asarray(t, float), 0.95)
    return float(r[0]), float(r[2]), float(r[3])

def lag1(t, x):
    m, _, _ = sen(t, x)
    t = np.asarray(t, float); x = np.asarray(x, float)
    res = x - (np.median(x - m * t) + m * t)
    res = res - res.mean()
    d = np.dot(res, res)
    return float(np.dot(res[:-1], res[1:]) / d) if d > 0 else 0.0

def hamed_rao_p(x):
    return float(pmk.hamed_rao_modification_test(np.asarray(x, float)).p)

def loo_test(t, x):
    t = np.asarray(t, float); x = np.asarray(x, float)
    base_sign = np.sign(sen(t, x)[0])
    same, sig = 0, 0
    for i in range(len(x)):
        m = np.ones(len(x), bool); m[i] = False
        s = sen(t[m], x[m])[0]
        p = mk_naive(x[m])[2]
        same += (np.sign(s) == base_sign)
        sig += (p < ALPHA)
    n = len(x)
    return {"sign_kept": same / n, "still_sig": sig / n,
            "pass": (same == n) and (sig / n >= LOO_SIG_FRAC)}

def window_grid(t, x, min_len=None):
    n = len(x)
    min_len = min_len or max(10, int(round(WINDOW_MIN_FRAC * n)))
    out = []
    for i in range(0, n - min_len + 1):
        for j in range(i + min_len, n + 1):
            xs = x[i:j]
            m = sen(t[i:j], xs)[0]
            p = mk_naive(xs)[2]
            out.append((i, j - 1, m, p))
    return out, min_len

def window_test(t, x):
    t = np.asarray(t, float); x = np.asarray(x, float)
    base_sign = np.sign(sen(t, x)[0])
    grid, min_len = window_grid(t, x)
    ok = sum(1 for (_, _, m, p) in grid if p < ALPHA and np.sign(m) == base_sign)
    opp = [(int(t[i]), int(t[j])) for (i, j, m, p) in grid
           if p < ALPHA and np.sign(m) == -base_sign]
    frac = ok / len(grid)
    return {"agree_frac": frac, "n_windows": len(grid), "min_len": min_len,
            "opposite_sig_windows": opp, "pass": frac >= WINDOW_PASS_FRAC}

def interrogate(t, x, units="", scale=1.0, per=10.0, corroboration=None):
    t = np.asarray(t, float); x = np.asarray(x, float)
    ok = ~np.isnan(x); t, x = t[ok], x[ok]
    n = len(x)
    s, z, p1 = mk_naive(x)
    m, lo, hi = sen(t, x)
    p2 = hamed_rao_p(x)
    r1 = lag1(t, x)
    loo = loo_test(t, x)
    win = window_test(t, x)
    tests = {
        "T1_noise":   {"pass": p1 < ALPHA, "p": p1},
        "T2_memory":  {"pass": p2 < ALPHA, "p": p2, "lag1": r1},
        "T3_outlier": loo,
        "T4_window":  win,
    }
    if corroboration is not None:
        t2, x2 = corroboration
        m2 = sen(t2, x2)[0]; p_c = mk_naive(x2)[2]
        tests["T5_corroboration"] = {"pass": (p_c < ALPHA) and np.sign(m2) == np.sign(m), "p": p_c}
    passed = sum(v["pass"] for v in tests.values())
    total = len(tests)
    if not tests["T1_noise"]["pass"]:
        verdict = "NO TREND"
    elif passed == total:
        verdict = "ROBUST"
    else:
        verdict = "FRAGILE"
    return {
        "n": n, "t0": int(t[0]), "t1": int(t[-1]),
        "slope_per": m * per * scale, "ci_lo": lo * per * scale, "ci_hi": hi * per * scale,
        "total_change": m * (t[-1] - t[0]) * scale,
        "direction": "up" if m > 0 else "down" if m < 0 else "flat",
        "tests": tests, "score": passed, "of": total, "verdict": verdict,
        "units": units,
    }

def deseasonalize(x, period=12):
    x = np.asarray(x, float)
    clim = np.array([np.nanmean(x[i::period]) for i in range(period)])
    return x - np.tile(clim, len(x) // period + 1)[: len(x)]

def annual_means(x, period=12):
    x = np.asarray(x, float)
    k = len(x) // period
    return x[: k * period].reshape(k, period).mean(axis=1)

def explain(r, what, where):
    u, span = r["units"], f"{r['t0']}-{r['t1']}"
    ci = f"95% CI {r['ci_lo']:+.2f} to {r['ci_hi']:+.2f}"
    tail = f"Tests passed: {r['score']}/{r['of']}."
    if r["verdict"] == "NO TREND":
        return (f"{what}, {where}, {span}: no detectable trend. Best estimate "
                f"{r['slope_per']:+.2f} {u} per decade ({ci}), which cannot be told apart "
                f"from natural variability. {tail}")
    d = {"up": "rising", "down": "falling", "flat": "flat"}[r["direction"]]
    sig = {"ROBUST": "and the trend survives every test we throw at it.",
           "FRAGILE": "but the trend does NOT survive every test, so treat it with caution."}[r["verdict"]]
    return (f"{what}, {where}, {span}: {d} by {abs(r['slope_per']):.2f} {u} per decade "
            f"({ci}), {sig} {tail}")
