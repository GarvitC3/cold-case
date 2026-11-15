# Wireless field node (Pi Zero W -> Pi 4)

The Arduino (HC-SR04 snow depth + DHT11) can sit **outside** on a Raspberry Pi Zero W, while the Pi 4 ("gravity") with the 7" screen stays inside.
The Zero reads the Arduino's JSON lines, adds `node`, `seq` and `t`, and POSTs them over Wi-Fi to the Pi 4. The Pi 4 feeds them through the **same
parser and validation** as a USB cable, so everything downstream (snow filter, calibration, nowcast, bias tracker, CSV) is identical.

```
  Arduino Uno                                   Raspberry Pi Zero W (hostname: field, user: hecker)
  ┌──────────┐                                  ┌────────────────────────┐
  │       TX ├──[10 kΩ]──┬──────────────────────┤ GPIO15 / RXD   (pin 10)│   2.4 GHz Wi-Fi ))))  Pi 4 :8000/api/node
  │          │           │                      │                        │
  │          │         [10 kΩ]                  │                        │
  │          │           │                      │                        │
  │      GND ├───────────┴──────────────────────┤ GND            (pin 6) │
  │       5V ├──────────────────────────────────┤ 5V             (pin 2) │
  │       RX │  (not connected)                 │ GPIO14 / TXD   (pin 8) │  (not connected)
  └──────────┘                                  └────────────────────────┘
  HC-SR04 and DHT11 stay wired to the Arduino exactly as before.      Power bank --USB--> Zero (PWR IN)
```
* The **10 k / 10 k divider** drops the Arduino's 5 V TX to ~2.5 V, which the Zero's 3.3 V RXD reads as a clean high. Never connect 5 V directly to a GPIO.
* The Zero's **5 V pin powers the Arduino** (the Arduino is *not* also plugged into USB). Common **GND** is mandatory.
* Nothing needs to go from the Zero back to the Arduino, so Zero TXD stays free.

> **The Zero W is 2.4 GHz only.** A phone hotspot set to 5 GHz-only (or "5 GHz band" / "Extended compatibility off") will never show up. Set the hotspot to **2.4 GHz** (iPhone: *Maximize Compatibility* on).

## 1. Flash the Zero (Raspberry Pi Imager)
* **Device:** Raspberry Pi Zero  ·  **OS:** Raspberry Pi OS (other) -> **Raspberry Pi OS Lite (32-bit)**
* Edit settings: **hostname `field`**, **username `hecker`** (+ a password), **SSH on**, your **home Wi-Fi** (2.4 GHz), **Wi-Fi country `CA`**.

## 2. Enable the serial port, then check the wiring
```bash
ssh hecker@field.local
sudo raspi-config nonint do_serial_hw 0      # serial hardware ON
sudo raspi-config nonint do_serial_cons 1    # login console on serial OFF
sudo reboot
```
After the reboot, with the Arduino powered and wired:
```bash
stty -F /dev/serial0 115200 raw; timeout 8 cat /dev/serial0
# expect a line about every 2 s, e.g.  {"temp_c":21.40,"rh":41.00,"dist_cm":36.17}
```
Garbled characters? Add `dtoverlay=disable-bt` to `/boot/firmware/config.txt` (gives the good UART back from Bluetooth) and reboot. This is only needed if the data is garbled.

## 3. Find the Pi 4's address
On the Pi 4 open **Settings -> Field node -> Link & setup** (or just tap the green/amber/grey link chip in the top bar). It prints the Pi 4's LAN address(es) and port and the exact sender command to copy.
At home the Pi 4 is `hecker@192.168.2.231`, so the URL is:

```
http://192.168.2.231:8000/api/node
```
**The address changes when the network changes** (home Wi-Fi vs the venue hotspot). Always re-read it from that sheet at the venue; `.local` names are convenient but can fail, so the service uses an IP.

