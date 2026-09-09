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

from ..cli.repl import _on_off, _parse_clock_digits
from ..device import DV10Device, KEY_BACKLIGHT_COLORS, MemoryChannelInfo, SD_CARD_STATUS, TONE_SQUELCH_TYPES
from ..memory import (
    MemoryBank,
    MemoryChannel,
    from_live_channel,
    parse_backup_csv,
    write_backup_csv,
)
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
# process. File-format only, like the CLI's "mem" verbs: never touches the live
# MX/MA wire commands, only replays a loaded channel through f/m/step writes.
_memory_banks: list[MemoryBank] = []
_memory_channels: list[MemoryChannel] = []

# Client-side select-scan list, shared by every browser tab, never persisted
# or written to the receiver. See aor_dv10.selectscan.
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
            # Mirrors device.status()'s _try: swallow unexpected-format values
            # so one bad field can't take down the whole /api/status response.
            return None

    def _current_offset_freq():
        # OL requires an explicit slot number, so derive it from OF's
        # currently-active slot rather than assuming a bare read.
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
        # LM's raw 0-3 squelch-state digit. squelch_open above collapses 1-3
        # into one boolean, hiding state 3 ("detecting digital mode"); this lets
        # the panel show digital detection as its own indicator.
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
        # Confirmed against real hardware: CI is a 3-value SQL TYPE selector
        # (OFF/CTCSS/Reverse Tone), not a boolean. tone_squelch_enabled above
        # stays for the OFF/CTCSS toggle UI; this is the raw 0/1/2 value.
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
        # Mode-aware IF bandwidth. if_bandwidth_options_hz is {raw_digit: hz};
        # the panel needs only the Hz values, but the digits are kept in case a
        # future UI wants the raw value.
        "if_bandwidth_hz": _try(device.get_if_bandwidth_hz),
        "if_bandwidth_options_hz": _try(device.get_if_bandwidth_options_hz),
        # Device identification, for the nameplate and model-specific UI gating
        # (e.g. SAH/SAL are not distinct on the DV10). model()/device_family()/
        # firmware_version() are cached after first read, so polling every 1.5s
        # does not mean a fresh WI/VR round-trip each time.
        "model": _try(device.model),
        "device_family": _try(device.device_family),
        "firmware_version": _try(device.firmware_version),
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


@app.get("/api/memory/live_export/{bank}")
async def api_memory_live_export(bank: int):
    """Export a bank's LIVE content (MA) into this same backup-CSV shape
    (proposal item 17) - bridging the two separate worlds this project
    has had until now: the CSV-backup browser above (aor_dv10.memory,
    populated only by POST /api/memory/import) and the live-read/write
    rmem WS verbs (MA/MX directly against the receiver). Always reads
    fresh from the device - nothing cached here the way
    /api/memory/import's server-side state is. See
    aor_dv10.memory.from_live_channel()'s docstring for the field
    caveats this bridge can't fully paper over (mode format, no
    offset/step-adjust on the live side)."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    device = get_device()
    async with _lock:
        try:
            live_channels = device.read_memory_bank(bank)
            bank_info = device.get_memory_bank_info(bank)
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")
    csv_channels = [from_live_channel(c) for c in live_channels]
    csv_bank = MemoryBank(index=bank, protect=bank_info.protect, title=bank_info.tag)
    csv_text = write_backup_csv([csv_bank], csv_channels)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="ardv10_bank{bank:02d}_live_export.csv"'
        },
    )


@app.get("/api/memory/diff/{bank}")
async def api_memory_diff(bank: int):
    """Compare a CSV-imported bank (see /api/memory/import) against a
    fresh LIVE re-read (MA) of the same bank, to see what has changed on
    the receiver since the last backup (proposal item 18). Returns only
    the channels that actually differ - an empty list means this bank's
    CSV backup still matches the live receiver (or both sides are fully
    unprogrammed). See aor_dv10.memory.from_live_channel()'s docstring
    for what this comparison can't reliably say: there is no live
    counterpart for offset_khz/step_adjust_hz, and the mode field's
    exact wire shape isn't confirmed to match between the two worlds, so
    a reported mode difference is weaker evidence than a frequency/
    protect/name/pass-flag one."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    if not _memory_channels:
        raise HTTPException(404, "no memory database imported yet - POST /api/memory/import first")
    backup_by_channel = {c.channel: c for c in _memory_channels if c.bank == bank}
    device = get_device()
    async with _lock:
        try:
            live_channels = device.read_memory_bank(bank)
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")

    diffs = []
    for live in live_channels:
        live_csv = from_live_channel(live)
        backup = backup_by_channel.get(live.channel) or MemoryChannel(bank=bank, channel=live.channel)
        backup_key = (
            backup.is_empty, backup.frequency_hz, backup.mode,
            backup.protect, backup.pass_flag, backup.name.strip(),
        )
        live_key = (
            live_csv.is_empty, live_csv.frequency_hz, live_csv.mode,
            live_csv.protect, live_csv.pass_flag, live_csv.name.strip(),
        )
        if backup_key == live_key:
            continue
        diffs.append({
            "bank_channel": live_csv.bank_channel,
            "backup": _channel_json(backup),
            "live": _channel_json(live_csv),
        })
    return {
        "bank": bank,
        "compared": len(live_channels),
        "differences": len(diffs),
        "channels": diffs,
    }


