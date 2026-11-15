from datetime import date

import numpy as np
import pytest

from app import fdd as F
from conftest import synth_series

def test_slot_alignment_by_calendar_date():
    assert F.slot_of(date(2025, 11, 1)) == 0
    assert F.slot_of(date(2026, 4, 30)) == 181
    assert F.slot_of(date(2024, 2, 29)) == F.FEB29_SLOT == 120
    assert F.slot_of(date(2024, 3, 1)) == F.slot_of(date(2025, 3, 1)) == 121
    assert F.slot_of(date(2025, 7, 4)) is None and F.winter_of(date(2025, 7, 4)) is None

def test_date_of_slot_roundtrip_and_placeholder():
    for W in (2023, 2024, 2025):
        for s in range(F.SLOTS):
            d = F.date_of_slot(W, s)
            if d is None:
                assert s == F.FEB29_SLOT and not F.is_leap(W)
            else:
                assert F.slot_of(d) == s and F.winter_of(d) == W

def test_constant_cold_leap_vs_nonleap():
    s = synth_series(const=-10.0, end=date(2026, 5, 15))
    ws = F.build_winters(s)
    assert ws[2024].cum[-1] == pytest.approx(10 * 182)
    assert ws[2025].cum[-1] == pytest.approx(10 * 181)
    w = ws[2025]
    assert w.placeholder[F.FEB29_SLOT] and w.fdd[F.FEB29_SLOT] == 0
    assert w.cum[F.FEB29_SLOT] == w.cum[F.FEB29_SLOT - 1]
    assert w.complete and ws[2024].complete

def test_warm_days_contribute_zero():
    s = synth_series(const=+3.0, end=date(2026, 5, 15))
    w = F.build_winters(s)[2025]
    assert w.cum[-1] == 0.0 and w.fdd.sum() == 0.0

def test_short_gap_interpolated_long_gap_flagged():
    s = synth_series(const=-10.0, end=date(2026, 5, 15))
    i2 = (date(2024, 12, 10) - s.start).days
    s.values[i2:i2 + 2] = np.nan
    i5 = (date(2025, 1, 10) - s.start).days
    s.values[i5:i5 + 5] = np.nan
    w = F.build_winters(s)[2025]
    assert w.n_missing == 5 and not w.complete
    assert w.cum[-1] == pytest.approx(10 * 181 - 50)
    assert not np.isnan(w.tmean[F.slot_of(date(2024, 12, 10))])

def test_current_winter_is_partial():
    s = synth_series(end=date(2026, 11, 14), as_of=date(2026, 11, 11))
    ws = F.build_winters(s)
    cur = ws[2027]
    assert cur.last_slot == F.slot_of(date(2026, 11, 11)) == 10
    assert np.isnan(cur.cum[11]) and not cur.complete

def test_baseline_bands_ordered_and_exclude_current():
    s = synth_series(end=date(2026, 11, 14), as_of=date(2026, 11, 11))
    c = F.SiteClimate("x", s, date(2026, 11, 14))
    assert c.cur_W == 2027 and 2027 not in [w.W for w in c.completed]
    b = c.baseline
    assert b["n"] == 45
    for i in range(F.SLOTS):
        assert b["p10"][i] <= b["p25"][i] <= b["p50"][i] <= b["p75"][i] <= b["p90"][i]
    assert np.all(np.diff(b["p50"]) >= -1e-9)

def test_percentile_rank_midrank_ties():
    assert F.percentile_rank(0.0, np.zeros(10)) == pytest.approx(50.0)
    assert F.percentile_rank(5.0, np.array([1, 2, 3, 4.0])) == 100.0
    assert F.percentile_rank(0.0, np.array([1, 2, 3, 4.0])) == 0.0

def test_ice_up_threshold():
    assert F.fdd_threshold_for_ice(27.0, 2.7) == pytest.approx(100.0)

def test_real_nasa_cache_sanity():
    from app import nasa
    ser = nasa.read_cache("mississauga")
    if ser is None:
        pytest.skip("no NASA cache yet")
    c = F.SiteClimate("mississauga", ser, ser.as_of)
    assert c.baseline["n"] >= 40
    totals = [w.total for w in c.completed]
    assert 100 < np.median(totals) < 1500
