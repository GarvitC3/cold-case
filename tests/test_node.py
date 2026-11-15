import math
import time

import pytest

from app import node as N
from app.store import Store

def P(line):
    return N.parse_line(line, 1000.0)

def test_clean_line():
    r = P('{"temp_c":21.40,"rh":41.00,"dist_cm":36.17}')
    assert (r.temp_c, r.rh, r.dist_cm) == (21.4, 41.0, 36.17)
    assert r.temp_state == "ok" and r.dist_state == "ok"

@pytest.mark.parametrize("line", [
    "", "\x00\xff\xfe garbage", "ets Jan  8 2013,rst cause:2", "{", "}", "{}{", '{"temp_c":',
    '{"temp_c":21.4,"rh":', "[1,2,3]", "null", '"just a string"', "{'temp_c': 1}", "{{{{{{{{{{{",
])
def test_garbage_never_raises_and_yields_nothing_or_empty(line):
    r = P(line)
    assert r is None or (r.temp_c is None and r.dist_cm is None)

def test_boot_garbage_prefix_and_trailing_noise():
    r = P('\x07\x00ready>>{"temp_c":20.5,"rh":40,"dist_cm":30.0}\r\n')
    assert r.temp_c == 20.5 and r.dist_cm == 30.0

def test_null_nan_missing_extra_and_reordered_keys():
    r = P('{"dist_cm":null,"rh":NaN,"temp_c":nan,"extra":[1,2],"v":2}')
    assert r.temp_c is None and r.rh is None and r.dist_cm is None
    assert r.temp_state == "missing" and r.dist_state == "missing"
    r = P('{"dist_cm":40.5,"temp_c":19.0}')
    assert r.rh is None and r.dist_cm == 40.5
    r = P('{"temp_c":inf,"rh":-inf,"dist_cm":Infinity}')
    assert r.temp_c is None and r.rh is None and r.dist_cm is None

@pytest.mark.parametrize("d", [0, -1, 0.5, 401, 9999, "x"])
def test_impossible_distances_are_rejected(d):
    r = P('{"temp_c":20,"rh":40,"dist_cm":%s}' % (d if not isinstance(d, str) else '"x"'))
    assert r.dist_cm is None and r.dist_state in ("out_of_range", "missing")

def test_dht11_cannot_read_winter():
    for t in (0.0, -0.1, -12.0, -40.0, 50.0, 85.0):
        r = P('{"temp_c":%s,"rh":50,"dist_cm":40}' % t)
        assert r.temp_c is None and r.temp_state == "out_of_range", t
    assert P('{"temp_c":1.0,"rh":50,"dist_cm":40}').temp_c == 1.0

def test_ds18b20_range_and_sentinels():
    ok = P('{"temp_c":-18.5,"rh":null,"dist_cm":40,"temp_src":"ds18b20","v":2}')
    assert ok.temp_c == -18.5 and ok.temp_src == "ds18b20" and ok.temp_state == "ok"
    for bad in (85.0, -127.0, -60.0, 130.0):
        r = P('{"temp_c":%s,"temp_src":"ds18b20","dist_cm":40}' % bad)
        assert r.temp_c is None and r.temp_state == "out_of_range"

def test_humidity_out_of_range_dropped():
    assert P('{"temp_c":20,"rh":140,"dist_cm":40}').rh is None

def test_snow_from_dist_math():
    assert N.snow_from_dist(36.2, 45.2) == (pytest.approx(9.0), "ok")
    assert N.snow_from_dist(45.2, 45.2) == (0.0, "ok")
    assert N.snow_from_dist(46.5, 45.2) == (0.0, "ok")
    assert N.snow_from_dist(60.0, 45.2)[1] == "below_ground"
    assert N.snow_from_dist(36.2, None) == (None, "needs_calibration")
    assert N.snow_from_dist(None, 45.2) == (None, "out_of_range")

def test_snow_filter_rejects_spike_accepts_confirmed_step():
    f = N.SnowFilter(15.0)
    out = [f.update(t * 2.0, v) for t, v in enumerate([5, 5, 5, 5, 30, 5, 5])]
    assert max(out) < 6
    f = N.SnowFilter(15.0)
    out = [f.update(t * 2.0, v) for t, v in enumerate([5, 5, 5, 5, 15, 15])]
    assert out[-1] == pytest.approx(15.0)

def make_hub(tmp_path):
    return N.NodeHub(Store(tmp_path / "t.db"), "indoor_demo", 15.0)

def feed(hub, dist, n=3, t0=None):
    t0 = t0 or time.time()
    for i in range(n):
        hub.ingest(N.parse_line('{"temp_c":21,"rh":40,"dist_cm":%s}' % dist, t0 + i * 2.0))

def test_calibration_persists_undoes_and_survives_restart(tmp_path):
    hub = make_hub(tmp_path)
    feed(hub, 40.0)
    assert hub.snapshot()["snow"]["state"] == "needs_calibration"
    hub.start_calibration(seconds=0.0)
    feed(hub, 45.0, n=3)
    assert hub.ground_cm == 45.0 and hub.cal["state"] == "done"
    feed(hub, 36.0, n=3)
    assert hub.snapshot()["snow"]["cm"] == pytest.approx(9.0)
    hub.start_calibration(seconds=0.0)
    feed(hub, 50.0, n=3)
    assert hub.ground_cm == 50.0 and hub.undo_calibration() and hub.ground_cm == 45.0
    hub2 = make_hub(tmp_path)
    assert hub2.ground_cm == 45.0

def test_calibration_fails_cleanly_without_readings(tmp_path):
    hub = make_hub(tmp_path)
    hub.start_calibration(seconds=0.0)
    hub.ingest(N.parse_line('{"temp_c":21,"dist_cm":null}', time.time()))
    assert hub.cal["state"] == "averaging"
    hub.cal["t0"] -= 10.0
    hub.tick()
    assert hub.cal["state"] == "failed" and hub.ground_cm is None

def test_node_state_machine_live_dropout_offline(tmp_path):
    hub = make_hub(tmp_path)
    assert hub.state() == "offline"
    feed(hub, 40, n=1, t0=1000.0)
    assert hub.state(1003.0) == "live" and hub.state(1008.0) == "dropout" and hub.state(1012.0) == "offline" and hub.state(1100.0) == "offline"
    assert hub.snapshot(1100.0)["temp"]["c"] is None

def test_sim_node_is_deterministic_and_parseable():
    class Hub:
        on_calibration = None
        def mark_connection(self, *a): pass
    s = N.SimNode(Hub(), snow_fixed=9.0)
    r = s.reading(time.time())
    assert r.dist_state == "ok" and r.temp_state == "ok" and 20 < r.temp_c < 23
    assert abs((N.SimNode.GROUND_TRUE_CM - r.dist_cm) - 9.0) < 1.5
