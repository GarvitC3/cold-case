import math

import numpy as np
import pytest

from app import model as M

def test_usace_conversion_arithmetic():
    assert 0.8 * 2.54 * math.sqrt(1.8) == pytest.approx(2.726, abs=0.005)
    assert 0.5 * 2.54 * math.sqrt(1.8) == pytest.approx(1.70, abs=0.01)
    assert 0.7 * 2.54 * math.sqrt(1.8) == pytest.approx(2.39, abs=0.01)

def test_bare_ice_100_fdd_is_27cm():
    assert M.ice_cm(100.0, 0.0) == pytest.approx(27.0)

def test_snow_reduces_growth_monotonic_and_smooth():
    depths = np.arange(0, 60.5, 0.5)
    h = np.array([M.ice_cm(200.0, d) for d in depths])
    assert np.all(np.diff(h) < 0)
    p = M.DEFAULT_PARAMS
    max_slope = p.alpha * math.sqrt(200.0) * (1 - p.snow_floor) / p.snow_lambda_cm
    assert np.max(np.abs(np.diff(h))) <= max_slope * 0.5 + 1e-9
    assert np.all(np.diff(h, 2) > 0)
    assert h.min() > 0

def test_deep_snow_roughly_halves_growth():
    bare = M.ice_cm(200.0, 0.0)
    for d in (25.0, 30.0, 40.0):
        assert 0.50 <= M.ice_cm(200.0, d) / bare <= 0.60
    assert M.snow_factor(1000) == pytest.approx(0.5, abs=1e-6)

def test_modest_snow_is_not_absurd():
    assert 0.65 <= M.snow_factor(10.0) <= 0.80
    for d in (3.0, 10.0, 17.0):
        assert 0.62 <= M.snow_factor(d) <= 0.92

def test_band_contains_central_and_orders():
    e = M.ice_estimate(212.0, 9.0)
    assert e["lo"] < e["cm"] < e["hi"]
    assert e["cm"] == pytest.approx(M.DEFAULT_PARAMS.alpha * e["factor"] * math.sqrt(212.0))

def test_monotone_non_decreasing_in_fdd():
    f = np.linspace(0, 2000, 400)
    h = M.ice_cm(f, 12.0)
    assert np.all(np.diff(h) >= 0)

def test_nan_and_negative_inputs_are_safe():
    assert math.isnan(M.ice_cm(float("nan"), 3.0))
    assert M.ice_cm(-5.0, 0.0) == 0.0
    assert M.snow_factor(None) == 1.0 and M.snow_factor(float("nan")) == 1.0 and M.snow_factor(-4) == 1.0
    e = M.ice_estimate(None, 5)
    assert math.isnan(e["cm"])

def test_inverse():
    for snow in (0.0, 8.0, 25.0):
        need = M.fdd_for_ice(20.0, snow)
        assert M.ice_cm(need, snow) == pytest.approx(20.0)
