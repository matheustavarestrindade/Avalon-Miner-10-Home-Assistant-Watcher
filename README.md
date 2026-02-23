# Avalon Miner Watcher for Home Assistant

A Home Assistant custom integration that monitors and controls **Canaan Avalon miners** (tested on the Avalon 1045) directly over the local network using the cgminer TCP API protocol (port 4028).

## Features

- **Live monitoring** — hashrate, temperature, power draw, fan speed, pool info, per-board frequencies, and more, refreshed every 30 seconds
- **Per-miner configuration** — set frequency zones (4 zones per miner), voltage level, and hash board target from the HA UI
- **Auto-start hashing** — when a miner comes back online, the integration automatically pushes your saved frequency + voltage profile to it
- **Control entities** — start/stop hashing switch, reboot button, soft-shutdown button
- **HACS compatible** — install as a standard custom repository

---

## Requirements

- Home Assistant 2026.2.2 or newer
- Avalon miner reachable on your local network with **port 4028 open** (cgminer API port)
- No extra Python packages required — uses only the standard library (`asyncio`, `socket`)

---

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/matheustavarestrindade/Avalon-Miner-10-Home-Assistant-Watcher` as type **Integration**
3. Search for **Avalon Miner Watcher** and install it
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/avalon_miner` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Avalon Miner Watcher**
3. Enter the **IP address** of your miner (port defaults to `4028`)
4. On the next screen, configure the startup profile:

| Field | Description | Default |
|---|---|---|
| Frequency Zone 1 (MHz) | Lowest ASIC clock zone | 325 |
| Frequency Zone 2 (MHz) | Second zone | 337 |
| Frequency Zone 3 (MHz) | Third zone | 350 |
| Frequency Zone 4 (MHz) | Highest zone | 362 |
| Voltage Level | Hardware voltage-level units (0–60) | 25 |
| Hash Board Number | Board index to apply settings to (0 = all) | 0 |
| Auto-start hashing | Push config automatically when miner reconnects | ✅ |

> Frequencies must be in strictly ascending order (Zone 1 < Zone 2 < Zone 3 < Zone 4).  
> Valid frequency values are the 69 clock steps supported by Avalon ASICs (25, 300, 312, 325 … 1200 MHz).

You can re-configure all options at any time via **Settings → Integrations → Avalon Miner → Configure**.

---

## Entities

Each miner gets its own **Device** entry in HA. The following entities are created:

### Sensors

| Entity | Unit | Description |
|---|---|---|
| Hashrate (Average) | MH/s | Long-running average hashrate |
| Hashrate (30s) | MH/s | Rolling 30-second hashrate |
| Hashrate (1m) | MH/s | Rolling 1-minute hashrate |
| Temperature (Intake) | °C | Ambient intake temperature |
| Temperature (Average) | °C | Average across all sensors |
| Temperature (Max) | °C | Peak temperature recorded |
| Output Power | W | Power delivered to hash boards |
| Hash Board Voltage | V | Voltage at the hash boards |
| Output Current | A | Current to hash boards |
| Fan 1 Speed | RPM | First fan speed |
| Fan 2 Speed | RPM | Second fan speed |
| Fan Duty Cycle | % | Fan PWM duty cycle |
| Accepted Shares | — | Total accepted shares |
| Rejected Shares | — | Total rejected shares |
| Hardware Errors | — | ASIC-level hardware error count |
| Best Share | — | Best share submitted |
| Pool Rejected % | % | Pool-side reject percentage |
| Uptime | s | Seconds since miner started |
| Pool URL | — | Active pool address |
| Pool User | — | Pool worker username |
| Pool Status | — | Pool connection status (Alive / Dead) |
| Firmware Version | — | Miner firmware string |
| Model | — | Controller model number |
| MAC Address | — | Miner MAC address |
| Board N Freq Zone 1–4 | MHz | Per-board frequency zones (created dynamically) |
| Board N Hashrate | MH/s | Per-board hashrate (created dynamically) |

### Switch

| Entity | Description |
|---|---|
| Hashing | Turn hashing ON (applies saved frequency + voltage) or OFF (shuts down hash power) |

### Number (editable)

| Entity | Range | Description |
|---|---|---|
| Frequency Zone 1 | 25–1200 MHz | Live-editable ASIC clock zone 1 |
| Frequency Zone 2 | 25–1200 MHz | Live-editable ASIC clock zone 2 |
| Frequency Zone 3 | 25–1200 MHz | Live-editable ASIC clock zone 3 |
| Frequency Zone 4 | 25–1200 MHz | Live-editable ASIC clock zone 4 |
| Voltage Level | 0–60 | Live-editable hardware voltage level |

Changing a number entity sends the command **immediately** to the miner and persists the value to the config entry so it survives restarts.

### Buttons

| Entity | Description |
|---|---|
| Reboot Miner | Triggers a full hardware reboot |
| Soft Shutdown | Triggers an OS-level software shutdown |

---

## How it works

The integration communicates with the miner over a **raw TCP socket on port 4028** using the cgminer API text protocol — the same protocol used by the official Avalon firmware.

- **Poll cycle**: every **30 seconds** the coordinator queries `estats`, `summary`, `pools`, `version`, and `ascset|0,hashpower` to build a complete snapshot.
- **Health detection**: each poll starts with a lightweight TCP probe (400 ms timeout). If the miner is unreachable all entities become `unavailable`.
- **Auto-start on reconnect**: when a miner transitions from offline to online and `auto_start` is enabled, the integration waits for `MHS 30s > 5` (up to 10 attempts, 10 s apart) then pushes `fan enable → set voltage → set frequency`. This mirrors the behaviour of the original TypeScript implementation.

---

## Supported Models

Developed and tested against the **Avalon 1045**. Any Avalon miner running cgminer firmware with the `ascset` command set should work (Avalon 10xx series).

---

## License

MIT
