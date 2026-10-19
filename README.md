# samsung-tui

A local terminal remote for Samsung **Tizen** TVs, built with
[Textual](https://textual.textualize.io/). It talks to the TV over your LAN —
no cloud, no account, no ADB.

Verified against a Samsung **CU7000** (2023, Tizen). Other Tizen models should
work; the interfaces used are standard.

<img width="1434" height="671" alt="image" src="https://github.com/user-attachments/assets/14d15afd-a712-4e94-877b-dd96985f41c9" />


## Why not ADB

Samsung TVs run **Tizen**, not Android. ADB is Android-only and cannot connect
to them. Enabling Developer Mode on a Samsung TV opens Tizen's `sdb` port
(`26101`), not an Android package manager — it still cannot disable preinstalled
apps. This app uses the two interfaces the TV actually exposes:

| Interface                                                  | Port | Used for                                                |
| ---------------------------------------------------------- | ---- | ------------------------------------------------------- |
| `http://<host>:8001/api/v2/`                               | 8001 | Device facts; `POST /api/v2/applications/<id>` launches |
| `wss://<host>:8002/api/v2/channels/samsung.remote.control` | 8002 | Keys and text                                           |

## Install

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/). The TV must be
on the same LAN. No developer mode is needed — the TV asks once to allow the
remote connection.

```sh
git clone <repo-url> samsung-tui
cd samsung-tui
uv sync
```

## Run

```sh
uv run samsung-tui
```

Options:

```sh
uv run samsung-tui --host 192.168.1.50   # override the saved address
uv run samsung-tui --probe               # print device info, then exit
uv run samsung-tui --scan                # find TVs on the LAN, then exit
uv run samsung-tui --reset-token         # forget the active TV's token
uv run samsung-tui --no-connect          # explore the UI without the TV
```

## First connection

1. Start the app. With no config yet, it initializes an empty one and **scans
   the LAN**, then shows a picker. Choose your TV.
2. The status bar shows `Connecting…` and the TV displays an **Allow** prompt.
   Accept it with the remote.
3. The token is saved to `~/.config/samsung-tui/config.json` (mode `0600`) and
   reused on later runs, so the prompt appears only once **per TV**. Records are
   keyed by the name the TV reports (for example `Living Room TV`), and the last
   selection is remembered in `active`: restarting reconnects to that set without
   a scan.

If you deny the prompt, or the token is rejected, the app reports it and
reconnects. Use `--reset-token` to pair again from scratch.

## What it can control

- **Navigation** — D-pad, OK, Back, Home, Exit
- **System** — Menu, Source, Guide, Power (toggle), Settings shortcut
- **Volume / channel** — up, down, mute; channel up/down
- **Playback** — rewind, play, pause, stop, fast-forward
- **Text entry** — types into the field focused on the TV (open a search box
  first)
- **App launch** — grid of ~140 apps, filterable by name or ID, plus a custom-ID
  field
- **Device info** — model, firmware, power state, resolution, network

Every command is logged in the **Log** tab, and incoming TV channel events are
logged too.

## What it cannot do

- **Read the screen.** Port 8002 carries no framebuffer and no UI state. There
  is no screenshot equivalent to `adb shell screencap`.
- **Power on from fully off.** There is no Wake-on-LAN on these sets; `Power`
  toggles a set that is still on its network standby.
- **Remove or disable preinstalled apps.** No package manager is exposed, and
  the system partition is signed and read-only.
- **List installed apps.** Many firmware versions answer neither
  `ed.installedApp.get` nor `/api/v2/applications`, so the launcher ships a
  curated catalog; a wrong ID fails silently.

## Service mode (destructive)

The **Service** tab exposes the documented Samsung entry sequence
(`MUTE 1 8 2 POWER`) behind a typed `SERVICE` confirmation, plus a free-form
key-sequence runner (max 40 keys).

Two honest limits:

- **Unverified.** The sequence is model/firmware-specific and has not been
  confirmed on this CU7000. If it does not match, the set just power-cycles.
- **No EEPROM automation.** `write EEPROM`, `ADC calibration`, and factory
  reset are *menu items inside service mode*, not key codes. The API can only
  press keys, and this channel cannot read the screen — so automating a choice
  inside that menu would be navigation without sight. The TUI opens the door;
  it does not walk through it.

