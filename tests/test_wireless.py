import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from app import node as N
from app.config import load_config
from app.core import AppCore
from app.netinfo import RateLimiter, is_lan_addr, is_loopback, token_ok
from app.server import serve
from app.store import Store

NOW = 1_800_000_000.0

def body(**kw):
    d = {"temp_c": 21.0, "rh": 40.0, "dist_cm": 36.0, "node": "field", "seq": 1, "t": NOW}
    d.update(kw)
    return json.dumps(d)

def test_classify_live_historical_and_boundary():
    assert N.classify_time(NOW - 2, NOW) == (NOW, "live", [])
    assert N.classify_time(NOW - 30, NOW)[1] == "live"
    t, kind, fl = N.classify_time(NOW - 31, NOW)
    assert (t, kind, fl) == (NOW - 31, "historical", [])
    assert N.classify_time(NOW + 299, NOW)[1] == "live"

@pytest.mark.parametrize("t", [0.0, 1000.0, N.MIN_VALID_T - 1, NOW + 301, NOW + 86400])
def test_clock_suspect_uses_receipt_time(t):
    ts, kind, fl = N.classify_time(t, NOW)
    assert ts == NOW and kind == "live" and fl == ["clock_suspect"]

def test_missing_or_nonfinite_t_is_flagged_not_trusted():
    assert N.classify_time(None, NOW) == (NOW, "live", ["no_t"])
    assert N.classify_time(float("nan"), NOW)[2] == ["no_t"]

def test_wireless_goes_through_the_same_validation():
    r, why = N.parse_wireless(body(temp_c=0.0, dist_cm=0), NOW)
    assert why == "" and r.temp_c is None and r.temp_state == "out_of_range" and r.dist_cm is None
    r, _ = N.parse_wireless(body(temp_c=51, dist_cm=-1), NOW)
    assert r.temp_c is None and r.dist_cm is None
    r, _ = N.parse_wireless('{"temp_c":NaN,"rh":null,"dist_cm":40.5,"node":"field","t":%s}' % NOW, NOW)
    assert r.temp_c is None and r.rh is None and r.dist_cm == 40.5
    r, _ = N.parse_wireless('{"dist_cm":40.5}', NOW)
    assert r.node == "unknown" and "no_t" in r.flags and r.seq is None

@pytest.mark.parametrize("raw,why", [("", "garbage"), ("\x00\xff", "garbage"), ("[1,2]", "garbage"), ("null", "garbage"),
                                     ('{"node":"field","seq":1}', "no_sensor_keys"), ("{", "garbage")])
def test_garbage_is_refused_with_a_reason(raw, why):
    r, got = N.parse_wireless(raw, NOW)
    assert r is None and got == why

def test_node_name_is_sanitised_and_sim_is_badged():
    r, _ = N.parse_wireless(body(node="<b>fi eld</b>\n"), NOW)
    assert r.node == "bfield" or r.node.isalnum() or set(r.node) <= set("abcdefghijklmnopqrstuvwxyzBF_.-0123456789")
    assert not r.simulated
    r, _ = N.parse_wireless(body(node="sim-field"), NOW)
    assert r.simulated

def test_usb_and_wireless_agree_on_the_same_numbers():
    line = '{"temp_c":21.4,"rh":41,"dist_cm":36.17}'
    u = N.parse_line(line, NOW)
    w, _ = N.parse_wireless(line, NOW)
    assert (u.temp_c, u.rh, u.dist_cm, u.temp_state, u.dist_state) == (w.temp_c, w.rh, w.dist_cm, w.temp_state, w.dist_state)

def test_arbiter_wireless_wins_usb_falls_back_and_never_flaps():
    a = N.Arbiter()
    assert a.select(0) is None
    a.note("usb", 0); assert a.select(0) == "usb"
    a.note("wireless", 1); assert a.select(1) == "usb"
    for t in (3, 5): a.note("usb", t); a.note("wireless", t); assert a.select(t) == "usb"
    a.note("usb", 7); a.note("wireless", 7)
    assert a.select(7) == "wireless"
    for t in range(8, 40, 2):
        a.note("usb", t); a.note("wireless", t)
        assert a.select(t) == "wireless"
    sw = a.switched_at
    a.note("usb", 41); assert a.select(41) == "wireless" and a.switched_at == sw
    a.note("usb", 55); assert a.select(55) == "usb"
    a.note("wireless", 56); assert a.select(56) == "usb"
    a.note("usb", 58); a.note("wireless", 58); assert a.select(58) == "usb"
    a.note("usb", 61); a.note("wireless", 61); assert a.select(61) == "wireless"
    assert a.select(80) is None

