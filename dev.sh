#!/usr/bin/env bash
cd "$(dirname "$0")"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
STAMP=$(mktemp)
trap 'kill $PID 2>/dev/null; rm -f "$STAMP"; exit 0' INT TERM
echo "COLD CASE dev server -> http://127.0.0.1:8000   (Ctrl-C to stop)"
while true; do
  touch "$STAMP"
  $PY -m app --sim "$@" & PID=$!
  while kill -0 $PID 2>/dev/null; do
    sleep 1
    if [ -n "$(find app -name '*.py' -newer "$STAMP" 2>/dev/null | head -1)" ]; then
      echo "backend code changed - restarting"; kill $PID 2>/dev/null; break
    fi
  done
  wait $PID 2>/dev/null
  sleep 0.5
done
