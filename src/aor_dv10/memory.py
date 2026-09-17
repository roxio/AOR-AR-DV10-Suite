
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Optional

from .constants import BANK_COUNT as _BANK_COUNT, CHANNELS_PER_BANK as _CHANNELS_PER_BANK
from .device import ANALOG_MODES, DIGITAL_MODES, MemoryChannelInfo

_HEADER_PREFIX = "DEPMICRO-BACKUP"
_JSON_FORMAT = "aor-dv10-suite.memory"

_CHIRP_HEADER = [
    "Location", "Name", "Frequency", "Duplex", "Offset", "Tone",
    "rToneFreq", "cToneFreq", "DtcsCode", "DtcsPolarity", "Mode", "TStep",
    "Skip", "Comment", "URCALL", "RPT1CALL", "RPT2CALL", "DVCODE",
]
_CHIRP_MODE_FROM_ANALOG = {
    "0": "FM", "1": "AM", "2": "FM", "3": "FM",
    "4": "USB", "5": "LSB", "6": "CW",
}
_ANALOG_FROM_CHIRP_MODE = {
    "FM": "0", "NFM": "0", "WFM": "0", "AM": "1", "USB": "4",
    "LSB": "5", "CW": "6", "RTTY": "6", "RTTYR": "6",
}

_GENERIC_FREQ_ALIASES = {
    "frequency": "freq", "freq": "freq", "mhz": "freq",
    "freq_mhz": "freq", "frequency_mhz": "freq",
    "name": "name", "label": "name", "tag": "name", "title": "name",
    "mode": "mode", "modulation": "mode",
    "step": "step", "step_khz": "step", "tstep": "step",
}


def _pad_name(name: str) -> str:
    name = (name or "")[:12]
    return name.ljust(12)


def _parse_bank_channel(bbcc: str) -> tuple[int, int]:
    bbcc = bbcc.strip().zfill(4)
    return int(bbcc[:2]), int(bbcc[2:])


@dataclass
class MemoryBank:

    index: int
    protect: bool
    title: str

    def to_csv_row(self) -> str:
        return f"MB,{self.index:02d},{1 if self.protect else 0},{_pad_name(self.title)}"


@dataclass
class MemoryChannel:

    bank: int
    channel: int
    protect: bool = False
    frequency_hz: Optional[int] = None
    step_hz: Optional[int] = None
    offset_khz: Optional[float] = None
    mode: Optional[str] = None
    pass_flag: bool = False
    name: str = ""

    @property
    def bank_channel(self) -> str:
        return f"{self.bank:02d}-{self.channel:02d}"

    @property
    def is_empty(self) -> bool:
        return self.frequency_hz is None

    @property
    def frequency_mhz(self) -> Optional[float]:
        return None if self.frequency_hz is None else self.frequency_hz / 1_000_000

    def describe_mode(self) -> str:
        if not self.mode or len(self.mode) < 3:
            return "?"
        d, a, n = self.mode[0], self.mode[1], self.mode[2]
        return f"{DIGITAL_MODES.get(a, a)} / {ANALOG_MODES.get(n, n)}"

    def to_csv_row(self) -> str:
        bbcc = f"{self.bank:02d}{self.channel:02d}"
        if self.is_empty:
            return f"MC,{bbcc},,,,,,,{_pad_name('')}"
        freq = f"{self.frequency_mhz:010.5f}"
        step_khz = (self.step_hz or 0) / 1000
        offset = self.offset_khz if self.offset_khz is not None else 0.0
        mode = (self.mode or "000").ljust(3)[:3]
        return (
            f"MC,{bbcc},{1 if self.protect else 0},{freq},"
            f"{step_khz:06.2f},{offset:06.2f},{mode},"
            f"{1 if self.pass_flag else 0},{_pad_name(self.name)}"
        )



def from_live_channel(info: MemoryChannelInfo) -> MemoryChannel:
    if not info.registered:
        return MemoryChannel(bank=info.bank, channel=info.channel)
    return MemoryChannel(
        bank=info.bank,
        channel=info.channel,
        protect=info.write_protect,
        frequency_hz=info.frequency_hz,
        step_hz=info.step_hz,
        offset_khz=None,
        mode=info.mode,
        pass_flag=info.pass_channel,
        name=info.tag.strip(),
    )


