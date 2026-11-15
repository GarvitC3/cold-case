#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PI="${PI:-hecker@192.168.2.231}"
DEST="${DEST:-cold-case}"
echo "==> syncing to $PI:~/$DEST"
rsync -az --delete \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'data/coldcase.sqlite3*' --exclude 'data/logs' --exclude 'docs/screens' \
  ./ "$PI:$DEST/"
echo "==> restarting service (installing first if this is a fresh Pi)"
ssh -t "$PI" "cd ~/$DEST && if systemctl list-unit-files | grep -q '^cold-case.service'; then sudo systemctl restart cold-case && systemctl --no-pager --lines=5 status cold-case; else ./install.sh; fi"
echo "==> done. The app listens on 0.0.0.0:8000 (private LAN only): http://${PI#*@}:8000 from a laptop. Wireless node URL: http://${PI#*@}:8000/api/node"
