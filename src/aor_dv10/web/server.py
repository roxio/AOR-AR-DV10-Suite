"""Minimal web panel - phase 2 starting point.

Serves a single page styled as a "graphical command line" (a dark terminal
readout plus a status header, in the browser) that talks to one shared
DV10Device over a WebSocket, using the exact same short verbs as the desktop
CLI (see aor_dv10.cli.repl.HELP). Multiple browser tabs share one device
connection (there's exactly one physical/simulated receiver, after all).

NOTE: this reimplements a small, plain-text version of the CLI's dispatch
logic rather than importing aor_dv10.cli.repl.Repl, because that class wraps
its output in Rich console formatting meant for a terminal. A follow-up
worth doing is factoring a formatting-agnostic dispatcher both can share.

Run with:  pip install -e ".[web]"  &&  python -m aor_dv10.web.server [--simulator]
Then open http://127.0.0.1:8000/

Or reach it by a friendly LAN name instead of an IP:port, the same way a
printer or other LAN appliance shows up as "printer.local": pass --mdns
(optionally --mdns-name to change the label from the "aordv10" default) and
open http://aordv10.local:<port>/ from any device on the same LAN. This
needs the "zeroconf" package (included in the [web] extra) and binds to
0.0.0.0 by default once --mdns is given, since other devices need to reach
it - be aware this exposes control of the receiver (including power on/off
via ZP/QP) to anyone on your LAN, with no authentication.

Integrated with the CLI: run `dv10-cli --web` (see cli/__main__.py) to get
both the interactive REPL *and* this web panel from one command, sharing
one DV10Device / one serial connection, via start_in_thread() below -
rather than each opening (and fighting over) its own connection to the
same COM port. protocol.codec.CommandChannel.send() is lock-guarded so
issuing commands from the REPL's thread and this panel's request-handling
thread concurrently is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import shlex
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..cli.repl import _on_off
from ..device import DV10Device, KEY_BACKLIGHT_COLORS, SD_CARD_STATUS, TONE_SQUELCH_TYPES
from ..memory import MemoryBank, MemoryChannel, parse_backup_csv, write_backup_csv
from ..protocol.codec import DV10Error
from ..selectscan import SelectScanList, run_select_scan
from ..timer import (
    RecordingTimer,
    receive_mode_memory_channel,
    receive_mode_memory_scan,
    receive_mode_search_bank,
    receive_mode_vfo,
    receive_mode_vfo_search,
)
from ..transport.base import TransportError

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AOR AR-DV10 Web Panel")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_device: Optional[DV10Device] = None
_lock = asyncio.Lock()

# "mem" import state, shared by every browser tab against this one server
# process - same file-format-only split as the CLI's "mem" verb family
# (aor_dv10.cli.repl.Repl._dispatch_mem): never touches the live MX/MA
# memory-channel wire commands, only replays a loaded channel's
# frequency/mode/step through the already-confirmed f/m/step writes. See
# aor_dv10.memory's module docstring.
_memory_banks: list[MemoryBank] = []
_memory_channels: list[MemoryChannel] = []

# Client-side select-scan list, shared by
# every browser tab, never persisted or written to the receiver. See
# aor_dv10.selectscan and the CLI's own "select" verb
# (aor_dv10.cli.repl.Repl._dispatch_select).
_select_scan_list = SelectScanList()


def get_device() -> DV10Device:
    assert _device is not None, "device not initialised - server started incorrectly"
    return _device


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status():
    device = get_device()
    async with _lock:
        s = device.status()
    def _try(fn):
        try:
            return fn()
        except (DV10Error, ValueError, TypeError):
            # Mirror device.status()'s _try: also swallow unexpected-format
            # values (e.g. an MX record read as a frequency) so one bad
            # field can't take down the whole /api/status response.
            return None

    def _current_offset_freq():
        # OL now requires an explicit slot number (see
        # DV10Device.get_offset_freq()'s docstring) - derive it
        # from OF's currently-active slot rather than assuming a bare read.
        raw_of = device.get_offset_slot()
        digits = "".join(ch for ch in raw_of if ch.isdigit())
        return device.get_offset_freq(int(digits) if digits else 0)

    return {
        "frequency_hz": s.frequency_hz,
        "mode": s.mode,
        "mode_description": s.mode_info.describe() if s.mode_info else None,
        "squelch": s.squelch,
        "volume": s.volume,
        "smeter": s.smeter,
        "smeter_dbm": s.smeter_reading.dbm if s.smeter_reading else None,
        "squelch_open": s.smeter_reading.squelch_open if s.smeter_reading else None,
        # LM's own 0-3 squelch-state digit (see device.SQUELCH_STATES) -
        # squelch_open above collapses states 1-3 into one boolean, which
        # hides state 3 ("detecting digital mode") behind the same
        # generic "open" the web panel already showed for a plain
        # noise/level/tone squelch opening. This lets the panel show
        # digital-signal detection as its own distinct indicator instead.
        "squelch_state": s.smeter_reading.squelch_state if s.smeter_reading else None,
        "agc_on": s.agc_on,
        "agc_speed": s.agc_speed,
        "attenuator_state": s.attenuator_state,
        "connected": device.connected,
        # Extended fields - see aor_dv10.device for the
        # manual-sourced, not-yet-wire-confirmed methods backing these.
        "squelch_level": _try(device.get_squelch_level),
        "noise_squelch_level": _try(device.get_noise_squelch_level),
        "frequency_step_hz": _try(device.get_frequency_step_hz),
        "step_adjust_hz": _try(device.get_step_adjust_hz),
        "tone_squelch_enabled": _try(device.get_tone_squelch_enabled),
        # Confirmed against real hardware: CI is a 3-value SQL TYPE
        # selector (OFF/CTCSS/Reverse Tone), not a boolean - see
        # aor_dv10.device.TONE_SQUELCH_TYPES and the "sqltype" verb
        # below. tone_squelch_enabled above stays for the existing
        # OFF/CTCSS toggle UI; this is the raw 0/1/2 value.
        "squelch_tone_type": _try(device.get_squelch_tone_type),
        "tone_squelch_freq": _try(device.get_tone_squelch_freq),
        "dcs_enabled": _try(device.get_dcs_enabled),
        "dcs_code": _try(device.get_dcs_code),
        "dmr_color_code": _try(device.get_dmr_color_code),
        "dmr_mute_by_color_code": _try(device.get_dmr_mute_by_color_code),
        "dmr_slot": _try(device.get_dmr_slot),
        "p25_nac": _try(device.get_p25_nac),
        "p25_mute_by_nac": _try(device.get_p25_mute_by_nac),
        "nxdn_ran": _try(device.get_nxdn_ran),
        "nxdn_mute_by_ran": _try(device.get_nxdn_mute_by_ran),
        "dcr_descramble_code": _try(device.get_dcr_descramble_code),
        "voice_descrambler_enabled": _try(device.get_voice_descrambler_enabled),
        "voice_descrambler_freq": _try(device.get_voice_descrambler_freq),
        "offset_slot": _try(device.get_offset_slot),
        "offset_freq": _try(_current_offset_freq),
        "priority_enabled": _try(device.get_priority_enabled),
        "priority_channel": _try(device.get_priority_channel),
        "priority_interval": _try(device.get_priority_interval),
        "beep_level": _try(device.get_beep_level),
        "volume_limit": _try(device.get_volume_limit),
        "digital_gain": _try(device.get_digital_gain),
        "manual_gain": _try(device.get_manual_gain),
        "lcd_contrast": _try(device.get_lcd_contrast),
        "backlight_mode": _try(device.get_backlight_mode),
        # Mode-aware IF bandwidth - see the "bw" verb above and
        # DV10Device.get_if_bandwidth_hz()/get_if_bandwidth_options_hz().
        # if_bandwidth_options_hz is {raw_digit: hz}; the panel only
        # needs the Hz values for its <select>, but the digits are kept
        # in case a future UI wants to show/send the raw value too.
        "if_bandwidth_hz": _try(device.get_if_bandwidth_hz),
        "if_bandwidth_options_hz": _try(device.get_if_bandwidth_options_hz),
        # Device identification, for the nameplate readout and for
        # model-specific UI gating (e.g. SAH/SAL aren't functionally
        # distinct on the DV10 - see aor_dv10.device.
        # ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY). model()/
        # device_family() are cached on the device object after their
        # first read, so polling these every 1.5s doesn't mean a fresh
        # WI wire round-trip every time.
        "model": _try(device.model),
        "device_family": _try(device.device_family),
        "analog_modes_without_distinction": sorted(_try(device.analog_modes_without_distinction) or set()),
    }


def _channel_json(c: MemoryChannel) -> dict:
    return {
        "bank": c.bank,
        "channel": c.channel,
        "bank_channel": c.bank_channel,
        "is_empty": c.is_empty,
        "protect": c.protect,
        "frequency_mhz": c.frequency_mhz,
        "step_hz": c.step_hz,
        "offset_khz": c.offset_khz,
        "mode": c.mode,
        "mode_description": c.describe_mode() if not c.is_empty else None,
        "pass_flag": c.pass_flag,
        "name": c.name.strip(),
    }


@app.post("/api/memory/import")
async def api_memory_import(request: Request):
    """Load an "AR-DV10 Connect" memory-bank backup CSV export (the file
    format the companion PC app produces, see aor_dv10.memory) into this
    server process's shared, in-memory "mem" state - browsed with
    GET /api/memory and tuned to with POST /api/memory/tune/{bank}/{channel}.
    Purely a file-format parse; nothing is sent to the device by importing.

    Takes the raw CSV bytes as the request body (not a multipart upload -
    the browser side just does fetch(..., {method: "POST", body: file}),
    a File object being a Blob) so this doesn't need the optional
    "python-multipart" package on top of the [web] extra's dependencies."""
    global _memory_banks, _memory_channels
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "empty request body - expected the raw CSV file bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"not a text file (expected UTF-8): {exc}")
    try:
        banks, channels = parse_backup_csv(text)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _memory_banks, _memory_channels = banks, channels
    programmed = sum(1 for c in channels if not c.is_empty)
    return {"banks": len(banks), "channels": len(channels), "programmed": programmed}


