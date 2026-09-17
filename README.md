[English](README.md) | [Polski](README.pl.md)

# AOR AR-DV10 control suite

Control software for the AOR AR-DV10 digital voice receiver over USB: a
shared core protocol library, an interactive command line, a desktop GUI,
and a web panel that's itself a "graphical command line" in the browser.
All of them sit on one `DV10Device` API, so protocol fixes and new
commands only need to be made once.

<img width="1133" height="471" alt="DV10-webpanel" src="https://github.com/user-attachments/assets/c9062085-49a0-4de0-92e1-10ebbfc8aea1" />

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   CLI       │   │   GUI       │   │  Web panel  │
│ (dv10-cli)  │   │ (PySide6)   │   │ (FastAPI)   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └─────────────────┼─────────────────┘
                    DV10Device               (aor_dv10/device.py)
                          │
                    CommandChannel           (aor_dv10/protocol/)
                          │
                     Transport                (aor_dv10/transport/)
                    /            \
            SerialTransport   SimulatorTransport
             (real USB)      (fake device, no hardware needed)
```

<img width="885" height="338" alt="DV10-clipanel" src="https://github.com/user-attachments/assets/529fa03c-b2b1-4f0a-9f92-369ae52b63ed" />

`dv10-cli --web` runs the CLI *and* the web panel together, from one
command, sharing one `DV10Device` / one serial connection - see "One
command, both interfaces" below.

## Status

The core USB/protocol library, the desktop CLI, and the web panel are
complete and tested against a built-in simulator (see below): the web
panel's WebSocket terminal and button panels reach every verb family the
CLI has, including live memory channels/banks, search banks, scan groups,
pass frequencies, VFO/scheduled recording, SD card management, the
spectrum scope, and the select-scan list. The desktop GUI (PySide6) is
still a working skeleton covering only the original handful of controls,
meant as a starting point for further work rather than a finished
product.

Most of the wire-protocol details have been cross-referenced against
AOR's own command-list documentation and, where possible, verified
against real hardware (see "Protocol notes" below); a smaller number of
values are still carried over from a related sibling device's spec by
family resemblance and haven't been independently re-confirmed.

The code base is deliberately comment-free: it favours descriptive names,
small single-purpose modules and this README plus the in-app `help` over
inline commentary (see "Conventions" below).

## Highlights

- **One device API, three front ends.** CLI, GUI and web panel all drive
  the same `DV10Device` facade, composed from `device_*` mixins, over one
  locked `CommandChannel` - no per-interface protocol code.
- **Runs with no hardware.** A full in-process `SimulatorTransport`
  answers the real wire protocol, so the whole suite (and its 577-test
  suite) runs before you ever plug in a receiver.
- **~120 documented command codes** in a standalone registry
  (`protocol/commands.py`), each annotated with its access mode and a
  confidence note (confirmed on hardware / manual-sourced / unconfirmed).
- **Byte-exact protocol tracing** always on, in a ring buffer, surfaced
  both in the CLI (`debug on|off|last|save`) and over HTTP
  (`/api/debug/trace`).
- **Memory interchange in five formats** - the "AR-DV10 Connect" backup
  CSV, a JSON snapshot, CHIRP CSV, generic frequency CSV, and ADIF 3.1.4
  - plus import straight from a URL.
- **A real live memory-bank editor** (MA/MX) with per-row and per-bank
  writes, write-protect handling, and a diff against the imported CSV.
- **Server-side automation**: interval jobs (periodic memory backups and
  program searches) that keep running with no browser open.
- **Signal log, snapshots, telemetry and select-scan** panels, all built
  from data already polled or from explicit device commands.
- **Bilingual UI** (English/Polish) and a README in both languages.

## Install

```bash
pip install -e ".[dev]"        # core + CLI + tests
pip install -e ".[gui]"        # + desktop GUI (PySide6)
pip install -e ".[web]"        # + web panel (FastAPI/uvicorn)
```

Requires Python 3.10+.

Core dependencies are `pyserial`, `prompt_toolkit` and `rich`; the
optional extras add `PySide6` (GUI) and `fastapi` / `uvicorn[standard]` /
`websockets` / `zeroconf` (web panel). Two console scripts are installed:
`dv10-cli` and `dv10-web`.

## Try it without hardware

Everything works against an in-process simulated DV10, so you can explore
the whole suite before ever plugging in real hardware:

```bash
dv10-cli --simulator
dv10-cli --simulator --web                  # ...plus the web panel, one process, one shared device
python -m aor_dv10.gui.app --simulator      # requires the [gui] extra
dv10-web --simulator                        # requires the [web] extra, then open http://127.0.0.1:8000/
```

## Use it with a real DV10

```bash
dv10-cli                      # auto-detects the DV10 by USB VID/PID
dv10-cli --port COM7          # ...or specify the port explicitly (Windows)
dv10-cli --port /dev/ttyACM0  # ...(Linux)
```

The receiver is auto-detected by USB vendor/product ID (`0x08D0` /
`0x0101`); pass `--port` (CLI) or `--serial-port` (`dv10-web`) to
override, and `--baud` if it isn't the default 115200.

## One command, both interfaces

`dv10-cli --web` starts the interactive terminal *and* the web panel
together from a single command, sharing one `DV10Device` / one serial
connection, instead of running `dv10-cli` and `dv10-web` as two separate
processes that would each try to open the same COM port (which usually
doesn't even work - most OSes only let one process hold a serial port open
at a time):

```bash
dv10-cli --web                       # CLI + web panel at http://127.0.0.1:8000/
dv10-cli --web --web-port 9000       # ...on a different port
dv10-cli --mdns                      # implies --web, plus http://aordv10.local:8000/ on the LAN
dv10-cli --simulator --web           # try the combo without hardware first
```

Needs the `[web]` extra installed (`pip install -e ".[web]"`) - if it's
missing, `--web`/`--mdns` print a clear message and exit rather than
silently running CLI-only. A command typed into the terminal and a command
sent from a browser tab both reach the exact same receiver connection, so
either interface sees the other's changes immediately (protected by a lock
around each command's request/response cycle - see `protocol/codec.py`'s
`CommandChannel` - so the two interfaces can't corrupt each other's
commands even if used at the literal same instant).

## Debugging against real hardware

Every command sent to (and every line read back from) the receiver is
always recorded, byte-exact, in an in-memory ring buffer - whether or not
anything asked for it - so "what exactly did the radio just say?" is
answerable after the fact, not just if tracing happened to be on already.

```bash
dv10-cli --port COM7 --debug session.log   # trace from startup, echoed to the
                                            # console AND appended to session.log
