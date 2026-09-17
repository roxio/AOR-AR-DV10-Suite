
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from .protocol.parsing import parse_known_fields

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
    letter = letter.strip().upper()
    if letter not in ("A", "B", "Z"):
        raise ValueError(f'vfo letter must be "A", "B", or "Z" - got {letter!r}')
    return f"VF{letter}"


def receive_mode_vfo_search() -> str:
    return "VS"


def receive_mode_search_bank(bank: int) -> str:
    return f"SS{int(bank):02d}"


def receive_mode_memory_channel(bank: int, channel: int) -> str:
    return f"MR{int(bank):02d}{int(channel):02d}"


def receive_mode_memory_scan(bank: int) -> str:
    return f"MS{int(bank):02d}"


def format_once_time(month: int, day: int, hour: int, minute: int) -> str:
    return f"{int(month):02d}{int(day):02d}{int(hour):02d}{int(minute):02d}"


def format_weekly_time(hour: int, minute: int) -> str:
    return f"{int(hour):02d}{int(minute):02d}"


def parse_timer_time(repeat: str, raw: str) -> dict:
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
    total = 0
    for d in days:
        total |= int(d)
    return str(total)


def parse_weekday_mask(raw: str) -> Tuple[int, ...]:
    raw = raw.strip()
    if not raw.isdigit():
        return ()
    total = int(raw)
    return tuple(bit for bit in (1, 2, 4, 8, 16, 32, 64) if total & bit)


@dataclass
class RecordingTimer:

    action: str = "off"
    timer_type: Optional[int] = None
    repeat: Optional[str] = None
    receive_mode: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    weekdays: tuple = ()
    alarm_volume: Optional[int] = None


def format_timer_value(timer: RecordingTimer) -> str:
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
    return parse_known_fields(text, ("XE", "TY", "RP", "RM", "TS", "TE", "WE", "AG"))


def parse_timer_response(text: str) -> RecordingTimer:
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
