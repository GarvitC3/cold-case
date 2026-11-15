import json
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import date

import pytest

from app.config import load_config
from app.core import AppCore
from app.node import NodeHub, SimNode
from app.server import serve
from app.store import Store

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture(scope="module")
def live(tmp_path_factory):
    st = Store(tmp_path_factory.mktemp("db") / "i.db")
    hub = NodeHub(st, "indoor_demo")
    core = AppCore(load_config(), st, hub, offline=True, sim=True)
    sim = SimNode(hub, period=0.05, snow_fixed=9.0); sim.start()
    port = free_port(); srv = serve(core, "127.0.0.1", port)
    time.sleep(0.5)
    yield core, f"http://127.0.0.1:{port}"
    sim.stop(); srv.shutdown()

def get(url, **kw):
    return urllib.request.urlopen(url, timeout=10, **kw)

def post(url, body=None):
    r = urllib.request.Request(url, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=10))

@pytest.mark.parametrize("path", ["/api/state", "/api/season", "/api/trend", "/api/raw/nasa?n=7", "/api/debug"])
def test_every_json_route_is_valid_strict_json(live, path):
    _, base = live
    body = get(base + path).read().decode()
    json.loads(body, parse_constant=lambda c: (_ for _ in ()).throw(ValueError("NaN/Infinity in JSON: " + c)))

def test_bad_inputs_degrade_politely(live):
    _, base = live
    for bad in ("/api/nope", "/nothing.html", "/../app/config.py", "/%2e%2e/app/config.py", "/js/../../app/core.py"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + bad)
        assert e.value.code in (403, 404)

def test_static_assets_and_csv(live):
    _, base = live
    assert b"<title>Cold Case</title>" in get(base + "/").read()
    r = get(base + "/js/main.js"); assert "javascript" in r.headers["Content-Type"]
    assert get(base + "/fonts/inter-latin-wght-normal.woff2").read(4) == b"wOF2"
    time.sleep(0.3)
    assert get(base + "/api/export.csv").read().decode().startswith("utc_time,unix_ts")

def test_control_endpoints(live):
    core, base = live
    assert post(base + "/api/site", {"id": "bogus"})["ok"] is False
    assert post(base + "/api/site", {"id": "sudbury"})["ok"] is True
    assert json.load(get(base + "/api/state"))["site"]["id"] == "sudbury"
    post(base + "/api/site", {"id": "mississauga"})
    assert post(base + "/api/mode", {"mode": "weird"})["ok"] is False
    assert post(base + "/api/clock", {"date": "not-a-date"})["ok"] is False
    assert post(base + "/api/clock", {"date": "1999-01-01"})["ok"] is False
    assert post(base + "/api/pref", {"key": "evil", "value": 1})["ok"] is False
    assert post(base + "/api/calibrate")["ok"] is True

def test_sse_streams_and_survives_rude_clients(live):
    _, base = live
    r = get(base + "/api/stream")
    seen = b""
    t0 = time.time()
    while b"event: state" not in seen and time.time() - t0 < 5:
        seen += r.read(64)
    assert b"event: state" in seen
    r.close()
    for _ in range(8):
        c = socket.create_connection(("127.0.0.1", int(base.rsplit(":", 1)[1])))
        c.sendall(b"GET /api/stream HTTP/1.1\r\nHost: x\r\n\r\n"); c.close()
    time.sleep(1.0)
    assert json.load(get(base + "/api/state"))["site"]["id"]

def test_clock_set_from_ui_changes_the_date(live):
    core, base = live
    assert post(base + "/api/clock", {"date": "2027-01-15"})["ok"] is True
    st = json.load(get(base + "/api/state"))
    assert st["clock"]["today"] == "2027-01-15" and st["clock"]["trusted"] is True
    assert st["now"]["winter"]["label"] == "2026–27"
    core.clock_offset = 0.0; core.store.set("clock_offset", 0.0); core._snap_cache = None

@pytest.mark.parametrize("fake_today", [date(2026, 6, 1), date(2026, 11, 5), date(2025, 1, 1), date(2031, 2, 2)])
def test_system_clock_jumps_never_break_the_snapshot(live, monkeypatch, fake_today):
    core, _ = live
    monkeypatch.setattr(core, "today", lambda: fake_today)
    core._snap_cache = None
    s = json.loads(core.snapshot_json(max_age=0))
    assert s["now"]["phase"] in ("offseason", "none", "forming", "season", "no_data")
    json.dumps(s, allow_nan=False)