@app.get("/api/memory")
async def api_memory_list(
    q: Optional[str] = Query(None, description="case-insensitive substring match on channel name"),
    bank: Optional[int] = Query(None, ge=0, le=39),
    include_empty: bool = Query(False),
    limit: int = Query(200, ge=1, le=2000),
):
    """List/search the currently-imported memory database (see
    /api/memory/import). Capped at 2000 rows (the DV10's own total
    channel count) and 200 by default, since the full database is large
    enough that the browser shouldn't render it unbounded."""
    if not _memory_channels:
        raise HTTPException(404, "no memory database imported yet - POST /api/memory/import first")
    rows = _memory_channels
    if bank is not None:
        rows = [c for c in rows if c.bank == bank]
    if not include_empty:
        rows = [c for c in rows if not c.is_empty]
    if q:
        needle = q.strip().lower()
        rows = [c for c in rows if needle in c.name.strip().lower()]
    total = len(rows)
    return {
        "total": total,
        "returned": min(total, limit),
        "channels": [_channel_json(c) for c in rows[:limit]],
    }


@app.get("/api/memory/banks")
async def api_memory_banks():
    if not _memory_banks:
        raise HTTPException(404, "no memory database imported yet - POST /api/memory/import first")
    return {
        "banks": [
            {"index": b.index, "protect": b.protect, "title": b.title.strip()}
            for b in _memory_banks
        ]
    }


@app.post("/api/memory/tune/{bank}/{channel}")
async def api_memory_tune(bank: int, channel: int):
    """Tune the live device to an imported channel by replaying its
    frequency/mode/step through the ordinary, already-confirmed f/m/step
    writes (enter_vfo_mode() first, matching the precondition those writes
    already have) - NOT a live MX/MA memory-channel read, see
    aor_dv10.memory's module docstring."""
    if not _memory_channels:
        raise HTTPException(404, "no memory database imported yet - POST /api/memory/import first")
    match = next((c for c in _memory_channels if c.bank == bank and c.channel == channel), None)
    if match is None:
        raise HTTPException(404, f"no such channel: {bank:02d}-{channel:02d}")
    if match.is_empty:
        raise HTTPException(400, f"channel {match.bank_channel} is unprogrammed")

    device = get_device()
    async with _lock:
        try:
            device.enter_vfo_mode("A")
            device.set_frequency_hz(match.frequency_hz)
            if match.step_hz:
                device.set_frequency_step_hz(match.step_hz)
            if match.mode and len(match.mode) == 3:
                device.set_mode(match.mode[1:3])
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")
    return {"tuned": match.bank_channel, "frequency_mhz": match.frequency_mhz, "name": match.name.strip()}


@app.get("/api/debug/trace")
async def api_debug_trace(n: int = Query(50, ge=1, le=2000)):
    """Retroactive protocol trace - see the WS "debug last"/"debug save"
    verbs' comment in _dispatch_plain() and CommandChannel's always-on
    trace ring buffer. Every raw TX/RX line from either interface is
    recorded regardless of whether anyone asked for it beforehand."""
    device = get_device()
    return {"lines": device.trace_lines(n)}


@app.get("/api/memory/export")
async def api_memory_export():
    if not _memory_channels:
        raise HTTPException(404, "no memory database imported yet - POST /api/memory/import first")
    csv_text = write_backup_csv(_memory_banks, _memory_channels)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ardv10_memory_export.csv"'},
    )


