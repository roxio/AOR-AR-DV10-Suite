"""Typed encode/decode for TR, the AR-DV1's scheduled recording/alarm
timer. Confirmed from the AR-DV1 spec for what's confirmed vs.
reconstructed here.

Deliberately its OWN module, not folded into device.py, mirroring how
aor_dv10.memory was split out for the CSV backup format (see that
module's own docstring for the general principle): TR is "a command
embedded inside a command" (its RM sub-field is itself a small grammar of
5 different shapes - VFx/VS/SSbb/MRbbcc/MSbb), and the AR-DV1 spec's own
table entry for TR is INTERNALLY INCONSISTENT in a way none of this
project's other composite commands are - worth keeping isolated so a
future correction doesn't ripple through device.py's other, more solidly
confirmed sections.

THE SPEC INCONSISTENCY, IN DETAIL (independently re-verified by reading
page 21 of the AR-DV1 COMMAND LIST PDF directly, both as a rendered image
and via the PDF's own extracted text layer - the two agree, so this isn't
an OCR artifact on this project's end):

* The command's own syntax cell reads (verbatim): "TR1 TYe RPm RMrrr....
  TSttt.... TEttt.... WEx... AGvv" - i.e. NO "XE" field at all, and "TR1"
  rather than "TRn".
* But the very same table entry's Remarks/Default lines read: "Timer will
  quit when TRnXE0 command is executed (i.e. e=0)" and "Default: TRn XE0
  TY0 RMVFA TS01010000 TE01010000" - both CLEARLY using "TRn" (not "TR1")
  and CLEARLY including an "XE" field the syntax cell never mentions.

This project treats the Remarks/Default prose as authoritative over the
syntax cell (a table cell is exactly the kind of place a Word->PDF export
tool - this document was built with PrimoPDF/Nitro per its own metadata -
silently drops or garbles content; free-flowing prose sentences don't
fail the same way), and reconstructs the real field list as:

    TRn XEe [TYy] [RPm] [RMrrr....] [TSttt....] [TEttt....] [WEx....] [AGvv]

with XE always required (never shown omitted anywhere) and every other
field individually optional, based on the remark "TY, RM, TS, TE, WE may
be omitted at the same time regardless of 'm' parameter" plus RP itself
being absent from the Default line alongside WE/AG (implying it, too,
defaults when omitted - to "m=0", one-time).

STILL GENUINELY UNRESOLVED, not just "unconfirmed against real hardware"
but unconfirmable from this document at all:

* TY's value is used in the syntax ("TYe"/"TYy" in different renderings)
  but NEVER DEFINED anywhere in this command's entry - every other
  variable letter (e for XE, m for RP, rr for RM, ttt for TS/TE, x for
  WE, vv for AG) gets an explicit "letter = meaning" line except this
  one. TY is modelled here as an OPAQUE passthrough (``timer_type``,
  an int 0-9 or None) - not validated, not interpreted. Treat any
  particular value as a guess.
* Whether "n" in "TRn" is a real multi-timer index (this receiver having
  more than one independent schedule slot) or just this document's
  generic single-letter-placeholder convention applied to something that
  is actually a single, unnumbered timer is NOT determinable from the
  spec: no range is ever given for "n" (contrast with e.g. SE's "bb ---
  bank" or SG's group range, both spelled out elsewhere in this same
  document), and "To read: TR<CR>" is bare - no index argument at all,
  unlike every genuinely-numbered/indexed read in this spec (SRbb, SGgg,
  MGgg, PRbb, ...). This project therefore models TR as a SINGLE,
  unnumbered timer - see DV10Device.read_recording_timer()/
  write_recording_timer(), which take no timer-number argument - but
  this is this project's own interpretation of an ambiguous document,
  not a spec statement.
* WE's value width is never given a digit count (contrast with every
  other field here, which all specify one, e.g. "mm: Delay time 01~99").
  format_weekday_mask() below sends the plain decimal sum with no
  padding, flagged the same way.

None of this has been checked against real hardware. Given the above, the
signature exposed here (RecordingTimer, format_timer_value(),
parse_timer_response()) is a best-effort reconstruction, not a confirmed
implementation - callers should treat every value modelled here as a
hypothesis to verify, especially TY and WE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

# Weekday bitmask values, exactly as the AR-DV1 spec's own WE table lists
# them (see the module docstring's "WE's value width" caveat for why the
# rendered width of the SUM of these is itself unconfirmed).
SUNDAY = 1
MONDAY = 2
TUESDAY = 4
WEDNESDAY = 8
THURSDAY = 16
FRIDAY = 32
SATURDAY = 64

_ACTION_TO_CODE = {"off": "0", "alarm": "1", "recording": "2"}
_CODE_TO_ACTION = {v: k for k, v in _ACTION_TO_CODE.items()}

_REPEAT_TO_CODE = {"once": "0", "weekly": "1"}
_CODE_TO_REPEAT = {v: k for k, v in _REPEAT_TO_CODE.items()}


def receive_mode_vfo(letter: str) -> str:
    """Build TR's RM sub-field for "receive on VFO <letter>" - RM's own
    "VFx = Specify VFO mode. X is for one of A, B and Z" shape."""
    letter = letter.strip().upper()
    if letter not in ("A", "B", "Z"):
        raise ValueError(f'vfo letter must be "A", "B", or "Z" - got {letter!r}')
    return f"VF{letter}"


def receive_mode_vfo_search() -> str:
    """Build TR's RM sub-field for "receive via VFO search" - RM's own
    "VS = Specify VFO Search" shape."""
    return "VS"


def receive_mode_search_bank(bank: int) -> str:
    """Build TR's RM sub-field for "receive via a program search over
    search bank ``bank``" - RM's own "SSbb = Specify Programming Search"
    shape."""
    return f"SS{int(bank):02d}"


def receive_mode_memory_channel(bank: int, channel: int) -> str:
    """Build TR's RM sub-field for "receive a specific live memory
    channel" - RM's own "MRbbcc = Specify memory channel" shape."""
    return f"MR{int(bank):02d}{int(channel):02d}"


