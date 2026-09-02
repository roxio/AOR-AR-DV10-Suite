"""Parser/writer for the "AR-DV10 Connect" memory-bank/channel backup CSV
format (``DEPMICRO-BACKUP,MEM BANK,AR-DV10,...`` header, then ``MB``/``MC``
records) - the file a real user exported from their DV10 via the companion
PC app.

This is deliberately a FILE-format feature, not a live-device one: it reads
and writes the backup CSV directly, independent of whatever the live serial
``MX``/``MA`` commands turn out to want on the wire. That split matters:
composite, multi-field *device* writes (memory channels among them) are too
risky to guess at: a wrong guess there doesn't just get rejected, it writes
plausible-looking garbage into a real memory slot. A backup file has no such
risk - worst case a re-import fails validation - so it's fair game to
implement fully from real example data, which is exactly what this module
does.

Confirmed against the real 2041-line sample file (40 banks x 50 channels
= 2000 channel records, matching the operating manual's "2000 channels,
40 banks of 50" exactly):

- ``MB,<bank 00-39>,<protect 0/1>,<title, space-padded to 12 chars>``
- ``MC,<bank+channel as 4-digit "BBCC">,<protect 0/1 or blank>,``
  ``<freq "DDDD.DDDDD" MHz or blank>,<step "DDD.DD" kHz or blank>,``
  ``<offset "DDD.DD" or blank>,<mode 3-char "dan" code or blank>,``
  ``<pass flag 0/1 or blank>,<name, space-padded to 12 chars>``

An unprogrammed channel still gets an ``MC`` row (so every one of the 2000
slots is always present) with every field but the bank/channel number and
name blank. The file is UTF-8 with a BOM and CRLF line endings - this
module handles both. Channel/bank names are whatever ASCII the receiver
itself accepts (see manual 10.3 "INPUT CHARACTERS & SYMBOLS" - no
diacritics); a literal ``?`` in a name is the device's own substitution for
an unsupported character, not a decoding bug in this module.

Still open, and worth confirming once someone can compare a live ``MA``
read-back against a matching row in a fresh export of the same channel:
whether the live wire format matches this file's field layout at all, what
sign convention the offset field uses (all-zero in the sample data, so
unobserved), and what the "pass flag" column (all-zero in the sample data)
actually toggles - it lines up with the manual's per-channel "PASS" flag by
position, but that's inference, not confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .device import ANALOG_MODES, DIGITAL_MODES

_HEADER_PREFIX = "DEPMICRO-BACKUP"
_BANK_COUNT = 40
_CHANNELS_PER_BANK = 50


def _pad_name(name: str) -> str:
    name = (name or "")[:12]
    return name.ljust(12)


def _parse_bank_channel(bbcc: str) -> tuple[int, int]:
    bbcc = bbcc.strip().zfill(4)
    return int(bbcc[:2]), int(bbcc[2:])


@dataclass
class MemoryBank:
    """One ``MB`` record: a memory bank's title and erase-protect flag."""

    index: int
    protect: bool
    title: str

    def to_csv_row(self) -> str:
        return f"MB,{self.index:02d},{1 if self.protect else 0},{_pad_name(self.title)}"


@dataclass
class MemoryChannel:
    """One ``MC`` record. ``is_empty`` is True for an unprogrammed slot -
    every other field is then ``None``/``False``/``""`` and should be
    ignored rather than treated as meaningful zero values."""

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
        """"BB-CC", matching the manual's own BANK-CH field notation."""
        return f"{self.bank:02d}-{self.channel:02d}"

    @property
    def is_empty(self) -> bool:
        return self.frequency_hz is None

    @property
    def frequency_mhz(self) -> Optional[float]:
        return None if self.frequency_hz is None else self.frequency_hz / 1_000_000

    def describe_mode(self) -> str:
        """Human-readable decode of the raw 3-char mode code, reusing
        DIGITAL_MODES/ANALOG_MODES from aor_dv10.device - see that
        module's docstrings for the "dan" layout (receiving/digital-
        select/analog-select)."""
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


def parse_backup_csv(text: str) -> tuple[list[MemoryBank], list[MemoryChannel]]:
    """Parse an "AR-DV10 Connect" memory-bank backup export (as read from
    disk with any encoding - pass the decoded text) into
    (banks, channels). Raises ValueError if the header doesn't match the
    expected format, so a wrong file is caught early rather than silently
    producing an empty result."""
    text = text.lstrip("﻿")  # strip a UTF-8 BOM if present
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
    """Inverse of parse_backup_csv(): render (banks, channels) back into
    the same textual format, CRLF-terminated to match the real export
    (no BOM added - callers writing to disk can prepend "\\ufeff"
    themselves if they specifically need byte-identical AR-DV10 Connect
    compatibility). ``timestamp`` fills the header's date/time field;
    left blank if not given, since it's cosmetic and this project has no
    reason to fabricate one."""
    lines = [f"DEPMICRO-BACKUP,MEM BANK,AR-DV10,P,{timestamp}"]
    lines.extend(b.to_csv_row() for b in sorted(banks, key=lambda b: b.index))
    lines.extend(c.to_csv_row() for c in sorted(channels, key=lambda c: (c.bank, c.channel)))
    return "\r\n".join(lines) + "\r\n"


def empty_bank_set() -> tuple[list[MemoryBank], list[MemoryChannel]]:
    """A fresh, fully-populated-but-empty (banks, channels) pair matching
    the DV10's fixed layout (40 banks x 50 channels) - a starting point
    for building a new memory database from scratch rather than editing
    an existing export."""
    banks = [MemoryBank(index=i, protect=False, title="") for i in range(_BANK_COUNT)]
    channels = [
        MemoryChannel(bank=b, channel=c)
        for b in range(_BANK_COUNT)
        for c in range(_CHANNELS_PER_BANK)
    ]
    return banks, channels
