# COLD CASE

*Is winter still cold enough to make safe ice — and how does this winter compare with every one since 1981?*

A touchscreen instrument for NASA Space Apps 2026 ("Be An Earth System Trend Detective!"): **NASA POWER daily
temperature** + a **field node** (ultrasonic snow depth) → **Stefan ice model** → *how thick is the ice, and is that
normal?* Every number wears its source colour — **NASA = cobalt · FIELD NODE = amber · MODEL = ice-violet · NORMAL = grey-blue** —
and tapping any number opens a Trace drawer showing exactly where it came from.

> **Status: feature-complete.** NOW · SEASON · TREND, on real NASA data; Pi install + kiosk scripts; story mode; touch-only UI audited for a 7" screen; optional **wireless field node** (Pi Zero W -> Wi-Fi -> this Pi, `docs/FIELD_NODE.md`). **Not yet run on the actual Pi** — see *Residual gaps*.

## Run it on the Pi (the real thing)
```bash
./deploy.sh                      # from your Mac: rsync to hecker@192.168.2.231:~/cold-case, installs on first run
# or on the Pi itself:
cd ~/cold-case && ./install.sh && sudo reboot
```
`install.sh` is idempotent: apt deps (only if missing), a venv that reuses the system numpy/scipy/pymannkendall, `dialout` group,
`cold-case.service` (systemd, restart-always), kiosk autostart (XDG + labwc), screen-blanking off. After reboot the app opens fullscreen by
itself. The **NASA cache ships in `data/cache/`**, so Wi-Fi is not needed. Optional refresh on the hotspot: `./.venv/bin/python prefetch.py`.

**Touchscreen only.** Nothing needs a keyboard or mouse. Tap the **link chip** for the field-node sheet; hold the **COLD CASE** title for 1 s for Settings (mode, node, ground level, site, sync, date, exit kiosk). Every tap target is >= 44 px, text is >= 12 px, neighbours are >= 8 px apart — enforced by
`tools/touch_audit.py` at 800x480, 1024x600, 1280x720 and 720x1280 (0 findings). The Touch Display 2 is natively portrait; rotate it in
Screen Configuration for landscape — both orientations are designed.

## Wireless field node (optional)
The Arduino can sit outside on a **Pi Zero W** that forwards its readings over 2.4 GHz Wi-Fi to `POST http://<this Pi>:8000/api/node` (home: `http://192.168.2.231:8000/api/node`).
USB and Wi-Fi go through the same parser; **Wi-Fi wins when both are alive, USB is the fallback**, late/replayed packets are stored but never shown as live.
The top bar's link chip (**green <= 10 s · amber <= 60 s · grey offline**) opens **Settings -> Field node**: addresses to give the Zero, the exact sender command, *Test link*, packet stats and the last 20 raw packets.
Wiring, flashing, hotspot and service install: `docs/FIELD_NODE.md` (+ `tools/deploy_node.sh`). Only private-LAN addresses may post; no other write endpoint is exposed to the LAN.

## Dev loop (Mac)
```bash
python3 -m venv .venv && .venv/bin/pip install numpy scipy pymannkendall pyserial pytest playwright
make dev                                 # simulated USB + simulated Wi-Fi node -> http://127.0.0.1:8000 (auto-restarts on edits)
./dev.sh                                 # simulated USB node only
./dev.sh --today 2026-02-10              # pretend it is mid-winter (real NASA data, truncated to today-3)
.venv/bin/python -m pytest tests -q      # 160+ tests incl. tests/test_wireless.py
.venv/bin/python tools/sim_wireless.py --scenario chaos   # dropouts, duplicates, garbage, oversize, floods against a running app
.venv/bin/python tools/link_shots.py     # link chip in green / amber / offline + Settings -> Field node (~85 s)
.venv/bin/python tools/screenshot.py --scenario winter --sizes 800x480 --screens now,season,trend
.venv/bin/python tools/touch_audit.py    # tap-target / text-size / gap audit
.venv/bin/python tools/perf.py           # fps under 1x/4x/6x/12x CPU throttle + auto-degrade
.venv/bin/python tools/resilience.py     # kill the backend under a live page; it must recover by itself
.venv/bin/python tools/soak.py 30        # soak with USB + Wi-Fi sim nodes at 40x (writes docs/SOAK.txt)
```
Keyboard shortcuts exist only for presenting from a laptop: `1`-`3` screens, `S` story tour.

