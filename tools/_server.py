import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def post(url, path, body="{}"):
    r = urllib.request.Request(url + path, data=body.encode(), headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(r, timeout=5).read()

@contextlib.contextmanager
def backend(*flags, port=None, calibrate=True, logdir=None, flags_=(), sim=True):
    port = port or free_port()
    env = dict(os.environ, COLDCASE_LOGDIR=logdir or tempfile.mkdtemp())
    proc = subprocess.Popen([sys.executable, "-m", "app", "--port", str(port), "--db", tempfile.mktemp(suffix=".db"), "--offline", *(["--sim"] if sim else []), *flags, *flags_],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try: urllib.request.urlopen(url + "/api/state", timeout=1).read(); break
        except Exception: time.sleep(0.25)
    if calibrate:
        time.sleep(2.5); post(url, "/api/calibrate"); time.sleep(8.5)
    try:
        yield url, proc, env["COLDCASE_LOGDIR"]
    finally:
        proc.send_signal(signal.SIGTERM)
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
