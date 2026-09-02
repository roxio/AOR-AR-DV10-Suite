# AOR AR-DV10 control suite

Control software for the AOR AR-DV10 digital voice receiver over USB: a
shared core protocol library, a Yaesu-CAT-flavoured interactive command
line, a desktop GUI, and a web panel that's itself a "graphical command
line" in the browser. All four sit on one `DV10Device` API, so protocol
fixes and new commands only need to be made once.

<img width="1133" height="471" alt="DV10-webpanel" src="https://github.com/user-attachments/assets/69e68c61-a441-4382-b312-dd1161585ae8" />

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
<img width="1133" height="338" alt="DV10-clipanel" src="https://github.com/user-attachments/assets/319c739f-bb07-4722-ae93-4682e3a038b8" />

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

## Install

```bash
pip install -e ".[dev]"        # core + CLI + tests
pip install -e ".[gui]"        # + desktop GUI (PySide6)
pip install -e ".[web]"        # + web panel (FastAPI/uvicorn)
```

Requires Python 3.10+.

## Try it without hardware

Everything works against an in-process simulated DV10, so you can explore
the whole suite before ever plugging in real hardware:

```bash
dv10-cli --simulator
dv10-cli --simulator --web                  # ...plus the web panel, one process, one shared device
python -m aor_dv10.gui.app --simulator      # requires the [gui] extra
python -m aor_dv10.web.server --simulator   # requires the [web] extra, then open http://127.0.0.1:8000/
```

## Use it with a real DV10

```bash
dv10-cli                      # auto-detects the DV10 by USB VID/PID
dv10-cli --port COM7          # ...or specify the port explicitly (Windows)
dv10-cli --port /dev/ttyACM0  # ...(Linux)
```

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
around each command's request/response cycle - see
`protocol/codec.py`'s `CommandChannel`, so the two interfaces can't corrupt
each other's commands even if used at the literal same instant).

## A clickable GUI, not just a command line in a browser

The web panel at `/` is a full point-and-click dashboard: a light,
card-based layout with a big tabular-mono frequency readout, a segmented
S-meter bargraph, buttons instead of native dropdowns for every
mode/squelch/AGC/attenuator selector, flat on/off switches, and a
scroll-to-tune rotary knob (mouse wheel or arrow keys) plus a direct-entry
numeric keypad next to the frequency field. It talks to the same
WebSocket verbs as the raw console underneath, so nothing about the wire
protocol changed - only what you interact with:

- **Frequency**: big readout, a numeric field + *Set*, and step buttons
  (±1 MHz / ±25 kHz / ±5 kHz) for quick tuning.
- **VFO A / B / Z** buttons to enter VFO mode on a given VFO before
  writing tuning/level parameters (required by the real hardware - see
  "Protocol notes" below).
- **S-meter**: a live dB bar plus an SQL open/closed pill, polled from
  `/api/status`.
- **Mode**: button rows for the digital and analog halves of `MD`, with a
  human-readable readout of what's currently selected.
- **Squelch**: mode buttons (`SQ`) plus level sliders for `LQ`/`NQ`.
- **Levels**: AGC speed and attenuator buttons, plus the *actually*
  working volume control - **volume limit** (`AV`/VOL ATT), since `AG`
  (audio gain) is confirmed non-functional on real hardware and the true
  volume knob is a plain analog control - along with digital sound gain
  (`DA`) and manual gain (`RG`, for AGC=RF-G).
- **Options & power**: beep level slider (`BP`), LCD contrast (`LN`) and
  backlight mode (`LB`) controls, result-code-prefixing (`RE`) toggle,
  Power ON/OFF buttons.
- **Advanced Squelch**: CTCSS/DCS enable toggles plus tone/code pickers
  (`CI`/`CN`/`DI`/`DS`).
- **Digital Codes**: DMR color code + slot + mute-by-code (`CC`/`OT`/`CM`),
  P25 NAC code + mute (`PC`/`PM`), NXDN RAN code + mute (`NC`/`NM`).
- **Descramblers**: the D-CR 15-bit scramble code (`DC`) and the analog
  voice-inversion descrambler toggle (`SI`).
- **Offset Reception**: offset slot + direction (`OF`) and, per slot,
  unsigned offset frequency (`OL`) - `OL` is a combined slot+frequency
  write, and reading it back needs the slot number too.
- **Priority Reception**: monitor toggle, priority channel, and check
  interval (`PO`/`PP`/`TI`).