```

Or turn it on mid-session (same in the CLI or the web panel's raw console):

```
DV10> debug on              # live TX/RX lines from here on, dimmed in the console
DV10> debug on session.log  # ...and also append them to a file as they happen
DV10> raw MA 0000           # try whatever you're investigating
DV10> debug last 20         # show the last 20 traced lines - works even without "debug on"
DV10> debug save session.log
DV10> debug off
```

Each line looks like `[14:32:07.118] TX b'RF0145.50000\r'` /
`[14:32:07.121] RX b'?'` - the `repr()` of the *exact* bytes, so a stray
space, an unexpected CR/LF, or a non-ASCII byte a real unit sends back is
visible rather than silently stripped or decoded away. That precision
matters when comparing what a real receiver actually sends against what
this project currently assumes about the wire protocol.

The web panel has the same history via `GET /api/debug/trace?n=50` and the
raw console's `debug last [N]` / `debug save <path>` verbs (no live toggle
there yet - `debug on`'s live echo is CLI-only for now).

## Command-line interface (`dv10-cli`)

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--port PORT` | auto-detect by VID/PID | Serial device, e.g. `COM7` / `/dev/ttyACM0`. |
| `--baud N` | `115200` | Serial baud rate. |
| `--simulator` | off | Use the in-process simulated receiver. |
| `--run CMD` | - | Run one command non-interactively and exit; repeatable. |
| `--debug [LOGFILE]` | - | Trace raw TX/RX from startup; optional logfile also appended. |
| `--web` | off | Also start the web panel in this process (shared device). |
| `--web-host HOST` | `127.0.0.1` (or `0.0.0.0` with `--mdns`) | Web panel bind address. |
| `--web-port PORT` | `8000` | Web panel HTTP port. |
| `--mdns` | off | Advertise the web panel via mDNS; implies `--web`. |
| `--mdns-name NAME` | `aordv10` | mDNS hostname label (`NAME.local`). |
| `--export-commands {json,csv}` | - | Dump the full command registry to stdout and exit (no device). |

Non-interactive one-shot usage runs several commands in order and prints
each result:

```bash
dv10-cli --simulator --run "f 145.5" --run status
```

Dump the full command mnemonic registry (every code this project knows
about, not just the ones with a typed `device.py` helper) as
machine-readable JSON or CSV, no device connection needed:

```bash
dv10-cli --export-commands json > commands.json
```

### `dv10-web` (standalone)

`dv10-web` serves the web panel on its own (`--host`, `--port`,
`--serial-port`, `--baud`, `--simulator`, `--mdns`, `--mdns-name`). Use it
when you don't need the terminal; use `dv10-cli --web` when you want both
over one connection.

### Interactive commands

Short verbs, in the spirit of typing commands into a Yaesu CAT terminal.
Run `help` (or `?`) inside the REPL for the full, always-current list -
tab completion is wired to the same shared registry (`verb_registry.py`)
the web panel's `help` uses.

