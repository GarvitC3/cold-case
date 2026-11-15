import io
import json
import sqlite3
import sys
import threading
import time
import types
import urllib.error
from datetime import date

import numpy as np
import pytest

from app import nasa
from app import node as N
from app.config import SITE_BY_ID
from app.store import Store
from conftest import synth_series

SITE = SITE_BY_ID["mississauga"]

def good_cache(tmp_path, twice=True):
    s = synth_series(end=date(2026, 11, 11))
    nasa.write_cache(SITE, s, "http://x", {"api": {"version": "t"}}, tmp_path)
    if twice:
        nasa.write_cache(SITE, s, "http://x", {"api": {"version": "t"}}, tmp_path)
    return s

def test_corrupt_cache_falls_back_to_last_good(tmp_path):
    s = good_cache(tmp_path)
    nasa.cache_path(SITE.id, tmp_path).write_text('{"t2m": [1, 2, tru')
    r = nasa.read_cache(SITE.id, tmp_path)
    assert r is not None and len(r.values) == len(s.values)

def test_both_copies_corrupt_returns_none_not_exception(tmp_path):
    good_cache(tmp_path)
    for f in tmp_path.glob("power_*"):
        f.write_text("\x00\x00garbage")
    assert nasa.read_cache(SITE.id, tmp_path) is None

def test_wrong_shape_cache_is_rejected(tmp_path):
    (tmp_path / f"power_{SITE.id}.json").write_text(json.dumps({"start": "19811101", "t2m": "nope"}))
    assert nasa.read_cache(SITE.id, tmp_path) is None

class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False

def payload(days):
    return json.dumps({"properties": {"parameter": {"T2M": days}}, "header": {"api": {"version": "x"}, "sources": ["T"]}}).encode()

@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(nasa.time, "sleep", lambda s: None)

