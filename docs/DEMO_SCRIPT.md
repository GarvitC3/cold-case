# Demo script (touch only — no keyboard, no mouse)

**Before judges arrive (2 min)**
1. Power the Pi + node. Wait ~20 s: the top bar shows **NASA · as of <date>**, the **link chip** (`Field node · USB · 1 s ago`, or `Wi-Fi` when the Pi Zero is the live source) and **INDOOR DEMO**.
2. **Set ground level:** point the sensor at the bare table, nothing under it -> NOW -> *Snow depth* tile -> **Set ground level** -> *Start* (5 s, remembered).
3. Slide a book under the sensor: the snow tile and the snow layer on the lake respond. Remove it.
> Wireless node: tap the **link chip** -> *Field node* sheet (addresses for the Zero, *Test link*, last packets). Unplug the Zero's power and watch the chip go green -> amber -> grey while the tiles empty on purpose; plug it back in and it recovers by itself. Details: `docs/FIELD_NODE.md`.
> Settings (mode, node, ground level, site, date, sync, exit kiosk): **hold the COLD CASE title for one second.** After 90 s idle the story tour plays; touch to stop it.

## 60-second pitch
| Time | Screen | Say | Touch |
|---|---|---|---|
| 0:00 | **NOW** | "Lake ice only exists if it stays cold long enough. NASA's temperature record says how much cold this winter has banked; our sensor adds snow on the ground, which NASA doesn't have; a physics model turns both into ice thickness." | Point at the lake. |
| 0:15 | **NOW** | "Blue is NASA, amber is our sensor, violet is the model." | Slide the book under the sensor. |
| 0:25 | **NOW** | "It's mid-November, so the honest answer is: still open water. NASA's last day is three days old — that gap is why the node exists." | Tap **Cold banked** -> Trace drawer. |
| 0:38 | **SEASON** | "This winter against 45 others." | Drag along the chart; tap **Coldest**. |
| 0:48 | **TREND** | "Season cold is falling at all five sites, but we put every trend on trial: mostly *fragile*, Moosonee *no trend*." | Tap the Mississauga row. |

## 3-minute walkthrough
1. **NOW (60 s)** — sensor on the shore measures snow; ice is *modelled* (band = our uncertainty); dashed line = normal for the date; ladder lights only when the *low end* of the band clears a threshold. Tap **Air temp**: indoor demo, never counted as climate data. Tap the big number: formula, inputs, sources, and the "no ice is safe ice" caveat.
2. **SEASON (60 s)** — blue solid = NASA-verified, shaded strip = days NASA hasn't published. Drag to read any day.
3. **TREND (60 s)** — stripes (Ed Hawkins' idea). Row -> tabs for season cold and the 20/30 cm ice-up date, four tests in words.

## If a judge asks
- **Is the ice measured?** No: snow depth and air temperature are; ice is modelled with a stated band.
- **Why 0 cm today?** Real: NASA POWER showed +9 C at Mississauga on 11 Nov.
- **Is this NASA data?** Yes: POWER daily T2M 1981 -> 11 Nov 2026, cached. It is a reanalysis, not a thermometer.
- **Is the node wired?** Either: USB, or a Pi Zero W on Wi-Fi (the chip says which). Both use the same validation; late packets are stored but never shown as live.
- **Why is the node indoors?** Demo mode; outdoors, flip it in Settings. The prototype DHT11 cannot read below 0 C (DS18B20 is the fix).