**Status / identity**

```
s, status              show the panel (frequency/mode/squelch/volume/S-meter/AGC/ATT)
id                     model + firmware + normalized device family
serial                 RN: receiver serial number
sn                     SN: read-only "output serial number" (distinct from RN)
zi [TEXT]              ZI: show/set the receiver ID string
clock [YYMMDDHHmm]     DT: show/set the system clock
vi                     VI: dump all three VFOs (frequency/step/step-adjust/mode)
rx                     RX: read receiver status
```

**Tuning**

```
f [MHZ]                show or set frequency, e.g. "f 145.500000" (needs VFO mode)
m [MODE]               show or set raw mode code, e.g. "m F0" (FM, digital off)
step [HZ]              show or set the tuning step
stepadj [HZ]           SH: show/set frequency-step adjust
movenext / moveprev    front-panel Up / Down equivalent
bw [HZ]                IF bandwidth by Hz (no arg lists valid choices)
ifbw [VALUE]           IF: IF bandwidth by raw digit
delay [DECISECONDS]    DL: standalone delay (000-099, 100 = unlimited)
freetime [SECONDS]     FR: standalone free time (00-60 s; 0 = OFF)
```

**Mode / receiver settings**

```
vfo [A|B|Z] [MHZ] [MODE]   select/set a VFO (the way into VFO mode)
agc on|off             legacy on/off AGC (maps to Mid/Fast) - see agcspd
agcspd [0-3]           AGC speed (0=Fast, 1=Mid, 2=Slow, 3=RF-G)
att on|off             legacy on/off attenuator - see attst
attst [0-2]            attenuator state (0=OFF, 1=ON, 2=10 dB)
re on|off              toggle numeric result-code prefixing
backlight [0|1|2]      LB: LCD backlight (0=OFF, 1=CONT, 2=AUTO)
klcolor [0-7]          KL: key backlight colour
contrast [00-63]       LN: LCD contrast
mgain [000-110]        RG: manual (non-AGC) gain
digain [01.00-15.94]   DA: digital-mode audio gain
vollimit [00-15]       AV: volume ceiling
writeprotect on|off    PT: write-protect flag
power on|off           ZP (connect) / QP (disconnect)
reset [full]           RS: DESTRUCTIVE system / full factory reset
```

**Squelch / levels**

```
sq [0|1|2]             squelch MODE (0=Auto, 1=Noise, 2=Level) - not a level
lq [LEVEL]             level-squelch threshold 00-99 (used when sq=2)
nq [LEVEL]             noise-squelch threshold 00-39 (used when sq=1)
vol [LEVEL]            audio gain (error 60 on some units - use vollimit)
beep on|off            key beep
beeplvl [0-7]          BP: key-beep volume
tone on|off            CTCSS tone squelch enable
tonefreq [VALUE]       CTCSS tone
dcs on|off             DCS squelch enable
dcscode [VALUE]        DCS code
sqltype [0-2]          CI: tone-squelch type (0=OFF, 1=CTCSS, 2=Reverse)
```

**Memory**

```
mem load <path>        load an "AR-DV10 Connect" memory-bank backup CSV export
mem find <text>        search loaded channel names
mem list [bank]        list programmed channels, optionally one bank
mem goto <bank>-<ch>   tune to a loaded channel (via f/m/step - not a live read)
mem export <path>      write the loaded (possibly edited) database back to CSV
rmem read <bank> <ch>  MA: read one live memory channel from the receiver
rmem readbank <bank>   MA: read a whole live bank (50 slots)
rmem write <bank> <ch> <MHZ> [mode] [tag]   MX: write a live channel
rmem tune <bank> <ch>  MR: tune the receiver to a live memory channel
rmem delete <bank> <ch>    MQ: delete a live channel
rmem bank <bank>       MW read: bank tag / protect / channel count
rmem bankset <bank> [count] [protect 0|1] [tag]   MW: set bank metadata
rmem bankdel <bank>    MB: delete a whole bank
rmem find <text> [bank]    search live channels by name
regchan                MM: register the current channel as the last-channel memory
```

**Search / scan / pass / select**

```
search write|read|run|delete <bank>       SE/SR/SS/SX program-search banks
search lolimit|hilimit [MHZ]              SL/SU search session limits
scan sread|swrite|mread|mwrite <group> ...    SG/MG scan groups
scan autostore [on|off]                   AS: auto-store on search hits
scan banklink [bank...|clear]             BK: linked banks for scan
pass mark [MHZ] | pass mark bank <bank> [MHZ] | pass mark allbanks <MHZ>
                                          PW: mark a pass (skip) frequency
pass list [bank]                          PR: list pass frequencies
pass delete ...                           PD: delete pass frequencies
select add|remove <bank> <ch> | select list | select clear
select run [cycles] [dwell_s]             host-side select-scan list and runner
```