## 4. Install the sender on the Zero
From this repo on your computer (does steps 4 and 5 for you; re-run it any time the Pi 4's address changes):
```bash
tools/deploy_node.sh http://192.168.2.231:8000/api/node          # copies node_sender.py + service to hecker@field.local, enables, restarts
```
Or by hand:
```bash
scp field-node/node_sender.py hecker@field.local:~/
scp field-node/node-sender.service hecker@field.local:~/
ssh hecker@field.local
sed -i 's#GRAVITY_IP_OR_NAME:PORT#192.168.2.231:8000#' ~/node-sender.service
sudo cp ~/node-sender.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now node-sender
journalctl -u node-sender -f          # "sent {...}" lines = it works;  "offline, saved: ..." = the Pi 4 is unreachable (it buffers and retries)
```
Optional shared secret: put `node_token = "something"` under `[node]` in the Pi 4's `config.toml`, restart, and end the URL with `/api/node?token=something`
(the sender only takes a URL, so the token travels in the query string; the sheet prints it for you). Default is **off**.

## 5. Add the venue hotspot BEFORE leaving home
Do this with the hotspot **off**, while the Zero is still on your home network, so it joins by itself on site:
```bash
sudo nmcli connection add type wifi con-name hotspot ssid "NAME" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "PASS"
nmcli connection show            # "hotspot" should be listed
```
Put the Pi 4 on the same hotspot. Then read its new address in **Link & setup** and re-run `tools/deploy_node.sh <new URL>`.

## 6. Shutting down
**Always `sudo shutdown -h now` on the Zero before cutting power** (SD cards corrupt when power is yanked). Wait for the green LED to stop flashing.

## What the Pi 4 does with a packet
| Rule | Behaviour |
|---|---|
| Who may post | `POST /api/node` from private-LAN addresses only (10/8, 172.16/12, 192.168/16, 169.254/16, loopback). Anyone else: 403. It is the **only** write endpoint the LAN can use. |
| Size / rate | Body <= 2 KB (413 otherwise, body unread), 40 req/s per address (429), 8 in flight (503). |
| Garbage | 400. Same tolerant parser as USB: null / NaN / -1 / 0 distance, missing keys, DHT11 limited to 0-50 C (below that the temperature stays empty). |
| Live source | **Wi-Fi if its last sample is <= 10 s old, else USB if <= 10 s old, else "no node".** The active source keeps the job; USB->Wi-Fi needs Wi-Fi steady for >= 5 s (and >= 5 s since the last switch) so it never flaps. Only one source drives the tiles; the Trace drawer says which. |
| Late data | A packet whose `t` is > 30 s older than its arrival is **historical**: stored at its own timestamp (bias tracker, CSV) and **never shown as live**. De-duplicated on (node, t). Backlog older than 3 days is dropped. |
| Wrong clock | The Zero has no RTC. If `t` is before 2026 or > 5 min ahead of the Pi 4, the receipt time is stored instead and the packet is flagged `clock_suspect`. (The Zero fixes itself via NTP once it is online; the first packets after boot may be flagged.) |
| Ground level | Calibrated **per source**. Moving the sensor onto the Zero changes its height: the app asks for a new *Set ground level* instead of silently showing wrong snow depths. |
| Node vanishes | Tiles go empty after 10 s, the nowcast falls back to NASA + model, the chip turns amber (<= 60 s) then grey. When packets resume it recovers with no restart. |
| Simulated | Nodes named `sim...` (`--sim-wireless`, `tools/sim_wireless.py`) are badged **SIMULATED** everywhere. |

**Link chip (top bar):** `Field node · Wi-Fi · 2 s ago` - green <= 10 s, amber <= 60 s, grey "offline" beyond that with the last-seen age. Tap it for details.
**Settings -> Field node:** both links, the Pi 4's addresses and the sender command, **Test link**, packets per minute / duplicates / rejected, and the last 20 raw packets.

**Test link** posts a harmless `selftest` packet from the Pi 4 to each of its own addresses. It proves the app listens on that address (and the token rules work); it cannot prove the Zero's Wi-Fi. From the Zero, the sheet also prints a `curl` line that does the real end-to-end check.

## Try it without hardware
```bash
make dev                                   # simulated USB node + simulated Wi-Fi node, both badged SIMULATED (watch arbitration)
make dev-wireless                          # Wi-Fi only
python tools/sim_wireless.py --scenario chaos   # dropouts, duplicates, out-of-order bursts, garbage, oversize, bad token, flood
.venv/bin/python tools/link_shots.py       # photographs the chip in green / amber / offline
```

## Known limits
* **DHT11 reads 0-50 C only.** Outdoors in winter the temperature stays empty ("out of sensor range"); a DS18B20 probe is the fix. Snow depth is unaffected.
* **No battery readout** anywhere (out of scope). **Power-bank runtime is unmeasured**; some banks switch off when the draw is very low, so test yours overnight before relying on it.
* A backlog replayed by a Zero whose clock is wrong cannot be told apart from fresh data (it is treated as live and flagged `clock_suspect`).
* Wi-Fi range, hotspot sleep timers and phone battery savers are outside our control. If the chip is amber, check the hotspot first.