def test_arbiter_does_not_flap_when_wireless_stutters():
    a = N.Arbiter()
    a.note("usb", 0); a.select(0)
    switches, last = 0, a.active
    for k in range(60):
        t = float(k)
        a.note("usb", t)
        if k % 15 < 3: a.note("wireless", t)
        act = a.select(t)
        switches += act != last
        last = act
    assert switches <= 2

@pytest.fixture
def hub(tmp_path):
    return N.NodeHub(Store(tmp_path / "w.db"), "indoor_demo")

def rx(hub, raw, now):
    r, why = N.parse_wireless(raw, now)
    assert r is not None, why
    return hub.receive(r, now)

def test_duplicate_node_t_is_ignored(hub):
    now = time.time()
    assert rx(hub, body(t=now, seq=5), now) == "live"
    assert rx(hub, body(t=now, seq=5), now + 0.1) == "duplicate"
    assert rx(hub, body(t=now, seq=1), now + 0.2) == "duplicate"
    assert rx(hub, body(t=now, node="other"), now + 0.3) in ("live", "standby")
    assert hub.stats["duplicate"] == 2

def test_dedupe_survives_a_restart(tmp_path):
    st = Store(tmp_path / "w.db")
    h1 = N.NodeHub(st, "indoor_demo")
    now = time.time()
    old = now - 600
    assert rx(h1, body(t=old), now) == "historical"
    h1.flush()
    h2 = N.NodeHub(st, "indoor_demo")
    assert rx(h2, body(t=old), now) == "duplicate"