def _dispatch_plain(device: DV10Device, line: str) -> object:
    """Same short-verb grammar as the desktop CLI, plain-text in/out.

    Most verbs return ``str``, but a handful of getters (``step``,
    ``stepadj``, ...) return whatever DV10Device itself returns - e.g.
    ``int | None`` for get_frequency_step_hz()/get_step_adjust_hz(). The
    CLI's REPL prints these fine as-is (rich's Console.print() stringifies
    anything); the WebSocket endpoint below is the one caller that needs
    an actual ``str`` to send over the wire, so it does the stringifying
    itself rather than every verb branch here doing it individually."""
    parts = shlex.split(line)
    if not parts:
        return ""
    verb, args = parts[0].lower(), parts[1:]

    def on_off(tok: str) -> bool:
        if tok.lower() in ("on", "1", "true"):
            return True
        if tok.lower() in ("off", "0", "false"):
            return False
        raise ValueError(f"expected on/off, got {tok!r}")

    if verb in ("help", "?"):
        return (
            "commands: s|status, f [MHZ], m [MODE], sq [0|1|2] (squelch MODE, not level), "
            "lq [LEVEL], nq [LEVEL], vol [LEVEL], agc on|off, agcspd [0-3], "
            "beep on|off, att on|off, attst [0-2], re on|off, vfo [A|B|Z], power on|off, "
            "step [HZ], stepadj [HZ], tone on|off, tonefreq [VALUE], dcs on|off, "
            "dcscode [VALUE], dmrcc [00-16], dmrcm on|off, dmrslot [VALUE], "
            "p25nac [000-FFF], p25pm on|off, nxdnran [00-63], nxdnnm on|off, "
            "dcrcode [00000-32767], descr on|off, offset [00-39] [+|-], offsetfreq [00-39] [MHZ], "
            "prio on|off, priochan [BANK] [CH], priointerval [1-99], regchan, beeplvl [0-7], "
            "vollimit [00-15], digain [01.00-15.94], mgain [000-110], contrast [00-63], "
            "backlight [VALUE], movenext, moveprev, "
            "debug last [N], debug save PATH, "
            "raw CODE [VALUE], describe CODE"
        )
    if verb in ("s", "status"):
        st = device.status()
        mode_desc = st.mode_info.describe() if st.mode_info else st.mode
        smeter_desc = st.smeter_reading.describe() if st.smeter_reading else st.smeter
        return (
            f"freq={st.frequency_hz and st.frequency_hz / 1_000_000:.6f}MHz "
            f"mode={mode_desc} sql_mode={st.squelch} vol={st.volume} "
            f"smeter={smeter_desc} agc={st.agc_speed or ('on' if st.agc_on else 'off')} "
            f"att={st.attenuator_state}"
        )
    if verb == "f":
        if args:
            device.set_frequency_hz(round(float(args[0]) * 1_000_000))
        return f"{device.get_frequency_hz() / 1_000_000:.6f} MHz"
    if verb == "m":
        if args:
            device.set_mode(args[0])
        return device.get_mode()
    if verb == "sq":
        if args:
            device.set_squelch(args[0])
        return device.get_squelch()
    if verb == "vol":
        if args:
            device.set_volume(args[0])
        return device.get_volume()
    if verb == "agc":
        device.set_agc(on_off(args[0]))
        return "ok"
    if verb == "beep":
        device.set_beep(on_off(args[0]))
        return "ok"
    if verb == "att":
        device.set_attenuator(on_off(args[0]))
        return "ok"
    if verb == "lq":
        if args:
            device.set_squelch_level(args[0])
        return device.get_squelch_level()
    if verb == "nq":
        if args:
            device.set_noise_squelch_level(args[0])
        return device.get_noise_squelch_level()
    if verb == "agcspd":
        if args:
            device.set_agc_speed(args[0])
        return device.get_agc_speed()
    if verb == "attst":
        if args:
            device.set_attenuator_state(args[0])
        return device.get_attenuator_state()
    if verb == "re":
        device.set_result_code_prefixing(on_off(args[0]))
        return "ok"
    if verb == "vfo":
        vfo = args[0] if args else "A"
        device.enter_vfo_mode(vfo)
        return f"VFO {vfo.upper()}"
    if verb == "power":
        if not args or args[0].lower() not in ("on", "off"):
            raise ValueError("usage: power on|off")
        resp = device.power_on() if args[0].lower() == "on" else device.power_off()
        # Surface the device's actual reply (same "CODE value" idiom as
        # the "raw" verb below) instead of a hardcoded "ok" that masked
        # whatever really came back - see PROTOCOL.md, QP's response was
        # never confirmed and this "ok" was hiding that gap.
        return f"{resp.code} {resp.value or ''}".strip()
    if verb == "raw":
        code, value = args[0], (args[1] if len(args) > 1 else None)
        resp = device.raw(code, value)
        return f"{resp.code} {resp.value or ''}".strip()
    if verb == "describe":
        return device.describe(args[0])
    # -- extended verbs - see aor_dv10.device for the
    # manual-sourced, not-yet-wire-confirmed methods backing these.
    if verb == "step":
        if args:
            device.set_frequency_step_hz(int(float(args[0])))
        return device.get_frequency_step_hz()
    if verb == "stepadj":
        if args:
            device.set_step_adjust_hz(int(float(args[0])))
        return device.get_step_adjust_hz()
    if verb == "tone":
        device.set_tone_squelch_enabled(on_off(args[0]))
        return "ok"
    if verb == "tonefreq":
        if args:
            device.set_tone_squelch_freq(args[0])
        return device.get_tone_squelch_freq()
    if verb == "dcs":
        device.set_dcs_enabled(on_off(args[0]))
        return "ok"
    if verb == "sqltype":
        # Confirmed against real hardware: CI is 0=OFF/1=CTCSS/
        # 2=Reverse Tone, not a boolean - see aor_dv10.device.
        # TONE_SQUELCH_TYPES. DCS is independent (DI, see "dcs" above),
        # not one of this selector's values.
        if args:
            device.set_squelch_tone_type(args[0])
        value = device.get_squelch_tone_type()
        return f"{value} ({TONE_SQUELCH_TYPES.get(value, 'unknown')})"
    if verb == "dcscode":
        if args:
            device.set_dcs_code(args[0])
        return device.get_dcs_code()
    if verb == "dmrcc":
        if args:
            device.set_dmr_color_code(int(args[0]))
        return device.get_dmr_color_code()
    if verb == "dmrcm":
        device.set_dmr_mute_by_color_code(on_off(args[0]))
        return "ok"
    if verb == "dmrslot":
        if args:
            device.set_dmr_slot(args[0])
        return device.get_dmr_slot()
    if verb == "p25nac":
        if args:
            device.set_p25_nac(args[0])
        return device.get_p25_nac()
    if verb == "p25pm":
        device.set_p25_mute_by_nac(on_off(args[0]))
        return "ok"
    if verb == "nxdnran":
        if args:
            device.set_nxdn_ran(int(args[0]))
        return device.get_nxdn_ran()
    if verb == "nxdnnm":
        device.set_nxdn_mute_by_ran(on_off(args[0]))
        return "ok"
    if verb == "dcrcode":
        if args:
            device.set_dcr_descramble_code(int(args[0]))
        return device.get_dcr_descramble_code()
    if verb == "descr":
        device.set_voice_descrambler_enabled(on_off(args[0]))
        return "ok"
    if verb == "offset":
        # OF takes an explicit direction sign
        # too - "offset <slot> [+|-]" (default "+") - see
        # DV10Device.set_offset_slot().
        if args:
            direction = args[1] if len(args) > 1 else "+"
            device.set_offset_slot(int(args[0]), direction)
        return device.get_offset_slot()
    if verb == "offsetfreq":
        # OL always needs an explicit slot number,
        # for both reads and writes - "offsetfreq <slot> [freq_mhz]" - see
        # DV10Device.get_offset_freq()/set_offset_freq(). With no args at
        # all, falls back to whatever slot OF currently has active.
        if len(args) >= 2:
            device.set_offset_freq(int(args[0]), float(args[1]))
        if args:
            slot = int(args[0])
        else:
            raw_of = device.get_offset_slot()
            digits = "".join(ch for ch in raw_of if ch.isdigit())
            slot = int(digits) if digits else 0
        return device.get_offset_freq(slot)
    if verb == "regchan":
        # MM: register the current VFO/channel as "last channel memory" -
        # see DV10Device.register_last_channel() for the
        # AR-DV1-spec two-phase-response handling this relies on.
        code = device.register_last_channel()
        return f"registration result code: {code}"
    if verb == "prio":
        device.set_priority_enabled(on_off(args[0]))
        return "ok"
    if verb == "priochan":
        if len(args) >= 2:
            device.set_priority_channel(int(args[0]), int(args[1]))
        return device.get_priority_channel()
    if verb == "priointerval":
        if args:
            device.set_priority_interval(int(args[0]))
        return device.get_priority_interval()
    if verb == "beeplvl":
        if args:
            device.set_beep_level(int(args[0]))
        return device.get_beep_level()
    if verb == "vollimit":
        if args:
            device.set_volume_limit(int(args[0]))
        return device.get_volume_limit()
    if verb == "digain":
        if args:
            device.set_digital_gain(float(args[0]))
        return device.get_digital_gain()
    if verb == "mgain":
        if args:
            device.set_manual_gain(int(args[0]))
        return device.get_manual_gain()
    if verb == "contrast":
        if args:
            device.set_lcd_contrast(int(args[0]))
        return device.get_lcd_contrast()
    if verb == "backlight":
        if args:
            device.set_backlight_mode(args[0])
        return device.get_backlight_mode()
    if verb == "id":
        model = device.model()
        firmware = device.firmware_version()
        family = device.device_family()
        return f"{model or '?'} (firmware {firmware or '?'}, family={family or 'unknown'})"
    if verb == "movenext":
        device.move_next()
        return "ok"
    if verb == "moveprev":
        device.move_previous()
        return "ok"
    # -- ported from the desktop CLI -
    # see aor_dv10.cli.repl.Repl.dispatch()/_dispatch_* for the originals.
    if verb == "vi":
        lines = []
        for v in device.read_vfo_info():
            freq = f"{v.frequency_hz / 1_000_000:.5f} MHz" if v.frequency_hz is not None else "?"
            lines.append(
                f"VFO-{v.vfo}  {freq}  step={v.step_hz}  stepadj={v.step_adjust_hz}  mode={v.mode}"
            )
        return "\n".join(lines) if lines else "(no VFOs)"
    if verb == "vs":
        device.execute_vfo_search()
        return "VFO search started"
    if verb == "ve":
        if args:
            delay_ds = int(args[0]) if len(args) > 0 else None
            free_s = int(args[1]) if len(args) > 1 else None
            auto_store = _on_off(args[2]) if len(args) > 2 else None
            device.write_vfo_search_settings(
                delay_ds=delay_ds, free_time_s=free_s, auto_store=auto_store
            )
        s = device.read_vfo_search_settings()
        return f"delay={s.delay_ds} free={s.free_time_s} autostore={s.auto_store}"
    if verb == "klcolor":
        if args:
            device.set_key_backlight_color(int(args[0]))
        n = device.get_key_backlight_color()
        return f"{n} ({KEY_BACKLIGHT_COLORS.get(n, 'unknown')})"
    if verb == "ifbw":
        if args:
            device.set_if_bandwidth(args[0])
        return device.get_if_bandwidth()
    if verb == "bw":
        # Mode-aware IF bandwidth by Hz value - see
        # DV10Device.set_if_bandwidth_hz()/get_if_bandwidth_options_hz().
        # Distinct from "ifbw" above, which takes/returns the raw digit
        # whose meaning depends on the current mode; this one lets the
        # web panel (and CLI) offer an actual "15 kHz"/"8 kHz"/"2.6 kHz"
        # picker instead of requiring the raw digit to be known already.
        # Mirrors the CLI's "bw" formatting (see cli/repl.py) rather than
        # a bare value, since this is the terminal a person is most
        # likely to actually be typing "bw" into live - see the choices
        # text for why an empty list can mean two different things
        # (unrecognised mode vs. a digital mode auto-selecting the
        # filter itself, not user-settable at all).
        if args:
            device.set_if_bandwidth_hz(int(args[0]))
        hz = device.get_if_bandwidth_hz()
        options = sorted(device.get_if_bandwidth_options_hz().values())
        if options:
            choices = ", ".join(str(v) for v in options)
        else:
            digital = device.get_mode_info().digital_select
            if digital and digital != "Digital off":
                choices = f"none - auto-selected by the receiver while digital ({digital}) is active"
            else:
                choices = "none known for the current mode"
        return f"{hz if hz is not None else '?'} Hz (choices: {choices})"
    if verb == "delay":
        if args:
            device.set_delay_time_ds(int(args[0]))
        return str(device.get_delay_time_ds())
    if verb == "freetime":
        if args:
            device.set_free_time_s(int(args[0]))
        return str(device.get_free_time_s())
    if verb == "serial":
        return device.get_serial_number()
    if verb == "rmem":
        return _dispatch_plain_rmem(device, args)
    if verb == "search":
        return _dispatch_plain_search(device, args)
    if verb == "scan":
        return _dispatch_plain_scan(device, args)
    if verb == "pass":
        return _dispatch_plain_pass(device, args)
    if verb == "timer":
        return _dispatch_plain_timer(device, args)
    if verb == "sd":
        return _dispatch_plain_sd(device, args)
    if verb == "scope":
        return _dispatch_plain_scope(device, args)
    if verb == "select":
        return _dispatch_plain_select(device, args)
    # -- protocol tracing - see aor_dv10.protocol.codec's
    # CommandChannel trace ring buffer: every raw TX/RX line is always
    # recorded regardless of interface, so these are purely retroactive
    # ("what actually happened") rather than a live toggle - a live sink
    # would need per-connection broadcast plumbing this endpoint doesn't
    # have yet. The CLI's "debug on" (aor_dv10.cli.repl) covers the
    # watch-it-happen-live case; this covers "pull the last N lines" from
    # the browser too, since both interfaces share one device/one trace.
    if verb == "debug":
        if not args:
            return "usage: debug last [N] | debug save <path>"
        sub, rest = args[0].lower(), args[1:]
        if sub == "last":
            n = int(rest[0]) if rest else 20
            lines = device.trace_lines(n)
            return "\n".join(lines) if lines else "(no trace recorded yet)"
        if sub == "save":
            if not rest:
                return "usage: debug save <path>"
            count = device.save_trace(rest[0])
            return f"Wrote {count} trace lines to {rest[0]}"
        return f"unknown 'debug' subcommand: {sub!r}"
    return f"unknown command: {verb!r} (try 'help')"


