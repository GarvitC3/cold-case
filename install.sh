#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
APPDIR="$(pwd)"; ME="$(id -un)"
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
[ "$ME" = root ] && { echo "Run as your normal user (it uses sudo where needed)."; exit 1; }

say "1/7  System packages (skipped if already present / offline)"
NEED=""
for pkg in python3-serial python3-numpy python3-scipy python3-venv curl util-linux; do dpkg -s "$pkg" >/dev/null 2>&1 || NEED="$NEED $pkg"; done
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  apt-cache show chromium >/dev/null 2>&1 && NEED="$NEED chromium" || NEED="$NEED chromium-browser"
fi
if [ -n "$NEED" ]; then
  echo "installing:$NEED"
  sudo apt-get update -qq || echo "(apt update failed — offline? trying anyway)"
  sudo apt-get install -y $NEED || { echo "!! could not install:$NEED — connect to the internet and re-run"; exit 1; }
else echo "all present"; fi

say "2/7  Python environment (system-site-packages so the already-installed numpy/scipy/pymannkendall are reused)"
[ -d .venv ] || python3 -m venv --system-site-packages .venv
if ! .venv/bin/python -c "import pymannkendall" 2>/dev/null; then
  .venv/bin/pip install --quiet pymannkendall || .venv/bin/pip install --quiet --break-system-packages pymannkendall || {
    echo "!! pymannkendall missing and no internet. Run once on the hotspot:  pip install --break-system-packages pymannkendall"; exit 1; }
fi
.venv/bin/python -c "import numpy, scipy, serial, pymannkendall; print('python deps ok')"

say "3/7  Serial access (dialout group)"
id -nG "$ME" | grep -qw dialout || { sudo usermod -aG dialout "$ME"; echo "added $ME to dialout (takes effect after reboot)"; }

say "4/7  NASA cache"
if ls data/cache/power_*.json >/dev/null 2>&1; then echo "cache present: $(ls data/cache/power_*.json | wc -l) sites"
else echo "no cache - fetching (needs internet)"; .venv/bin/python prefetch.py || echo "!! prefetch failed - run ./.venv/bin/python prefetch.py on the hotspot"; fi

say "5/7  systemd service (auto-restart on crash)"
sed -e "s#@USER@#$ME#g" -e "s#@APPDIR@#$APPDIR#g" deploy/cold-case.service | sudo tee /etc/systemd/system/cold-case.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable cold-case >/dev/null
sudo systemctl restart cold-case
sleep 2; systemctl is-active cold-case

say "6/7  Kiosk autostart (XDG autostart works on both Wayfire and labwc)"
chmod +x kiosk.sh deploy.sh install.sh
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/cold-case-kiosk.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Cold Case kiosk
Exec=$APPDIR/kiosk.sh
X-GNOME-Autostart-enabled=true
DESK
if [ -d "$HOME/.config/labwc" ] || command -v labwc >/dev/null; then
  mkdir -p "$HOME/.config/labwc"
  grep -q "cold-case/kiosk.sh\|$APPDIR/kiosk.sh" "$HOME/.config/labwc/autostart" 2>/dev/null || echo "$APPDIR/kiosk.sh &" >> "$HOME/.config/labwc/autostart"
fi
sudo raspi-config nonint do_blanking 1 2>/dev/null && echo "screen blanking disabled" || echo "(could not disable blanking via raspi-config; kiosk.sh also tries xset)"

say "7/7  Check"
curl -fs http://127.0.0.1:8000/api/state >/dev/null && echo "backend answers on :8000" || echo "!! backend not answering yet: journalctl -u cold-case -n 30"

cat <<MSG

Done. Next:
  sudo reboot
Display notes:
  * Touch Display 2 is natively portrait (720x1280). For landscape: Screen Configuration (Preferences) -> rotate 90 deg,
    or add  display_auto_detect=1  + video=DSI-1:720x1280@60,rotate=90  to /boot/firmware/cmdline.txt.
    Portrait also works: the layout adapts.
  * Logs:   journalctl -u cold-case -f      and      data/logs/coldcase.log
  * Settings: hold the COLD CASE title for 1 second.   Leave kiosk: Settings -> Exit kiosk.
  * Phone/laptop view: set host = "0.0.0.0" in config.toml (viewers are read-only), then sudo systemctl restart cold-case
MSG
