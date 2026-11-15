import numpy as np
import pymannkendall as pmk
import pytest

from app import trend as T

YEARS = np.arange(1982, 2026, dtype=float)

def test_mk_matches_pymannkendall():
    rng = np.random.default_rng(0)
    for k in range(6):
        x = np.round(rng.normal(0, 3, 44) + 0.15 * k * np.arange(44), 0)
        s, z, p = T.mk_naive(x)
        r = pmk.original_test(x)
        assert s == r.s and z == pytest.approx(r.z, abs=1e-9) and p == pytest.approx(r.p, abs=1e-9)

def test_theil_sen_recovers_slope():
    x = 1000 - 5.0 * (YEARS - 1982)
    m, lo, hi, _ = T.sen(YEARS, x)
    assert m == pytest.approx(-5.0) and lo <= m <= hi

def test_clean_trend_is_robust():
    rng = np.random.default_rng(1)
    x = 1000 - 8.0 * (YEARS - 1982) + rng.normal(0, 25, len(YEARS))
    r = T.interrogate(YEARS, x, "u")
    assert r["verdict"] == "ROBUST" and r["score"] == 4 and r["direction"] == "down"
    assert r["slope_per"] == pytest.approx(-80, abs=25)
    assert r["ci_lo"] < r["slope_per"] < r["ci_hi"]

def test_pure_noise_is_no_trend():
    rng = np.random.default_rng(2)
    r = T.interrogate(YEARS, 1000 + rng.normal(0, 60, len(YEARS)), "u")
    assert r["verdict"] == "NO TREND" and not r["tests"]["T1_noise"]["pass"]

def test_late_step_change_is_fragile():
    rng = np.random.default_rng(3)
    x = np.where(YEARS < 2016, 1000.0, 860.0) + rng.normal(0, 25, len(YEARS))
    r = T.interrogate(YEARS, x, "u")
    assert r["verdict"] == "FRAGILE"
    assert r["tests"]["T1_noise"]["pass"] and not r["tests"]["T4_window"]["pass"]

def test_outlier_driven_trend_fails_outlier_test():
    x = np.full(len(YEARS), 1000.0) + np.random.default_rng(4).normal(0, 20, len(YEARS))
    x[:3] += 400
    r = T.interrogate(YEARS, x, "u")
    assert r["verdict"] in ("FRAGILE", "NO TREND")
    assert not (r["tests"]["T3_outlier"]["pass"] and r["tests"]["T4_window"]["pass"])

def test_degenerate_inputs_are_safe():
    assert T.interrogate(YEARS[:5], np.arange(5.0))["verdict"] == "TOO FEW"
    r = T.interrogate(YEARS, np.full(len(YEARS), 3.0))
    assert r["verdict"] == "NO TREND"
    x = np.arange(44.0); x[[3, 9]] = np.nan
    assert T.interrogate(YEARS, x)["n"] == 42

def test_narration_is_generated_from_numbers():
    rng = np.random.default_rng(1)
    r = T.interrogate(YEARS, 1000 - 8.0 * (YEARS - 1982) + rng.normal(0, 25, len(YEARS)), "°C-days")
    txt = T.explain(r, "Season cold", "Testville")
    assert "falling by" in txt and "Testville" in txt and f"{r['score']}/{r['of']}" in txt
    assert len(T.test_sentences(r)) == 4

def test_real_data_site_analysis_runs():
    from datetime import date
    from app import fdd as F, nasa
    s = nasa.read_cache("sudbury")
    if s is None:
        pytest.skip("no cache")
    a = T.analyse_site(F.SiteClimate("sudbury", s, s.as_of))
    assert a["season"]["verdict"] in ("ROBUST", "FRAGILE", "NO TREND") and len(a["years"]) >= 40
    assert a["iceup"]["30"]["n_reached"] <= a["iceup"]["30"]["n_winters"]