**Scope / recording / SD card**

```
scope fast | scope normal                  FD/GL one-shot scope scan (text sparkline)
sd dir | sd info | sd status              SD card directory / info / status
sd rec start|stop                         SD REC: recording (stop is front-panel only on DV10)
sd play <name> | sd play stop             SD PLY: playback
sd rsq [on|off]                           SD RSQ: squelch-skip
sd backup <kind> | sd restore <name>      SD MMW/MMR (DV1/DV3 only - refused on DV10)
timer / timer show|status / timer off
timer set <target> <once|weekly> <start> <end> [alarm|recording] [days] [volume]
                                          TR: scheduled recording / alarm timer
```

**Priority / digital codes / offset**

```
prio on|off            priority-channel monitoring (PO)
priochan [BANK CH]     PP: priority channel
priointerval [1-99]    TI: priority-check interval (seconds)
dmrcc [00-16]          CC: DMR colour code
dmrcm on|off           CM: DMR mute-by-colour-code
dmrslot [VALUE]        OT: DMR slot selection
p25nac [000-FFF]       PC: P25 NAC code
p25pm on|off           PM: P25 mute-by-NAC
nxdnran [00-63]        NC: NXDN RAN code
nxdnnm on|off          NM: NXDN mute-by-RAN
dcrcode [00000-32767]  DC: DCR descramble code
descr on|off           SI: analog voice descrambler (V.SCR)
offset [SLOT [+/-]]    OF: offset slot + direction (00=off, 01-19=user, 20-39=preset)
offsetfreq [SLOT [MHZ]]    OL: offset frequency for a slot (unsigned)
```

**Raw / experimental**

```
raw CODE [VALUE]       send any of the ~120 documented commands, e.g. "raw LM"
describe CODE          explain a command code and its expected value
an, ct, dj, dk, lc, lt, ox, ts, vq, zs, zt, rt, sb, sp
                       thin typed wrappers around otherwise raw-only codes
debug on [logfile] | debug off | debug last [N] | debug save <path>
help, ?                print the full command list
quit, exit             disconnect and leave
```

## Desktop GUI (PySide6)

`python -m aor_dv10.gui.app` (or with `--simulator`) opens a minimal Qt
window covering the original handful of controls. It is a **phase-2
skeleton**, not at parity with the CLI or web panel, and is the next
interface slated for real work.

## Web panel

Open it with any of `dv10-cli --web`, `dv10-cli --mdns`, or a standalone
`dv10-web` - it's the same FastAPI server (`web/server.py`) serving
`web/static/index.html`. It's not just a command line in a browser: it's a
full point-and-click dashboard that talks to the same WebSocket verbs as
the raw console underneath, so nothing about the wire protocol changed -
only what you interact with.

### Panels

- **Frequency / tuning** - a big tabular-mono readout, numeric keypad and
  *Set*, step buttons (±1 MHz / ±25 kHz / ±5 kHz), a scroll-to-tune rotary
  knob (mouse wheel or arrow keys), and VFO A/B/Z selection.
- **S-meter** - a live dB bar plus an SQL open/closed pill, polled from
  `/api/status`, with a sparkline of recent readings.
- **Mode / squelch / levels** - button rows for the digital and analog
  halves of `MD`, squelch mode plus `LQ`/`NQ` sliders, AGC speed,
  attenuator, and the *actually* working volume control (**volume limit**,
  `AV`), since `AG` (audio gain) is confirmed non-functional on real
  hardware and the true volume knob is analog.
- **More: Squelch / Levels / Codes / Offset · Priority** - CTCSS/DCS,
  DMR/P25/NXDN/DCR digital codes (each code carries its own
  confidence-dot tooltip), descrambler, offset reception, and priority
  reception.
- **Favorites · Signal log · Alerts · Snapshots · Automation · Presets** -
  named VFO targets, the signal log with threshold alerts, memory
  snapshots, interval automation jobs, and quick presets.
- **Memory Channels & Live Memory** - a searchable/browsable view of an
  imported backup (tune-to-channel), the live **Memory Bank Editor**, and
  a CSV column-mapping helper.
- **VFO · Search · Recording · SD Card** - VFO search settings, program
  search banks, scan groups, pass frequencies, recording timers, and SD
  card management.
- **Search Banks · Scan Groups · Pass Frequencies** - dedicated editors
  for those three search-side structures.
- **Spectrum Scope · Select-Scan · Additional Settings** - FD/GL scope
  views, the host-side select-scan list, and assorted extras.
- **Raw console & Command queue** - the original terminal-style input
  (`raw`, `describe`, `help`, ...) plus a queue of pending commands with
  their per-action timeouts; destructive commands never auto-fire.