def _live_channel_json(c: MemoryChannelInfo) -> dict:
    return {
        "bank": c.bank,
        "channel": c.channel,
        "bank_channel": f"{c.bank:02d}-{c.channel:02d}",
        "registered": c.registered,
        "pass_channel": c.pass_channel,
        "frequency_hz": c.frequency_hz,
        "frequency_mhz": (c.frequency_hz / 1_000_000) if c.frequency_hz is not None else None,
        "step_hz": c.step_hz,
        "step_adjust_hz": c.step_adjust_hz,
        "mode": c.mode,
        "write_protect": c.write_protect,
        "tag": c.tag.strip() if c.tag else "",
    }


def _parse_live_channel_write_body(body: dict) -> dict:
    """Shared field parsing for the two write endpoints below - takes the
    already-JSON-decoded request body dict and returns the kwargs
    write_memory_channel() wants, doing the mhz->hz conversion and basic
    type coercion by hand (no pydantic model - this file otherwise parses
    request bodies manually too, see api_memory_import())."""
    kwargs: dict = {}
    if body.get("frequency_mhz") is not None:
        kwargs["frequency_hz"] = round(float(body["frequency_mhz"]) * 1_000_000)
    if body.get("step_hz") is not None:
        kwargs["step_hz"] = int(body["step_hz"])
    if body.get("step_adjust_hz") is not None:
        kwargs["step_adjust_hz"] = int(body["step_adjust_hz"])
    if body.get("mode") is not None and str(body["mode"]).strip() != "":
        kwargs["mode"] = str(body["mode"]).strip()
    if body.get("pass_channel"):
        kwargs["pass_channel"] = True
    if body.get("write_protect"):
        kwargs["write_protect"] = True
    if body.get("tag") is not None:
        kwargs["tag"] = str(body["tag"])
    return kwargs


def _complete_write_kwargs(device: DV10Device, bank: int, channel: int, kwargs: dict) -> dict:
    """Fill any field the request left out from the channel's CURRENT stored
    record, so the MX that goes out is always the receiver's own complete
    canonical form (MP/RF/ST/SH/MD/PT/TT), never a partial one.

    Real-hardware finding: a partial MX - one missing sub-fields the
    receiver's own channel dump always carries - comes back error 40
    (PC_RESULT_FORMAT_ERR), even though the AR-DV1 spec calls those fields
    optional-and-keep-previous. Rather than trust "keep previous", this
    reads the record and resends the previous values explicitly, which is
    also what makes an edit of one field provably leave the rest alone.

    An unregistered slot has nothing to carry over (every field but
    bank/channel/registered is meaningless there - see MemoryChannelInfo),
    so it is programmed from exactly what the request supplied."""
    try:
        current = device.read_memory_channel(bank, channel)
    except DV10Error:
        return kwargs
    if not current.registered:
        return kwargs
    merged = dict(kwargs)
    for key, value in (
        ("frequency_hz", current.frequency_hz),
        ("step_hz", current.step_hz),
        ("step_adjust_hz", current.step_adjust_hz),
        ("mode", current.mode),
        ("tag", current.tag),
    ):
        if merged.get(key) is None and value is not None:
            merged[key] = value
    return merged