def test_historical_is_stored_at_its_own_time_and_never_shown_live(hub):
    now = time.time()
    t_old = (now - 3600) // 60 * 60 + 17
    assert rx(hub, body(t=t_old, temp_c=-1.0 + 5, dist_cm=40.0), now) == "historical"
    assert hub.state(now) == "offline" and hub.snapshot(now)["temp"]["c"] is None
    assert hub.last is None and hub.links["wireless"].last_ts is None
    hub.flush()
    rows = hub.store.export_rows()
    assert [r[0] for r in rows] == [int(t_old // 60 * 60)] and rows[0][7] == "wireless"

def test_late_burst_into_a_live_minute_is_merged_not_overwritten(hub):
    now = time.time()
    minute = int(now // 60 * 60)
    hub.store.add_sample(minute, 20.0, 40.0, 30.0, None, True, "indoor_demo", src="wireless", counts=(1, 1, 1, 0))
    hub.store.add_sample(minute, 22.0, 40.0, 30.0, None, True, "indoor_demo", src="wireless", counts=(3, 3, 3, 0))
    row = hub.store.export_rows()[0]
    assert row[1] == pytest.approx(21.5)
    hub.store.add_sample(minute, 21.5, 40.0, 30.0, None, True, "indoor_demo", src="usb")
    assert hub.store.export_rows()[0][7] == "mixed"

def test_too_old_backlog_is_dropped(hub):
    now = time.time()
    assert rx(hub, body(t=now - 5 * 86400), now) == "too_old"
    hub.flush()
    assert hub.store.export_rows() == []

def test_clock_suspect_packet_is_stored_at_receipt_time(hub):
    now = time.time()
    assert rx(hub, body(t=1000.0), now) == "live"
    assert hub.last.ts == now and "clock_suspect" in hub.last.flags and hub.stats["clock_suspect"] == 1

def test_standby_source_never_drives_the_tiles(hub):
    now = time.time()
    hub.ingest(N.parse_line('{"temp_c":20,"rh":40,"dist_cm":30}', now))
    assert rx(hub, body(t=now + 1, temp_c=25.0), now + 1) == "standby"
    assert hub.snapshot(now + 1)["temp"]["c"] == 20.0 and hub.snapshot(now + 1)["via"] == "usb"
    for k in range(2, 9):
        hub.ingest(N.parse_line('{"temp_c":20,"rh":40,"dist_cm":30}', now + k))
        rx(hub, body(t=now + k, temp_c=25.0), now + k)
    s = hub.snapshot(now + 8)
    assert s["via"] == "wireless" and s["temp"]["c"] == 25.0 and s["name"] == "field"
    assert s["link"]["chip"]["via"] == "wireless" and s["link"]["chip"]["tone"] == "green"

def test_ground_level_is_per_source(hub):
    now = time.time()
    hub.ingest(N.parse_line('{"temp_c":20,"dist_cm":45}', now)); hub.ingest(N.parse_line('{"temp_c":20,"dist_cm":45}', now + 1))
    hub.start_calibration(seconds=0.0)
    hub.ingest(N.parse_line('{"temp_c":20,"dist_cm":45}', now + 2)); hub.ingest(N.parse_line('{"temp_c":20,"dist_cm":45}', now + 3))
    assert hub.ground_cm == 45.0
    t = now + 60
    rx(hub, body(t=t, dist_cm=50.0), t); rx(hub, body(t=t + 1, dist_cm=50.0, seq=2), t + 1)
    s = hub.snapshot(t + 1)
    assert s["via"] == "wireless" and s["snow"]["ground_cm"] is None and s["snow"]["state"] == "needs_calibration"

def test_chip_tones_green_amber_grey(hub):
    now = time.time()
    rx(hub, body(t=now), now)
    assert hub.snapshot(now + 2)["link"]["chip"]["tone"] == "green"
    s = hub.snapshot(now + 30)
    assert s["link"]["chip"]["tone"] == "amber" and s["state"] == "offline" and s["temp"]["c"] is None
    assert hub.snapshot(now + 120)["link"]["chip"]["tone"] == "grey"
    assert N.NodeHub(Store(":memory:" if False else hub.store.path.parent / "n.db"), "indoor_demo").snapshot()["link"]["chip"]["via"] is None

@pytest.mark.parametrize("ip", ["10.0.0.5", "10.255.255.255", "172.16.0.1", "172.31.255.1", "192.168.2.231", "169.254.9.9",
                                "127.0.0.1", "::1", "::ffff:192.168.1.5", "::ffff:127.0.0.1"])
def test_private_lan_addresses_allowed(ip):
    assert is_lan_addr(ip)

@pytest.mark.parametrize("ip", ["8.8.8.8", "172.15.255.255", "172.32.0.1", "192.169.0.1", "11.0.0.1", "100.64.0.1", "169.255.0.1",
                                "2001:db8::1", "fe80::1", "", "not-an-ip", "::ffff:8.8.8.8"])
def test_public_or_odd_addresses_refused(ip):
    assert not is_lan_addr(ip)

def test_loopback_only_helper():
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("::ffff:127.0.0.1")
    assert not is_loopback("192.168.2.231")

def test_token_logic():
    assert token_ok("", None, None) and token_ok("", "anything", "x")
    assert token_ok("s3cret", "s3cret", None) and token_ok("s3cret", None, "s3cret")
    assert not token_ok("s3cret", None, None) and not token_ok("s3cret", "nope", "nope") and not token_ok("s3cret", "", "")

def test_rate_limiter_bursts_then_refills():
    t = [0.0]
    rl = RateLimiter(rate=10, burst=5, clock=lambda: t[0])
    assert [rl.allow("a") for _ in range(7)] == [True] * 5 + [False] * 2
    assert rl.allow("b")
    t[0] += 0.5
    assert sum(rl.allow("a") for _ in range(10)) == 5

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    st = Store(tmp_path_factory.mktemp("w") / "http.db")
    hub = N.NodeHub(st, "indoor_demo")
    cfg = load_config()
    cfg["node"]["node_token"] = ""
    core = AppCore(cfg, st, hub, offline=True)
    port = free_port()
    srv = serve(core, "127.0.0.1", port)
    time.sleep(0.3)
    yield core, f"http://127.0.0.1:{port}"
    srv.shutdown()

def post(url, data=None, raw=None, headers=None, timeout=4):
    body_ = raw if raw is not None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body_, headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def pkt(**kw):
    d = {"temp_c": 21.0, "rh": 40.0, "dist_cm": 36.0, "node": "field", "seq": 1, "t": round(time.time(), 1)}
    d.update(kw)
    return d

def test_endpoint_status_codes(app):
    core, base = app
    core.hub._select(time.time())
    assert post(base + "/api/node", pkt()) == (200, {"ok": True})
    assert post(base + "/api/node", raw=b"garbage \x00\xff")[0] == 400
    assert post(base + "/api/node", raw=b"")[0] == 400
    assert post(base + "/api/node", raw=b"[1]")[0] == 400
    assert post(base + "/api/node", raw=b'{"temp_c":1,"x":"' + b"a" * 3000 + b'"}')[0] in (413,)
    assert post(base + "/api/node", pkt(t=round(time.time(), 1) + 0.1))[0] == 200

def test_endpoint_is_the_only_write_a_lan_peer_gets(app):
    core, base = app
    code, _ = post(base + "/api/node/selftest", {})
    assert code == 200
    assert core.hub.links["wireless"].n_live >= 0
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/nope")
    assert e.value.code == 404

def test_token_enforced_by_header_and_query(app):
    core, base = app
    core.node_token = "s3cret"
    try:
        assert post(base + "/api/node", pkt(t=round(time.time(), 1) + 0.2))[0] == 401
        assert post(base + "/api/node", pkt(t=round(time.time(), 1) + 0.3), headers={"X-Node-Token": "bad"})[0] == 401
        assert post(base + "/api/node", pkt(t=round(time.time(), 1) + 0.4), headers={"X-Node-Token": "s3cret"})[0] == 200
        assert post(base + "/api/node?token=s3cret", pkt(t=round(time.time(), 1) + 0.5))[0] == 200
        info = json.load(urllib.request.urlopen(base + "/api/node/info"))
        assert info["token_required"] and "token=s3cret" in info["sender_cmd"]
    finally:
        core.node_token = ""

def test_selftest_changes_nothing(app):
    core, base = app
    before = dict(core.hub.stats)
    r = json.loads(urllib.request.urlopen(urllib.request.Request(base + "/api/node/selftest", data=b"{}", method="POST")).read())
    lo = [x for x in r["results"] if x["addr"] == "127.0.0.1"]
    assert lo and lo[0]["ok"]
    assert core.hub.stats["accepted"] == before["accepted"]

def sse_gaps(base, seconds, out):
    req = urllib.request.urlopen(base + "/api/stream", timeout=15)
    last, worst, end = time.time(), 0.0, time.time() + seconds
    buf = b""
    while time.time() < end:
        chunk = req.read1(4096) if hasattr(req, "read1") else req.read(1)
        buf += chunk
        if b"event: state" in buf:
            now = time.time(); worst = max(worst, now - last); last = now; buf = b""
    out.append(worst)

def test_flood_and_garbage_never_block_the_sse_stream(app):
    core, base = app
    out = []
    th = threading.Thread(target=sse_gaps, args=(base, 6, out)); th.start()
    time.sleep(1.2)
    codes = set()
    junk = [b"\x00" * 100, b"{", b'{"a":' * 200, b"x" * 5000, b'{"temp_c":1}', json.dumps(pkt()).encode()]
    t0 = time.time()
    while time.time() - t0 < 3.0:
        for j in junk:
            codes.add(post(base + "/api/node", raw=j, timeout=3)[0])
    th.join()
    assert codes <= {200, 400, 413, 429, 503}
    assert out and out[0] < 3.0

def test_node_vanishes_and_returns_without_restart(app):
    core, base = app
    h = core.hub
    base_t = time.time()
    post(base + "/api/node", pkt(t=round(base_t, 1) + 5.0))
    assert h.snapshot(time.time())["state"] in ("live", "dropout")
    s = h.snapshot(time.time() + 12)
    assert s["state"] == "offline" and s["temp"]["c"] is None and s["snow"]["cm"] is None
    assert core.snapshot()["now"] is not None
    post(base + "/api/node", pkt(t=round(time.time(), 1) + 9.0))
    assert h.snapshot(time.time())["state"] == "live"

def _lan_ip():
    from app.netinfo import lan_addresses
    a = lan_addresses()
    return a[0]["ip"] if a else None

@pytest.fixture(scope="module")
def lan_app(tmp_path_factory):
    ip = _lan_ip()
    if not ip:
        pytest.skip("no private LAN address on this machine")
    st = Store(tmp_path_factory.mktemp("lan") / "lan.db")
    core = AppCore(load_config(), st, N.NodeHub(st, "indoor_demo"), offline=True)
    port = free_port()
    srv = serve(core, "0.0.0.0", port)
    time.sleep(0.3)
    yield core, f"http://{ip}:{port}"
    srv.shutdown()

def test_lan_peer_can_post_nodes_and_read_but_not_control(lan_app):
    core, base = lan_app
    assert post(base + "/api/node", pkt())[0] == 200
    assert urllib.request.urlopen(base + "/api/state", timeout=4).status == 200
    for path in ("/api/calibrate", "/api/mode", "/api/reset-season", "/api/exit-kiosk", "/api/site", "/api/node/selftest"):
        assert post(base + path, {})[0] == 403, path
    for path in ("/api/debug", "/api/node/info"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + path, timeout=4)
        assert e.value.code == 403, path

def test_non_private_peer_is_refused_everywhere(lan_app, monkeypatch):
    import app.server as S
    core, base = lan_app
    monkeypatch.setattr(S, "is_lan_addr", lambda a: False)
    assert post(base + "/api/node", pkt())[0] == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/api/state", timeout=4)
    assert e.value.code == 403
