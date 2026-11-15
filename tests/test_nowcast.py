from datetime import date, timedelta

import pytest

from app import fdd as F
from app.model import DEFAULT_PARAMS as P
from app.model import ice_cm
from app.nowcast import NodeDay, compute_nowcast
from conftest import synth_series

TODAY = date(2026, 12, 20)
AS_OF = date(2026, 12, 15)

@pytest.fixture(scope="module")
def climate():
    s = synth_series(end=TODAY, as_of=AS_OF, seed=3)
    return F.SiteClimate("x", s, TODAY)

def nc(climate, mode="outdoor", days=None, partial=None, frac=0.5, snow=0.0):
    return compute_nowcast(climate, TODAY, frac, mode, days or {}, partial, snow, P)

def full_days(start, end, mean, cov=1.0):
    out, d = {}, start
    while d <= end:
        out[d] = NodeDay(d, mean, cov)
        d += timedelta(days=1)
    return out

def test_verified_matches_nasa_cumulative(climate):
    n = nc(climate, mode="indoor_demo")
    cur = climate.winters[2027]
    assert n["fdd"]["verified"] == pytest.approx(cur.cum[F.slot_of(AS_OF)])
    assert n["as_of"] == AS_OF.isoformat() and n["gap_days"] == 5

def test_indoor_demo_excludes_node_entirely(climate):
    warm_room = full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), -20.0)
    n = nc(climate, mode="indoor_demo", days=warm_room, partial=NodeDay(TODAY, -20.0, 1.0))
    assert n["fdd"]["node"] == 0.0 and n["fdd"]["node_used"] is False
    assert n["fdd"]["now"] == n["fdd"]["verified"]
    assert n["fdd"]["compare_date"] == AS_OF.isoformat()
    assert n["bias"]["status"] == "indoor_demo"

def test_outdoor_fuses_node_days_after_as_of(climate):
    days = full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), -6.0)
    n = nc(climate, days=days, partial=NodeDay(TODAY, -4.0, 0.9), frac=0.5)
    assert n["fdd"]["node_days_used"] == 4 and n["fdd"]["node_days_excluded"] == 0
    assert n["fdd"]["node"] == pytest.approx(4 * 6.0 + 4.0 * 0.5)
    assert n["fdd"]["now"] == pytest.approx(n["fdd"]["verified"] + n["fdd"]["node"])
    assert n["fdd"]["compare_date"] == TODAY.isoformat()

def test_low_coverage_days_are_excluded_not_filled(climate):
    days = full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), -6.0)
    days[AS_OF + timedelta(days=2)] = NodeDay(AS_OF + timedelta(days=2), -30.0, 0.5)
    n = nc(climate, days=days, partial=None)
    assert n["fdd"]["node_days_excluded"] == 1 and n["fdd"]["lower_bound"] is True
    assert n["fdd"]["node"] == pytest.approx(3 * 6.0)

def test_node_warm_days_add_no_cold(climate):
    days = full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), +3.0)
    assert nc(climate, days=days)["fdd"]["node"] == 0.0

def test_node_days_before_as_of_are_never_double_counted(climate):
    days = full_days(AS_OF - timedelta(days=5), AS_OF, -10.0)
    n = nc(climate, days=days)
    assert n["fdd"]["node"] == 0.0 and n["fdd"]["node_used"] is False

def test_ice_now_uses_fused_fdd_and_snow(climate):
    days = full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), -8.0)
    n = nc(climate, days=days, snow=10.0)
    assert n["ice"]["cm"] == pytest.approx(ice_cm(n["fdd"]["now"], 10.0))
    assert n["ice"]["lo"] < n["ice"]["cm"] < n["ice"]["hi"]
    assert n["ice_normal"]["cm"] == pytest.approx(ice_cm(n["normal"]["p50"], 10.0))

def test_bias_needs_enough_overlap_then_reports_node_minus_nasa(climate):
    few = full_days(AS_OF - timedelta(days=1), AS_OF, -5.0)
    assert nc(climate, days=few)["bias"]["status"] == "collecting"
    overlap = {}
    for k in range(5):
        d = AS_OF - timedelta(days=k)
        overlap[d] = NodeDay(d, climate.series.get(d) + 1.4, 1.0)
    b = nc(climate, days=overlap)["bias"]
    assert b["status"] == "ok" and b["n"] == 5 and b["bias_c"] == pytest.approx(1.4)

def test_early_season_has_no_divide_by_zero():
    s = synth_series(end=date(2026, 11, 14), as_of=date(2026, 11, 11), const=6.0)
    c = F.SiteClimate("x", s, date(2026, 11, 14))
    n = compute_nowcast(c, date(2026, 11, 14), 0.5, "indoor_demo", {}, None, 5.0, P)
    assert n["phase"] == "none" and n["ice"]["cm"] == 0.0 and n["ice_normal"]["cm"] == 0.0
    assert n["delta"]["available"] is False and n["delta"]["pct_of_normal"] is None
    assert n["rank"]["tied"] == n["rank"]["n"]

def test_offseason_is_a_state_not_an_error():
    s = synth_series(end=date(2026, 7, 10), as_of=date(2026, 7, 7))
    c = F.SiteClimate("x", s, date(2026, 7, 10))
    n = compute_nowcast(c, date(2026, 7, 10), 0.5, "indoor_demo", {}, None, None, P)
    assert n["phase"] == "offseason"

def test_payload_is_strict_json(climate):
    import json
    json.dumps(nc(climate, days=full_days(AS_OF + timedelta(days=1), TODAY - timedelta(days=1), -6.0)), allow_nan=False)

def test_first_ice_dates_come_from_the_record(climate):
    fi = nc(climate)["first_ice"]["10"]
    assert fi["n_winters"] == 45 and fi["median"] is not None
    assert fi["p10"] <= fi["median"] <= fi["p90"]

def test_unknown_snow_widens_the_band_downward_never_upward(climate):
    days = {TODAY - timedelta(days=k): NodeDay(TODAY - timedelta(days=k), -10.0, 1.0) for k in range(1, 12)}
    known = nc(climate, days=days, snow=0.0)["ice"]
    unknown = nc(climate, days=days, snow=None)
    ice = unknown["ice"]
    assert unknown["snow"]["known"] is False
    assert ice["cm"] == pytest.approx(known["cm"]) and ice["hi"] == pytest.approx(known["hi"])
    assert ice["lo"] < known["lo"] * 0.55 and ice["lo"] > 0