def receive_mode_memory_scan(bank: int) -> str:
    """Build TR's RM sub-field for "receive via a memory scan over bank
    ``bank``" - RM's own "MSbb = Specify memory channel [scan]" shape
    (the spec's own wording literally says "memory channel" here too,
    almost certainly a copy-paste from the MR line just above it in the
    same cell - modelled as memory SCAN, matching the MS mnemonic and
    this project's own existing memory-scan naming, not as a second way
    to spell MR)."""
    return f"MS{int(bank):02d}"


def format_once_time(month: int, day: int, hour: int, minute: int) -> str:
    """TR's TS/TE field for a one-time (``repeat="once"``) schedule -
    "MMDDhhmm" per the spec's own "ttt.... = Time start or time end. One
    time specifies as MMDDhhmm" line."""
    return f"{int(month):02d}{int(day):02d}{int(hour):02d}{int(minute):02d}"


def format_weekly_time(hour: int, minute: int) -> str:
    """TR's TS/TE field for a weekly (``repeat="weekly"``) schedule -
    "hhmm" (24-hour) per the same spec line's "Weekly time specifies as
    hhmm in 24 hour display"."""
    return f"{int(hour):02d}{int(minute):02d}"


def parse_timer_time(repeat: str, raw: str) -> dict:
    """Decode a TS/TE value per ``repeat`` ("once" => MMDDhhmm 8 digits,
    "weekly" => hhmm 4 digits). Returns a plain dict rather than a
    dataclass since the field set genuinely differs by ``repeat`` and a
    caller almost always already knows which one it asked for. Returns
    ``{}`` for anything that doesn't parse as digits of the expected
    length, rather than raising - this is read-back decoding, not input
    validation."""
    raw = raw.strip()
    if repeat == "once" and len(raw) == 8 and raw.isdigit():
        return {
            "month": int(raw[0:2]),
            "day": int(raw[2:4]),
            "hour": int(raw[4:6]),
            "minute": int(raw[6:8]),
        }
    if repeat == "weekly" and len(raw) == 4 and raw.isdigit():
        return {"hour": int(raw[0:2]), "minute": int(raw[2:4])}
    return {}


def format_weekday_mask(days) -> str:
    """Sum the given weekday bit values (SUNDAY/MONDAY/.../SATURDAY, or
    their raw ints) into TR's WE field. No zero-padding - the spec never
    states a digit width for this field, unlike every other field in the
    same table row, see the module docstring."""
    total = 0
    for d in days:
        total |= int(d)
    return str(total)


def parse_weekday_mask(raw: str) -> Tuple[int, ...]:
    """Decompose a WE value back into the individual weekday bits it's
    made of (SUNDAY/MONDAY/.../SATURDAY subset), in that order. Returns
    an empty tuple for anything that isn't a parseable non-negative
    integer."""
    raw = raw.strip()
    if not raw.isdigit():
        return ()
    total = int(raw)
    return tuple(bit for bit in (1, 2, 4, 8, 16, 32, 64) if total & bit)