def parse_backup_csv(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    text = text.lstrip("﻿")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(_HEADER_PREFIX):
        raise ValueError(
            f'not an AR-DV10 Connect backup file - expected the first line to '
            f'start with {_HEADER_PREFIX!r}, got '
            f'{(lines[0][:40] if lines else "(empty file)")!r}'
        )

    banks: list[MemoryBank] = []
    channels: list[MemoryChannel] = []
    for lineno, line in enumerate(lines[1:], start=2):
        fields = line.split(",")
        record = fields[0].strip()
        if record == "MB":
            if len(fields) != 4:
                raise ValueError(f"line {lineno}: MB record with {len(fields)} fields, expected 4")
            index = int(fields[1])
            protect = fields[2].strip() == "1"
            title = fields[3].rstrip()
            banks.append(MemoryBank(index=index, protect=protect, title=title))
        elif record == "MC":
            if len(fields) != 9:
                raise ValueError(f"line {lineno}: MC record with {len(fields)} fields, expected 9")
            bank, channel = _parse_bank_channel(fields[1])
            freq_raw = fields[3].strip()
            if not freq_raw:
                channels.append(MemoryChannel(bank=bank, channel=channel))
                continue
            channels.append(
                MemoryChannel(
                    bank=bank,
                    channel=channel,
                    protect=fields[2].strip() == "1",
                    frequency_hz=round(float(freq_raw) * 1_000_000),
                    step_hz=round(float(fields[4]) * 1000) if fields[4].strip() else None,
                    offset_khz=float(fields[5]) if fields[5].strip() else None,
                    mode=fields[6].strip() or None,
                    pass_flag=fields[7].strip() == "1",
                    name=fields[8].rstrip(),
                )
            )
        else:
            raise ValueError(f"line {lineno}: unrecognised record type {record!r}")

    return banks, channels


def write_backup_csv(
    banks: list[MemoryBank], channels: list[MemoryChannel], *, timestamp: str = ""
) -> str:
    lines = [f"DEPMICRO-BACKUP,MEM BANK,AR-DV10,P,{timestamp}"]
    lines.extend(b.to_csv_row() for b in sorted(banks, key=lambda b: b.index))
    lines.extend(c.to_csv_row() for c in sorted(channels, key=lambda c: (c.bank, c.channel)))
    return "\r\n".join(lines) + "\r\n"


def empty_bank_set() -> tuple[list[MemoryBank], list[MemoryChannel]]:
    banks = [MemoryBank(index=i, protect=False, title="") for i in range(_BANK_COUNT)]
    channels = [
        MemoryChannel(bank=b, channel=c)
        for b in range(_BANK_COUNT)
        for c in range(_CHANNELS_PER_BANK)
    ]
    return banks, channels




def backup_to_json(banks: list[MemoryBank], channels: list[MemoryChannel]) -> str:
    data = {
        "format": _JSON_FORMAT,
        "version": 1,
        "banks": [
            {"index": b.index, "protect": b.protect, "title": b.title}
            for b in sorted(banks, key=lambda b: b.index)
        ],
        "channels": [
            {
                "bank": c.bank,
                "channel": c.channel,
                "protect": c.protect,
                "frequency_hz": c.frequency_hz,
                "step_hz": c.step_hz,
                "offset_khz": c.offset_khz,
                "mode": c.mode,
                "pass_flag": c.pass_flag,
                "name": c.name,
            }
            for c in sorted(channels, key=lambda c: (c.bank, c.channel))
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def backup_from_json(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}")
    if not isinstance(data, dict) or data.get("format") != _JSON_FORMAT:
        raise ValueError("not an aor-dv10-suite memory JSON backup")

    banks, channels = empty_bank_set()
    by_bank = {b.index: b for b in banks}
    for b in data.get("banks", []) or []:
        try:
            idx = int(b["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if idx in by_bank:
            by_bank[idx].protect = bool(b.get("protect"))
            by_bank[idx].title = str(b.get("title", ""))
    by_ch = {(c.bank, c.channel): c for c in channels}
    for c in data.get("channels", []) or []:
        try:
            key = (int(c["bank"]), int(c["channel"]))
        except (KeyError, TypeError, ValueError):
            continue
        target = by_ch.get(key)
        if target is None:
            continue
        target.protect = bool(c.get("protect"))
        target.frequency_hz = c.get("frequency_hz")
        target.step_hz = c.get("step_hz")
        target.offset_khz = c.get("offset_khz")
        target.mode = c.get("mode")
        target.pass_flag = bool(c.get("pass_flag"))
        target.name = str(c.get("name", ""))
    return banks, channels




def write_chirp_csv(channels: list[MemoryChannel]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(_CHIRP_HEADER)
    loc = 0
    for c in sorted(channels, key=lambda c: (c.bank, c.channel)):
        if c.is_empty:
            continue
        code = c.mode if (c.mode and len(c.mode) == 3) else "0F0"
        digital, analog = code[1], code[2]
        mode = "DV" if digital != "F" else _CHIRP_MODE_FROM_ANALOG.get(analog, "FM")
        writer.writerow([
            loc,
            (c.name or "").strip()[:8],
            f"{c.frequency_mhz:.6f}",
            "",
            "0.000000",
            "",
            "88.5",
            "88.5",
            "023",
            "NN",
            mode,
            f"{(c.step_hz or 5000) / 1000:.2f}",
            "S" if c.pass_flag else "",
            "",
            "",
            "",
            "",
            "0",
        ])
        loc += 1
    return out.getvalue()


def parse_chirp_csv(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError("empty CHIRP CSV")
    header = [h.strip().lower() for h in rows[0]]
    if "frequency" not in header:
        raise ValueError("not a CHIRP CSV - no 'Frequency' column in the header")

    def idx(name: str) -> int:
        return header.index(name) if name in header else -1

    i_loc, i_name = idx("location"), idx("name")
    i_freq, i_mode = idx("frequency"), idx("mode")
    i_step, i_skip = idx("tstep"), idx("skip")

    banks, channels = empty_bank_set()
    by_ch = {(c.bank, c.channel): c for c in channels}
    seq = 0
    for cells in rows[1:]:
        freq_raw = cells[i_freq].strip() if i_freq >= 0 and i_freq < len(cells) else ""
        if not freq_raw:
            continue
        loc = seq
        if i_loc >= 0 and i_loc < len(cells) and cells[i_loc].strip():
            try:
                loc = int(float(cells[i_loc]))
            except ValueError:
                loc = seq
        seq = loc + 1
        bank, channel = divmod(loc, _CHANNELS_PER_BANK)
        if bank >= _BANK_COUNT:
            continue
        target = by_ch.get((bank, channel))
        if target is None:
            continue
        try:
            target.frequency_hz = round(float(freq_raw) * 1_000_000)
        except ValueError:
            continue
        mode_str = cells[i_mode].strip().upper() if 0 <= i_mode < len(cells) else "FM"
        analog = _ANALOG_FROM_CHIRP_MODE.get(mode_str)
        target.mode = ("0F" + analog) if analog is not None else "0F0"
        step_raw = cells[i_step].strip() if 0 <= i_step < len(cells) else ""
        if step_raw:
            try:
                target.step_hz = round(float(step_raw) * 1000)
            except ValueError:
                target.step_hz = None
        target.pass_flag = (0 <= i_skip < len(cells) and cells[i_skip].strip().upper() == "S")
        target.name = cells[i_name].strip() if 0 <= i_name < len(cells) else ""
        target.protect = False
    return banks, channels


def parse_generic_freq_csv(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("empty CSV")
    header = [c.strip().lower() for c in rows[0]]
    mapped = [_GENERIC_FREQ_ALIASES.get(h) for h in header]
    if "freq" in mapped:
        col: dict[str, int] = {}
        for i, key in enumerate(mapped):
            if key and key not in col:
                col[key] = i
        data_rows = rows[1:]
    else:
        col = {"freq": 0, "name": 1, "mode": 2, "step": 3}
        data_rows = rows

    banks, channels = empty_bank_set()
    by_ch = {(c.bank, c.channel): c for c in channels}

    def cell(cells, key: str) -> str:
        i = col.get(key, -1)
        return cells[i].strip() if 0 <= i < len(cells) else ""

    seq = 0
    for cells in data_rows:
        freq_raw = cell(cells, "freq")
        if not freq_raw:
            continue
        try:
            val = float(freq_raw)
        except ValueError:
            continue
        hz = round(val * 1_000_000) if val < 100_000 else round(val)
        if seq >= _BANK_COUNT * _CHANNELS_PER_BANK:
            break
        bank, channel = divmod(seq, _CHANNELS_PER_BANK)
        target = by_ch[(bank, channel)]
        target.frequency_hz = hz
        name = cell(cells, "name")
        if name:
            target.name = name
        analog = _ANALOG_FROM_CHIRP_MODE.get(cell(cells, "mode").upper())
        target.mode = ("0F" + analog) if analog is not None else "0F0"
        step_raw = cell(cells, "step")
        if step_raw:
            try:
                target.step_hz = round(float(step_raw) * 1000)
            except ValueError:
                target.step_hz = None
        seq += 1

    if seq == 0:
        raise ValueError("no usable frequency rows found")
    return banks, channels
