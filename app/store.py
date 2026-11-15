from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .nowcast import NodeDay

log = logging.getLogger("coldcase.store")
MIN_FREE_BYTES = 50 * 1024 * 1024

class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.ok = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5.0)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS samples(
                    ts INTEGER PRIMARY KEY,          -- unix seconds, start of the minute
                    temp_c REAL, rh REAL, dist_cm REAL, snow_cm REAL,
                    temp_ok INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT 'indoor_demo');
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS wl_seen(node TEXT NOT NULL, t10 INTEGER NOT NULL, PRIMARY KEY(node, t10)) WITHOUT ROWID;
                """
            )
            self._migrate()
            self.db.commit()
        except sqlite3.Error as e:
            log.error("database unavailable (%s) — running without persistence", e)
            self.ok = False
            self.db = None

    def _migrate(self) -> None:
        have = {r[1] for r in self.db.execute("PRAGMA table_info(samples)")}
        for col, ddl in (("src", "TEXT"), ("nt", "INTEGER"), ("nrh", "INTEGER"), ("nd", "INTEGER"), ("ns", "INTEGER")):
            if col not in have:
                self.db.execute(f"ALTER TABLE samples ADD COLUMN {col} {ddl}")

    def get(self, key: str, default: Any = None) -> Any:
        if not self.ok:
            return default
        try:
            with self.lock:
                row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default
        except (sqlite3.Error, ValueError) as e:
            log.warning("kv get %s failed: %s", key, e)
            return default

    def set(self, key: str, value: Any) -> bool:
        if not self.ok:
            return False
        try:
            with self.lock:
                self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
                self.db.commit()
            return True
        except sqlite3.Error as e:
            log.warning("kv set %s failed: %s", key, e)
            return False

    def _disk_ok(self) -> bool:
        try:
            return shutil.disk_usage(str(self.path.parent)).free > MIN_FREE_BYTES
        except OSError:
            return True

    def add_sample(self, ts: int, temp_c: Optional[float], rh: Optional[float], dist_cm: Optional[float],
                   snow_cm: Optional[float], temp_ok: bool, mode: str, src: str = "usb",
                   counts: Optional[Tuple[int, int, int, int]] = None) -> None:
        if not self.ok or not self._disk_ok():
            return
        vals = (temp_c, rh, dist_cm, snow_cm)
        n = counts or tuple(0 if v is None else 1 for v in vals)
        try:
            with self.lock:
                row = self.db.execute("SELECT temp_c,rh,dist_cm,snow_cm,nt,nrh,nd,ns,temp_ok,src FROM samples WHERE ts=?",
                                      (ts,)).fetchone()
                if row:
                    old_v, old_n = row[0:4], [(c if c is not None else (0 if v is None else 1)) for v, c in zip(row[0:4], row[4:8])]
                    merged, mn = [], []
                    for ov, on, nv, nn in zip(old_v, old_n, vals, n):
                        tot = on + nn
                        merged.append(((ov * on + nv * nn) / tot) if (tot and ov is not None and nv is not None)
                                      else (ov if (nv is None or not nn) else nv))
                        mn.append(tot)
                    vals, n = tuple(merged), tuple(mn)
                    temp_ok = bool(row[8]) or temp_ok
                    src = row[9] if row[9] == src or row[9] is None else "mixed"
                self.db.execute(
                    "INSERT OR REPLACE INTO samples(ts,temp_c,rh,dist_cm,snow_cm,temp_ok,mode,src,nt,nrh,nd,ns) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, *vals, 1 if temp_ok else 0, mode, src, *n))
                self.db.commit()
        except sqlite3.Error as e:
            log.warning("sample write failed: %s", e)

    def seen_load(self, limit: int = 20000) -> List[Tuple[str, int]]:
        if not self.ok:
            return []
        try:
            with self.lock:
                self.db.execute("DELETE FROM wl_seen WHERE t10 < ?", (int((time.time() - 3 * 86400) * 10),))
                self.db.commit()
                return list(self.db.execute("SELECT node,t10 FROM wl_seen ORDER BY t10 DESC LIMIT ?", (limit,)))
        except sqlite3.Error as e:
            log.warning("seen load failed: %s", e)
            return []

    def seen_add(self, keys: List[Tuple[str, int]]) -> None:
        if not self.ok or not keys:
            return
        try:
            with self.lock:
                self.db.executemany("INSERT OR IGNORE INTO wl_seen(node,t10) VALUES(?,?)", keys)
                self.db.commit()
        except sqlite3.Error as e:
            log.warning("seen write failed: %s", e)

    def recent(self, since_ts: float) -> List[Tuple[int, Optional[float], Optional[float]]]:
        if not self.ok:
            return []
        try:
            with self.lock:
                return list(self.db.execute(
                    "SELECT ts,temp_c,snow_cm FROM samples WHERE ts>=? ORDER BY ts", (int(since_ts),)))
        except sqlite3.Error as e:
            log.warning("recent read failed: %s", e)
            return []

    def outdoor_days(self, since: date) -> Dict[date, NodeDay]:
        if not self.ok:
            return {}
        try:
            since_ts = datetime(since.year, since.month, since.day).timestamp()
            with self.lock:
                rows = list(self.db.execute(
                    "SELECT date(ts,'unixepoch','localtime') d, AVG(temp_c), COUNT(*) "
                    "FROM samples WHERE mode='outdoor' AND temp_ok=1 AND temp_c IS NOT NULL AND ts>=? GROUP BY d",
                    (int(since_ts),)))
        except sqlite3.Error as e:
            log.warning("outdoor_days failed: %s", e)
            return {}
        out: Dict[date, NodeDay] = {}
        for d, mean, n in rows:
            try:
                dd = date.fromisoformat(d)
            except ValueError:
                continue
            out[dd] = NodeDay(dd, float(mean), min(1.0, n / 1440.0))
        return out

    def today_partial(self, today: date, minutes_elapsed: float) -> Optional[NodeDay]:
        days = self.outdoor_days(today)
        nd = days.get(today)
        if nd is None or minutes_elapsed < 1:
            return None
        n = nd.coverage * 1440.0
        return NodeDay(today, nd.mean_c, min(1.0, n / max(1.0, minutes_elapsed)))

    def export_rows(self):
        if not self.ok:
            return []
        try:
            with self.lock:
                return list(self.db.execute("SELECT ts,temp_c,rh,dist_cm,snow_cm,temp_ok,mode,src FROM samples ORDER BY ts"))
        except sqlite3.Error as e:
            log.warning("export failed: %s", e)
            return []

    def reset_samples(self) -> None:
        if not self.ok:
            return
        try:
            with self.lock:
                self.db.execute("DELETE FROM samples")
                self.db.commit()
        except sqlite3.Error as e:
            log.warning("reset failed: %s", e)