## Judging-criteria map
| Criterion | What earns it here |
|---|---|
| **Impact** | Winter roads / lake ice as the human-scale consequence; ice-up-date metric; clear "so what" (cited sources in `docs/IMPACT.md`; confirm wording before quoting) |
| **Creativity** | Lake cross-section driven by live snow; NASA + node fusion nowcast; tap-to-trace |
| **Validity** | Daily NASA POWER; tested trend engine with honest verdicts (FRAGILE / NO TREND reported as found); referenced Stefan model with uncertainty band; bias tracker; limits stated in the Trace drawer |
| **Relevance** | Answers "what is changing, where, by how much, is it significant" with NASA data |
| **Presentation** | Touch-first UI, 60-second pitch + 3-minute walkthrough (`docs/DEMO_SCRIPT.md`), story mode, screenshots at 4 sizes |

## Troubleshooting
* **Blank / "No NASA data yet"** -> `./.venv/bin/python prefetch.py` (needs internet).  **Node offline** -> tap the link chip: USB reconnects by itself (`/dev/ttyUSB*`/`ttyACM*`); for Wi-Fi run *Test link* and `journalctl -u node-sender -f` on the Zero.
* **"Clock unverified" banner** -> Settings -> Date (the Pi has no RTC).  **Snow shows "—"** -> Settings or the Snow tile -> *Set ground level*.
* **Logs:** `journalctl -u cold-case -f` and `data/logs/coldcase.log`.  **Leave kiosk:** Settings -> Exit kiosk (or SSH `pkill -f coldcase-chrome`).
* **Temperature shows "out of sensor range" outdoors:** expected — the DHT11 cannot read below 0 C; a DS18B20 probe is the field fix (tap a number on NOW -> Trace drawer).

## Honesty notes
* `--sim` / `--sim-wireless` / `tools/sim_wireless.py` produce a **SIMULATED** node; everything they feed is badged. Nothing on screen is typed in by hand.
* POWER temperature is model-based reanalysis, not a thermometer. Ice thickness is **modelled** (simplified Stefan law + snow factor, with an uncertainty band). *No ice is safe ice.*

## Known limitations
* **The wireless path has not been run on the real Zero + Pi 4.** It is tested end to end against the real endpoint with simulated packets (`tests/test_wireless.py`, `tools/sim_wireless.py`); the divider wiring, serial setup and power-bank runtime are untested hardware steps.
* **Not yet run on the real Pi / display / node.** `install.sh`, `kiosk.sh` and the systemd unit are syntax-checked (`bash -n`) but untested on Pi OS; Wayland/labwc autostart in particular must be confirmed after the first reboot.
* **Performance numbers are from a Mac (Chrome, CPU-throttled)**, not a Pi 4. See `docs/PERF.txt`.
* **Model limitation (no freeze-up delay):** modelled early-winter ice and first-ice dates run early, most at the northern sites.
* Cut on purpose (scope lock): Time Machine and Proof screens, custom lat/lon, imperial units, DS18B20 firmware v2, ECCC station cross-check.

## Repo layout
`app/` backend (nasa, fdd, model, nowcast, trend, node, netinfo, store, core, server) · `field-node/` Zero sender + service · `web/` frontend (no CDN, Inter self-hosted) · `tests/` 160+ tests ·
`tools/` screenshot, link_shots, sim_wireless, deploy_node.sh, touch audit, perf, resilience, soak · `deploy/` + `install.sh` `kiosk.sh` `deploy.sh` · `data/cache/` NASA cache ·
`docs/` screens, demo script, impact, perf results · `reference/` the v1 files

Credits: NASA POWER (CC BY 4.0) · Lifesaving Society ice thresholds · Stefan / Michel / USACE / Seidou et al. · Ed Hawkins' warming stripes (CC BY 4.0) · Inter (OFL).
