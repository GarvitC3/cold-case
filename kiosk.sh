#!/usr/bin/env bash
URL="${COLDCASE_URL:-http://127.0.0.1:8000/?kiosk=1}"
STOP=/tmp/coldcase-kiosk.stop
exec 9>/tmp/coldcase-kiosk.lock
flock -n 9 || exit 0
rm -f "$STOP"

for _ in $(seq 1 90); do curl -fs -o /dev/null "http://127.0.0.1:8000/api/state" && break; sleep 1; done

(xset s off; xset -dpms; xset s noblank) >/dev/null 2>&1 || true
command -v raspi-config >/dev/null && sudo -n raspi-config nonint do_blanking 1 >/dev/null 2>&1 || true

BROWSER=$(command -v chromium || command -v chromium-browser || true)
[ -z "$BROWSER" ] && { echo "no chromium found" >&2; exit 1; }

while [ ! -e "$STOP" ]; do
  "$BROWSER" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito \
    --autoplay-policy=no-user-gesture-required --check-for-update-interval=31536000 \
    --no-first-run --disable-translate --disable-pinch --overscroll-history-navigation=0 \
    --user-data-dir=/tmp/coldcase-chrome "$URL"
  [ -e "$STOP" ] && break
  sleep 2
done