- **Memory Channels**: import an "AR-DV10 Connect" memory-bank backup CSV
  export (the file the companion PC app produces), then search/browse the
  2000 channels by name or bank and tune the receiver to any programmed
  one with a click. This is a **file-format feature**, not a live-memory
  one - it never reads or writes the receiver's actual `MX`/`MA` memory
  banks; "tune" just replays the loaded channel's frequency/mode/step
  through the same `f`/`m`/`step` writes everything else here uses. See
  `aor_dv10.memory` - the parser/writer round-trips a real 2041-line
  export byte-for-byte, not just against synthetic test data.
- A collapsible **"Raw console (advanced)"** panel keeps the original
  terminal-style input (`raw`, `describe`, `help`, ...) for anything that
  doesn't have a dedicated control yet - which, honestly, is still a lot:
  *writing* memory channels/banks on the live device, search banks,
  scan/search groups, SD card file operations, and serial backup/restore
  are all real DV10 features without typed controls yet, because their
  wire format is a composite, multi-field record this project hasn't been
  able to reverse-engineer safely without real-hardware access.

The page polls `/api/status` roughly every 1.5s and skips updating any
control the user currently has focused, so it won't yank a slider out
from under you while you're dragging it. Open it with any of the
`dv10-cli --web`, `dv10-cli --mdns`, or standalone `dv10-web` commands
above - it's the same server, just a richer front end
(`web/static/index.html`).

**Language**: an EN/PL switch sits in the top-right corner. It translates
every label, button, heading, and dynamically-derived readout (mode,
squelch state, toasts) client-side, remembers your choice in the
browser's `localStorage`, and otherwise defaults to Polish if your
browser's language is Polish and English otherwise. The one thing that
stays in English regardless is the collapsible "Raw console" panel's
command/response text - that's the device's own raw wire format, not
something this project generates, so translating it would misrepresent
what's actually on the wire.

## Reach the web panel by a LAN name instead of an IP

By default the web panel is only reachable at `http://127.0.0.1:8000/` on
the machine it's running on. Pass `--mdns` (to either `dv10-web` standalone
or `dv10-cli` - see "One command, both interfaces" above) to also advertise
it on the LAN via mDNS, the same way a printer or other network appliance
shows up as `printer.local` - so any device on the same network (phone,
laptop, ...) can reach it by name instead of hunting down an IP address:

```bash
dv10-cli --mdns                              # -> http://aordv10.local:8000/, plus the CLI
dv10-web --mdns                              # -> http://aordv10.local:8000/, web panel only
dv10-web --mdns --mdns-name myshack          # -> http://myshack.local:8000/
dv10-web --simulator --mdns                  # try it without hardware first
```

This needs the `zeroconf` package (included in the `[web]` extra - see
Install above) and, once `--mdns` is given, binds to `0.0.0.0` instead of
`127.0.0.1` by default (pass `--host` explicitly to override), since other
devices on the LAN need to actually reach it.

> **Security note:** the web panel has no authentication - anyone who can
> open the URL can send any command, including powering the receiver on/off
> (`ZP`/`QP`). `--mdns` makes it reachable by name from anywhere on your
> LAN, not just this machine, so only use it on a network you trust (e.g.
> your home network, not a shared/public one).
>
> `.local` names resolve via mDNS, which Windows, macOS, and Linux (with
> Avahi) all support out of the box for *browsing to* a `.local` address,
> even though this project is the one doing the *advertising* here rather
> than the OS. If `http://aordv10.local:8000/` doesn't resolve from another
> device, try `http://<the running machine's LAN IP>:8000/` instead (printed
> in the terminal `dv10-web --mdns` was started from, alongside the
> `.local` address) while troubleshooting mDNS/firewall settings on your
> network.

## Protocol notes

A few real-hardware behaviors worth knowing before wiring up a real DV10:

- **Requests take no space between the command code and its value** -
  `RF0145.50000`, not `RF 0145.50000`.
- **Writes to tuning parameters (`RF`, `AC`, `SQ`, `AT`, ...) only succeed
  while the receiver is in VFO mode**, not while browsing a memory
  channel - switch to VFO on the front panel, or send `vfo [A|B|Z]`
  first, if a write comes back with a `?` error. `enter_vfo_mode()`
  wraps the real command for this (`VF <letter>`).
- **`MD` (mode), `LM` (S-meter), `AT`/`AC` (attenuator/AGC speed), and
  `SQ` (squelch)** all decode to more structured values than a first
  read of the DV10/DV1 command summary suggests: `MD` splits into
  separate digital/analog mode selections, `LM` decodes to `-dB` plus a
  squelch open/closed state rather than a plain linear bar, `AT`/`AC`
  are multi-state selectors rather than on/off booleans, and `SQ`
  selects a squelch *mode* rather than a level (`LQ`/`NQ` carry the
  actual thresholds). Some of these decodes come from a closely related
  sibling device's spec by family resemblance rather than independent
  DV10-specific confirmation - `AG` (legacy audio gain) in particular is
  confirmed non-functional; use `AV` (volume limit) instead.