@app.get("/api/memory/live_bank/{bank}")
async def api_memory_live_bank(bank: int):
    """Bank editor (table view): read every channel slot in a live bank
    as structured JSON, including the fields the CSV-shaped
    /api/memory/live_export/{bank} can't carry (step_adjust_hz has no CSV
    counterpart - see aor_dv10.memory.from_live_channel()'s docstring).
    Always reads fresh from the device, same as live_export."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    device = get_device()
    async with _lock:
        try:
            channels = device.read_memory_bank(bank)
            bank_info = device.get_memory_bank_info(bank)
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")
    return {
        "bank": bank,
        "bank_tag": bank_info.tag.strip(),
        "bank_protect": bank_info.protect,
        "channel_count": bank_info.channel_count,
        "channels": [_live_channel_json(c) for c in channels],
    }


@app.post("/api/memory/live_bank/{bank}/batch")
async def api_memory_live_bank_batch_write(bank: int, request: Request):
    """Bank editor: write multiple channels in one bank in one request -
    the "overwrite whole bank" action (the browser loops this endpoint
    once per selected bank for "overwrite several banks", rather than
    this project inventing a second cross-bank endpoint for what's really
    just "do the per-bank thing more than once").

    Body: {"channels": [{"channel": N, ...same fields as the single-write
    endpoint..., "force": bool}, ...], "force": bool} - a per-item force
    overrides the batch-level default for that one item. Each channel is
    attempted independently: one write-protect refusal or device error
    doesn't abort the rest, so a stuck/protected slot can't turn a whole-
    bank overwrite into an all-or-nothing operation. Returns per-channel
    results so the UI can show exactly which rows saved and which
    didn't."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    body = await request.json()
    items = body.get("channels") or []
    batch_force = bool(body.get("force"))
    device = get_device()
    results = []
    async with _lock:
        for item in items:
            try:
                ch = int(item["channel"])
            except (KeyError, TypeError, ValueError):
                results.append({"channel": item.get("channel"), "ok": False, "error": "missing/invalid channel"})
                continue
            if not (0 <= ch <= 49):
                results.append({"channel": ch, "ok": False, "error": "channel must be 00-49"})
                continue
            force = batch_force or bool(item.get("force"))
            try:
                if not force:
                    current = device.read_memory_channel(bank, ch)
                    if current.registered and current.write_protect:
                        results.append({"channel": ch, "ok": False, "error": "write-protected (retry with force)"})
                        continue
                kwargs = _complete_write_kwargs(
                    device, bank, ch, _parse_live_channel_write_body(item)
                )
                device.write_memory_channel(bank, ch, **kwargs)
                results.append({"channel": ch, "ok": True})
            except DV10Error as exc:
                results.append({"channel": ch, "ok": False, "error": str(exc)})
    return {"bank": bank, "results": results}