- **Telemetry** - read-only status queries
  (`AN/VQ/CT/DJ/DK/LD/LU/LC/LT/NR/LS/TS/RT/RX/MDB/ZI/RN`) as clickable
  `[CODE] value` rows.

The page polls `/api/status` roughly every 1.5 s and skips updating any
control the user currently has focused, so it won't yank a slider out
from under you while you're dragging it. Long, deep panels (favorites,
log, presets, codes) are laid out as responsive multi-column blocks so the
page stays compact rather than one long scroll.

### Memory interchange

The imported/exported memory database is format-agnostic:

| Format | Import | Export |
|---|---|---|
| "AR-DV10 Connect" backup CSV | yes | yes |
| JSON snapshot (`aor-dv10-suite.memory`) | yes | yes |
| CHIRP CSV | yes | yes |
| Generic frequency CSV | yes | - |
| ADIF 3.1.4 | yes | yes |
| Generic frequency CSV from a URL | yes | - |

Importing replaces the in-memory database used by the browser/editor. The
backup-CSV parser/writer round-trips a real 2041-line export byte-for-byte.

### Live Memory Bank Editor

Reads a bank straight off the receiver (`MA`) into an editable table and
writes edits back with composite `MX` writes. You can save a single row,
or push a whole loaded bank with "Overwrite Bank" / "Overwrite All Loaded
Banks". Write-protected rows are skipped unless "Include write-protected
rows" is on, and omitted fields are filled from the current channel so a
partial edit preserves the rest. A **diff** view compares the imported CSV
against the live bank field-by-field, and a one-shot live CSV export dumps
a bank as read from hardware.

### Snapshots

Timestamped JSON snapshots of the imported database are stored
server-side under `dv10_backups/` and can be created, listed, restored and
deleted. Filenames are sanitised (no path traversal).

### Automation

Interval jobs run **server-side**, so periodic memory backups and periodic
program searches continue even with no browser open. Each job has a
Run-now action. Only `backup` and `scan` actions exist.

### Signal log & alerts

Logs each squelch-open / digital-detect event with frequency, level and
mode. Threshold alerts are debounced state-transition alerts and respect
browser notification permission.

### Select-Scan

A host-side list of memory channels (never written to the receiver). The
runner blocks this browser tab's connection for the whole scan each time
it fires; the optional recurring schedule is client-side and stops on
reload.

### Language

An EN/PL switch sits in the top-right corner. It translates every label,
button, heading and dynamically-derived readout (mode, squelch state,
toasts) client-side, remembers your choice in `localStorage`, and defaults
to Polish if your browser's language is Polish, English otherwise. The one
thing that stays in English regardless is the raw console's
command/response text - that's the device's own wire format.

### Reach the panel by a LAN name (mDNS)

Pass `--mdns` (to `dv10-cli` or `dv10-web`) to advertise the panel on the
LAN, the same way a printer shows up as `printer.local`, so any device on
the network can reach it by name:

```bash
dv10-cli --mdns                              # -> http://aordv10.local:8000/, plus the CLI
dv10-web --mdns                              # -> http://aordv10.local:8000/, web panel only
dv10-web --mdns --mdns-name myshack          # -> http://myshack.local:8000/
dv10-web --simulator --mdns                  # try it without hardware first
```

This needs the `zeroconf` package (in the `[web]` extra) and, once
`--mdns` is given, binds to `0.0.0.0` instead of `127.0.0.1` by default
(pass `--host` / `--web-host` to override).

> **Security note:** the web panel has no authentication - anyone who can
> open the URL can send any command, including powering the receiver
> on/off (`ZP`/`QP`). `--mdns` makes it reachable by name from anywhere on
> your LAN, so only use it on a network you trust.
>
> `.local` names resolve via mDNS, which Windows, macOS and Linux (with
> Avahi) all support out of the box for *browsing to* a `.local` address.
> If `http://aordv10.local:8000/` doesn't resolve from another device, try
> `http://<the running machine's LAN IP>:8000/` instead (printed at
> startup) while troubleshooting mDNS/firewall settings.

## HTTP API