- **`RE` (numeric result-code prefixing) is device-side state that
  survives a power cycle and a client restart.** Once turned on, every
  response - not just errors - is prefixed with a 2-digit result code
  (e.g. `20RF0145.50000` for a successful read). The protocol layer
  always recognizes and strips this prefix regardless of whether it
  "thinks" `RE` is on, so this doesn't require any special handling from
  a caller; `raw RE 0` turns prefixing back off if you want cleaner raw
  transcripts.

If a real receiver's response doesn't match what this project assumes,
turning on tracing (see "Debugging against real hardware" above) and
comparing the exact bytes is the fastest way to track down the
discrepancy.

## CLI cheat sheet

Short verbs, in the spirit of typing commands into a Yaesu CAT terminal:

```
s, status              show the panel (frequency/mode/squelch/volume/S-meter/AGC)
f [MHZ]                show or set frequency, e.g. "f 145.500000" (needs VFO mode)
m [MODE]                show or set raw mode code, e.g. "m F0" (FM, digital off)
sq [0|1|2]              show or set squelch MODE (0=Auto,1=Noise,2=Level) - not a level
lq [LEVEL]              show or set level-squelch threshold (00-99, used when sq=2)
nq [LEVEL]              show or set noise-squelch threshold (00-39, used when sq=1)
vol [LEVEL]            show or set volume
agc on|off             legacy on/off AGC (maps to Mid/Fast speed) - see agcspd
agcspd [0-3]            show or set AGC speed directly (0=Fast,1=Mid,2=Slow,3=RF-G)
beep on|off            key beep
att on|off             legacy on/off attenuator (maps to 10dB-ATT/AMP-OFF) - see attst
attst [0-2]             show or set attenuator state directly (0=AMP ON,1=AMP+ATT OFF,2=10dB ATT)
re on|off               toggle numeric result-code prefixing
vfo [A|B|Z]             select a VFO (default A) - needed before f/sq/att/agcspd/etc. writes will succeed
power on|off           ZP (connect) / QP (disconnect)
mem load <path>         load an "AR-DV10 Connect" memory-bank backup CSV export
mem find <text>          search loaded channel names
mem list [bank]          list programmed channels, optionally filtered to one bank
mem goto <bank>-<ch>    tune to a loaded channel (via f/m/step - not a live memory read)
mem export <path>       write the loaded database back to CSV
raw CODE [VALUE]       any of the ~100 documented commands, e.g. "raw LM"
describe CODE          what a command code does
help, quit
```

(Several more verbs - tuning step, CTCSS/DCS, DMR/P25/NXDN codes,
offset/priority reception, and audio/display settings - are also
available; run `help` inside the REPL for the full current list.)

Non-interactive one-shot usage: `dv10-cli --simulator --run "f 145.5" --run status`.

Dump the full command mnemonic registry (every code this project knows
about, not just the ones with a typed `device.py` helper) as machine-
readable JSON or CSV, no device connection needed:
`dv10-cli --export-commands json > commands.json`.

## Project layout

```
src/aor_dv10/
  transport/     SerialTransport (real USB) + SimulatorTransport (fake), common interface
  protocol/      command registry (commands.py) + framing/codec (codec.py)
  device.py      DV10Device - the API everything else builds on
  cli/           interactive REPL + non-interactive runner (dv10-cli)
  gui/           PySide6 desktop app (phase 2 skeleton)
  web/           FastAPI web panel: status API + WebSocket command console,
                 at full parity with the CLI's command set
tests/           pytest suite, runs entirely against the simulator
```

## Next steps

1. Run `dv10-cli --port <your-port>` against a real receiver and compare
   responses to the simulator; fix up `device.py` / `serial_transport.py`
   encodings for anything that doesn't match.
2. Flesh out the desktop GUI (PySide6) to the same depth as the web
   panel - it's still the original phase-2 skeleton, now the one
   interface visibly behind `DV10Device`'s full surface.
3. Factor the CLI's and web panel's command dispatch into one shared,
   formatting-agnostic module (noted in `web/server.py`) - the two are
   still hand-ported copies of each other (`cli/repl.py`'s `dispatch()`
   vs. `web/server.py`'s `_dispatch_plain()`), which has already caused
   at least one naming-collision bug between two similarly-named verbs
   before the two were brought back into parity.
4. Package the desktop apps (PyInstaller) for easy distribution once the
   protocol is verified.

## License

MIT - see [LICENSE](LICENSE).
