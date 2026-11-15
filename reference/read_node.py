import json
import sys

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

with serial.Serial(port, 115200, timeout=3) as s:
    while True:
        line = s.readline().decode(errors="ignore").strip()
        if not line.startswith("{"):
            continue
        try:
            print(json.loads(line))
        except ValueError:
            pass
