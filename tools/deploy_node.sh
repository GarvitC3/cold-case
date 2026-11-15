#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${1:-}"
[ -n "$URL" ] || { echo "usage: $0 http://<pi4-address>:8000/api/node[?token=...]"; exit 2; }
case "$URL" in http://*/api/node*) ;; *) echo "URL must look like http://IP:8000/api/node"; exit 2;; esac
ZERO="${ZERO:-hecker@field.local}"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
ESC_URL="$(printf '%s' "$URL" | sed -e 's/[\\&|]/\\&/g')"
sed -e "s|http://GRAVITY_IP_OR_NAME:PORT/api/node|$ESC_URL|" field-node/node-sender.service > "$TMP"
echo "==> copying to $ZERO"
scp -q field-node/node_sender.py "$ZERO:node_sender.py"
scp -q "$TMP" "$ZERO:node-sender.service"
echo "==> installing and restarting"
ssh -t "$ZERO" "sudo cp ~/node-sender.service /etc/systemd/system/node-sender.service && sudo systemctl daemon-reload && sudo systemctl enable node-sender >/dev/null 2>&1 && sudo systemctl restart node-sender && sleep 3 && systemctl --no-pager --lines=6 status node-sender"
echo "==> done. On the Pi 4, the link chip should turn green within a few seconds."