Factory reset through the normal menu is `Settings → General y privacidad →
Restablecer` (default PIN `0000`); the TV runs its own confirmation.

## Finding TVs

The TV address does not have to be known up front.

```sh
uv run samsung-tui --scan                              # /24 of the active TV
uv run samsung-tui --scan --subnet 192.168.0.0/24      # explicit range
```

In the TUI, press **`ctrl+d`**. Two methods are unioned:

1. **SSDP** `ssdp:all` multicast to `239.255.255.250:1900` — fast, but some
   firmware suppresses the advertisement.
2. A bounded **TCP sweep of port 8001** across the /24 — slower, but catches
   TVs that ignore SSDP.

Every candidate is then confirmed with `GET /api/v2/` and must report
`device.type == "Samsung SmartTV"`, so phones, routers and NAS boxes never
appear. Picking a TV records it under its own name, stores that address,
marks it `active`, and reconnects — reusing its token if it has one, otherwise
prompting once on that set.

## Config

`~/.config/samsung-tui/config.json` (mode `0600`) holds only TV state:

```json
{
  "active": "Living Room TV",
  "tvs": {
    "Living Room TV": {"host": "192.168.1.50", "token": "…"},
    "Bedroom TV": {"host": "192.168.1.60", "token": "…"}
  }
}
```

- **`tvs`** — one record per set, keyed by the name from `/api/v2/`, each with
  its own address and token.
- **`active`** — the TV selected last. On start the app connects to it directly;
  `ctrl+d` changes it and rewrites `active`. With no `active` TV the app scans
  instead of guessing an address.
- If a TV's DHCP address changes, pick it again from `ctrl+d` (or edit its
  `host`); the token follows the **name**, so it does not re-pair.
- `--reset-token` clears the token for the **active** TV only.

## App catalog

The ID catalog lives in **code**, not config: `src/samsung_tui/apps.py` holds
~140 applications, sourced from
[tavicu/homebridge-samsung-tizen](https://tavicu.github.io/homebridge-samsung-tizen/extra/applications.html).

The **Apps** tab is a grid of buttons ordered by name, filterable by name or ID;
**Enter** launches the top match, or click any button.

Launching uses `POST /api/v2/applications/<id>`, which answers `true` on this
firmware, and falls back to the `ed.apps.launch` WebSocket event if the endpoint
refuses. The **Log** tab labels the path actually used: `(REST)` or `(WS)`.

Each entry keeps every ID the source lists, because many IDs changed starting
with 2020 models. The app launches the **rightmost (newest)** ID by default,
which is what a 2023 set expects. If an app still does not open, find its row
and paste one of the alternates into the custom-ID field.

## Keys

| Binding  | Action                  |
| -------- | ----------------------- |
| `ctrl+q` | Quit                    |
| `ctrl+r` | Reconnect               |
| `ctrl+d` | Discover TVs on the LAN |
| `f5`     | Refresh device info     |
| `ctrl+l` | Clear log               |

## Reversibility

The app itself does not modify TV settings: it sends remote keys, text, and
app-launch requests, and reads `/api/v2/`. It does not install, uninstall, or
persist anything on the TV.

The **Service** tab is the exception by nature: sequences sent there act on the
real set. Nothing inside service mode is reversible by this app.

To remove the app's pairing from the TV, delete the entry under
**Settings → General y privacidad → Administrador de dispositivos → Lista de
dispositivos externos** (the device name is `samsung-tui`), and delete
`~/.config/samsung-tui/` on this machine.

## Development

```sh
uv run python scripts/smoke.py                  # headless UI + config tests
uv run python scripts/screenshot.py out.svg     # render the UI to SVG
uv run --with ruff ruff check src scripts
```

## License

MIT. See [LICENSE](LICENSE).

## Layout

```
src/samsung_tui/
  app.py        Textual UI and event loop
  tv.py         WebSocket client + REST probe (threaded)
  discovery.py  SSDP + port-8001 sweep, validated via /api/v2/
  apps.py       embedded app-ID catalog (~140 entries)
  config.py     per-TV records, active selection, tokens
  keys.py       KEY_* codes actually used
  app.tcss      styles
scripts/
  smoke.py      headless UI and config checks
  screenshot.py render the UI to SVG
```
