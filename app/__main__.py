from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
import threading
from datetime import date

from .config import DB_PATH, LOG_DIR, load_config
from .core import AppCore
from .node import NodeHub, SerialManager, SimNode
from .server import serve
from .store import Store

def setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.handlers.RotatingFileHandler(LOG_DIR / "coldcase.log", maxBytes=1_000_000, backupCount=3)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)

def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m app", description="COLD CASE backend")
    ap.add_argument("--sim", action="store_true", help="simulated field node (all values wear a SIMULATED badge)")
    ap.add_argument("--sim-wireless", action="store_true",
                    help="simulated WIRELESS node: posts to this app's own /api/node as 'sim-field' (with --sim: both sources, to show arbitration)")
    ap.add_argument("--sim-snow", type=float, default=None, help="pin simulated snow depth (cm), for screenshots")
    ap.add_argument("--sim-period", type=float, default=2.0, help="seconds between simulated samples (soak tests use 0.05)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--today", default=None, help="DEV CLOCK: pretend today is YYYY-MM-DD (NASA data truncated to today-3)")
    ap.add_argument("--offline", action="store_true", help="never touch the network")
    ap.add_argument("--db", default=None, help="alternate SQLite path (tests / screenshots)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("coldcase")

    cfg = load_config()
    store = Store(args.db or DB_PATH)
    hub = NodeHub(store, cfg["node"]["mode"], float(cfg["node"].get("snow_filter_s", 15)))
    today = date.fromisoformat(args.today) if args.today else None
    core = AppCore(cfg, store, hub, today_override=today, offline=args.offline, sim=args.sim)

    sim = args.sim or args.sim_wireless
    core.sim = sim
    hub.sim_mode = sim
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    if sim:
        if args.sim:
            SimNode(hub, period=args.sim_period, snow_fixed=args.sim_snow).start()
            log.info("SIMULATED usb node running")
    else:
        SerialManager(hub, int(cfg["node"]["baud"]), str(cfg["node"].get("serial_port", ""))).start()
    core.start_background()
    srv = serve(core, host, port)
    port = srv.server_address[1]
    if args.sim_wireless:
        token = f"?token={core.node_token}" if core.node_token else ""
        SimNode(hub, period=args.sim_period, snow_fixed=args.sim_snow, via="wireless", seed=11,
                url=f"http://127.0.0.1:{port}/api/node{token}").start()
        log.info("SIMULATED wireless node running (posting to itself as 'sim-field')")
    print(f"COLD CASE  http://{host}:{port}   ({'SIM ' + ('usb+wireless' if args.sim and args.sim_wireless else 'wireless' if args.sim_wireless else 'usb') + ' node' if sim else 'serial node'}"
          f"{', DEV CLOCK ' + args.today if args.today else ''}{', offline' if core.offline else ''})", flush=True)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    hub.flush()
    core.stop_flag.set()
    return 0

if __name__ == "__main__":
    sys.exit(main())