All routes are on the web panel server; the UI is one consumer of them.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serve the web panel UI (`static/index.html`). |
| GET | `/api/status` | Full device telemetry snapshot (JSON). |
| POST | `/api/reconnect` | Reconnect the serial transport. |
| POST | `/api/memory/import` | Import an "AR-DV10 Connect" backup CSV. |
| POST | `/api/memory/autolabel` | Auto-name blank channels `"<mode> <freq>"`. |
| GET | `/api/memory` | Query the imported DB (`q`, `bank`, `include_empty`, `limit`). |
| GET | `/api/memory/banks` | List imported banks (`index`, `protect`, `title`). |
| POST | `/api/memory/tune/{bank}/{channel}` | Tune the receiver to an imported channel. |
| GET | `/api/memory/export` | Download the DB as backup CSV. |
| GET | `/api/memory/export_json` | Download the DB as a JSON snapshot. |
| POST | `/api/memory/import_json` | Import a JSON snapshot. |
| GET | `/api/memory/export_chirp` | Download the DB as CHIRP CSV. |
| POST | `/api/memory/import_chirp` | Import a CHIRP CSV. |
| POST | `/api/memory/import_freqs` | Import a generic frequency CSV. |
| POST | `/api/import/url` | Fetch and import a frequency CSV from a URL. |
| GET | `/api/adif/export` | Download the DB as ADIF. |
| POST | `/api/adif/import` | Import ADIF text. |
| GET | `/api/memory/backups` | List server-side JSON snapshots. |
| POST | `/api/memory/backups` | Create a timestamped snapshot. |
| POST | `/api/memory/backups/{name}/restore` | Restore a snapshot. |
| DELETE | `/api/memory/backups/{name}` | Delete a snapshot. |
| GET | `/api/memory/live_export/{bank}` | Read a live bank off hardware as CSV. |
| GET | `/api/memory/diff/{bank}` | Diff imported DB vs the live bank. |
| GET | `/api/memory/live_bank/{bank}` | Read a live bank for the editor. |
| POST | `/api/memory/live_bank/{bank}/batch` | Batch live write (MX); per-item results. |
| POST | `/api/memory/live_bank/{bank}/{channel}` | Single live write (MX); 409 if protected. |
| DELETE | `/api/memory/live_bank/{bank}/{channel}` | Delete a live channel. |
| POST | `/api/hits` | Append a signal-log event. |
| GET | `/api/hits` | Read recent signal-log events. |
| DELETE | `/api/hits` | Clear the signal log. |
| GET | `/api/scheduler/jobs` | List automation jobs. |
| POST | `/api/scheduler/jobs` | Create a job (`backup` / `scan`). |
| DELETE | `/api/scheduler/jobs/{job_id}` | Delete a job. |
| POST | `/api/scheduler/jobs/{job_id}/run` | Run a job immediately. |
| GET | `/api/debug/trace` | Recent raw TX/RX trace lines. |

## WebSocket protocol

The panel's terminal speaks a **plain-text, one-command-per-frame**
protocol at `/ws` - no JSON envelope. Send `f 145.500`, `rmem read 00 05`,
`help`, ... and receive exactly one text frame back per frame sent
multi-line replies (e.g. `rmem dump`) arrive as a single frame containing
`\n`; errors come back as `error: ...`. The verbs are the same families as
the CLI (`f`, `m`, `sq`, `rmem`, `search`, `scan`, `pass`, `timer`, `sd`,
`scope`, `select`, `debug`, `raw`, ...), dispatched by `_dispatch_plain`.

## Web panel notes & caveats

The web panel keeps its inline hints to one short line; the fuller
reasoning - and every "unconfirmed on hardware" caveat - lives here.

- **Spectrum scope (FD/GL).** Both only return data while the receiver is
  already "in scope mode". No command or front-panel procedure to enter
  that mode is documented anywhere in the AR-DV10/AR-DV1 material (the
  operating manual never mentions a bandscope feature). On real hardware
  these buttons will most likely return error 30 ("Not in scope mode")
  rather than data - established from the documentation trail, not tested
  live.
- **Factory reset (RS).** System reset keeps memory data; Full reset erases
  everything (manual 11.2 items 4/5). The 0/1 argument encoding is an
  unconfirmed guess, so either button may behave unexpectedly on a real
  unit. Use only on hardware you don't mind losing settings/memories on.
  Both are armed on first click and send on a second click within 3
  seconds.
- **Memory Bank Editor (live MA/MX).** Loads live memory bank(s) from the
  receiver into the editable table. You can save a single row, or push a
  whole loaded bank's rows back (MX) with "Overwrite Bank" / "Overwrite
  All Loaded Banks". Either overwrite action is destructive in the same
  sense any MX write is: it replaces whatever was in that slot, edited or
  not. Write-protected rows are skipped unless the "Include write-protected
  rows" checkbox is on.
- **Live memory / CSV bridge.** Live MA reads have a different (smaller)
  confirmed field set than the "AR-DV10 Connect" CSV format: there is no
  offset and no step-adjust on the live side, and the exact shape of the
  mode code is not confirmed to match - treat a reported mode difference
  with that in mind. Frequency / protect / name / pass-flag differences are
  solid.
