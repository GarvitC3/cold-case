from __future__ import annotations

import hmac
import ipaddress
import re
import socket
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

_LAN_NETS = [ipaddress.ip_network(n) for n in
             ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8")]

def is_loopback(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(_unmap(addr))
    except ValueError:
        return False
    return ip.is_loopback

def _unmap(addr: str) -> str:
    a = (addr or "").strip()
    return a[7:] if a.lower().startswith("::ffff:") else a

def is_lan_addr(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(_unmap(addr))
    except ValueError:
        return False
    if ip.version == 6:
        return ip.is_loopback
    return any(ip in n for n in _LAN_NETS)

def token_ok(configured: str, header: Optional[str], query: Optional[str]) -> bool:
    if not configured:
        return True
    for given in (header, query):
        if given and hmac.compare_digest(str(given).encode(), str(configured).encode()):
            return True
    return False

class RateLimiter:

    def __init__(self, rate: float = 40.0, burst: float = 80.0, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.b: Dict[str, Tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            tokens, last = self.b.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            ok = tokens >= 1.0
            self.b[key] = (tokens - 1.0 if ok else tokens, now)
            if len(self.b) > 256:
                for k in [k for k, (_, t) in self.b.items() if now - t > 60]:
                    self.b.pop(k, None)
            return ok

_IP4 = re.compile(r"\binet (\d+\.\d+\.\d+\.\d+)")

def lan_addresses() -> List[Dict[str, str]]:
    found: List[Tuple[str, str]] = []
    for cmd in (["ip", "-4", "-o", "addr", "show", "scope", "global"], ["ifconfig"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        iface = ""
        for line in out.splitlines():
            if cmd[0] == "ip":
                parts = line.split()
                if len(parts) > 3 and "inet" in parts:
                    found.append((parts[1], parts[parts.index("inet") + 1].split("/")[0]))
            else:
                if line and not line[0].isspace():
                    iface = line.split(":")[0]
                m = _IP4.search(line)
                if m:
                    found.append((iface, m.group(1)))
        if found:
            break
    if not found:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            found.append(("?", s.getsockname()[0]))
            s.close()
        except OSError:
            pass
    out_l, seen = [], set()
    for iface, ip in found:
        if ip in seen or not is_lan_addr(ip) or is_loopback(ip):
            continue
        seen.add(ip)
        out_l.append({"iface": iface, "ip": ip})
    return out_l