@dataclass
class RecordingTimer:
    """TR: the scheduled recording/alarm timer - see this module's
    docstring for the significant reconstruction/ambiguity caveats before
    trusting any field here, especially ``timer_type`` (spec never
    defines what it means) and ``weekdays`` (spec never states WE's wire
    width).

    ``action`` is XE: "off" (0, deactivate), "alarm" (1), or "recording"
    (2) - the one field that's always sent, never omitted, per the spec's
    own remark that the timer is stopped specifically via "TRnXE0".

    Every other field is optional and independently omittable when
    writing (``None`` => omit that sub-field, the same omit-convention
    every other composite write in this project follows - see
    aor_dv10.device.write_search_bank()'s docstring for what that implies
    about "keeps previous value" vs. "resets"; TR's own spec text doesn't
    actually say which applies here, unlike SE's, so treat that as
    ANOTHER unconfirmed point, not a stated fact).

    ``receive_mode`` is a raw RM token - build one with
    receive_mode_vfo()/receive_mode_vfo_search()/
    receive_mode_search_bank()/receive_mode_memory_channel()/
    receive_mode_memory_scan() rather than hand-formatting it.

    ``start``/``end`` are raw TS/TE tokens - build one with
    format_once_time()/format_weekly_time() depending on ``repeat``,
    decode one with parse_timer_time().
    """

    action: str = "off"  # "off" | "alarm" | "recording"
    timer_type: Optional[int] = None  # TY - UNDOCUMENTED meaning, opaque passthrough
    repeat: Optional[str] = None  # "once" | "weekly" - None means omit RP (defaults to "once")
    receive_mode: Optional[str] = None  # raw RM token
    start: Optional[str] = None  # raw TS token
    end: Optional[str] = None  # raw TE token
    weekdays: tuple = ()  # weekly only - WEEKDAY_* bit values
    alarm_volume: Optional[int] = None  # AG - 00 to 99


def format_timer_value(timer: RecordingTimer) -> str:
    """Render a RecordingTimer as the value to send after "TR" (device.py
    prepends "TR" itself, matching every other composite command in this
    project). Field order follows the spec's own syntax cell: XE TY RP RM
    TS TE WE AG - see the module docstring for why XE is trusted from the
    Remarks/Default prose rather than the syntax cell, which omits it."""
    if timer.action not in _ACTION_TO_CODE:
        raise ValueError(f'action must be "off", "alarm", or "recording" - got {timer.action!r}')
    parts = [f"XE{_ACTION_TO_CODE[timer.action]}"]
    if timer.timer_type is not None:
        parts.append(f"TY{int(timer.timer_type)}")
    if timer.repeat is not None:
        if timer.repeat not in _REPEAT_TO_CODE:
            raise ValueError(f'repeat must be "once" or "weekly" - got {timer.repeat!r}')
        parts.append(f"RP{_REPEAT_TO_CODE[timer.repeat]}")
    if timer.receive_mode is not None:
        parts.append(f"RM{timer.receive_mode}")
    if timer.start is not None:
        parts.append(f"TS{timer.start}")
    if timer.end is not None:
        parts.append(f"TE{timer.end}")
    if timer.weekdays:
        parts.append(f"WE{format_weekday_mask(timer.weekdays)}")
    if timer.alarm_volume is not None:
        parts.append(f"AG{int(timer.alarm_volume):02d}")
    return " ".join(parts)


def _parse_fields(text: str) -> dict:
    """Split a TR response body into {2-letter code: value} by matching
    each of TR's own known field codes at successive whitespace-separated
    token starts - deliberately a small, self-contained copy of the same
    approach aor_dv10.device._parse_composite_fields() uses (rather than
    importing it), keeping this module independent - see the module
    docstring for why. Only recognises TR's own fields (XE/TY/RP/RM/TS/
    TE/WE/AG); an unrecognised token is skipped rather than raising, the
    same "be lenient reading, be careful writing" stance the rest of this
    project takes."""
    codes = ("XE", "TY", "RP", "RM", "TS", "TE", "WE", "AG")
    fields: dict = {}
    for token in text.split():
        for code in codes:
            if token.upper().startswith(code):
                fields[code] = token[len(code):]
                break
    return fields


def parse_timer_response(text: str) -> RecordingTimer:
    """Decode a TR read-back response body into a RecordingTimer. Unknown
    or missing fields decode to their "omitted" representation (None/())
    rather than raising - this is read-back decoding of a device response,
    not validation of user input."""
    fields = _parse_fields(text.strip())
    action = _CODE_TO_ACTION.get(fields.get("XE", ""), "off")
    ty_raw = fields.get("TY")
    repeat_raw = fields.get("RP")
    return RecordingTimer(
        action=action,
        timer_type=int(ty_raw) if ty_raw and ty_raw.isdigit() else None,
        repeat=_CODE_TO_REPEAT.get(repeat_raw) if repeat_raw is not None else None,
        receive_mode=fields.get("RM"),
        start=fields.get("TS"),
        end=fields.get("TE"),
        weekdays=parse_weekday_mask(fields.get("WE", "")),
        alarm_volume=int(fields["AG"]) if fields.get("AG", "").isdigit() else None,
    )
