from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
DB_PATH = ROOT / "data" / "coldcase.sqlite3"
LOG_DIR = Path(os.environ.get("COLDCASE_LOGDIR") or (ROOT / "data" / "logs"))
WEB_DIR = ROOT / "web"

@dataclass(frozen=True)
class Site:
    id: str
    name: str
    short: str
    lat: float
    lon: float

SITES: List[Site] = [
    Site("mississauga", "Mississauga", "Mississauga", 43.59, -79.64),
    Site("sudbury", "Sudbury", "Sudbury", 46.49, -81.00),
    Site("timmins", "Timmins", "Timmins", 48.47, -81.33),
    Site("kapuskasing", "Kapuskasing", "Kapuskasing", 49.42, -82.43),
    Site("moosonee", "Moosonee (James Bay coast)", "Moosonee", 51.27, -80.65),
]
SITE_BY_ID = {s.id: s for s in SITES}

THRESHOLDS: List[Dict[str, Any]] = [
    {"id": "person", "cm": 10.0, "hi": None, "label": "On foot", "icon": "person"},
    {"id": "snowmobile", "cm": 12.0, "hi": None, "label": "Snowmobile / ATV", "icon": "snowmobile"},
    {"id": "car", "cm": 20.0, "hi": 30.0, "label": "One car", "icon": "car"},
    {"id": "truck", "cm": 30.0, "hi": 38.0, "label": "Pickup / truck", "icon": "truck"},
]

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "site": {"default": "mississauga"},
    "node": {"mode": "indoor_demo", "serial_port": "", "baud": 115200, "snow_filter_s": 15, "node_token": ""},
    "ice": {
        "alpha_bare": 2.7,
        "alpha_low": 2.2,
        "alpha_high": 3.2,
        "snow_lambda_cm": 12.0,
        "snow_floor": 0.5,
    },
    "display": {"units": "metric", "reduce_motion": False},
    "server": {"host": "0.0.0.0", "port": 8000},
}

def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw

def _mini_toml(text: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    section: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = out.setdefault(line[1:-1].strip(), {})
        elif "=" in line and section is not None:
            k, v = line.split("=", 1)
            section[k.strip()] = _parse_value(v)
    return out

def _read_toml(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import tomllib

        return tomllib.loads(text)
    except ImportError:
        return _mini_toml(text)
    except Exception:
        return {}

def load_config(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    cfg = copy.deepcopy(DEFAULTS)
    user = _read_toml(path or (ROOT / "config.toml"))
    for sec, vals in user.items():
        if isinstance(vals, dict):
            cfg.setdefault(sec, {}).update(vals)
    if os.environ.get("COLDCASE_PORT"):
        try:
            cfg["server"]["port"] = int(os.environ["COLDCASE_PORT"])
        except ValueError:
            pass
    if cfg["site"].get("default") not in SITE_BY_ID:
        cfg["site"]["default"] = "mississauga"
    return cfg