- **SD card (AR-DV10).** Rec Stop / Backup / Restore are disabled in the
  panel. A real AR-DV10 reportedly wedges if these are sent remotely (per
  the AR-DV1 spec's own `/` stop convention). Stop recording with the
  front-panel ● key.
- **Automation.** Interval jobs run server-side - periodic memory backups
  and periodic program searches, even with no browser open. Each job has a
  Run-now action.
- **Comm speed (SB).** Changing this remotely can sever the very serial
  connection used to send the command. The Set button is armed on first
  click and sends on a second click within 3 seconds.
- **Digital codes (CC/CM/OT/PC/PM/NC/NM/DC).** The selection commands
  (CI/DI) are confirmed against real hardware; the CN/DS tone and code
  tables are manual-sourced and not wire-confirmed. Every code in the
  "Digital Codes" panel carries its own confidence-dot tooltip.
- **Experimental / unused commands.** Only a one-line description exists
  for these in the command registry - no fuller spec was available to
  confirm field formats, so every control is a literal raw passthrough.
  Treat values as unconfirmed.
- **Visualizations.** Sparkline / squelch history / error log are built
  purely from data already polled every ~1.5 s. No new device commands;
  history resets on page reload.
- **Select-Scan.** The list is client-side only (never written to the
  receiver). "select run" blocks this browser tab's connection for the
  whole scan each time it fires; the optional recurring schedule is
  client-side and stops on reload.
- **Pass frequencies (PW/PR/PD).** A per-bank or all-banks skip list for
  program search, separate from memory channels.
- **Signal log & alerts.** Logs each squelch-open / digital-detect event
  with frequency, level and mode, kept in this browser's `localStorage`.
  Threshold alerts are debounced state-transition alerts and respect
  browser notification permission.
- **Serial number (SN vs RN).** SN is a separate command from RN - not a
  duplicate. Unlike RN it has no dedicated spec section in any reference
  document available to this project; it may be an orphaned placeholder in
  the command summary table with nothing confirmed behind it.
- **Telemetry drawer.** Read-only telemetry commands
  (`AN/VQ/CT/DJ/DK/LD/LU/LC/LT/NR/LS/TS/RT/RX/MDB/ZI/RN`) - device status
  queries only, no write controls.
- **Command queue.** Shows pending commands with their per-action
  timeouts. Destructive commands never auto-fire - they require explicit
  confirmation.
- **Register last channel (MM).** Registers whatever the receiver is
  currently tuned to as its own "last channel memory" (what it powers back
  up on). Real effect on the device; cannot be undone; invalid while
  write-protect (PT) is on.
- **Search banks (SE/SR).** A saved frequency range with its own step/mode
  for program search, separate from memory channels.
- **VFO panel / templates.** "Set VFO" writes frequency/mode as separate
  RF/MD commands after selecting the VFO - VF's embedded fields are
  confirmed to silently no-op on a real DV10. Named VFO targets are stored
  in the browser's `localStorage`, not auto-saved to the device.
- **Scan groups (SG/MG).** Search-side (SG) and memory-side (MG) groups
  link several banks into one scan pass. SG has its own per-group
  auto-store field; MG does not - a real protocol asymmetry.
- **Sleep timer (SP).** Marked "No function" for the DV10 in the official
  command summary table - kept for completeness; likely a no-op.

## Protocol notes

A few real-hardware behaviors worth knowing before wiring up a real DV10:

- **Requests take no space between the command code and its value** -
  `RF0145.50000`, not `RF 0145.50000`.
- **Writes to tuning parameters (`RF`, `AC`, `SQ`, `AT`, ...) only succeed
  while the receiver is in VFO mode**, not while browsing a memory
  channel - switch to VFO on the front panel, or send `vfo [A|B|Z]`
  first, if a write comes back with a `?` error. `enter_vfo_mode()` wraps
  the real command for this (`VF <letter>`).
- **`MD` (mode), `LM` (S-meter), `AT`/`AC` (attenuator/AGC speed), and
  `SQ` (squelch)** all decode to more structured values than a first read
  of the DV10/DV1 command summary suggests: `MD` splits into separate
  digital/analog mode selections, `LM` decodes to `-dB` plus a squelch
  open/closed state rather than a plain linear bar, `AT`/`AC` are
  multi-state selectors rather than on/off booleans, and `SQ` selects a
  squelch *mode* rather than a level (`LQ`/`NQ` carry the actual
  thresholds). Some of these decodes come from a closely related sibling
  device's spec by family resemblance rather than independent DV10-specific
  confirmation - `AG` (legacy audio gain) in particular is confirmed
  non-functional; use `AV` (volume limit) instead.
- **`RE` (numeric result-code prefixing) is device-side state that
  survives a power cycle and a client restart.** Once turned on, every
  response - not just errors - is prefixed with a 2-digit result code
  (e.g. `20RF0145.50000` for a successful read). The protocol layer always
  recognizes and strips this prefix regardless of whether it "thinks" `RE`
  is on, so this doesn't require any special handling from a caller; `raw
  RE 0` turns prefixing back off if you want cleaner raw transcripts.
- **Timeouts and resync.** On a missing response, `CommandChannel.send`
  writes a bare `\r` to resync and discards one line. Read-only commands
  (`value is None`) are retried once; writes raise `DV10ResyncNeeded`
  instead of being silently re-sent, so a side-effecting command is never
  duplicated.

If a real receiver's response doesn't match what this project assumes,
turning on tracing (see "Debugging against real hardware" above) and
comparing the exact bytes is the fastest way to track down the
discrepancy.

## Testing

```bash
pytest                # 577 tests, entirely against the simulator
pytest --cov          # with coverage (fails under 70%)
```

The suite runs with no hardware: `SimulatorTransport` implements the wire
protocol and mutable device state. Test modules cover the protocol codec
and retry/resync, command utils, the command registry, the device family
detection, memory models and cross-format interop, ADIF and record
formats, the recording timer, scope and select-scan, the CLI (smoke,
verbs, export, SD, timer, VFO) and the web layer (integration, dispatch
parity, live bank editor, memory, the front-end guards). The tests double
as the executable specification for the wire behaviours described above.

## Conventions

- **No comments in source.** The code base is intentionally comment-free
  (see "Status"); rely on descriptive names, small modules, type hints and
  this README / the in-app `help`. A handful of mandatory tool directives
  (`# noqa`, `# type: ignore`, `# pragma: no cover`) are the only
  exceptions, since they're functional.
- **Linting.** `ruff` with `E`, `F`, `W`, `I`, `UP`, `B`, line length 120
  (`pyproject.toml`).
- **Shared, not duplicated, where it matters.** The device API, command
  registry, response parsers, token helpers and the verb list are shared
  modules. The CLI and web dispatchers are still hand-ported copies of each
  other (see "Next steps").

## Project layout

```
src/aor_dv10/
  device.py         DV10Device - the API everything else builds on
  device_types.py   value tables, enums and dataclasses (Status, MemoryChannelInfo, ...)
  device_tuning.py        tuning step / step-adjust (ST/SH)
  device_memory.py        memory channels & banks, search banks, scan groups, pass freqs
  device_signals.py       squelch, S-meter, AGC, attenuator, CTCSS/DCS, digital codes
  device_settings.py      volume/gain, contrast/backlight, clock, timers, write-protect
  device_scope.py         spectrum scope (FD/GL)
  device_sd.py            SD card directory/info/record/playback/backup
  device_priority.py      priority reception (PO/PP/TI)
  device_system.py        power, status(), result-code prefixing, IF bandwidth, trace
  device_extra.py         experimental / raw-only codes (AN, CT, DJ, OX, VQ, SB, ...)
  memory.py         offline memory model + CSV/JSON/CHIRP interop
  adif.py           ADIF 3.1.4 import/export
  record_format.py  human-readable record formatters (search banks, scan groups, pass)
  timer.py          recording/alarm timer model + wire codec
  selectscan.py     host-side select-scan list + runner
  verb_registry.py  single shared (verb, usage) table for CLI completion + web help
  command_utils.py  shared token helpers (on_off, split_command, clock digits, ...)
  constants.py      bank/channel/tag constants
  transport/        SerialTransport (real USB) + SimulatorTransport (fake)
  protocol/         command registry (commands.py), framing/codec (codec.py),
                    response parsing (parsing.py)
  cli/              interactive REPL + non-interactive runner (dv10-cli)
  gui/              PySide6 desktop app (phase-2 skeleton)
  web/              FastAPI web panel: status API, REST endpoints, WebSocket
                    console, static/index.html
tests/              pytest suite, runs entirely against the simulator
docs/               PROTOCOL.md / ROADMAP.md (kept locally, not published)
```

## Next steps

1. Run `dv10-cli --port <your-port>` against a real receiver and compare
   responses to the simulator; fix up `device.py` / `serial_transport.py`
   encodings for anything that doesn't match.
2. Flesh out the desktop GUI (PySide6) to the same depth as the web
   panel - it's still the original phase-2 skeleton, now the one interface
   visibly behind `DV10Device`'s full surface.
3. Factor the CLI's and web panel's command dispatch into one shared,
   formatting-agnostic module - the two are still hand-ported copies of
   each other (`cli/repl.py`'s `dispatch()` vs. `web/server.py`'s
   `_dispatch_plain()`), which has already caused at least one
   naming-collision bug between two similarly-named verbs.
4. Package the desktop apps (PyInstaller) for easy distribution once the
   protocol is verified.

## License

MIT - see [LICENSE](LICENSE).