_WEEKDAY_BITS = {"sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64}


def _dispatch_plain_rmem(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_rmem() - see its docstring."""
    if not args:
        return (
            "usage: rmem read <bank> <ch> | rmem readbank <bank> | "
            "rmem write <bank> <ch> <freq_mhz> [mode] [tag...] | "
            "rmem tune <bank> <ch> | rmem delete <bank> <ch> | "
            "rmem bank <bank> | rmem bankset <bank> [count] [protect 0|1] [tag...] | "
            "rmem bankdel <bank> | rmem find <text> [bank]"
        )
    sub, rest = args[0].lower(), args[1:]

    def _fmt_channel(c) -> str:
        if not c.registered:
            return f"{c.bank:02d}-{c.channel:02d}  (not registered)"
        freq = f"{c.frequency_hz / 1_000_000:.5f} MHz" if c.frequency_hz is not None else "?"
        return (
            f"{c.bank:02d}-{c.channel:02d}  {freq}  mode={c.mode}  "
            f"pass={c.pass_channel} protect={c.write_protect}  {c.tag!r}"
        )

    if sub == "read":
        if len(rest) < 2:
            return "usage: rmem read <bank> <ch>"
        return _fmt_channel(device.read_memory_channel(int(rest[0]), int(rest[1])))
    if sub == "readbank":
        if not rest:
            return "usage: rmem readbank <bank>"
        channels = device.read_memory_bank(int(rest[0]))
        registered = [c for c in channels if c.registered]
        lines = [_fmt_channel(c) for c in registered]
        lines.append(f"({len(registered)} registered of {len(channels)} slots)")
        return "\n".join(lines)
    if sub == "write":
        if len(rest) < 3:
            return "usage: rmem write <bank> <ch> <freq_mhz> [mode] [tag...]"
        bank, ch = int(rest[0]), int(rest[1])
        freq_hz = round(float(rest[2]) * 1_000_000)
        mode = rest[3] if len(rest) > 3 else None
        tag = " ".join(rest[4:]) if len(rest) > 4 else None
        device.write_memory_channel(bank, ch, frequency_hz=freq_hz, mode=mode, tag=tag)
        return f"wrote {bank:02d}-{ch:02d}"
    if sub == "tune":
        if len(rest) < 2:
            return "usage: rmem tune <bank> <ch>"
        device.tune_memory_channel(int(rest[0]), int(rest[1]))
        return "ok"
    if sub == "delete":
        if len(rest) < 2:
            return "usage: rmem delete <bank> <ch>"
        device.delete_memory_channel(int(rest[0]), int(rest[1]))
        return "deleted"
    if sub == "bank":
        if not rest:
            return "usage: rmem bank <bank>"
        info = device.get_memory_bank_info(int(rest[0]))
        return (
            f"bank {info.bank:02d}: channels={info.channel_count} "
            f"protect={info.protect} tag={info.tag!r}"
        )
    if sub == "bankset":
        if not rest:
            return "usage: rmem bankset <bank> [count] [protect 0|1] [tag...]"
        bank = int(rest[0])
        count = int(rest[1]) if len(rest) > 1 else None
        protect = _on_off(rest[2]) if len(rest) > 2 else None
        tag = " ".join(rest[3:]) if len(rest) > 3 else None
        device.write_memory_bank(bank, channel_count=count, protect=protect, tag=tag)
        return f"bank {bank:02d} set"
    if sub == "bankdel":
        if not rest:
            return "usage: rmem bankdel <bank>"
        device.delete_memory_bank(int(rest[0]))
        return "bank deleted"
    if sub == "find":
        if not rest:
            return "usage: rmem find <text> [bank]"
        needle = rest[0].strip().lower()
        banks = [int(rest[1])] if len(rest) > 1 else list(range(40))
        hits = []
        for bank in banks:
            for c in device.read_memory_bank(bank):
                if c.registered and needle in c.tag.strip().lower():
                    hits.append(c)
        if not hits:
            return "(no matches)"
        lines = []
        for c in hits[:50]:
            freq = f"{c.frequency_hz / 1_000_000:.5f} MHz" if c.frequency_hz is not None else "?"
            lines.append(f"{c.bank:02d}-{c.channel:02d}  {freq}  mode={c.mode}  {c.tag!r}")
        if len(hits) > 50:
            lines.append(f"... and {len(hits) - 50} more")
        return "\n".join(lines)
    return f"unknown 'rmem' subcommand: {sub!r}"


def _dispatch_plain_search(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_search() - see its docstring."""
    if not args:
        return (
            "usage: search write <bank> [lo_mhz] [hi_mhz] [step_hz] [step_adj_hz] "
            "[mode] [protect 0|1] [tag...] | search read <bank> | search run <bank> | "
            "search delete <bank> | search lolimit [mhz] | search hilimit [mhz]"
        )
    sub, rest = args[0].lower(), args[1:]

    def _fmt_bank(info) -> str:
        lo = f"{info.lower_limit_hz / 1_000_000:.4f}" if info.lower_limit_hz is not None else "?"
        hi = f"{info.upper_limit_hz / 1_000_000:.4f}" if info.upper_limit_hz is not None else "?"
        return (
            f"bank {info.bank:02d}: {lo}-{hi} MHz  step={info.step_hz}  "
            f"stepadj={info.step_adjust_hz}  mode={info.mode}  "
            f"protect={info.write_protect}  {info.tag!r}"
        )

    if sub == "write":
        if not rest:
            return (
                "usage: search write <bank> [lo_mhz] [hi_mhz] [step_hz] [step_adj_hz] "
                "[mode] [protect 0|1] [tag...]"
            )
        bank = int(rest[0])
        lo = round(float(rest[1]) * 1_000_000) if len(rest) > 1 else None
        hi = round(float(rest[2]) * 1_000_000) if len(rest) > 2 else None
        step_hz = int(float(rest[3])) if len(rest) > 3 else None
        step_adj_hz = int(float(rest[4])) if len(rest) > 4 else None
        mode = rest[5] if len(rest) > 5 else None
        protect = _on_off(rest[6]) if len(rest) > 6 else False
        tag = " ".join(rest[7:]) if len(rest) > 7 else None
        device.write_search_bank(
            bank, lower_limit_hz=lo, upper_limit_hz=hi, step_hz=step_hz,
            step_adjust_hz=step_adj_hz, mode=mode, write_protect=protect, tag=tag,
        )
        return f"search bank {bank:02d} set"
    if sub == "read":
        if not rest:
            return "usage: search read <bank>"
        return _fmt_bank(device.read_search_bank(int(rest[0])))
    if sub == "run":
        if not rest:
            return "usage: search run <bank>"
        device.execute_search(int(rest[0]))
        return "search started"
    if sub == "delete":
        if not rest:
            return "usage: search delete <bank>"
        device.delete_search_bank(int(rest[0]))
        return "search bank deleted"
    if sub == "lolimit":
        if rest:
            device.set_search_lower_limit(round(float(rest[0]) * 1_000_000))
        hz = device.get_search_lower_limit()
        return f"{hz / 1_000_000:.4f} MHz" if hz is not None else "?"
    if sub == "hilimit":
        if rest:
            device.set_search_upper_limit(round(float(rest[0]) * 1_000_000))
        hz = device.get_search_upper_limit()
        return f"{hz / 1_000_000:.4f} MHz" if hz is not None else "?"
    return f"unknown 'search' subcommand: {sub!r}"


def _parse_bank_link_tokens(tokens: list[str]):
    """Ported from Repl._parse_bank_link_tokens() - see its docstring."""
    if tokens == ["clear"]:
        return []
    return [int(t) for t in tokens]


def _dispatch_plain_scan(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_scan() - see its docstring."""
    if not args:
        return (
            "usage: scan sread <group> | "
            "scan swrite <group> [delay_ds] [free_s] [autostore 0|1] [bank...|clear] | "
            "scan mread <group> | "
            "scan mwrite <group> [delay_ds] [free_s] [bank...|clear] | "
            "scan autostore [on|off] | scan banklink [bank...|clear]"
        )
    sub, rest = args[0].lower(), args[1:]

    def _fmt_group(info, *, kind: str) -> str:
        return (
            f"{kind} group {info.group:02d}: delay={info.delay_ds} free={info.free_time_s} "
            f"autostore={info.auto_store} banks={list(info.bank_link)}"
        )

    if sub == "sread":
        if not rest:
            return "usage: scan sread <group>"
        return _fmt_group(device.read_search_scan_group(int(rest[0])), kind="search")
    if sub == "swrite":
        if not rest:
            return "usage: scan swrite <group> [delay_ds] [free_s] [autostore 0|1] [bank...|clear]"
        group = int(rest[0])
        delay_ds = int(rest[1]) if len(rest) > 1 else None
        free_s = int(rest[2]) if len(rest) > 2 else None
        auto_store = _on_off(rest[3]) if len(rest) > 3 else None
        bank_link = _parse_bank_link_tokens(rest[4:]) if len(rest) > 4 else None
        device.write_search_scan_group(
            group, delay_ds=delay_ds, free_time_s=free_s,
            auto_store=auto_store, bank_link=bank_link,
        )
        return f"search scan group {group:02d} set"
    if sub == "mread":
        if not rest:
            return "usage: scan mread <group>"
        return _fmt_group(device.read_memory_scan_group(int(rest[0])), kind="memory")
    if sub == "mwrite":
        if not rest:
            return "usage: scan mwrite <group> [delay_ds] [free_s] [bank...|clear]"
        group = int(rest[0])
        delay_ds = int(rest[1]) if len(rest) > 1 else None
        free_s = int(rest[2]) if len(rest) > 2 else None
        bank_link = _parse_bank_link_tokens(rest[3:]) if len(rest) > 3 else None
        device.write_memory_scan_group(
            group, delay_ds=delay_ds, free_time_s=free_s, bank_link=bank_link,
        )
        return f"memory scan group {group:02d} set"
    if sub == "autostore":
        if rest:
            device.set_auto_store(_on_off(rest[0]))
        return "on" if device.get_auto_store() else "off"
    if sub == "banklink":
        if rest:
            device.set_bank_link(_parse_bank_link_tokens(rest))
        return str(device.get_bank_link())
    return f"unknown 'scan' subcommand: {sub!r}"


def _dispatch_plain_pass(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_pass() - see its docstring."""
    if not args:
        return (
            "usage: pass mark [mhz] | pass mark bank <bank> [mhz] | "
            "pass mark allbanks <mhz> | pass list [bank] | pass delete | "
            "pass delete bank <bank> [index] | pass delete allbanks"
        )
    sub, rest = args[0].lower(), args[1:]

    if sub == "mark":
        if rest and rest[0].lower() == "bank":
            if len(rest) < 2:
                return "usage: pass mark bank <bank> [mhz]"
            bank = int(rest[1])
            freq = round(float(rest[2]) * 1_000_000) if len(rest) > 2 else None
            device.mark_pass_frequency(frequency_hz=freq, bank=bank)
        elif rest and rest[0].lower() == "allbanks":
            if len(rest) < 2:
                return "usage: pass mark allbanks <mhz>"
            freq = round(float(rest[1]) * 1_000_000)
            device.mark_pass_frequency(frequency_hz=freq, all_banks=True)
        elif rest:
            freq = round(float(rest[0]) * 1_000_000)
            device.mark_pass_frequency(frequency_hz=freq)
        else:
            device.mark_pass_frequency()
        return "marked"
    if sub == "list":
        bank = int(rest[0]) if rest else None
        entries = device.list_pass_frequencies(bank=bank)
        used = [e for e in entries if e.frequency_hz is not None]
        lines = [f"{e.index:02d}: {e.frequency_hz / 1_000_000:.4f} MHz" for e in used]
        lines.append(f"({len(used)} of {len(entries)} slots used)")
        return "\n".join(lines)
    if sub == "delete":
        if rest and rest[0].lower() == "bank":
            if len(rest) < 2:
                return "usage: pass delete bank <bank> [index]"
            bank = int(rest[1])
            index = int(rest[2]) if len(rest) > 2 else None
            device.delete_pass_frequencies(bank=bank, index=index)
        elif rest and rest[0].lower() == "allbanks":
            device.delete_pass_frequencies(all_banks=True)
        elif not rest:
            device.delete_pass_frequencies()
        else:
            return "usage: pass delete | pass delete bank <bank> [index] | pass delete allbanks"
        return "deleted"
    return f"unknown 'pass' subcommand: {sub!r}"


def _dispatch_plain_timer(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_timer() - see its docstring, and
    aor_dv10.timer's module docstring for the significant
    spec-reconstruction caveats around TR."""

    def _fmt_timer(t: RecordingTimer) -> str:
        return (
            f"action={t.action} type={t.timer_type} repeat={t.repeat} "
            f"mode={t.receive_mode} start={t.start} end={t.end} "
            f"weekdays={list(t.weekdays)} volume={t.alarm_volume}"
        )

    if not args:
        return _fmt_timer(device.read_recording_timer())
    sub, rest = args[0].lower(), args[1:]

    if sub == "off":
        device.write_recording_timer(RecordingTimer(action="off"))
        return "timer deactivated"
    if sub == "set":
        if len(rest) < 4:
            return (
                "usage: timer set <target> <once|weekly> <start> <end> "
                "[alarm|recording] [days] [volume]"
            )
        target, repeat, start, end = rest[0], rest[1], rest[2], rest[3]
        action = rest[4] if len(rest) > 4 else "recording"
        days_arg = rest[5] if len(rest) > 5 else None
        volume = int(rest[6]) if len(rest) > 6 else None

        if target == "vs":
            receive_mode = receive_mode_vfo_search()
        elif target.startswith("vfo:"):
            receive_mode = receive_mode_vfo(target.split(":", 1)[1])
        elif target.startswith("bank:"):
            receive_mode = receive_mode_search_bank(int(target.split(":", 1)[1]))
        elif target.startswith("scan:"):
            receive_mode = receive_mode_memory_scan(int(target.split(":", 1)[1]))
        elif target.startswith("ch:"):
            bank_s, _, ch_s = target.split(":", 1)[1].partition("-")
            receive_mode = receive_mode_memory_channel(int(bank_s), int(ch_s))
        else:
            return (
                f'unknown target {target!r} - expected "vfo:A", "vs", "bank:<n>", '
                f'"ch:<bank>-<ch>", or "scan:<n>"'
            )

        if repeat not in ("once", "weekly"):
            return 'repeat must be "once" or "weekly"'
        weekdays: tuple = ()
        if days_arg and days_arg != "-":
            try:
                weekdays = tuple(_WEEKDAY_BITS[d.strip().lower()] for d in days_arg.split(","))
            except KeyError as exc:
                return f"unknown weekday {exc.args[0]!r} - use sun,mon,tue,wed,thu,fri,sat"

        device.write_recording_timer(
            RecordingTimer(
                action=action, repeat=repeat, receive_mode=receive_mode,
                start=start, end=end, weekdays=weekdays, alarm_volume=volume,
            )
        )
        return _fmt_timer(device.read_recording_timer())
    if sub in ("show", "status"):
        return _fmt_timer(device.read_recording_timer())
    return f"unknown 'timer' subcommand: {sub!r}"


def _dispatch_plain_sd(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_sd() - see its docstring."""
    if not args:
        return "usage: sd dir|info|status|rec|play|rsq|backup|restore ..."
    sub, rest = args[0].lower(), args[1:]

    if sub == "dir":
        files = device.sd_dir()
        if not files:
            return "(no files)"
        lines = []
        for f in files:
            detail = f"duration={f.duration}" if f.duration is not None else f"size={f.size_bytes}"
            ext = f".{f.extension}" if f.extension else ""
            lines.append(f"{f.name}{ext}  {detail}  {f.timestamp}")
        return "\n".join(lines)
    if sub == "info":
        info = device.sd_info()
        return f"free={info.free_kb}KB (~{info.free_hours}h)  total={info.total_kb}KB"
    if sub == "status":
        digit = device.sd_status()
        return f"{digit} - {SD_CARD_STATUS.get(digit, 'unknown')}"
    if sub == "rec":
        if not rest or rest[0].lower() not in ("start", "stop"):
            return "usage: sd rec start|stop"
        if rest[0].lower() == "start":
            device.sd_record_start()
            return "recording started"
        device.sd_record_stop()
        return "recording stopped"
    if sub == "play":
        if not rest:
            return "usage: sd play <name>|stop"
        if rest[0].lower() == "stop":
            device.sd_play_stop()
            return "playback stopped"
        device.sd_play(rest[0])
        return f"playing {rest[0]}"
    if sub == "rsq":
        if not rest:
            skip = device.get_sd_squelch_skip()
            return f"squelch skip: {'on' if skip == '1' else 'off'}"
        if rest[0].lower() not in ("on", "off"):
            return "usage: sd rsq [on|off]"
        device.set_sd_squelch_skip(rest[0].lower() == "on")
        return f"squelch skip set to {rest[0].lower()}"
    if sub == "backup":
        if not rest:
            return "usage: sd backup <kind> - one of SRCHBK/SRCHGRP/MEMCH/SCANGRP/SYSYEM"
        device.sd_backup(rest[0])
        return f"backed up {rest[0]}"
    if sub == "restore":
        if not rest:
            return "usage: sd restore <name>"
        device.sd_restore(rest[0])
        return f"restored {rest[0]}"
    return f"unknown 'sd' subcommand: {sub!r}"


def _dispatch_plain_scope(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_scope() - see its docstring re: the "no
    known way to enter scope mode" caveat, which applies here identically."""
    if not args or args[0].lower() not in ("fast", "normal"):
        return "usage: scope fast|normal"
    sub = args[0].lower()
    ramp = " .:-=+*#%@"

    def _spark(values: list) -> str:
        if not values:
            return "(no data)"
        lo, hi = min(values), max(values)
        if hi == lo:
            return ramp[-1] * len(values)
        span = hi - lo
        return "".join(ramp[round((v - lo) / span * (len(ramp) - 1))] for v in values)

    if sub == "fast":
        dbm_values = device.read_scope_data_fast()
        lines = [_spark(dbm_values)]
        if dbm_values:
            lines.append(f"{len(dbm_values)} points, {min(dbm_values)}..{max(dbm_values)} dBm")
        return "\n".join(lines)

    lines_data = device.read_scope_data_normal()
    if not lines_data:
        return "(no data)"
    levels = [int(line.level_raw) for line in lines_data]
    lo_mhz = lines_data[0].frequency_hz / 1_000_000
    hi_mhz = lines_data[-1].frequency_hz / 1_000_000
    return (
        f"{_spark(levels)}\n"
        f"{len(lines_data)} points, {lo_mhz:.5f}-{hi_mhz:.5f} MHz"
    )


def _dispatch_plain_select(device: DV10Device, args: list[str]) -> str:
    """Ported from Repl._dispatch_select() - see its docstring. Uses the
    module-level _select_scan_list (shared by every browser tab against
    this one server process), unlike the CLI's per-Repl-instance one."""
    if not args:
        return (
            "usage: select add <bank> <ch> | select remove <bank> <ch> | "
            "select list | select clear | select run [cycles] [dwell_s]"
        )
    sub, rest = args[0].lower(), args[1:]

    if sub == "add":
        if len(rest) < 2:
            return "usage: select add <bank> <ch>"
        _select_scan_list.add(int(rest[0]), int(rest[1]))
        return f"added {int(rest[0]):02d}-{int(rest[1]):02d} ({len(_select_scan_list)} in list)"
    if sub == "remove":
        if len(rest) < 2:
            return "usage: select remove <bank> <ch>"
        removed = _select_scan_list.remove(int(rest[0]), int(rest[1]))
        return "removed" if removed else "(not in list)"
    if sub == "list":
        if not _select_scan_list.entries:
            return "(empty)"
        return "\n".join(f"{bank:02d}-{channel:02d}" for bank, channel in _select_scan_list)
    if sub == "clear":
        _select_scan_list.clear()
        return "cleared"
    if sub == "run":
        cycles = int(rest[0]) if len(rest) > 0 and rest[0].lower() != "none" else None
        dwell_s = float(rest[1]) if len(rest) > 1 else 2.0
        entries = list(_select_scan_list.entries)
        lines = []
        for bank, channel in run_select_scan(
            device.tune_memory_channel, entries, dwell_s=dwell_s, cycles=cycles
        ):
            lines.append(f"-> {bank:02d}-{channel:02d}")
        return "\n".join(lines) if lines else "(nothing scanned)"
    return f"unknown 'select' subcommand: {sub!r}"


def _detect_local_ip() -> str:
    """Best-effort LAN IP for mDNS advertisement: opens a UDP socket toward
    a public address (UDP "connect" sends no packets) purely to ask the OS
    which local interface/IP it would route through - the standard
    cross-platform trick for this. Falls back to loopback if there's no
    route (e.g. offline)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _start_mdns(name: str, port: int):
    """Advertise this web panel on the LAN as "<name>.local", so it can be
    reached at http://<name>.local:<port>/ instead of an IP address - the
    same pattern printers and other LAN appliances use. Returns a
    (Zeroconf, ServiceInfo) pair to unregister on shutdown, or (None, None)
    if the "zeroconf" package isn't installed or registration otherwise
    fails - the server still runs either way, just without the friendly
    name (reachable by IP:port as before)."""
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        print(
            "--mdns was given but the 'zeroconf' package isn't installed - "
            "run: pip install -e \".[web]\" (it's included in the web extra). "
            "Continuing without mDNS; the panel is still reachable by IP:port."
        )
        return None, None

    ip = _detect_local_ip()
    hostname = f"{name}.local."
    try:
        info = ServiceInfo(
            "_http._tcp.local.",
            f"{name}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            server=hostname,
            properties={"path": "/"},
        )
        zc = Zeroconf()
        zc.register_service(info)
        print(f"Advertising on the LAN as http://{name}.local:{port}/ (resolved to {ip})")
        return zc, info
    except Exception as exc:  # pragma: no cover - best-effort, network-dependent
        print(f"mDNS advertisement failed ({exc}); continuing without it.")
        return None, None


@dataclass
class EmbeddedWebPanel:
    """A web panel running in a background thread against a device this
    process already owns - returned by :func:`start_in_thread`. Call
    :meth:`stop` to shut it (and any mDNS advertisement) back down."""

    server: "object"  # uvicorn.Server - typed loosely so importing this module doesn't require uvicorn
    thread: threading.Thread
    host: str
    port: int
    mdns_name: Optional[str]
    _zc: object = None
    _zc_info: object = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def mdns_url(self) -> Optional[str]:
        return f"http://{self.mdns_name}.local:{self.port}/" if self.mdns_name else None

    def stop(self, timeout: float = 3.0) -> None:
        """Ask the background uvicorn server to shut down and wait (up to
        ``timeout`` seconds) for its thread to exit, then unregister any
        mDNS advertisement. Safe to call even if startup failed partway."""
        self.server.should_exit = True
        self.thread.join(timeout=timeout)
        if self._zc is not None:
            self._zc.unregister_service(self._zc_info)
            self._zc.close()


def start_in_thread(
    device: DV10Device,
    *,
    host: Optional[str] = None,
    port: int = 8000,
    mdns: bool = False,
    mdns_name: str = "aordv10",
) -> EmbeddedWebPanel:
    """Run this web panel in a background thread against an ALREADY-CONNECTED
    device, for embedding into another entry point - see cli/__main__.py's
    ``--web`` flag, the reason this exists: the CLI and the web panel share
    one DV10Device / one serial connection instead of each opening (and
    fighting over) its own, which usually wouldn't even work - most OSes
    only let one process hold a serial port open at a time.

    Does NOT call device.connect()/disconnect() - the caller owns the
    device's lifecycle and should call EmbeddedWebPanel.stop() before
    disconnecting it. Raises ImportError with a friendly message if the
    "zeroconf" package is needed (mdns=True) but not installed - matching
    _start_mdns()'s standalone behaviour, except here it's surfaced as an
    exception rather than a print+continue, since the caller (the CLI) is
    better placed to decide how to report it alongside its own output.
    """
    global _device
    _device = device

    resolved_host = host if host is not None else ("0.0.0.0" if mdns else "127.0.0.1")

    import uvicorn

    zc = zc_info = None
    used_mdns_name: Optional[str] = None
    if mdns:
        zc, zc_info = _start_mdns(mdns_name, port)
        if zc is not None:
            used_mdns_name = mdns_name

    config = uvicorn.Config(app, host=resolved_host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="dv10-web")
    thread.start()

    return EmbeddedWebPanel(
        server=server,
        thread=thread,
        host=resolved_host,
        port=port,
        mdns_name=used_mdns_name,
        _zc=zc,
        _zc_info=zc_info,
    )


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    device = get_device()
    await websocket.send_text("Connected to AR-DV10 web panel. Type 'help' for commands.")
    try:
        while True:
            line = await websocket.receive_text()
            async with _lock:
                try:
                    reply = _dispatch_plain(device, line)
                except (DV10Error, ValueError, IndexError) as exc:
                    reply = f"error: {exc}"
            # _dispatch_plain() returns non-str for a few numeric getters
            # (see its docstring) - websocket.send_text() requires an
            # actual str, so stringify here rather than at every one of
            # _dispatch_plain()'s many verb branches.
            if reply is None:
                reply = ""
            elif not isinstance(reply, str):
                reply = str(reply)
            await websocket.send_text(reply)
    except WebSocketDisconnect:
        pass


def main(argv: list[str] | None = None) -> int:
    global _device
    parser = argparse.ArgumentParser(description="AOR AR-DV10 web panel server")
    parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: 127.0.0.1, or 0.0.0.0 automatically if --mdns is given, "
        "since other devices on the LAN need to reach it)",
    )
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    parser.add_argument("--serial-port", help="Explicit USB serial device; omit to auto-detect")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--simulator", action="store_true", help="Use the in-process simulator")
    parser.add_argument(
        "--mdns",
        action="store_true",
        help="Advertise the panel on the LAN via mDNS as http://<--mdns-name>.local:<port>/ "
        "(needs the 'zeroconf' package, included in the [web] extra). SECURITY: this exposes "
        "control of the receiver, including power on/off, to anyone on your LAN with no "
        "authentication - only use it on a network you trust.",
    )
    parser.add_argument(
        "--mdns-name",
        default="aordv10",
        help='mDNS hostname label to advertise as (default: "aordv10", giving http://aordv10.local)',
    )
    args = parser.parse_args(argv)

    host = args.host if args.host is not None else ("0.0.0.0" if args.mdns else "127.0.0.1")

    import uvicorn

    _device = (
        DV10Device.open_simulator()
        if args.simulator
        else DV10Device.open_serial(port=args.serial_port, baudrate=args.baud)
    )
    try:
        _device.connect()
    except TransportError as exc:
        print(f"Could not connect: {exc}")
        return 1

    zc = zc_info = None
    if args.mdns:
        zc, zc_info = _start_mdns(args.mdns_name, args.port)

    try:
        uvicorn.run(app, host=host, port=args.port)
    finally:
        _device.disconnect()
        if zc is not None:
            zc.unregister_service(zc_info)
            zc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
