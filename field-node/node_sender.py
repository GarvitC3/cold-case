#!/usr/bin/env python3
import os, sys, time, json, termios, argparse, urllib.request

p = argparse.ArgumentParser()
p.add_argument("--url", required=True)
p.add_argument("--port", default="/dev/serial0")
p.add_argument("--node", default="field")
p.add_argument("--backlog", default="/dev/shm/node_backlog.jsonl")
a = p.parse_args()

def open_serial(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY)
    t = termios.tcgetattr(fd)
    t[0] = 0
    t[1] = 0
    t[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    t[3] = 0
    t[4] = t[5] = termios.B115200
    t[6][termios.VMIN] = 1
    t[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, t)
    termios.tcflush(fd, termios.TCIFLUSH)
    return os.fdopen(fd, "rb")

def post(obj):
    req = urllib.request.Request(a.url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return 200 <= r.status < 300

def save(obj):
    try:
        if os.path.exists(a.backlog) and os.path.getsize(a.backlog) > 2000000:
            os.remove(a.backlog)
        with open(a.backlog, "a") as f:
            f.write(json.dumps(obj) + "\n")
    except Exception:
        pass

def flush_backlog():
    if not os.path.exists(a.backlog):
        return
    with open(a.backlog) as f:
        lines = f.read().splitlines()
    sent = 0
    for ln in lines[:20]:
        try:
            obj = json.loads(ln)
        except ValueError:
            sent += 1
            continue
        try:
            post(obj)
        except Exception:
            break
        sent += 1
    rest = lines[sent:]
    if rest:
        with open(a.backlog, "w") as f:
            f.write("\n".join(rest) + "\n")
    else:
        os.remove(a.backlog)

ser = open_serial(a.port)
print("reading", a.port, "->", a.url, flush=True)
seq = 0
while True:
    raw = ser.readline()
    try:
        d = json.loads(raw.decode("utf-8", "ignore"))
    except ValueError:
        continue
    if not isinstance(d, dict):
        continue
    seq += 1
    d.update({"node": a.node, "seq": seq, "t": round(time.time(), 1)})
    try:
        post(d)
        print("sent", d, flush=True)
        try:
            flush_backlog()
        except Exception:
            pass
    except Exception as e:
        save(d)
        print("offline, saved:", e, flush=True)
