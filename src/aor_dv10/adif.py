
from __future__ import annotations

import re

from .constants import BANK_COUNT, CHANNELS_PER_BANK
from .memory import MemoryBank, MemoryChannel, empty_bank_set

_ADIF_MODE_FROM_ANALOG = {
    "0": "FM", "1": "AM", "2": "FM", "3": "FM",
    "4": "USB", "5": "LSB", "6": "CW",
}
_ANALOG_FROM_ADIF_MODE = {
    "FM": "0", "NFM": "0", "WFM": "0", "AM": "1", "USB": "4",
    "LSB": "5", "CW": "6",
}

_FIELD_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*):(\d+)(?::([A-Za-z]))?>", re.ASCII)


def _adif_mode(mode: str | None) -> str:
    code = mode if (mode and len(mode) == 3) else "0F0"
    if code[1] != "F":
        return "DATA"
    return _ADIF_MODE_FROM_ANALOG.get(code[2], "FM")


def _field(tag: str, value: str) -> str:
    return f"<{tag}:{len(value)}>{value}"


def write_adif(channels: list[MemoryChannel]) -> str:
    out = [
        "AR-DV10 memory export",
        _field("ADIF_VER", "3.1.4"),
        _field("PROGRAMID", "aor_dv10"),
        _field("PROGRAMVERSION", "0.1.0"),
        "<EOH>",
    ]
    for c in sorted(channels, key=lambda c: (c.bank, c.channel)):
        if c.is_empty:
            continue
        fields = [
            _field("FREQ", f"{c.frequency_mhz:.6f}"),
            _field("MODE", _adif_mode(c.mode)),
        ]
        if c.name:
            fields.append(_field("NAME", c.name.strip()))
        if c.pass_flag:
            fields.append(_field("COMMENT", "pass"))
        fields.append("<EOR>")
        out.append(" ".join(fields))
    return "\n".join(out) + "\n"


def _parse_record(record: str) -> dict:
    fields: dict = {}
    for m in _FIELD_RE.finditer(record):
        tag = m.group(1).upper()
        length = int(m.group(2))
        value = record[m.end(): m.end() + length]
        fields[tag] = value
    return fields


def parse_adif(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    upper = text.upper()
    eoh = upper.find("<EOH>")
    body = text[eoh + 5:] if eoh != -1 else text
    records = re.split(r"<EOR>", body, flags=re.IGNORECASE)

    banks, channels = empty_bank_set()
    by_ch = {(c.bank, c.channel): c for c in channels}
    seq = 0
    for record in records:
        fields = _parse_record(record)
        freq_raw = (fields.get("FREQ") or "").strip()
        if not freq_raw:
            continue
        try:
            val = float(freq_raw)
        except ValueError:
            continue
        hz = round(val) if val >= 100_000 else round(val * 1_000_000)
        if seq >= BANK_COUNT * CHANNELS_PER_BANK:
            break
        bank, channel = divmod(seq, CHANNELS_PER_BANK)
        target = by_ch[(bank, channel)]
        target.frequency_hz = hz
        name = (fields.get("NAME") or "").strip()
        if name:
            target.name = name
        analog = _ANALOG_FROM_ADIF_MODE.get((fields.get("MODE") or "").strip().upper())
        target.mode = ("0F" + analog) if analog is not None else "0F0"
        seq += 1

    if seq == 0:
        raise ValueError("no usable <FREQ> records found in the ADIF text")
    return banks, channels