@app.post("/api/memory/live_bank/{bank}/{channel}")
async def api_memory_live_channel_write(bank: int, channel: int, request: Request):
    """Bank editor: write one live memory channel (MX) - the per-row Save
    action. Body: any of frequency_mhz/step_hz/step_adjust_hz/mode/
    pass_channel/write_protect/tag (all optional, same "omitted = leave
    unchanged" semantics as write_memory_channel() itself), plus an
    optional force:true.

    Write-protect guard (same spirit as the WS rmem panel's rmemWrite()
    JS guard, proposal item 15 - enforced server-side here since this is
    a stateless per-request API rather than something a JS confirm-arm
    can straddle across two calls to the SAME endpoint): refuses with 409
    if the channel is CURRENTLY write-protected and force wasn't set,
    rather than silently overwriting it. The browser side re-asks the
    user and retries the same request with force:true."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    if not (0 <= channel <= 49):
        raise HTTPException(400, "channel must be 00-49")
    body = await request.json()
    force = bool(body.get("force"))
    kwargs = _parse_live_channel_write_body(body)
    device = get_device()
    async with _lock:
        try:
            if not force:
                current = device.read_memory_channel(bank, channel)
                if current.registered and current.write_protect:
                    raise HTTPException(
                        409, "channel is write-protected - retry with force:true to override"
                    )
            kwargs = _complete_write_kwargs(device, bank, channel, kwargs)
            device.write_memory_channel(bank, channel, **kwargs)
            updated = device.read_memory_channel(bank, channel)
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")
    return _live_channel_json(updated)


@app.delete("/api/memory/live_bank/{bank}/{channel}")
async def api_memory_live_channel_delete(bank: int, channel: int):
    """Bank editor: delete one live memory channel (MQ) - the table's
    per-row Delete action. Same underlying call as the WS "rmem delete"
    verb (device.delete_memory_channel())."""
    if not (0 <= bank <= 39):
        raise HTTPException(400, "bank must be 00-39")
    if not (0 <= channel <= 49):
        raise HTTPException(400, "channel must be 00-49")
    device = get_device()
    async with _lock:
        try:
            device.delete_memory_channel(bank, channel)
        except DV10Error as exc:
            raise HTTPException(502, f"device error: {exc}")
    return {"deleted": f"{bank:02d}-{channel:02d}"}


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
            "backlight [VALUE], movenext, moveprev, sp [VALUE], sn, "
            "mem load/find/list/goto/export, "
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
        # "vfo [A|B|Z] [mhz] [mode]". On a real DV10 the atomic VF write only
        # changes the VFO letter - embedded RF/MD fields are a silent no-op - so
        # frequency/mode go through the standalone RF and MD writes after it.
        vfo = (args[0] if args else "A").strip().upper()
        if vfo not in ("A", "B", "Z"):
            raise ValueError(f'vfo must be "A", "B", or "Z"')
        device.enter_vfo_mode(vfo)
        if len(args) > 1:
            device.set_frequency_hz(round(float(args[1]) * 1_000_000))
        if len(args) > 2:
            device.set_mode(args[2])
        return f"VFO {vfo}"
    if verb == "power":
        if not args or args[0].lower() not in ("on", "off"):
            raise ValueError("usage: power on|off")
        resp = device.power_on() if args[0].lower() == "on" else device.power_off()
        # Surface the device's actual reply instead of a hardcoded "ok": QP's
        # response was never confirmed and the "ok" was hiding that gap.
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
        # Confirmed against real hardware: CI is 0=OFF/1=CTCSS/2=Reverse Tone,
        # not a boolean. DCS is independent (DI), not one of these values.
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
        # OF takes an explicit direction sign: "offset <slot> [+|-]" (default "+").
        if args:
            direction = args[1] if len(args) > 1 else "+"
            device.set_offset_slot(int(args[0]), direction)
        return device.get_offset_slot()
    if verb == "offsetfreq":
        # OL always needs an explicit slot number, for reads and writes:
        # "offsetfreq <slot> [freq_mhz]". With no args, falls back to whatever
        # slot OF currently has active.
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
        # MM: register the current VFO/channel as "last channel memory". Relies
        # on register_last_channel()'s two-phase-response handling.
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
        # Mode-aware IF bandwidth by Hz value. Distinct from "ifbw" above,
        # which takes the raw digit whose meaning depends on the current mode;
        # this one lets the UI offer a real "15 kHz"/"8 kHz" picker. An empty
        # option list means either an unrecognised mode or a digital mode that
        # picks the filter itself - see the choices text.
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
    if verb == "zi":
        if args:
            device.set_receiver_id(" ".join(args))
        return device.get_receiver_id()
    if verb == "clock":
        if args:
            yy, mm, dd, hh, minute = _parse_clock_digits(" ".join(args))
            device.set_clock(yy, mm, dd, hh, minute)
        return device.get_clock()
    if verb == "writeprotect":
        if args:
            device.set_write_protect(_on_off(args[0]))
        return device.get_write_protect()
    if verb == "reset":
        full = bool(args) and args[0].strip().lower() in ("full", "1")
        device.reset(full=full)
        return "reset sent (full)" if full else "reset sent (system)"
    # -- previously raw-console-only commands. See DV10Device's get_*/set_*
    # docstrings for the shared "raw passthrough, format unconfirmed" caveats.
    if verb == "an":
        if args:
            device.set_earphone_antenna(_on_off(args[0]))
        return device.get_earphone_antenna()
    if verb == "ct":
        if args:
            device.set_function_code(" ".join(args))
        return device.get_function_code()
    if verb == "dj":
        if not args:
            raise ValueError("dj requires a value - it's write-only, there's nothing to read back")
        device.set_digital_data_output(" ".join(args))
        return "sent"
    if verb == "dk":
        return device.acquire_digital_data()
    if verb == "lc":
        if args:
            device.set_freq_data_output(_on_off(args[0]))
        return device.get_freq_data_output()
    if verb == "lt":
        if args:
            device.set_smeter_data_output(_on_off(args[0]))
        return device.get_smeter_data_output()
    if verb == "ox":
        if args:
            device.set_monitor_offset(_on_off(args[0]))
        return device.get_monitor_offset()
    if verb == "ts":
        if args:
            device.set_ttc_slot_number(" ".join(args))
        return device.get_ttc_slot_number()
    if verb == "vq":
        if args:
            device.set_voice_squelch(" ".join(args))
        return device.get_voice_squelch()
    if verb == "zs":
        if args:
            device.set_power_save(_on_off(args[0]))
        return device.get_power_save()
    if verb == "zt":
        if args:
            device.set_power_save_silent_time(" ".join(args))
        return device.get_power_save_silent_time()
    if verb == "rt":
        if args:
            device.set_receiver_status_output(_on_off(args[0]))
        return device.get_receiver_status_output()
    if verb == "rx":
        return device.get_receiver_status()
    if verb == "sb":
        if args:
            device.set_comm_speed(" ".join(args))
        return device.get_comm_speed()
    if verb == "sp":
        if args:
            device.set_sleep_timer(" ".join(args))
        return device.get_sleep_timer()
    if verb == "sn":
        return device.serial_number()
    if verb == "mem":
        return _dispatch_plain_mem(device, args)
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
    # -- protocol tracing. CommandChannel always records every TX/RX line, so
    # these endpoints are retroactive ("what actually happened"), not a live
    # toggle - a live sink would need broadcast plumbing this doesn't have.
    # The CLI's "debug on" covers watching it live; both share one trace.
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

    if sub == "dump":
        if not rest:
            return "usage: rmem dump <bank>"
        chans = device.read_memory_bank(int(rest[0]))
        lines = [_fmt_channel(c) for c in chans]
        lines.append(f"({len([c for c in chans if c.registered])} registered of {len(chans)} slots)")
        return "\n".join(lines)
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


def _dispatch_plain_mem(device: DV10Device, args: list[str]) -> str:
    """Proposal item 46: the "mem ..." verb family (load/find/list/goto/
    export - see Repl._dispatch_mem() for the original) was reachable only
    through REST (/api/memory/*), never as a text command like every other
    verb here - awkward from the Raw Console or a script. Ported to operate
    on this module's shared _memory_banks/_memory_channels (the same state
    POST /api/memory/import fills and GET /api/memory reads), so importing
    from the browser and "mem list"-ing from the console see the same data.

    Deliberately separate from "rmem ..." (the live MX/MA/MR/MW/MB/MQ wire
    commands, see _dispatch_plain_rmem()) - same file-format-only split as
    the CLI, see aor_dv10.memory's module docstring and
    aor_dv10.device.MemoryChannelInfo's docstring for why the two field
    layouts aren't interchangeable.

    "mem load <path>" reads a file from the SERVER's filesystem (the same
    machine this process runs on) - consistent with "debug save <path>"
    already doing server-side file I/O from this same console. Browser
    uploads go through POST /api/memory/import instead; either path fills
    the same shared state."""
    global _memory_banks, _memory_channels
    if not args:
        return (
            "usage: mem load <path> | mem find <text> | mem list [bank] | "
            "mem goto <bank>-<ch> | mem export <path>"
        )
    sub, rest = args[0].lower(), args[1:]

    if sub == "load":
        if not rest:
            return "usage: mem load <path>"
        path = rest[0]
        try:
            with open(path, "rb") as f:
                text = f.read().decode("utf-8-sig")
        except OSError as exc:
            return f"error: could not read {path!r}: {exc}"
        try:
            banks, channels = parse_backup_csv(text)
        except ValueError as exc:
            return f"error: {exc}"
        _memory_banks, _memory_channels = banks, channels
        programmed = sum(1 for c in channels if not c.is_empty)
        return (
            f"Loaded {len(banks)} banks / {len(channels)} channel slots "
            f"({programmed} programmed) from {path}"
        )
    if not _memory_channels:
        return "no memory database loaded - use 'mem load <path>' or POST /api/memory/import first"
    if sub == "find":
        if not rest:
            return "usage: mem find <text>"
        needle = " ".join(rest).strip().lower()
        hits = [
            c for c in _memory_channels
            if not c.is_empty and needle in c.name.strip().lower()
        ]
        if not hits:
            return "(no matches)"
        lines = [
            f"{c.bank_channel}  {c.frequency_mhz:9.5f} MHz  {c.mode}  {c.name.strip()}"
            for c in hits[:50]
        ]
        if len(hits) > 50:
            lines.append(f"... and {len(hits) - 50} more")
        return "\n".join(lines)
    if sub == "list":
        bank_filter = int(rest[0]) if rest else None
        rows = [
            c for c in _memory_channels
            if not c.is_empty and (bank_filter is None or c.bank == bank_filter)
        ]
        if not rows:
            return ("(no programmed channels)" if bank_filter is None else
                    f"(no programmed channels in bank {bank_filter:02d})")
        lines = [
            f"{c.bank_channel}  {c.frequency_mhz:9.5f} MHz  {c.mode}  {c.name.strip()}"
            for c in rows[:100]
        ]
        if len(rows) > 100:
            lines.append(f"... and {len(rows) - 100} more (use 'mem find' to narrow)")
        return "\n".join(lines)
    if sub == "goto":
        if not rest:
            return "usage: mem goto <bank>-<ch>"
        bank_str, _, ch_str = rest[0].partition("-")
        try:
            bank, channel = int(bank_str), int(ch_str)
        except ValueError:
            return f'expected "<bank>-<ch>", e.g. "00-05", got {rest[0]!r}'
        match = next(
            (c for c in _memory_channels if c.bank == bank and c.channel == channel),
            None,
        )
        if match is None:
            return f"error: no such channel: {bank:02d}-{channel:02d}"
        if match.is_empty:
            return f"error: channel {match.bank_channel} is unprogrammed"
        device.enter_vfo_mode("A")
        device.set_frequency_hz(match.frequency_hz)
        if match.step_hz:
            device.set_frequency_step_hz(match.step_hz)
        if match.mode and len(match.mode) == 3:
            device.set_mode(match.mode[1:3])
        return (
            f"Tuned to {match.bank_channel} ({match.name.strip() or 'unnamed'}): "
            f"{match.frequency_mhz:.5f} MHz"
        )
    if sub == "export":
        if not rest:
            return "usage: mem export <path>"
        path = rest[0]
        out = write_backup_csv(_memory_banks, _memory_channels)
        try:
            with open(path, "wb") as f:
                f.write(out.encode("utf-8"))
        except OSError as exc:
            return f"error: could not write {path!r}: {exc}"
        return f"Wrote {len(_memory_channels)} channel slots to {path}"
    return f"unknown 'mem' subcommand: {sub!r}"


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
        # AR-DV1's documented remote stop (SD REC /) WEDGES an AR-DV10 -
        # recording stops with the front-panel key only. Deny rather than send.
        if device.device_family() == "DV10":
            raise ValueError(
                "sd rec stop is not supported on the AR-DV10 - "
                "stop recording with the receiver's front-panel ● (record) key"
            )
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
        # SD MMW (file backup) is "No function" on the AR-DV10, AR-DV1/DV3 only.
        if device.device_family() == "DV10":
            raise ValueError(
                "sd backup is not supported on the AR-DV10 - it's an AR-DV1/DV3 feature"
            )
        device.sd_backup(rest[0])
        return f"backed up {rest[0]}"
    if sub == "restore":
        if not rest:
            return "usage: sd restore <name>"
        # SD MMR (file restore) is "No function" on the AR-DV10, AR-DV1/DV3 only.
        if device.device_family() == "DV10":
            raise ValueError(
                "sd restore is not supported on the AR-DV10 - it's an AR-DV1/DV3 feature"
            )
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
            # _dispatch_plain() returns non-str for a few numeric getters and
            # send_text() needs a str - stringify here rather than in every one
            # of its verb branches.
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