def test_429_is_retried_then_succeeds(monkeypatch, no_sleep):
    calls = {"n": 0}
    def fake(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", 429, "slow down", {}, None)
        return FakeResp(payload({"20261101": 3.0}))
    monkeypatch.setattr(nasa.urllib.request, "urlopen", fake)
    assert nasa.fetch_power(43.6, -79.6, date(2026, 11, 1), date(2026, 11, 1))["properties"]
    assert calls["n"] == 3

def test_403_is_not_hammered(monkeypatch, no_sleep):
    calls = {"n": 0}
    def fake(req, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, None)
    monkeypatch.setattr(nasa.urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError):
        nasa.fetch_power(1, 1, date(2026, 1, 1), date(2026, 1, 2))
    assert calls["n"] == 1

@pytest.mark.parametrize("body", [b'{"properties": {"parameter": {"T2M": {"2026', b"<html>proxy login</html>", b'{"properties": {}}', b'{"properties":{"parameter":{"T2M":{}}}}'])
def test_partial_or_wrong_json_never_reaches_the_cache(monkeypatch, no_sleep, tmp_path, body):
    s = good_cache(tmp_path)
    before = nasa.cache_path(SITE.id, tmp_path).read_bytes()
    monkeypatch.setattr(nasa.urllib.request, "urlopen", lambda req, timeout=0: FakeResp(body))
    with pytest.raises(RuntimeError):
        nasa.refresh_site(SITE, date(2026, 11, 14), tmp_path)
    assert nasa.cache_path(SITE.id, tmp_path).read_bytes() == before

def test_timeout_is_retried_and_reported(monkeypatch, no_sleep):
    def fake(req, timeout=0): raise TimeoutError("slow")
    monkeypatch.setattr(nasa.urllib.request, "urlopen", fake)
    with pytest.raises(RuntimeError):
        nasa.fetch_power(1, 1, date(2026, 1, 1), date(2026, 1, 2), retries=3)

def test_incremental_refresh_merges_and_overwrites_revised_days(monkeypatch, no_sleep, tmp_path):
    s = good_cache(tmp_path)
    old_nov8 = s.get(date(2026, 11, 8))
    days = {"20261108": old_nov8 + 5.0, "20261111": s.get(date(2026, 11, 11)), "20261112": -4.5, "20261113": -999.0}
    monkeypatch.setattr(nasa.urllib.request, "urlopen", lambda req, timeout=0: FakeResp(payload(days)))
    r = nasa.refresh_site(SITE, date(2026, 11, 14), tmp_path)
    assert r.get(date(2026, 11, 8)) == pytest.approx(old_nov8 + 5.0, abs=0.01)
    assert r.get(date(2026, 11, 12)) == -4.5 and r.as_of == date(2026, 11, 12)
    assert np.isnan(r.get(date(2026, 11, 13)))
    assert r.get(date(2026, 10, 1)) == pytest.approx(s.get(date(2026, 10, 1)), abs=0.01)

def test_database_unavailable_means_no_persistence_not_a_crash(monkeypatch, tmp_path):
    def boom(*a, **k): raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(sqlite3, "connect", boom)
    st = Store(tmp_path / "x.db")
    assert st.ok is False
    st.add_sample(1, 1.0, 1.0, 1.0, 1.0, True, "outdoor")
    assert st.get("k", "dflt") == "dflt" and st.set("k", 1) is False
    assert st.outdoor_days(date(2026, 11, 1)) == {} and st.recent(0) == [] and st.export_rows() == []

def test_locked_database_is_survivable(tmp_path):
    st = Store(tmp_path / "x.db")
    class Locked:
        def execute(self, *a, **k): raise sqlite3.OperationalError("database is locked")
        def commit(self): raise sqlite3.OperationalError("database is locked")
    st.db = Locked()
    st.add_sample(1, 1.0, 1.0, 1.0, 1.0, True, "outdoor")
    assert st.get("a", 5) == 5 and st.set("a", 1) is False and st.recent(0) == [] and st.outdoor_days(date(2026, 1, 1)) == {}

def test_disk_nearly_full_skips_writes(monkeypatch, tmp_path):
    import app.store as S
    st = Store(tmp_path / "x.db")
    monkeypatch.setattr(S.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=1024))
    st.add_sample(1700000000, 1.0, 1.0, 1.0, 1.0, True, "outdoor")
    assert st.recent(0) == []

def test_serial_hotplug_recovers(monkeypatch, tmp_path):
    opens = {"n": 0}

    class SerialException(OSError):
        pass

    class FakeSerial:
        def __init__(self, port, baud, timeout=0):
            opens["n"] += 1
            self.n = opens["n"]
            self.lines = [b'{"temp_c":21.0,"rh":40,"dist_cm":36.0}\n', b"\xff\xfe boot garbage\n", b'{"temp_c":21.1,"rh":40,"dist_cm":36.0}\n']
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def readline(self):
            if self.lines:
                return self.lines.pop(0)
            if self.n == 1:
                raise SerialException("device disconnected")
            time.sleep(0.05)
            return b""
    fake = types.ModuleType("serial"); fake.Serial = FakeSerial; fake.SerialException = SerialException
    monkeypatch.setitem(sys.modules, "serial", fake)
    monkeypatch.setattr(N, "find_ports", lambda override="": ["/dev/ttyUSB0"])
    hub = N.NodeHub(Store(tmp_path / "t.db"), "indoor_demo")
    mgr = N.SerialManager(hub)
    mgr.start()
    t0 = time.time()
    while time.time() - t0 < 8 and opens["n"] < 2:
        time.sleep(0.1)
    time.sleep(0.3)
    mgr.stop()
    assert opens["n"] >= 2
    assert hub.last is not None and hub.last.temp_c in (21.0, 21.1)
    assert any(l.startswith("?") for l in hub.raw_tail)

def test_no_serial_port_is_just_node_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(N, "find_ports", lambda override="": [])
    hub = N.NodeHub(Store(tmp_path / "t.db"), "indoor_demo")
    m = N.SerialManager(hub); m.start(); time.sleep(0.4); m.stop()
    assert hub.snapshot()["state"] == "offline"
