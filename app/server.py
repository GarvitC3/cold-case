from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .config import WEB_DIR
from .core import AppCore
from .netinfo import RateLimiter, is_lan_addr, is_loopback, token_ok
from .node import parse_wireless

log = logging.getLogger("coldcase.http")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
MAX_NODE_BODY = 2048
NODE_READ_TIMEOUT_S = 5.0
MAX_NODE_INFLIGHT = 8
SSE_POLL_S = 0.5
SSE_MIN_GAP_S = 0.9

def make_handler(core: AppCore):
    limiter = RateLimiter(rate=40.0, burst=80.0)
    inflight = threading.BoundedSemaphore(MAX_NODE_INFLIGHT)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ColdCase"

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: Dict[str, str] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

        def _is_local(self) -> bool:
            return is_loopback(self.client_address[0])

        def _is_lan(self) -> bool:
            return is_lan_addr(self.client_address[0])

        def _body(self) -> Dict[str, Any]:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}") if 0 < n < 10_000 else {}
            except (ValueError, OSError):
                return {}

        def do_GET(self) -> None:
            try:
                path = urlparse(self.path).path
                if not self._is_lan():
                    return self._json({"error": "private-network clients only"}, 403)
                if path in ("/api/debug", "/api/node/info") and not self._is_local():
                    return self._json({"error": "local-only"}, 403)
                if path == "/api/node/info":
                    return self._json(core.node_info())
                if path == "/api/state":
                    return self._send(200, core.snapshot_json().encode(), "application/json", {"Cache-Control": "no-store"})
                if path == "/api/stream":
                    return self._stream()
                if path == "/api/export.csv":
                    return self._csv()
                if path == "/api/debug":
                    return self._json(core.debug_info())
                if path == "/api/season":
                    return self._json(core.season())
                if path == "/api/trend":
                    return self._json(core.trend())
                if path == "/api/raw/nasa":
                    qs = parse_qs(urlparse(self.path).query)
                    return self._json(core.raw_nasa(int((qs.get("n") or ["14"])[0])))
                if path.startswith("/api/"):
                    return self._json({"error": "not found"}, 404)
                return self._static(path)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                log.exception("GET %s failed", self.path)
                try:
                    self._json({"error": "internal"}, 500)
                except OSError:
                    pass

        def _csv(self) -> None:
            import csv
            import io
            from datetime import datetime as _dt
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["utc_time", "unix_ts", "temp_c", "rh_pct", "dist_cm", "snow_cm", "thermometer_valid", "mode", "source"])
            for ts, t, rh, d, sn, ok, mode, src in core.store.export_rows():
                w.writerow([_dt.utcfromtimestamp(ts).isoformat() + "Z", ts, t, rh, d, sn, ok, mode, src or "usb"])
            self._send(200, buf.getvalue().encode(), "text/csv; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="cold-case-node.csv"', "Cache-Control": "no-store"})

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in f.parents and f != WEB_DIR.resolve():
                return self._json({"error": "forbidden"}, 403)
            if f.is_dir():
                f = f / "index.html"
            if not f.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript") or ctype.endswith("json"):
                ctype += "; charset=utf-8"
            cache = "public, max-age=31536000, immutable" if f.suffix == ".woff2" else "no-cache"
            self._send(200, f.read_bytes(), ctype, {"Cache-Control": cache})

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last, last_sent, last_ping = None, 0.0, time.time()
            try:
                self.wfile.write(b"retry: 2000\n\n")
                while True:
                    now = time.time()
                    cur = core.snapshot_json(max_age=0.4)
                    if (cur != last and now - last_sent >= SSE_MIN_GAP_S) or now - last_sent > 10:
                        self.wfile.write(b"event: state\ndata: " + cur.encode() + b"\n\n")
                        self.wfile.flush()
                        last, last_sent, last_ping = cur, now, now
                    elif now - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = now
                    time.sleep(SSE_POLL_S)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _node_reply(self, code: int, ok: bool, err: str = "", raw: str = "", nbytes: int = 0, close: bool = False) -> None:
            ip = self.client_address[0]
            core.hub.note_packet(ip, code, nbytes, raw, err if not ok else "")
            if close:
                self.close_connection = True
            body = {"ok": True} if ok else {"ok": False, "error": err}
            self._send(code, json.dumps(body).encode(), "application/json",
                       {"Cache-Control": "no-store", **({"Connection": "close"} if close else {})})

        def _node_post(self, url) -> None:
            if not self._is_lan():
                return self._node_reply(403, False, "forbidden", close=True)
            if not inflight.acquire(blocking=False):
                return self._node_reply(503, False, "busy", close=True)
            try:
                ip = self.client_address[0]
                if not limiter.allow(ip):
                    return self._node_reply(429, False, "rate_limited", close=True)
                try:
                    n = int(self.headers.get("Content-Length") or -1)
                except ValueError:
                    n = -1
                if n < 0:
                    return self._node_reply(400, False, "no_length", close=True)
                if n > MAX_NODE_BODY:
                    return self._node_reply(413, False, "too_large", nbytes=n, close=True)
                qs = parse_qs(url.query)
                if not token_ok(core.node_token, self.headers.get("X-Node-Token"), (qs.get("token") or [None])[0]):
                    return self._node_reply(401, False, "bad_token", nbytes=n, close=True)
                self.connection.settimeout(NODE_READ_TIMEOUT_S)
                try:
                    data = self.rfile.read(n) if n else b""
                except OSError:
                    return self._node_reply(408, False, "timeout", close=True)
                text = data.decode("utf-8", "ignore")
                r, why = parse_wireless(text, time.time())
                if r is None:
                    return self._node_reply(400, False, why, raw=text, nbytes=n)
                if r.node == "selftest":
                    return self._node_reply(200, True, raw=text, nbytes=n)
                outcome = core.hub.receive(r)
                core.hub.note_packet(ip, 200, n, text, outcome + (" " + "+".join(r.flags) if r.flags else ""))
                self.close_connection = False
                self._send(200, b'{"ok":true}', "application/json", {"Cache-Control": "no-store"})
            finally:
                inflight.release()

        def do_POST(self) -> None:
            try:
                url = urlparse(self.path)
                if url.path == "/api/node":
                    return self._node_post(url)
                if not self._is_local():
                    return self._json({"error": "control endpoints are local-only"}, 403)
                path = url.path
                if path == "/api/node/selftest":
                    return self._json(core.node_selftest())
                body = self._body()
                if path == "/api/calibrate":
                    return self._json({"ok": True, "cal": core.hub.start_calibration()})
                if path == "/api/calibrate/undo":
                    return self._json({"ok": core.hub.undo_calibration()})
                if path == "/api/calibrate/clear":
                    core.hub.clear_calibration()
                    return self._json({"ok": True})
                if path == "/api/site":
                    return self._json({"ok": core.set_site(str(body.get("id", "")))})
                if path == "/api/clock":
                    return self._json({"ok": core.set_clock(str(body.get("date", "")))})
                if path == "/api/pref":
                    return self._json({"ok": core.set_pref(str(body.get("key", "")), body.get("value"))})
                if path == "/api/sync":
                    return self._json({"ok": core.sync_now()})
                if path == "/api/reset-season":
                    core.reset_season()
                    return self._json({"ok": True})
                if path == "/api/exit-kiosk":
                    return self._json({"ok": core.exit_kiosk()})
                if path == "/api/mode":
                    return self._json({"ok": core.set_mode(str(body.get("mode", "")))})
                return self._json({"error": "not found"}, 404)
            except Exception:
                log.exception("POST %s failed", self.path)
                self._json({"error": "internal"}, 500)

    return Handler

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)) and not isinstance(exc, PermissionError):
            log.debug("client %s went away: %s", client_address, exc)
            return
        log.exception("unhandled error serving %s", client_address)

def serve(core: AppCore, host: str, port: int) -> Server:
    srv = Server((host, port), make_handler(core))
    core.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True, name="http").start()
    log.info("serving on http://%s:%d", host, port)
    return srv
