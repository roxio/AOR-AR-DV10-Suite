"""High-level, typed API to an AR-DV10, sitting on top of the protocol layer.

This is what the CLI, GUI, and web panel are all meant to import instead of
touching :mod:`aor_dv10.protocol` or :mod:`aor_dv10.transport` directly - one
place to fix up value encoding once it's confirmed against real hardware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from .protocol.codec import (
    CommandChannel,
    DV10Error,
    DV10ProtocolError,
    DV10ResyncNeeded,
    Response,
    describe_result_code,
)
from .timer import RecordingTimer, format_timer_value, parse_timer_response
from .transport.base import Transport
from .transport.serial_transport import SerialTransport, find_dv10_port
from .transport.simulator import SimulatorTransport


# -- MD (mode) decode tables --------------------------------------------------
#
# Confirmed via the AR-DV3 command spec, a newer sibling device sharing
# near-identical mnemonics with the DV10/DV1; presumed to apply to the DV10
# by family resemblance, and consistent with "0F0" observed on real DV10
# hardware (plain FM, digital off).
#
# MD's READ value is 3 chars "dan": d = currently-receiving digital mode
# (read-only info), a = selected digital mode, n = selected analog mode -
# e.g. "0F0" = receiving Auto, digital off, analog FM.
#
# MD's WRITE value is confirmed against real hardware to be the SAME 3-char
# "dan" shape, not a shorter reversed form. A 2-char write in either order
# is silently accepted (no error) but does NOT change the analog/digital
# selection - which is what made an earlier round of testing look like a
# working fix. Live repro: "raw MD 1F1" (3 chars) read back as "0F1"
# (analog now AM) and visibly changed the receiver, while the equivalent
# 2-char writes this project had been sending never did. set_mode() keeps
# the user-facing 2-char "<digital><analog>" convention for callers and
# pads it into the 3-char wire shape internally; do not "fix" this back to
# a bare 2-character write. The read-only leading "d" position accepted an
# arbitrary DIGITAL_MODES-valid digit in testing; "0" (Auto) is sent as a
# safe placeholder, but its exact accepted range hasn't been tested.
DIGITAL_MODES = {
    "0": "Auto",
    "1": "D-STAR",
    "2": "YAESU",
    "3": "ALINCO",
    "4": "D-CR",
    "5": "P25",
    "6": "dPMR",
    "7": "DMR",
    "8": "TETRA T-DM",
    "9": "TETRA T-TC",
    "F": "Digital off",
}

ANALOG_MODES = {
    "0": "FM",
    "1": "AM",
    "2": "SAH",
    "3": "SAL",
    "4": "USB",
    "5": "LSB",
    "6": "CW",
}

# -- per-model analog-mode gating -------------------------------------------
#
# Per user report against real DV10 hardware: SAH ("2") and SAL ("3") - the
# two narrow/synchronous-AM variants sharing one IF_BANDWIDTH_HZ row - are
# NOT functionally distinct on the AR-DV10. The receiver accepts and echoes
# either code without error, so this is UI-level guidance, not a
# protocol-level restriction (set_mode()/_mode_write_value() deliberately
# still accept both), but selecting one over the other makes no
# audible/measurable difference on that model. The AR-DV3 spec documents
# them as two separate codes, so this is presumed - not confirmed either
# way - NOT to apply to other AR-DV1-family receivers; hence gating by
# detected device family rather than disabling it for every model.
ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY = {
    "DV10": {"2", "3"},  # SAH, SAL
}


def _validate_mode_pair(mode: str) -> str:
    """Validate a "<digital><analog>" 2-char mode code and return it
    UNCHANGED (natural order, still 2 characters). Must NOT be assumed to
    need the 3-character "dan" wire shape _mode_write_value() (used by
    standalone set_mode()) was confirmed to need - see
    write_memory_channel()."""
    mode = mode.strip().upper()
    if len(mode) != 2:
        raise ValueError(
            f'mode must be exactly 2 characters, "<digital><analog>" '
            f'(e.g. "F0" for FM/digital-off) - got {mode!r}'
        )
    digital, analog = mode[0], mode[1]
    if digital not in DIGITAL_MODES:
        raise ValueError(
            f"unknown digital mode code {digital!r} - expected one of "
            f"{', '.join(sorted(DIGITAL_MODES))}"
        )
    if analog not in ANALOG_MODES:
        raise ValueError(
            f"unknown analog mode code {analog!r} - expected one of "
            f"{', '.join(sorted(ANALOG_MODES))}"
        )
    return mode


def _mode_write_value(mode: str) -> str:
    """Validate a "<digital><analog>" 2-char mode code and return the
    3-character value standalone MD actually wants on the wire: the same
    "dan" shape MD reads back, with "0" (Auto) as a safe placeholder for the
    read-only leading "d" position - see the DIGITAL_MODES comment block for
    the real-hardware finding behind this. Used by set_mode() only;
    write_memory_channel()'s own embedded MD sub-field uses the separate,
    still-unconfirmed _validate_mode_pair()."""
    mode = mode.strip().upper()
    if len(mode) != 2:
        raise ValueError(
            f'mode must be exactly 2 characters, "<digital><analog>" '
            f'(e.g. "F0" for FM/digital-off) - got {mode!r}'
        )
    digital, analog = mode[0], mode[1]
    if digital not in DIGITAL_MODES:
        raise ValueError(
            f"unknown digital mode code {digital!r} - expected one of "
            f"{', '.join(sorted(DIGITAL_MODES))}"
        )
    if analog not in ANALOG_MODES:
        raise ValueError(
            f"unknown analog mode code {analog!r} - expected one of "
            f"{', '.join(sorted(ANALOG_MODES))}"
        )
    return f"0{digital}{analog}"


# -- AT (attenuator) decode table ---------------------------------------------
#
# The AR-DV3 spec documents AT as a 3-state selector (0=AMP ON, 1=AMP OFF &
# ATT OFF, 2=10dB ATT), but a real DV10 doesn't behave that way: per user
# report the value that switches the ~10dB SIGNAL ATTENUATOR ON is 1, and 0
# ("AMP ON" per the DV3 spec) is just the no-attenuation baseline. The
# labels below reflect the effect on the *actual receiver* (the web panel
# and CLI "attst" share these); the wire values are unchanged - a
# label/correctness fix, not a remapping of what is sent (see
# set_attenuator()/set_attenuator_state()). State 2 (10dB ATT) is a DV3-only
# extra; DV10/DV1 only reach 0 and 1 (the web panel greys 2 out unless a
# DV3 is detected).
ATTENUATOR_STATES = {
    "0": "ATT OFF",
    "1": "ATT ON",
    "2": "10dB ATT",
}

# -- AC (AGC speed) decode table -----------------------------------------------
#
# Confirmed via the AR-DV3 spec: a 4-state speed selector, not on/off. The
# DV3 spec also says it's only valid in AM mode (other modes -> result code
# 30), but a real DV10 test succeeded while apparently in FM - unconfirmed
# either way.
AGC_SPEEDS = {
    "0": "Fast",
    "1": "Mid",
    "2": "Slow",
    "3": "RF-G",
}

# -- KL (key backlight color) decode table --------------------------------
#
# n=3's spec-literal label is "MAGENDA", not "MAGENTA" - confirmed a genuine
# spec typo (not a pdftotext artifact) via both the rendered PDF image and
# pdftotext's raw text layer, the same cross-check used for the "SYSYEM"
# backup-kind typo below - kept literal here rather
# than corrected, same rationale as SD_BACKUP_KIND_ALL.
KEY_BACKLIGHT_COLORS = {
    "0": "OFF",
    "1": "BLUE",
    "2": "RED",
    "3": "MAGENDA",  # sic
    "4": "GREEN",
    "5": "CYAN",
    "6": "YELLOW",
    "7": "ORANGE",
}

# -- IF (IF bandwidth) decode table ----------------------------------------
#
# Keyed by the spec's own named demodulation types (FM/AM/SAH/SAL/USB/LSB/
# CW) rather than 2-char MD-style mode codes: the spec's IF section
# documents no mapping between the two, and SAH/SAL share one row of values
# as do USB/LSB, so there is no clean 1:1 mapping to build. Values in Hz.
#
# FM's row was originally 5 entries (0-4) with digit "0" = 200 kHz, straight
# from the AR-DV10 operating manual's own table, never independently checked
# against real hardware. Per user report against real hardware (2026-09-01):
# FM only runs 6-100 kHz, no 200 kHz choice - "0"/200_000 removed below. Not
# confirmed which explanation is true (the device simply has one fewer
# choice and raw digits 1-4 keep their meaning - assumed here - vs. the
# whole raw-digit numbering shifting); the other rows are still only
# manual-derived and unconfirmed either way.
#
# Only applies while NO digital mode is selected (MD's digital_select is
# "Digital off"/"F"). Per user report against real hardware, IF is NOT
# user-settable at all while a digital mode is active: "bw 100000" and
# "bw 6000" both got result code 30 (PC_RESULT_CAN_NOT_SET_ERR, "cannot set
# given current conditions") even though 6000 is one of this table's own FM
# values. Per the AR-DV10 operating manual the receiver auto-selects the
# digital filter width from a fixed set (6/15/30 kHz) depending on what it
# is decoding, rather
# than taking a manual IF write - see get_if_bandwidth_options_hz().
IF_BANDWIDTH_HZ = {
    "FM": {"1": 100_000, "2": 30_000, "3": 15_000, "4": 6_000},
    "AM": {"0": 15_000, "1": 8_000, "2": 5_500, "3": 3_800},
    "SAH": {"0": 5_500, "1": 3_800},
    "SAL": {"0": 5_500, "1": 3_800},
    "USB": {"0": 2_600, "1": 1_800},
    "LSB": {"0": 2_600, "1": 1_800},
    "CW": {"0": 500, "1": 200},
}

# -- SQ (squelch mode) decode table --------------------------------------------
#
# Confirmed via the AR-DV3 spec: SQ selects the squelch *mode*, not a level,
# despite the command summary's "squelch level" description. The actual
# threshold is LQ (level squelch, 00-99) when SQ=2, or NQ (noise squelch,
# 00-39) when SQ=1.
SQUELCH_MODES = {
    "0": "Auto",
    "1": "Noise",
    "2": "Level",
}

# -- CI (tone squelch type) decode table -------------------------------------
#
# The manual's SQL TYPE menu (10.5) offers OFF/CTCSS/DCS/Reverse Tone as one
# 4-way choice, but the command summary lists CI ("Tone squelch ON/OFF") and
# DI ("DCS ON/OFF") as two separate commands. Confirmed against real DV10
# hardware that CI is NOT a boolean: with the front panel's SQL TYPE showing
# "REV.T" (Reverse Tone) CI read "2" (DI "0"); showing "DCS", CI read "0"
# (DI "1"). So CI is (at least) a 3-value selector, and DCS is DI's own
# independent boolean rather than one of CI's values.
#
# "1"=CTCSS is inferred by elimination (SQL TYPE's remaining choice) - it
# was not independently read back, so treat it as a strong guess rather
# than a confirmed value until someone checks.
TONE_SQUELCH_TYPES = {
    "0": "OFF",
    "1": "CTCSS",  # inferred by elimination - not independently confirmed
    "2": "Reverse Tone",
}

# -- LM (S-meter) squelch-state decode table -----------------------------------
SQUELCH_STATES = {
    0: "closed",
    1: "open (noise/level squelch)",
    2: "open (tone/DCS/reverse squelch)",
    3: "detecting digital mode",
}
"""Per the AR-DV1 wire-protocol spec's own LM entry (LMkkkc: "c: Squelch
status - 0: Squelch closes, 1: Noise squelch or level squelch opens,
2: Tone, DCS or reverse squelch opens, 3: Detecting digital mode"). The
previous mapping here was an unconfirmed manual-sourced guess that got
states 1-3 wrong in both which squelch types they group and what state 3
variant)."""


# -- manual-sourced tables ---------------------------------------------------
#
# Everything in this block is sourced from the official AR-DV10 *operating*
# manual's front-panel menu descriptions, not a CI serial-protocol manual
# (AOR publishes none beyond the bare mnemonic list in
# aor_dv10.protocol.commands.COMMANDS). That gives confident VALUE RANGES
# and MEANINGS but only inferred WIRE ENCODINGS - each method says which is
# which. Treat anything marked "unconfirmed" as a documented best guess,
# correctable by one real-hardware "raw CODE VALUE" test.

BACKLIGHT_MODES = {"0": "Off (default)", "1": "Continuous", "2": "Auto"}
"""LB (LCD backlight) choices per the manual (11.2 item 4): OFF/CONT/AUTO.
Digit encoding is an unconfirmed guess - the front panel shows text."""

CTCSS_TONES_HZ = [
    "60.0", "67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5",
    "91.5", "94.8", "97.4", "100.0", "103.5", "107.2", "110.9", "114.8", "118.8",
    "120.0", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2", "151.4", "156.7",
    "159.8", "162.2", "165.5", "167.9", "171.3", "173.8", "177.3", "179.9", "183.5",
    "186.2", "189.9", "192.8", "196.6", "199.5", "203.5", "206.5", "210.7", "218.1",
    "225.7", "229.1", "233.6", "241.8", "250.3", "254.1",
]
"""The CTCSS tone table as printed in the operating manual (10.5.1) - the
*values* are confirmed (that's what the receiver's menu shows). Confirmed
against the AR-DV1 wire spec that CN's own wire value is NOT this literal
decimal string but a 1-based index into this exact table (CN01 <-> [0] ...
CN52 <-> [51]) - see set_tone_squelch_freq()/_decode_cn()."""


def _decode_cn(raw: str) -> str:
    """Raw CN value -> the human-readable tone string used by
    get_tone_squelch_freq()/the CLI/the web GUI. Handles the plain "nn"
    shape as well as the "99nn" shape the spec says CN reads back while a
    search is active (99 = still searching, then the last-detected index,
    00 if none yet)."""
    raw = raw.strip()
    if len(raw) == 4 and raw.startswith("99"):
        raw = raw[2:]  # mid-search read: report the detected tone so far (00 if none yet)
    if raw in ("", "00"):
        return ""
    if raw == "99":
        return "SRCH"
    try:
        index = int(raw)
    except ValueError:
        return raw  # unrecognised shape - hand back the raw text rather than hide it
    if 1 <= index <= len(CTCSS_TONES_HZ):
        return CTCSS_TONES_HZ[index - 1]
    return raw

DCS_CODES = [
    "017", "023", "025", "026", "031", "032", "036", "043", "047", "050", "051",
    "053", "054", "065", "071", "072", "073", "074", "114", "115", "116", "122",
    "125", "131", "132", "134", "143", "145", "152", "155", "156", "162", "165",
    "172", "174", "205", "212", "223", "225", "226", "243", "244", "245", "246",
    "251", "252", "255", "261", "263", "265", "266", "271", "274", "306", "311",
    "315", "325", "331", "332", "343", "346", "351", "356", "364", "365", "371",
    "411", "412", "413", "423", "431", "432", "445", "446", "452", "454", "455",
    "462", "464", "465", "466", "503", "506", "516", "523", "526", "532", "546",
    "565", "606", "612", "624", "627", "631", "632", "654", "662", "664", "703",
    "712", "723", "731", "732", "734", "743", "754",
]
"""The DCS code table as printed in the operating manual (10.5.2) - same
confidence caveat as CTCSS_TONES_HZ above."""


@dataclass
class ModeInfo:
    """Decoded MD value. ``receiving_digital`` is read-only info (what the
    receiver is currently decoding); ``digital_select``/``analog_select`` are
    what a write would request. Any field can be ``None`` if the raw value
    was shorter than expected or the code wasn't recognised."""

    raw: str
    receiving_digital: Optional[str]
    digital_select: Optional[str]
    analog_select: Optional[str]

    def describe(self) -> str:
        parts = []
        if self.receiving_digital is not None:
            parts.append(f"receiving={self.receiving_digital}")
        if self.digital_select is not None:
            parts.append(f"digital={self.digital_select}")
        if self.analog_select is not None:
            parts.append(f"analog={self.analog_select}")
        return ", ".join(parts) if parts else f"(unrecognised MD value {self.raw!r})"


def _parse_composite_fields(text: str, *, tag_field: str | None = None) -> dict:
    """Split a space-separated "<2-letter code><value> ..." composite
    response - the shape now confirmed for MX/MA (live memory channels), OL
    (offset frequency) and several other AR-DV1 commands not yet implemented
    (VF/VI, TR, SE, MW, MG...) - into a ``{code: value}`` dict. Tokens that
    don't look like "2 letters + something" are ignored rather than raising,
    since a couple of these commands mix in bare flags/placeholders (e.g.
    MA's "- - -" for an unregistered channel) - see
    DV10Device.read_memory_channel() for where those are handled instead.

    ``tag_field``: a 2-letter code, e.g. "TT", to treat as "the rest of the
    line" rather than one whitespace-delimited token. Every composite
    response implemented here documents its tag/name sub-field LAST, so this
    is safe in practice even though AOR's spec has no escaping convention
    for a value containing a space. Without it a tag like "2M BAND" silently
    truncates to "2M" - confirmed via a live SE/SR round-trip smoke test;
    the same truncation affects MX/MW's tag handling. Parsing stops once the
    tag field is found."""
    fields: dict = {}
    for match in re.finditer(r"\S+", text):
        token = match.group()
        if len(token) > 2 and token[:2].isalpha():
            code = token[:2].upper()
            if tag_field and code == tag_field.upper():
                fields[code] = text[match.start() + 2 :].strip()
                break
            fields[code] = token[2:]
    return fields


@dataclass
class MemoryChannelInfo:
    """Decoded MX/MA live memory-channel record - see
    DV10Device.read_memory_channel()/write_memory_channel().

    Confirmed against the AR-DV1 wire spec to be a DIFFERENT field set from
    aor_dv10.memory.MemoryChannel (the AR-DV10 Connect *backup CSV* format):
    this one has a step_adjust_hz field the CSV format doesn't, and no
    offset field (which the CSV format has) - don't assume the two are
    interchangeable. ``registered`` is False for an unprogrammed slot (the
    spec's own "MAbbcc - - -" shape); every other field is then
    None/False/"" and should be ignored."""

    bank: int
    channel: int
    registered: bool
    pass_channel: bool = False
    frequency_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None  # natural "<digital><analog>" 2-char code (NOT reversed), see write_memory_channel()
    write_protect: bool = False
    tag: str = ""


@dataclass
class MemoryBankInfo:
    """Decoded MW live memory-bank record - see
    DV10Device.get_memory_bank_info()/write_memory_bank(). Distinct from
    aor_dv10.memory.MemoryBank (the backup CSV format's bank record, which
    only has index/protect/title - no channel_count)."""

    bank: int
    channel_count: Optional[int] = None
    protect: bool = False
    tag: str = ""


def _format_search_freq_mhz(hz: int) -> str:
    """"ffff.ffff" (4 integer + 4 decimal digits, decimal MHz => 100Hz) -
    the coarser resolution the AR-DV1 spec uses for search-bank limits (SE's
    SL/SU sub-fields and the standalone SL/SU) and for pass frequencies
    (PW/PR). Confirmed distinct from RF/OL's "ffff.fffff" (10Hz) by
    cross-checking the composite SE row and the standalone SL/SU entries,
    which show the same narrower width independently - not a documentation
    typo. See write_search_bank()."""
    return f"{hz / 1_000_000:09.4f}"


def _format_rf_freq_mhz(hz: int) -> str:
    """"ffff.fffff" (4 integer + 5 decimal digits, decimal MHz => 10Hz) -
    the SAME width standalone RF/OL use, confirmed (not inferred) from the
    AR-DV1 spec's own VF/VI table rows, and genuinely wider than the
    search-bank family's "ffff.ffff" (see _format_search_freq_mhz()). Kept
    as one helper so VF/VI's embedded RF field and the standalone RF command
    can't drift apart."""
    return f"{hz / 1_000_000:010.5f}"


def _format_bank_link(banks: Optional[List[int]]) -> str:
    """Render a bank-link list as the AR-DV1 spec's own "bbb..." token for
    BK (and the BK sub-field embedded in SG/MG): each bank as 2 digits, no
    separator. ``None`` or an empty list writes "99", the spec's own
    shorthand for "all bank links disabled"."""
    if not banks:
        return "99"
    return "".join(f"{int(b):02d}" for b in banks)


def _parse_bank_link(raw: str) -> List[int]:
    """Inverse of _format_bank_link(): "99" (or anything that isn't a
    clean run of 2-digit groups) decodes to an empty list (no banks
    linked); otherwise a list of bank numbers in the order they appeared
    on the wire."""
    raw = raw.strip()
    if not raw or raw == "99":
        return []
    if len(raw) % 2 != 0 or not raw.isdigit():
        return []
    return [int(raw[i : i + 2]) for i in range(0, len(raw), 2)]


@dataclass
class SearchBankInfo:
    """Decoded SE (write)/SR (read) search-bank record: a program-search
    scan range with its own step, step-adjust, mode, write-protect and name
    tag - distinct from a live memory bank (MemoryBankInfo above) even
    though several sub-field letters (ST/SH/MD/PT/TT) are shared.
    ``registered`` is False for a bank that has never been written; every
    other field is then meaningless. See
    DV10Device.write_search_bank()/read_search_bank()."""

    bank: int
    registered: bool
    lower_limit_hz: Optional[int] = None
    upper_limit_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None  # natural "<digital><analog>" 2-char code, see write_search_bank()
    write_protect: bool = False
    tag: str = ""


@dataclass
class ScanGroupInfo:
    """Decoded SG (search-side)/MG (memory-side) scan-group record.
    ``auto_store`` is only meaningful for a search-side (SG) group - the
    AR-DV1 spec's own MG entry has no AS sub-field at all, so this is
    always None for a memory-side (MG) group, see
    DV10Device.write_memory_scan_group(). ``bank_link`` is a tuple of
    linked bank numbers (empty tuple = none linked / "99")."""

    group: int
    delay_ds: Optional[int] = None  # tenths of a second, spec range 01-99
    free_time_s: Optional[int] = None  # seconds, spec range 00-60
    auto_store: Optional[bool] = None
    bank_link: tuple = ()


@dataclass
class PassFrequencyEntry:
    """One slot (00-49) of a PW/PR/PD pass-frequency list - either for VFO
    search (``bank is None``) or for a specific program-search bank
    (``bank=<n>``). ``frequency_hz`` is None for an empty slot (the AR-DV1
    spec's own "PRnn - - -" placeholder, the same convention as MA's
    "- - -" for an unregistered memory channel). See
    DV10Device.list_pass_frequencies()."""

    index: int
    frequency_hz: Optional[int]
    bank: Optional[int] = None


@dataclass
class VfoInfo:
    """One VFO's (A/B/Z) current receive settings, as read back by VI or
    written atomically by VF - see DV10Device.read_vfo_info()/
    enter_vfo_mode(). ``step_hz``/``step_adjust_hz`` use VF/VI's own "ST"/
    "SH" sub-fields, the same kHz-decimal wire format as the embedded ST/SH
    in MX/SE - NOT the standalone, separately-unconfirmed ST/SH commands."""

    vfo: str  # "A", "B", or "Z"
    frequency_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None  # natural "<digital><analog>" 2-char code


@dataclass
class VfoSearchSettings:
    """VE: the single, receiver-wide (not per-VFO, despite the name)
    VFO-search delay/free-time/auto-store configuration used when VS starts
    a VFO search - see DV10Device.read_vfo_search_settings()/
    write_vfo_search_settings(). Same field shape as ScanGroupInfo's
    search-side (SG) fields, but VE has no group number."""

    delay_ds: Optional[int] = None  # tenths of a second, spec range 01-99, default 20
    free_time_s: Optional[int] = None  # seconds, spec range 00-60, default 00
    auto_store: Optional[bool] = None  # default OFF


@dataclass
class SMeterReading:
    """Decoded LM value: ``LM`` + ``vvvq`` where ``vvv`` is a signal level of
    ``-vvv`` dB and ``q`` is a squelch state digit (0=closed, 1=noise/level
    squelch open, 2=tone/DCS/reverse squelch open, 3=detecting digital
    mode - confirmed against the AR-DV1 wire spec, see
    SQUELCH_STATES). ``dbm`` and ``squelch_state`` are ``None`` if the raw
    value couldn't be parsed."""

    raw: str
    dbm: Optional[int]
    squelch_state: Optional[int]

    @property
    def squelch_open(self) -> Optional[bool]:
        if self.squelch_state is None:
            return None
        return self.squelch_state != 0

    def describe(self) -> str:
        if self.dbm is None:
            return f"(unrecognised LM value {self.raw!r})"
        state = SQUELCH_STATES.get(self.squelch_state, f"state {self.squelch_state}")
        return f"{self.dbm} dB, squelch {state}"


@dataclass
class Status:
    frequency_hz: Optional[int]
    mode: Optional[str]
    squelch: Optional[str]
    volume: Optional[str]
    smeter: Optional[str]
    agc_on: Optional[bool]
    # Richer fields alongside the legacy ones above, populated best-effort;
    # None if the underlying read failed or didn't parse.
    mode_info: Optional[ModeInfo] = None
    smeter_reading: Optional[SMeterReading] = None
    agc_speed: Optional[str] = None
    attenuator_state: Optional[str] = None


# Commands confirmed (RF, AC, SQ, AT) or presumed (RG, ST, SH - same
# "tuning/level parameter" family, not individually retested) to reject
# writes with "?" unless the receiver is in VFO mode rather than browsing a
# memory channel.
# Deliberately excludes AG (its bare-read failure was a separate, resolved
# thing: RE 1 gave result code 60, "command does not exist" - this firmware
# has no bare AG read), MD (its VFO-mode requirement was never independently
# confirmed - an open question, not a presumption) and VF (confirmed to be
# the way *into* VFO mode: "raw VF A" succeeded, see enter_vfo_mode(), so
# gating it on already being in VFO mode would be backwards).
_VFO_MODE_WRITE_CODES = {"RF", "AC", "SQ", "AT", "RG", "ST", "SH"}

_VFO_MODE_HINT = (
    "the receiver needs to be in VFO mode (not browsing a memory channel) "
    "for this to work - confirmed against real hardware"
)


@dataclass
class SdCardFile:
    """One entry from SD DIR's per-file directory listing. The AR-DV1 spec
    documents two per-file line shapes by extension - WAV files get a
    recorded duration, everything else a byte size - so both fields stay
    Optional rather than picking one; see DV10Device.sd_dir()."""

    name: str
    extension: str
    timestamp: Optional[str] = None  # spec's own "yyyy/mm/dd HH:MM:SS" format, kept raw
    duration: Optional[str] = None  # spec's own "hh:nn:ss.s" format, WAV files only
    size_bytes: Optional[int] = None  # non-WAV files only


@dataclass
class SdCardInfo:
    """SD INF: SD card capacity summary."""

    free_kb: int
    free_hours: Optional[float]
    total_kb: int


# SD PST's single status digit -> meaning, same "raw value + lookup table"
# style as ATTENUATOR_STATES above - see DV10Device.sd_status().
SD_CARD_STATUS = {
    "0": "card present, no access",
    "1": "recording",
    "2": "playing back",
    "3": "processing (not recording or playing back)",
    "4": "SD card not found, can't be used, or another error",
}

# SD MMW's five documented backup-kind tokens. SD_BACKUP_KIND_ALL's wire
# token is spelled "SYSYEM", not "SYSTEM" - confirmed a real spec typo (not
# an OCR/extraction artifact) by cross-checking the rendered PDF page image
# and pdftotext's raw text layer independently. Implemented literally, on
# the (unconfirmed) theory that firmware matches its own manual's token.
SD_BACKUP_KIND_SEARCH_BANK = "SRCHBK"
SD_BACKUP_KIND_SEARCH_GROUP = "SRCHGRP"
SD_BACKUP_KIND_MEMORY_CHANNEL = "MEMCH"
SD_BACKUP_KIND_SCAN_GROUP = "SCANGRP"
SD_BACKUP_KIND_ALL = "SYSYEM"  # sic - see the note above
_SD_BACKUP_KINDS = {
    SD_BACKUP_KIND_SEARCH_BANK,
    SD_BACKUP_KIND_SEARCH_GROUP,
    SD_BACKUP_KIND_MEMORY_CHANNEL,
    SD_BACKUP_KIND_SCAN_GROUP,
    SD_BACKUP_KIND_ALL,
}

# Every SD-card error token the AR-DV1 spec documents, across SD
# DIR/INF/PST/REC/PLY/MMW/MMR (task 13, item 32: "proper error handling
# ... rather than a generic ?/DV10Error"), and a short human hint for each.
_SD_ERROR_HINTS = {
    "CARDBUSY": "SD card busy",
    "NOCARD": "SD card not found",
    "FAT12": "SD card is formatted FAT12 and can't be used by this receiver",
    "NOFILE": "the specified file does not exist on the SD card",
    "CARDFULL": "SD card has no free space left",
}


def _check_sd_error(text: str) -> None:
    """Raises DV10ProtocolError if ``text`` (an SD command's response value,
    code echo already stripped) is one of the AR-DV1 spec's documented
    SD-card error tokens. These arrive as plain text *inside* an
    otherwise-normal response body, not as a "<code>?" rejection, so they
    have to be checked explicitly rather than falling out of
    CommandChannel.send()'s own error handling. ``err.code`` carries the
    token itself (e.g. "CARDBUSY"), not a numeric string."""
    token = (text or "").strip().upper()
    hint = _SD_ERROR_HINTS.get(token)
    if hint is not None:
        raise DV10ProtocolError(token, text, hint=hint)


def _sd_value(resp: Response, prefix: str) -> str:
    """Strips an echoed ``prefix`` (e.g. "SD REC") from an SD command's
    response value. CommandChannel.send() strips it once for the FIRST line
    of a response, but read_pending() continuation lines (sd_dir()'s
    multi-line read) don't get that, so it is applied defensively every
    time; then raises via _check_sd_error() if what's left is a documented
    SD error token, otherwise returns the cleaned text."""
    text = (resp.value or "").strip()
    if text.upper().startswith(prefix.upper()):
        text = text[len(prefix):].strip()
    _check_sd_error(text)
    return text


@dataclass
class ScopeLine:
    """One decoded line of "GL" (frequency-scope, normal-speed) data.

    frequency_hz: centre frequency of this scan point, in Hz (from the
        spec's "fffff.fffff" MHz field).
    level_raw: the raw 2-digit "kk" level token as printed on the wire.
        NOTE: the AR-DV1 spec's own GL syntax ("Fffff.fffffLkkc") gives a
        2-digit level field, narrower than the 3-digit convention LM's
        S-meter reading and FD's own level chunks use. Implemented exactly
        as written, but UNCONFIRMED against real hardware and flagged here
        as a discrepancy worth a hardware check.
    squelch_state: the trailing single-digit "c" token (0/1; its precise
        meaning is not fully pinned down from the spec text alone).
    """

    frequency_hz: int
    level_raw: str
    squelch_state: int

    @property
    def squelch_open(self) -> bool:
        return self.squelch_state != 0


_GL_LINE_RE = re.compile(r"^F(\d{4,5}\.\d{5})L(\d{2})(\d)$")


class DV10Device:
    """High-level control surface for one AR-DV10 receiver."""

    def __init__(self, transport: Transport, timeout: float = 1.5):
        self._transport = transport
        self._chan = CommandChannel(transport, timeout=timeout)
        self._connected = False
        # Local best-effort tracking for set_mode()'s IF-bandwidth-restore
        # workaround - see set_mode()'s docstring.
        self._digital_active = False
        self._pre_digital_if_bandwidth: Optional[str] = None
        # Lazily populated by model() on first call, cleared on disconnect().
        # WI can't change mid-connection, and model()/device_family() is now
        # polled on every /api/status refresh (1.5s - see the web panel's
        # device_family-based SAH/SAL gating), so an uncached read would cost
        # a wire round-trip per poll.
        self._model_cache: Optional[str] = None
        # Same reasoning as _model_cache, for firmware_version()/VR - the web
        # nameplate polls it every /api/status refresh too.
        self._firmware_cache: Optional[str] = None

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def open_serial(cls, port: Optional[str] = None, baudrate: int = 115200) -> "DV10Device":
        """Convenience constructor: auto-detect (or use given) USB port."""
        return cls(SerialTransport(port=port, baudrate=baudrate))

    @classmethod
    def open_simulator(cls) -> "DV10Device":
        """Convenience constructor for the in-memory fake device."""
        return cls(SimulatorTransport())

    def connect(self) -> None:
        self._transport.open()
        self._connected = True

    def disconnect(self) -> None:
        if self._connected:
            try:
                # EX = "End remote control" - politely hand control back to
                # the front panel before closing, per the command summary.
                self._chan.send("EX")
            except DV10Error:
                pass  # best-effort; still close the port
        self._transport.close()
        self._connected = False
        self._model_cache = None
        self._firmware_cache = None

    @property
    def connected(self) -> bool:
        return self._connected

    def _write_with_hint(self, code: str, value: str):
        """Like ``self._chan.write()``, but adds the VFO-mode hint to a
        ``?`` error for commands known/presumed to need it - see
        _VFO_MODE_WRITE_CODES above."""
        try:
            return self._chan.write(code, value)
        except DV10ProtocolError as exc:
            if exc.code == "?" and exc.hint is None and code.upper() in _VFO_MODE_WRITE_CODES:
                raise DV10ProtocolError(exc.code, exc.raw_response, hint=_VFO_MODE_HINT) from exc
            raise

    def __enter__(self) -> "DV10Device":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.disconnect()

    # -- identification ----------------------------------------------------

    def firmware_version(self) -> str:
        """Raw VR response. Cached for the life of the connection, same
        as model() - see ``_firmware_cache``."""
        if self._firmware_cache is None:
            self._firmware_cache = self._chan.read("VR").value or ""
        return self._firmware_cache

    def model(self) -> str:
        """Raw WI response, e.g. "AOR AR-DV10" (message-only, no code
        echo - confirmed against real DV10 hardware, see WI's entry in
        aor_dv10.protocol.commands). Cached for the life of the
        connection - see ``_model_cache``."""
        if self._model_cache is None:
            self._model_cache = self._chan.read("WI").value or ""
        return self._model_cache

    def device_family(self) -> str:
        """Best-effort normalized model family - ``"DV10"``, ``"DV1"``,
        ``"DV3"``, or ``""`` if WI's raw response wasn't recognised - for
        UI-level feature gating only (see
        ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY and the web panel's
        DV3-only 10dB attenuator gating); nothing here branches on it at the
        wire level. Checks DV10 before DV1 deliberately: "DV1" is itself a
        substring of "DV10", so the other order would misidentify every real
        DV10 (which echoes "AOR AR-DV10")."""
        raw = self.model().upper()
        if "DV10" in raw:
            return "DV10"
        if "DV3" in raw:
            return "DV3"
        if "DV1" in raw:
            return "DV1"
        return ""

    def analog_modes_without_distinction(self) -> set:
        """ANALOG_MODES codes accepted but not functionally distinct from
        each other on the CURRENTLY CONNECTED device's family - see
        ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY. Empty for an unknown
        family or one with no such gating, so a caller that never checks
        this just sees every documented analog mode offered."""
        return set(ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY.get(self.device_family(), ()))

    def serial_number(self) -> str:
        return self._chan.read("SN").value or ""

    # -- frequency / mode --------------------------------------------------

    def get_frequency_hz(self) -> int:
        # Format confirmed on real AR-DV10 hardware: CODE + 4 zero-padded
        # integer digits + "." + 5 decimal digits, e.g. "RF0145.50000" -
        # decimal MHz, ~10 Hz resolution.
        raw = self._chan.read("RF").value or "0"
        return round(float(raw) * 1_000_000)

    def set_frequency_hz(self, hz: int) -> None:
        # Confirmed against real hardware: this raises DV10ProtocolError("?",
        # ...) unless the receiver is in VFO mode (not browsing a memory
        # channel). enter_vfo_mode() ("raw VF A") is the confirmed way in.
        mhz = hz / 1_000_000
        self._write_with_hint("RF", f"{mhz:010.5f}")

    def get_mode(self) -> str:
        return self._chan.read("MD").value or ""

    def get_mode_info(self) -> ModeInfo:
        """Decoded MD reading - see :class:`ModeInfo` and the AR-DV3-derived
        DIGITAL_MODES/ANALOG_MODES tables above."""
        raw = self.get_mode()
        d = raw[0] if len(raw) >= 1 else None
        a = raw[1] if len(raw) >= 2 else None
        n = raw[2] if len(raw) >= 3 else None
        return ModeInfo(
            raw=raw,
            receiving_digital=DIGITAL_MODES.get(d) if d is not None else None,
            digital_select=DIGITAL_MODES.get(a) if a is not None else None,
            analog_select=ANALOG_MODES.get(n) if n is not None else None,
        )

    def describe_mode(self) -> str:
        """Human-readable summary of the current mode, e.g. "receiving=Auto,
        digital=Digital off, analog=FM" for a raw "0F0"."""
        return self.get_mode_info().describe()

    def set_mode(self, mode: str) -> None:
        """Select the digital and analog mode, e.g. ``set_mode("F0")`` for
        FM with digital off.

        ``mode`` is a 2-character ``"<digital><analog>"`` code from the
        DIGITAL_MODES/ANALOG_MODES tables - the same field order MD reads
        back in - validated up front so a typo raises ValueError instead of
        a device-side format error.

        Confirmed against real hardware: the wire wants a 3-character value
        in the SAME "dan" shape MD reads back, not the 2-character reversed
        form this method sent before (see the DIGITAL_MODES comment for the
        live repro). Callers keep the 2-char convention and this pads it
        internally; do not "fix" this back to a bare 2-character write.

        Not routed through ``_write_with_hint()``: whether MD writes share
        the VFO-mode precondition other tuning/level writes have was never
        confirmed, so an unhinted "?" is more honest than a hint that may
        not apply.

        IF-bandwidth workaround: a real repro showed the DV10's IF selector
        is ONE register shared by every demodulation type - widen FM to
        100 kHz (IF1), switch to a digital mode and back to digital-off, and
        FM comes back reading IF3 (15 kHz). This snapshots the IF bandwidth
        when digital is switched ON and writes it back when digital is
        switched OFF. Tracked as plain instance state, so a change made from
        another session, the front panel or a raw MD/IF command bypasses it.
        Both the snapshot read and the restore write are best-effort - a
        DV10Error in either is swallowed rather than failing the mode change.
        """
        # Wire shape is the 3-char "dan" MD reads back, not a 2-char
        # reversed form - see the docstring and the DIGITAL_MODES comment.
        wire = _mode_write_value(mode)
        cleaned = mode.strip().upper()
        digital_target = cleaned[0]
        entering_digital = not self._digital_active and digital_target != "F"
        if entering_digital:
            try:
                self._pre_digital_if_bandwidth = self.get_if_bandwidth()
            except DV10Error:
                self._pre_digital_if_bandwidth = None

        self._chan.write("MD", wire)
        self._digital_active = digital_target != "F"

        if not self._digital_active and self._pre_digital_if_bandwidth is not None:
            try:
                self.set_if_bandwidth(self._pre_digital_if_bandwidth)
            except DV10Error:
                pass
            finally:
                self._pre_digital_if_bandwidth = None

    def enter_vfo_mode(
        self,
        vfo: str = "A",
        *,
        frequency_hz: Optional[int] = None,
        step_hz: Optional[int] = None,
        step_adjust_hz: Optional[int] = None,
        mode: Optional[str] = None,
    ) -> None:
        """Select a VFO by letter (A/B/Z) - confirmed on real DV10 hardware:
        "raw VF A" succeeds (bare "VF" ack). This is very likely the missing
        software way out of memory-channel mode before set_frequency_hz() and
        friends, replacing the manual front-panel switch - though calling it
        *from* memory-channel mode hasn't itself been confirmed, only that
        the command is accepted. A digit argument (the old "VF 0"/"VF 1"
        guess) is confirmed to fail with a format error.

        Also supports VF's full documented atomic form - ``VFt RFffff.fffff
        STggg.gg SHhhh.hh MDdan`` - so one write can select a VFO and set its
        frequency/step/step-adjust/mode. Passing only ``vfo`` sends the exact
        same bare "VFt" this method always has.

        ``mode`` is sent as a 2-character "<digital><analog>" value via
        ``_validate_mode_pair()`` (not the 3-character "dan" standalone MD
        was confirmed to need), by the same analogy as write_search_bank()'s
        embedded MD: VF is a composite command distinct from standalone MD.
        Inference by analogy, NOT confirmed against real hardware - a real
        candidate for the same silent-no-op bug standalone MD had, worth
        testing the same way if this embedded field is ever seen not to take
        effect."""
        value = vfo.strip().upper()
        if value not in ("A", "B", "Z"):
            raise ValueError(f'vfo must be "A", "B", or "Z" - got {vfo!r}')
        parts = []
        if frequency_hz is not None:
            parts.append(f"RF{_format_rf_freq_mhz(frequency_hz)}")
        if step_hz is not None:
            parts.append(f"ST{float(step_hz) / 1000:06.2f}")
        if step_adjust_hz is not None:
            parts.append(f"SH{float(step_adjust_hz) / 1000:06.2f}")
        if mode is not None:
            parts.append(f"MD{_validate_mode_pair(mode)}")
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("VF", value)

    def execute_vfo_search(self) -> None:
        """Raw VS: activate VFO search (bare command, no value) - uses
        whatever range/settings VFO-A/VFO-B currently have plus the VE
        settings below. Confirmed write-only per the spec (no read direction
        is documented for VS at all, unlike VF)."""
        self._chan.send("VS")

    def read_vfo_search_settings(self) -> VfoSearchSettings:
        """Raw VE (bare read): the current VFO-search delay/free-time/
        auto-store configuration - see VfoSearchSettings. Despite sharing
        the spec's "5-9 VFO" section with VF/VS, VE is a single
        receiver-wide setting, not per-VFO or per numbered group like
        SG/MG - hence no group argument."""
        resp = self._chan.read("VE")
        fields = _parse_composite_fields((resp.value or "").strip())
        delay_raw = fields.get("DL")
        free_raw = fields.get("FR")
        return VfoSearchSettings(
            delay_ds=int(delay_raw) if delay_raw and delay_raw.isdigit() else None,
            free_time_s=int(free_raw) if free_raw and free_raw.isdigit() else None,
            auto_store=(fields.get("AS") == "1") if "AS" in fields else None,
        )

    def write_vfo_search_settings(
        self,
        *,
        delay_ds: Optional[int] = None,
        free_time_s: Optional[int] = None,
        auto_store: Optional[bool] = None,
    ) -> None:
        """Raw VE (write): ``VE DLmm FRpp ASn`` - configure the VFO-search
        delay/free-time/auto-store settings used by execute_vfo_search()
        (VS). Same None-means-omit convention as every other composite write
        in this project."""
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if auto_store is not None:
            parts.append(f"AS{1 if auto_store else 0}")
        self._chan.write("VE", " ".join(parts) if parts else "")

    # -- levels --------------------------------------------------------

    def get_squelch_mode(self) -> str:
        """Raw SQ value (squelch *mode* selector: 0=Auto, 1=Noise, 2=Level)
        - see SQUELCH_MODES. NOT a squelch level despite the command summary
        calling SQ "squelch level"; the threshold is get_squelch_level() (LQ)
        or get_noise_squelch_level() (NQ)."""
        return self._chan.read("SQ").value or ""

    def set_squelch_mode(self, mode: str) -> None:
        # Same VFO-mode precondition as set_frequency_hz() - see there.
        self._write_with_hint("SQ", str(mode))

    # Legacy aliases kept for existing CLI/GUI callers. These read/write SQ,
    # the squelch *mode* selector - prefer get_squelch_level()/
    # set_squelch_level() (LQ) for the actual threshold.
    get_squelch = get_squelch_mode
    set_squelch = set_squelch_mode

    def get_squelch_level(self) -> str:
        """Raw LQ value (00-99): the level-squelch threshold used when SQ
        (squelch mode) is 2=Level."""
        return self._chan.read("LQ").value or ""

    def set_squelch_level(self, level: str) -> None:
        self._chan.write("LQ", str(level))

    def get_noise_squelch_level(self) -> str:
        """Raw NQ value (00-39): the noise-squelch threshold used when SQ
        (squelch mode) is 1=Noise."""
        return self._chan.read("NQ").value or ""

    def set_noise_squelch_level(self, level: str) -> None:
        self._chan.write("NQ", str(level))

    def get_volume(self) -> str:
        # Confirmed against real hardware: this firmware doesn't support AG
        # at all remotely - the bare read AND writes both fail with result
        # code 60 (command does not exist), not just the read as first
        # thought. Left as a normal read/write pair since that isn't
        # confirmed to generalise to every DV10 firmware revision.
        # The operating manual makes clear the physical volume knob is an
        # analog control with no software equivalent, so AG's non-function
        # is expected rather than a firmware bug. AV (get_volume_limit()) is
        # the actual remotely-controllable "volume": a 00-15 ceiling the
        # knob can't exceed, not the level itself.
        return self._chan.read("AG").value or ""

    def set_volume(self, level: str) -> None:
        self._chan.write("AG", str(level))

    def get_smeter(self) -> str:
        return self._chan.read("LM").value or ""

    def get_smeter_reading(self) -> SMeterReading:
        """Decoded LM reading - see :class:`SMeterReading` and
        SQUELCH_STATES for the AR-DV1-spec-confirmed meaning of the
        squelch-state digit."""
        raw = self.get_smeter()
        dbm: Optional[int] = None
        state: Optional[int] = None
        if len(raw) >= 4 and raw[:3].isdigit() and raw[3].isdigit():
            dbm = -int(raw[:3])
            state = int(raw[3])
        return SMeterReading(raw=raw, dbm=dbm, squelch_state=state)

    def get_agc_speed(self) -> str:
        """Raw AC value (0=Fast, 1=Mid, 2=Slow, 3=RF-G) - see AGC_SPEEDS
        above. Confirmed via the AR-DV3 spec to be a 4-state speed
        selector, not on/off."""
        return self._chan.read("AC").value or ""

    def set_agc_speed(self, speed: str) -> None:
        # Same VFO-mode precondition as set_frequency_hz() - see there.
        self._write_with_hint("AC", str(speed))

    def get_agc(self) -> bool:
        """Legacy boolean view of AC: True if the raw speed code isn't
        "0"/Fast. This is a rough simplification of AC's real 4-state
        meaning (see get_agc_speed()/AGC_SPEEDS) kept for existing
        callers."""
        return (self._chan.read("AC").value or "0") not in ("0", "")

    def set_agc(self, on: bool) -> None:
        # Same VFO-mode precondition as set_frequency_hz() - see there.
        # Legacy boolean wrapper around the real 4-state AC speed selector:
        # maps on->"1" (Mid), off->"0" (Fast). Prefer set_agc_speed() for
        # direct control of Fast/Mid/Slow/RF-G.
        self._write_with_hint("AC", "1" if on else "0")

    def get_beep_level(self) -> str:
        """Raw BP value. Per the AR-DV1 wire spec's own BP entry (``BPn``,
        n: 0-7, default 2, 0=Minimum/OFF, 7=Maximum) - a SINGLE digit, not
        the two-digit "00-15, default 05" this project assumed from the
        AR-DV10 operating manual's MENU-CONFIG listing ("BEEP (00-15)").
        Both are real AOR documents for closely related receivers and which
        one this firmware follows is unconfirmed against real hardware; the
        wire-spec encoding is used since a wrong single digit is simply
        rejected with "?" rather than silently misbehaving. Getter/setter
        still pass the raw string/int through."""
        return self._chan.read("BP").value or ""

    def set_beep_level(self, level: int) -> None:
        self._chan.write("BP", f"{int(level):d}")

    def set_beep(self, on: bool) -> None:
        """Legacy boolean wrapper, kept for existing CLI/GUI callers: maps
        on->"2" (the AR-DV1 wire spec's own default level), off->"0"
        (Minimum/OFF). Prefer set_beep_level() for direct control of the
        actual 0-7 range - see get_beep_level()'s docstring."""
        self.set_beep_level(2 if on else 0)

    def get_attenuator_state(self) -> str:
        """Raw AT value (0=ATT OFF, 1=ATT ON, 2=10dB ATT) - see
        ATTENUATOR_STATES above. The labels follow the real DV10's effect
        (1 engages the ~10dB signal attenuator, 0 is the no-attenuation
        baseline), not the AR-DV3 spec's "AMP ON/AMP OFF" wording - the
        wire values are unchanged. 2 (10dB) is DV3-only."""
        return self._chan.read("AT").value or ""

    def set_attenuator_state(self, state: str) -> None:
        # Same VFO-mode precondition as set_frequency_hz() - see there.
        self._write_with_hint("AT", str(state))

    def set_attenuator(self, on: bool) -> None:
        # Legacy boolean wrapper over the 3-state AT selector: on->"1"
        # (signal attenuator engaged), off->"0". Can't reach state 2 (the
        # DV3-only 10dB step) - use set_attenuator_state() for that.
        self._write_with_hint("AT", "1" if on else "0")

    # -- tuning step -------------------------------------------------------

    def get_frequency_step_hz(self) -> int | None:
        """ST: the tuning-step size used when turning the dial knob or
        pressing the fast-tune arrows; the manual (5.8) lists presets from
        10Hz to 500kHz.

        Confirmed against real hardware: a bare integer Hz write (this
        method's previous encoding) is rejected with result code 40 (format
        error). The wire format is ``STggg.gg``, the same kHz-decimal shape
        as SH and as the MX/SE/VI-embedded ST sub-field. 10Hz is the finest
        step this format can express (0.01 kHz); 500kHz fits its
        three-integer-digit range. Returns Hz, or None if ST came back
        empty/unparseable."""
        raw = self._chan.read("ST").value
        return round(float(raw) * 1000) if raw else None

    def set_frequency_step_hz(self, hz: int) -> None:
        # Same kHz-decimal wire format as the embedded ST sub-field in
        # MX/SE/VI writes, and the same VFO-mode precondition as
        # set_frequency_hz() - see get_frequency_step_hz().
        self._write_with_hint("ST", f"{float(hz) / 1000:06.2f}")

    def get_step_adjust_hz(self) -> int | None:
        """SH: a fine sub-step offset (0Hz up to half the ST step), per the
        manual's 5.9 "STEP-ADJUST".

        Corrected against the AR-DV1 wire spec's own SH entry: the wire
        format is ``SHnnn.nn``, a kHz-decimal value from a fixed enum (0.05,
        0.25, 0.5, 1, 2.5, 3.12, 3.75, 4.16, 4.5, 5.0, 6.25, 10.0, 12.5,
        15.0, 25.0, 50.0, 250.0 kHz; default 000.00) - the SAME format the
        MX/SE/VI-embedded SH sub-field already used. This standalone command
        previously sent/parsed a bare integer Hz, which is almost certainly
        wrong. The enum is not validated here (same "let the device reject
        it" philosophy used elsewhere). Returns Hz, or None if SH came back
        empty/unparseable."""
        raw = self._chan.read("SH").value
        return round(float(raw) * 1000) if raw else None

    def set_step_adjust_hz(self, hz: int) -> None:
        # Same kHz-decimal wire format as the embedded SH sub-field in
        # MX/SE/VI writes, not the bare integer Hz this sent previously -
        # see get_step_adjust_hz().
        self._write_with_hint("SH", f"{float(hz) / 1000:06.2f}")

    # -- advanced squelch: tone (CTCSS/reverse-tone) and DCS ----------------

    def get_tone_squelch_enabled(self) -> str:
        """Raw CI value as a boolean-shaped string ("0"/"1"/"2"), kept for
        existing callers (the CLI/web "tone on|off" verb) - but CI is NOT a
        boolean: see TONE_SQUELCH_TYPES/get_squelch_tone_type(). This covers
        only OFF ("0") vs CTCSS ("1", inferred); use
        set_squelch_tone_type("2") for Reverse Tone."""
        return self._chan.read("CI").value or ""

    def set_tone_squelch_enabled(self, on: bool) -> None:
        """Simplified OFF/CTCSS toggle - see get_tone_squelch_enabled()'s
        docstring for why this can't reach Reverse Tone (CI="2"); use
        set_squelch_tone_type() for that."""
        self._write_with_hint("CI", "1" if on else "0")

    def get_squelch_tone_type(self) -> str:
        """Raw CI value, decoded via TONE_SQUELCH_TYPES - the SQL TYPE menu's
        tone-squelch side (OFF/CTCSS/Reverse Tone). DCS is a separate,
        confirmed-independent toggle (DI, see get_dcs_enabled()), NOT one of
        CI's values: selecting DCS leaves CI reading "0" while DI flips to
        "1". See TONE_SQUELCH_TYPES for what is confirmed vs. inferred."""
        return (self._chan.read("CI").value or "").strip()

    def set_squelch_tone_type(self, value: str) -> None:
        """Raw CIn write - see get_squelch_tone_type()/
        TONE_SQUELCH_TYPES. To select DCS instead of OFF/CTCSS/Reverse
        Tone, use set_dcs_enabled(True) (DI) - confirmed independent of
        CI, not one of its values."""
        value = str(value).strip()
        if value not in TONE_SQUELCH_TYPES:
            raise ValueError(
                f"unknown squelch tone type {value!r} - expected one of "
                f"{', '.join(sorted(TONE_SQUELCH_TYPES))} ({', '.join(TONE_SQUELCH_TYPES.values())})"
            )
        self._write_with_hint("CI", value)

    def get_tone_squelch_freq(self) -> str:
        """The CTCSS tone frequency squelch opens on (e.g. "100.0"), "SRCH"
        for auto-detect/search, or "" if CN couldn't be parsed - decoded from
        CN's raw wire value via _decode_cn().

        Per the AR-DV1 spec's own CN entry: ``CNnn``, nn = 00 (response-only,
        "no tone") / 01-52 (a 1-based INDEX into CTCSS_TONES_HZ) / 99
        (search), default 99. This project's original guess - sending the
        literal decimal Hz value shown on the front panel, RF-style - was
        wrong, and a real device would have rejected every write it sent.
        The public API stays the human-readable Hz string / "SRCH"; only the
        wire
        encoding underneath changed."""
        return _decode_cn(self._chan.read("CN").value or "")

    def set_tone_squelch_freq(self, tone: str) -> None:
        """``tone`` is one of CTCSS_TONES_HZ (e.g. "100.0"), or "SRCH" to
        start an auto-detect search (CN99) - see get_tone_squelch_freq()'s
        docstring for the wire-encoding correction this now applies
        underneath. "OFF" is no longer accepted here: CN itself has no
        "off" wire value - use set_tone_squelch_enabled(False) (CI)
        instead to disable tone squelch."""
        tone = tone.strip().upper()
        if tone == "SRCH":
            self._write_with_hint("CN", "99")
            return
        if tone == "OFF":
            raise ValueError(
                'CN has no "OFF" wire value - use set_tone_squelch_enabled(False) instead'
            )
        try:
            index = CTCSS_TONES_HZ.index(tone) + 1
        except ValueError:
            raise ValueError(
                f"{tone!r} is not one of CTCSS_TONES_HZ and isn't \"SRCH\""
            ) from None
        self._write_with_hint("CN", f"{index:02d}")

    def get_dcs_enabled(self) -> str:
        """Raw DI value ("DCS ON/OFF") - confirmed against real DV10 hardware
        to be independent of CI/TONE_SQUELCH_TYPES: with the front panel's
        SQL TYPE showing "DCS", DI read "1" and CI read "0" (its OFF value)."""
        return self._chan.read("DI").value or ""

    def set_dcs_enabled(self, on: bool) -> None:
        self._write_with_hint("DI", "1" if on else "0")

    def get_dcs_code(self) -> str:
        """The DCS code squelch opens on (e.g. "023"), "SRCH" for an active
        auto-detect search, or "" if no code is (yet) detected - decoded
        from DS's raw wire value.

        Per the AR-DV1 spec's own DS entry: ``DSnnn``, nnn = 000
        (response-only, "no code") / 017-754 (a LITERAL DCS code matching
        DCS_CODES - unlike CN, never index-based) / 999 (search), default
        999. The shape here was already right; the one real bug was
        set_dcs_code() sending a literal "SRCH"/"OFF" string verbatim
        instead of translating "SRCH" to 999."""
        raw = (self._chan.read("DS").value or "").strip()
        if raw == "999":
            return "SRCH"
        if raw in ("", "000"):
            return ""
        return raw

    def set_dcs_code(self, code: str) -> None:
        """``code`` is one of DCS_CODES (e.g. "023"), or "SRCH" to start an
        auto-detect search (DS999) - see get_dcs_code()'s docstring for the
        SRCH-mapping fix this now applies. "OFF" is no longer accepted
        here: DS itself has no "off" wire value - use
        set_dcs_enabled(False) (DI) instead to disable DCS squelch."""
        code = code.strip().upper()
        if code == "SRCH":
            self._write_with_hint("DS", "999")
            return
        if code == "OFF":
            raise ValueError(
                'DS has no "OFF" wire value - use set_dcs_enabled(False) instead'
            )
        self._write_with_hint("DS", code)

    # -- digital-mode selective-call codes -----------------------------------
    #
    # DMR/P25/NXDN/D-CR all support filtering to one specific
    # color/NAC/RAN/scramble code instead of decoding everything - see
    # manual 10.7 "ADVANCED DIGITAL MODE SETTINGS". Values below are sent
    # as literal zero-padded decimal strings per the manual's own digit
    # counts; unconfirmed against real hardware.

    def get_dmr_color_code(self) -> str:
        """Raw CC value: DMR color code, 00-16 (00 = decode all)."""
        return self._chan.read("CC").value or ""

    def set_dmr_color_code(self, code: int) -> None:
        self._chan.write("CC", f"{int(code):02d}")

    def get_dmr_mute_by_color_code(self) -> str:
        """Raw CM value: when on, only CC's color code is decoded."""
        return self._chan.read("CM").value or ""

    def set_dmr_mute_by_color_code(self, on: bool) -> None:
        self._chan.write("CM", "1" if on else "0")

    def get_dmr_slot(self) -> str:
        """Raw OT value: which DMR slot(s) to decode - "1+2"=both/priority
        slot1, "2+1"=both/priority slot2, "1"=slot1 only, "2"=slot2 only.
        Sent/read as a literal code; exact digit(s) unconfirmed."""
        return self._chan.read("OT").value or ""

    def set_dmr_slot(self, slot: str) -> None:
        self._chan.write("OT", slot.strip())

    def get_p25_nac(self) -> str:
        """Raw PC value: APCO P25 NAC code, 3 hex digits, 000-FFF
        (000 = decode all)."""
        return self._chan.read("PC").value or ""

    def set_p25_nac(self, nac: str) -> None:
        self._chan.write("PC", nac.strip().upper().zfill(3))

    def get_p25_mute_by_nac(self) -> str:
        """Raw PM value: when on, only PC's NAC code is decoded."""
        return self._chan.read("PM").value or ""

    def set_p25_mute_by_nac(self, on: bool) -> None:
        self._chan.write("PM", "1" if on else "0")

    def get_nxdn_ran(self) -> str:
        """Raw NC value: NXDN RAN code, 00-63 (00 = decode all)."""
        return self._chan.read("NC").value or ""

    def set_nxdn_ran(self, ran: int) -> None:
        self._chan.write("NC", f"{int(ran):02d}")

    def get_nxdn_mute_by_ran(self) -> str:
        """Raw NM value: when on, only NC's RAN code is decoded."""
        return self._chan.read("NM").value or ""

    def set_nxdn_mute_by_ran(self, on: bool) -> None:
        self._chan.write("NM", "1" if on else "0")

    def get_dcr_descramble_code(self) -> str:
        """Raw DC value: the D-CR 15-bit scramble code, 00001-32767
        (00000 = no scramble code / off) - see manual 10.7."""
        return self._chan.read("DC").value or ""

    def set_dcr_descramble_code(self, code: int) -> None:
        self._chan.write("DC", f"{int(code):05d}")

    # -- analog voice descrambler ---------------------------------------------

    def get_voice_descrambler_enabled(self) -> str:
        """Raw SI value: analog voice-inversion descrambler (V.SCR),
        FM-only with 6/15kHz IF bandwidth - see manual 10.6. Not available
        on US-market units per the manual."""
        return self._chan.read("SI").value or ""

    def set_voice_descrambler_enabled(self, on: bool) -> None:
        self._write_with_hint("SI", "1" if on else "0")

    def get_voice_descrambler_freq(self) -> str:
        """Raw SC value: the descrambler carrier frequency, 2000-7000Hz -
        listed Read-only in the command summary, so likely a status
        readout rather than something set directly via SC (set via the
        front panel's V.SCR F. field, whose own CI mnemonic isn't in the
        summary - possibly folded into SC itself as a write too)."""
        return self._chan.read("SC").value or ""

    # -- offset reception -----------------------------------------------------

    def get_offset_slot(self) -> str:
        """Raw OF value: which offset-frequency slot (00-39) is active for
        offset reception, and its direction sign - see set_offset_slot()
        for the wire-format correction. 00 = offset reception
        disabled/0Hz; 01-19 = user-programmable slots (see
        get_offset_freq()/set_offset_freq()); 20-39 = factory presets."""
        return self._chan.read("OF").value or ""

    def set_offset_slot(self, slot: int, direction: str = "+") -> None:
        """Select which offset slot (00-39) is active, and its direction.

        Per the AR-DV1 spec's own OF entry: ``OFsnn`` - nn (00-39) is the
        slot, and ``s`` is a leading "+"/"-" DIRECTION sign this project's
        original implementation was missing entirely (it is NOT folded into
        OL's frequency). The sign may be omitted only when slot is 00 (offset
        reception off); this method omits it automatically then, and
        otherwise requires an explicit "+" or "-". See set_offset_freq() for
        the matching OL correction."""
        slot = int(slot)
        if slot == 0:
            self._write_with_hint("OF", "00")
            return
        direction = direction.strip()
        if direction not in ("+", "-"):
            raise ValueError(f'direction must be "+" or "-", got {direction!r}')
        self._write_with_hint("OF", f"{direction}{slot:02d}")

    def get_offset_freq(self, slot: int) -> str:
        """The offset frequency (unsigned decimal MHz string, e.g.
        "0000.60000") stored in the given slot (00-39) - direction comes from
        OF, not from this value. The wire response is ``"OLnn RFffff.fffff"``;
        both the ``OLnn`` echo (stripped by the protocol layer) and the
        ``RF`` sub-field prefix (stripped here) are removed.

        Per the AR-DV1 spec's own OL entry: unlike every other read here,
        OL's READ also requires the slot number (``OLnn<CR>``, not a bare
        ``OL<CR>``) - there is no "current" offset frequency. This project
        originally modelled OL as a single global signed value, wrong on both
        counts: it is per-slot (paired with OF's selector) and its frequency
        field is unsigned (OF carries direction). Also, per the spec's own
        remark, OL is the one exception to "each VFO/bank/channel has its own
        settings" - a single receiver-wide table."""
        raw = (self._chan.read(f"OL{int(slot):02d}").value or "").strip()
        # The channel layer strips only the "OLnn" echo, leaving
        # " RFffff.fffff" - peel "RF" off too so callers get a plain decimal.
        if raw.upper().startswith("RF"):
            raw = raw[2:]
        return raw

    def set_offset_freq(self, slot: int, mhz: float) -> None:
        """Program the offset frequency stored in ``slot`` (00-39).

        Per the AR-DV1 spec: slot 00 is fixed at 0Hz (offset reception off,
        not reprogrammable); 01-19 are user-programmable; 20-39 are factory
        presets the spec says "cannot be changed" - a write there is expected
        to be rejected, not silently accepted. ``mhz`` must be non-negative:
        direction is OF's separate sign field - see get_offset_freq()."""
        slot = int(slot)
        mhz = float(mhz)
        if mhz < 0:
            raise ValueError(
                "OL's frequency field is unsigned - use set_offset_slot(slot, direction) "
                "for the sign, not a negative mhz here"
            )
        # Zero-padded to the spec's own "ffff.fffff" width (RF's established
        # literal-decimal style) - e.g. 0.6 -> "0000.60000".
        self._write_with_hint("OL", f"{slot:02d} RF{mhz:010.5f}")

    # -- live memory channels (MX/MA/MR) and bank management (MW/MB/MQ) ------
    #
    # Implemented against the AR-DV1 wire spec's own "5-11 MEMORY CHANNEL"
    # section - the first real documented field layout this project has had
    # for these. Distinct from aor_dv10.memory's backup-CSV MemoryBank/
    # MemoryChannel: these talk to the *live* receiver, not an exported .csv
    # - see MemoryChannelInfo for the field differences.

    def _parse_memory_channel_response(
        self, bank: int, channel: int, text: str
    ) -> "MemoryChannelInfo":
        """``text`` is a single MA/MX-shaped response body (already past
        any "MAbbcc"/"MXbbcc" echo) - either "- - -" (unregistered, per
        the spec's own placeholder) or the composite MP/RF/ST/SH/MD/PT/TT
        fields."""
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        if not fields:
            return MemoryChannelInfo(bank=bank, channel=channel, registered=False)
        freq_raw = fields.get("RF")
        step_raw = fields.get("ST")
        stepadj_raw = fields.get("SH")
        return MemoryChannelInfo(
            bank=bank,
            channel=channel,
            registered=True,
            pass_channel=fields.get("MP") == "1",
            frequency_hz=round(float(freq_raw) * 1_000_000) if freq_raw else None,
            step_hz=round(float(step_raw) * 1000) if step_raw else None,
            step_adjust_hz=round(float(stepadj_raw) * 1000) if stepadj_raw else None,
            mode=fields.get("MD"),
            write_protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def write_memory_channel(
        self,
        bank: int,
        channel: int,
        *,
        frequency_hz: Optional[int] = None,
        step_hz: Optional[int] = None,
        step_adjust_hz: Optional[int] = None,
        mode: Optional[str] = None,
        pass_channel: bool = False,
        write_protect: bool = False,
        tag: Optional[str] = None,
    ) -> None:
        """Raw MX: program memory channel (bank, channel) - ``MXbbcc [MPp]
        [RFffff.fffff] [STggg.gg] [SHhhh.hh] [MDdan] [PTa] [TTttt]``.

        Per the AR-DV1 spec every field after ``bbcc`` may be omitted:
        RF/ST/SH/MD then keep whatever "previous settings" the receiver has
        (what that means with no live channel selected is unconfirmed) and
        MP/PT default to 0. This method sends a sub-field for everything it
        is given and omits the ones left at their Python default; it does not
        read back or replicate "previous settings" itself. ``mode`` uses the
        same "<digital><analog>" convention as set_mode(); ``tag`` is
        truncated to TT's documented 12 characters. DESTRUCTIVE: overwrites
        whatever was in that slot.

        **Real-DV10 finding (revised)**: MX's embedded MD sub-field wants the
        SAME 3-character "dan" shape standalone MD does - the syntax spells
        it ``MDdan``, real captured channel dumps carry ``MD000``/``MD0F0``
        (tests/test_memory_channels.py's hardware fixtures), and a live
        ``m F1``/``m F0`` round-trip reads back ``0F1``/``0F0``. The bare
        2-char form this method used to pass through verbatim is confirmed
        against real hardware to fail with error 40 (PC_RESULT_FORMAT_ERR):
        one character short. So a 2-char ``mode`` is padded via
        _mode_write_value() and a 3-char value is sent verbatim, keeping an
        unedited round-trip byte-identical.

        An earlier note here claimed a padded "0F0" also failed on a live MX
        write; that test wrote MD alone to an UNREGISTERED slot with no RF
        field (``raw MR`` on it answers 30, "channel not registered"), so it
        measured the empty-slot rejection, not the pad."""
        # MP and PT are ALWAYS emitted, never omitted-when-false. The spec
        # calls them optional (defaulting to 0), but a real AR-DV10's own
        # canonical channel dump always carries them -
        #   "MX0418 MP0 RF0439.10000 ST012.50 SH000.00 MD000 PT0 TTSR2BT..."
        # (tests/test_memory_channels.py's captured hardware fixture) - and
        # every live MX write sent WITHOUT them came back error 40
        # (PC_RESULT_FORMAT_ERR), whatever the MD value was.
        parts = ["MP1" if pass_channel else "MP0"]
        if frequency_hz is not None:
            parts.append(f"RF{float(frequency_hz) / 1_000_000:010.5f}")
        if step_hz is not None:
            parts.append(f"ST{float(step_hz) / 1000:06.2f}")
        if step_adjust_hz is not None:
            parts.append(f"SH{float(step_adjust_hz) / 1000:06.2f}")
        if mode is not None:
            # MX's MD sub-field is "MDdan" - 3 chars. A 2-char value
            # (natural, e.g. "F0") is padded the same way set_mode() does; a
            # 3-char dan value (e.g. "0F0"/"000") is already the wire shape
            # and goes verbatim, so an unedited round-trip is byte-identical.
            # A bare 2-char MD is confirmed on real hardware to fail with
            # error 40 - it is one character short.
            m = str(mode).strip().upper()
            if len(m) == 2:
                m = _mode_write_value(m)
            elif len(m) != 3:
                raise ValueError(
                    f'mode must be "<digital><analog>" 2 chars (e.g. "F0") '
                    f'or a 3-char dan value (e.g. "0F0") - got {m!r}'
                )
            parts.append(f"MD{m}")
        parts.append("PT1" if write_protect else "PT0")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:12]}")
        value = f"{int(bank):02d}{int(channel):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MX", value)

    def read_memory_channel(self, bank: int, channel: int) -> MemoryChannelInfo:
        """Raw MA (single-channel form): query the stored record for
        (bank, channel) - a pure read, unlike tune_memory_channel() (MR),
        which actually switches the receiver to receive that channel.
        ``.registered`` is False (every other field then meaningless) for
        an unprogrammed slot - see MemoryChannelInfo."""
        bank, channel = int(bank), int(channel)
        resp = self._chan.read(f"MA{bank:02d}{channel:02d}")
        return self._parse_memory_channel_response(bank, channel, resp.value or "")

    def read_memory_bank(self, bank: int, timeout: float = 5.0) -> List[MemoryChannelInfo]:
        """Raw MA (bank form): read every channel record in ``bank`` in one
        go - up to 50 records (manual: 40 banks x 50 channels).

        Confirmed against the AR-DV1 spec that "MAbb" (unlike the
        single-channel "MAbbcc" form) is a MULTI-LINE response: its result
        codes include 21 ("Reading, to be continued") alongside 20 ("Read
        completed"), the same shape already handled for MM. This sends
        "MAbb" once and keeps calling read_pending() until a line comes back
        with result_code 20, bounded by ``timeout`` seconds *per line*.

        UNCONFIRMED: how continuation lines identify which channel they are
        for is shown in no spec transcript - this assumes each line repeats
        its own channel number.

        The 21-vs-20 distinction is only visible with RE on (see
        set_result_code_prefixing()), so this temporarily turns RE on for the
        read and restores it, even on error, rather than silently returning a
        truncated result. NOT safe against another thread sending commands on
        this device concurrently: CommandChannel's lock protects each
        send()/read_pending() call, not this whole sequence."""
        bank = int(bank)
        bank_str = f"{bank:02d}"
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            first = self._chan.send(f"MA{bank_str}")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"MA{bank_str} reported more lines were coming (21) but "
                        f"none arrived within {timeout}s"
                    )
                responses.append(nxt)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)

        channels: List[MemoryChannelInfo] = []
        for resp in responses:
            # Use .raw, not .value, and strip the numeric result-code prefix
            # here: CommandChannel.send() (which produced responses[0]) also
            # strips whatever code it was TOLD it sent - "MA" + bank_str,
            # e.g. "MA00" - assuming a response echoes the code it was sent.
            # That holds for every single-response command but not for this
            # multi-line one, whose lines echo "MA" + the FULL 4-digit bbcc.
            # Real-hardware-confirmed bug (found building the CSV live-export
            # /diff bridge): the mismatch mangled the first line only (later
            # lines come from read_pending(), which never strips a code echo),
            # so channel 0 of every bank was always reported unregistered.
            # .raw predates both strippers, so it is uniform across lines.
            text = (resp.raw or "").strip()
            if resp.result_code is not None:
                prefix = str(resp.result_code)
                if text.startswith(prefix):
                    text = text[len(prefix):]
            up = text.upper()
            # Continuation lines may be prefixed "MA" (as the simulator
            # models it) or "MX" (real DV10: "MXbbcc MPx RF..."). Accept both.
            if up.startswith(("MA", "MX")):
                text, up = text[2:], up[2:]
            if up.startswith(bank_str):
                text = text[2:]
            text = text.strip()
            channel_str, _, rest = text.partition(" ")
            if not (channel_str.isdigit() and len(channel_str) == 2):
                continue  # not a channel line we recognise - skip rather than crash
            channels.append(self._parse_memory_channel_response(bank, int(channel_str), rest))
        # Real hardware may return lines only for the channels that are
        # actually programmed rather than a full 50-line dump, which made
        # "(N registered of N slots)" misleading (the web panel reported
        # "0 registered of 0 slots" for a bank that does have channels).
        # Normalise to the bank's documented capacity (50 slots).
        slots = [MemoryChannelInfo(bank=bank, channel=i, registered=False) for i in range(50)]
        for c in channels:
            if 0 <= c.channel < 50:
                slots[c.channel] = c
        return slots

    def tune_memory_channel(self, bank: int, channel: int) -> None:
        """Raw MR: switch the receiver into memory-read mode, actually
        RECEIVING (bank, channel) - unlike read_memory_channel() (MA),
        which only queries the stored record without changing what's
        being received. Raises DV10ProtocolError (result code 30) if the
        channel isn't registered."""
        self._chan.write("MR", f"{int(bank):02d}{int(channel):02d}")

    def write_memory_bank(
        self,
        bank: int,
        *,
        channel_count: Optional[int] = None,
        protect: Optional[bool] = None,
        tag: Optional[str] = None,
    ) -> None:
        """Raw MW: create/configure memory bank ``bank``'s own metadata
        (assigned channel count, write-protect, name tag) - NOT a channel
        write, see write_memory_channel() (MX) for individual channels.
        Fields left as None are omitted (spec defaults: MC 50, PT 0, TT
        none)."""
        parts = []
        if channel_count is not None:
            parts.append(f"MC{int(channel_count):02d}")
        if protect is not None:
            parts.append(f"PT{1 if protect else 0}")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:12]}")
        value = f"{int(bank):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MW", value)

    def get_memory_bank_info(self, bank: int) -> MemoryBankInfo:
        """Raw MW read form: query bank ``bank``'s metadata.

        UNCONFIRMED: the AR-DV1 spec's MW entry has no "To read:" line, so
        whether a bare "MWbb<CR>" really returns the bank's metadata isn't
        verified. Modelled like every other RW command here (bare code =
        read), on the assumption of a missing doc line - confirm against
        real hardware before relying on it."""
        bank = int(bank)
        bank_str = f"{bank:02d}"
        resp = self._chan.read(f"MW{bank_str}")
        text = (resp.value or "").strip()
        up = text.upper()
        if up.startswith("MW"):
            text, up = text[2:], up[2:]
        if up.startswith(bank_str):
            text = text[2:]
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        count_raw = fields.get("MC")
        return MemoryBankInfo(
            bank=bank,
            channel_count=int(count_raw) if count_raw and count_raw.isdigit() else None,
            protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def delete_memory_bank(self, bank: int) -> None:
        """Raw MB: delete memory bank ``bank`` AND every channel and pass
        -channel in it (per the spec's own remark). DESTRUCTIVE. Raises
        DV10ProtocolError (result code 30) if the bank isn't registered."""
        self._chan.write("MB", f"{int(bank):02d}")

    def delete_memory_channel(self, bank: int, channel: int) -> None:
        """Raw MQ: delete a single memory channel. DESTRUCTIVE. Raises
        DV10ProtocolError (result code 30) if the channel isn't
        registered."""
        self._chan.write("MQ", f"{int(bank):02d}{int(channel):02d}")

    # -- search banks (SE/SR/SS/SX) and session-only limits (SL/SU) ----------
    #
    # Implemented against the AR-DV1 wire spec's "5-10 SEARCH" section. A
    # search bank is a program-search scan-range record, distinct from a live
    # memory bank (MW above) despite sharing several sub-field letters.
    #
    # NOTE on the spec PDF: the "SE" table's own "To read:"/Response cell is
    # corrupted - a verbatim copy of the unrelated "SD DIR" table from a few
    # pages earlier (confirmed by direct re-read of the PDF, so a copy-paste
    # artifact in AOR's document, not a real SE response shape) and is
    # ignored here. SE's read side is inferred instead from the separate
    # "SR" entry, which itself shows no response layout (only the "SRbb"
    # request and result codes) - read_search_bank() assumes SR mirrors SE's
    # own write field layout, the way MA mirrors MX's. UNCONFIRMED, worth a
    # real-hardware check.

    def _parse_search_bank_response(self, bank: int, text: str) -> "SearchBankInfo":
        fields = _parse_composite_fields(text.strip(), tag_field="TT")
        if not fields:
            return SearchBankInfo(bank=bank, registered=False)
        lower_raw = fields.get("SL")
        upper_raw = fields.get("SU")
        step_raw = fields.get("ST")
        stepadj_raw = fields.get("SH")
        return SearchBankInfo(
            bank=bank,
            registered=True,
            lower_limit_hz=round(float(lower_raw) * 1_000_000) if lower_raw else None,
            upper_limit_hz=round(float(upper_raw) * 1_000_000) if upper_raw else None,
            step_hz=round(float(step_raw) * 1000) if step_raw else None,
            step_adjust_hz=round(float(stepadj_raw) * 1000) if stepadj_raw else None,
            mode=fields.get("MD"),
            write_protect=fields.get("PT") == "1",
            tag=fields.get("TT", "").strip(),
        )

    def write_search_bank(
        self,
        bank: int,
        *,
        lower_limit_hz: Optional[int] = None,
        upper_limit_hz: Optional[int] = None,
        step_hz: Optional[int] = None,
        step_adjust_hz: Optional[int] = None,
        mode: Optional[str] = None,
        write_protect: bool = False,
        tag: Optional[str] = None,
    ) -> None:
        """Raw SE: create/configure search bank ``bank`` - ``SEbb
        [SLffff.ffff] [SUffff.ffff] [STggg.gg] [SHhhh.hh] [MDdan] [PTa]
        [TTttt]``. Per the spec ST/SH/MD keep their previous value when
        omitted, PT resets to OFF and TT to blank - the same omit-semantics
        as write_memory_channel() (MX). SL/SU have no documented "previous
        value" fallback; they are simply omitted when left None.

        ``mode`` is sent as a 2-character "<digital><analog>" value via
        ``_validate_mode_pair()`` (not the 3-char "dan" standalone MD was
        confirmed to need), by analogy with MX's embedded MD: SE's MD
        sub-field is a different command from standalone MD. Inference by
        analogy, not a spec statement or a hardware test - a real candidate
        for the same silent no-op bug standalone MD had.

        Frequencies use the AR-DV1 spec's own SL/SU width ``ffff.ffff``
        (100 Hz), coarser than RF/OL's ``ffff.fffff`` (10 Hz) - see
        _format_search_freq_mhz() for how that was confirmed to be a genuine
        width difference, not a typo."""
        parts = []
        if lower_limit_hz is not None:
            parts.append(f"SL{_format_search_freq_mhz(lower_limit_hz)}")
        if upper_limit_hz is not None:
            parts.append(f"SU{_format_search_freq_mhz(upper_limit_hz)}")
        if step_hz is not None:
            parts.append(f"ST{float(step_hz) / 1000:06.2f}")
        if step_adjust_hz is not None:
            parts.append(f"SH{float(step_adjust_hz) / 1000:06.2f}")
        if mode is not None:
            # SE's embedded MD is modelled on MX's and must accept the same
            # two shapes: 3-char dan verbatim (DV10, e.g. "000") or 2-char
            # natural (DV1, e.g. "F0"). Never invent a pad.
            m = str(mode).strip().upper()
            if len(m) not in (2, 3):
                raise ValueError(
                    f'mode must be 2 chars (natural, e.g. "F0") or 3 chars '
                    f'(dan, e.g. "000") - got {m!r}'
                )
            parts.append(f"MD{m}")
        if write_protect:
            parts.append("PT1")
        if tag is not None:
            parts.append(f"TT{tag.strip()[:12]}")
        value = f"{int(bank):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("SE", value)

    def read_search_bank(self, bank: int) -> SearchBankInfo:
        """Raw SR: query search bank ``bank``'s stored record.

        Unlike read_memory_channel() (MA), which returns
        ``.registered=False`` for an unprogrammed slot, SR's own spec entry
        lists result code 30 as "Bank unregistered" - a real error, not a
        placeholder - so this raises DV10ProtocolError there instead. (The
        ``registered`` branch in _parse_search_bank_response() is defensive
        only.) See this section's opening note for why the response parsing
        is otherwise inferred rather than confirmed."""
        bank = int(bank)
        resp = self._chan.read(f"SR{bank:02d}")
        return self._parse_search_bank_response(bank, resp.value or "")

    def execute_search(self, bank: int) -> None:
        """Raw SS: start a program search over ``bank``'s configured
        range. Raises DV10ProtocolError (result code 30) if the bank isn't
        registered."""
        self._chan.write("SS", f"{int(bank):02d}")

    def delete_search_bank(self, bank: int) -> None:
        """Raw SX: delete search bank ``bank``. DESTRUCTIVE. Raises
        DV10ProtocolError (result code 30) if the bank isn't registered."""
        self._chan.write("SX", f"{int(bank):02d}")

    def get_search_lower_limit(self) -> Optional[int]:
        """Raw SL (bare read): the search range's current lower-limit
        frequency, in Hz - SESSION-only per the spec's own Remarks
        ("effective until SS is sent, receive mode changed, or power turned
        off"); to persist one, fold it into a search bank via
        write_search_bank(). None if nothing parseable comes back."""
        resp = self._chan.read("SL")
        raw = (resp.value or "").strip()
        return round(float(raw) * 1_000_000) if raw else None

    def set_search_lower_limit(self, frequency_hz: int) -> None:
        """Raw SL (write): set the search range's lower-limit frequency for
        THIS session only - see get_search_lower_limit()'s docstring for
        the "doesn't persist" caveat."""
        self._chan.write("SL", _format_search_freq_mhz(frequency_hz))

    def get_search_upper_limit(self) -> Optional[int]:
        """Raw SU (bare read): same session-only caveat as
        get_search_lower_limit(). Note the AR-DV1 spec's own SU entry
        describes its parameter as "low limit frequency" (an apparent
        copy-paste from SL directly above it) - treated as a documentation
        typo; the command name and its own out-of-range wording both point
        at upper-limit."""
        resp = self._chan.read("SU")
        raw = (resp.value or "").strip()
        return round(float(raw) * 1_000_000) if raw else None

    def set_search_upper_limit(self, frequency_hz: int) -> None:
        """Raw SU (write): set the search range's upper-limit frequency for
        THIS session only - see get_search_upper_limit()'s docstring."""
        self._chan.write("SU", _format_search_freq_mhz(frequency_hz))

    # -- scan groups (SG search-side / MG memory-side) and their shared
    #    standalone sub-commands (AS auto-store, BK bank-link) --------------
    #
    # A "scan group" bundles a delay time, free time and a set of linked
    # banks (plus, search-side only, an auto-store flag) under one group
    # number - SG for search banks, MG for memory banks. AS and BK are also
    # documented as usable standalone, so both get their own typed get/set.

    def _parse_scan_group_response(
        self, group: int, text: str, *, has_auto_store: bool
    ) -> "ScanGroupInfo":
        fields = _parse_composite_fields(text.strip())
        delay_raw = fields.get("DL")
        free_raw = fields.get("FR")
        return ScanGroupInfo(
            group=group,
            delay_ds=int(delay_raw) if delay_raw and delay_raw.isdigit() else None,
            free_time_s=int(free_raw) if free_raw and free_raw.isdigit() else None,
            auto_store=(fields.get("AS") == "1") if has_auto_store and "AS" in fields else None,
            bank_link=tuple(_parse_bank_link(fields.get("BK", ""))),
        )

    def write_search_scan_group(
        self,
        group: int,
        *,
        delay_ds: Optional[int] = None,
        free_time_s: Optional[int] = None,
        auto_store: Optional[bool] = None,
        bank_link: Optional[List[int]] = None,
    ) -> None:
        """Raw SG: configure search-side scan group ``group`` - ``SGgg
        [DLmm] [FRpp] [ASn] [BKbbb...]``. The 00-19 group range is confirmed
        via the sibling MG entry, which states it where SG's page does not -
        applied here by analogy.

        ``bank_link`` follows the SAME omit-convention as every other
        parameter: ``None`` (the default) leaves the BK sub-field out
        entirely, so the group's existing bank-link list is UNCHANGED - it
        does NOT mean "disable all links". To disable all links pass an EMPTY
        list (``[]``); _format_bank_link() then sends BK's documented "99"."""
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if auto_store is not None:
            parts.append(f"AS{1 if auto_store else 0}")
        if bank_link is not None:
            parts.append(f"BK{_format_bank_link(bank_link)}")
        value = f"{int(group):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("SG", value)

    def read_search_scan_group(self, group: int) -> ScanGroupInfo:
        """Raw SG (bare-group read): query search-side scan group
        ``group``'s configuration."""
        group = int(group)
        resp = self._chan.read(f"SG{group:02d}")
        return self._parse_scan_group_response(group, resp.value or "", has_auto_store=True)

    def write_memory_scan_group(
        self,
        group: int,
        *,
        delay_ds: Optional[int] = None,
        free_time_s: Optional[int] = None,
        bank_link: Optional[List[int]] = None,
    ) -> None:
        """Raw MG: configure memory-side scan group ``group`` (00-19) -
        ``MGgg [DLmm] [FRpp] [BKbbb...]``. Unlike SG, MG has NO auto-store
        sub-field at all per the AR-DV1 spec - there is deliberately no
        ``auto_store`` parameter here. ``bank_link`` follows the same
        omit-convention as write_search_scan_group(): ``None`` leaves the
        existing list unchanged, ``[]`` sends BK's "99" (disable all)."""
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if bank_link is not None:
            parts.append(f"BK{_format_bank_link(bank_link)}")
        value = f"{int(group):02d}"
        if parts:
            value += " " + " ".join(parts)
        self._chan.write("MG", value)

    def read_memory_scan_group(self, group: int) -> ScanGroupInfo:
        """Raw MG (bare-group read): query memory-side scan group ``group``.
        ``.auto_store`` is always None here - see write_memory_scan_group().

        UNCONFIRMED read direction, same gap as get_memory_bank_info() (MW):
        MG's own result-code text says only "20 --- Set completed", unlike
        SG's "20 --- Setting / Reading completed". Modelled as a bare-group
        read anyway, but treat it as less certain than
        read_search_scan_group() (SG) until checked against real hardware."""
        group = int(group)
        resp = self._chan.read(f"MG{group:02d}")
        return self._parse_scan_group_response(group, resp.value or "", has_auto_store=False)

    def get_auto_store(self) -> bool:
        """Raw AS (bare read): the standalone auto-store flag - "This
        command may be used alone" per the spec, independent of any
        particular SG group."""
        resp = self._chan.read("AS")
        return (resp.value or "").strip() == "1"

    def set_auto_store(self, enabled: bool) -> None:
        """Raw AS (write): standalone auto-store on/off. Per the spec this
        can be rejected with result code 30 while a search other than VFO
        search or program search is active - not modelled specially here,
        the caller just sees the resulting DV10ProtocolError."""
        self._chan.write("AS", "1" if enabled else "0")

    def get_bank_link(self) -> List[int]:
        """Raw BK (bare read): the standalone bank-link list - "This
        command may be used alone". Returns an empty list for "no banks
        linked" (raw "99", per the spec's own "bb = 99: All bank links
        are disabled")."""
        resp = self._chan.read("BK")
        return _parse_bank_link((resp.value or "").strip())

    def set_bank_link(self, banks: Optional[List[int]]) -> None:
        """Raw BK (write): standalone bank-link list. ``None`` or an empty
        list writes "99" (disable all links), matching the spec's own
        shorthand rather than requiring callers to spell that out."""
        self._chan.write("BK", _format_bank_link(banks))

    # -- pass frequencies (PW mark / PR list / PD delete) --------------------
    #
    # A "pass frequency" tells VFO search or a program search to skip past
    # a specific frequency instead of stopping on it - kept as its own list
    # of up to 50 slots per VFO search and, separately, per program-search
    # bank.

    def mark_pass_frequency(
        self,
        *,
        frequency_hz: Optional[int] = None,
        bank: Optional[int] = None,
        all_banks: bool = False,
    ) -> None:
        """Raw PW: mark a frequency to be skipped. Four documented shapes,
        selected by which of ``frequency_hz``/``bank``/``all_banks`` are
        given:

        * neither (bare "PW"): while VFO search is stopped on a busy
          channel, marks the CURRENT receive frequency for VFO search.
        * ``frequency_hz`` only ("PWffff.ffff"): marks that frequency for
          VFO search, independent of what's being received.
        * ``bank`` only ("PWbb"): while a program search over ``bank`` is
          stopped on a busy channel, marks the CURRENT receive frequency as
          a pass frequency in that bank.
        * both ("PWbbffff.ffff"): marks that frequency in ``bank``.

        ``all_banks=True`` sends "%%" instead of a bank number - the spec's
        "every search bank" wildcard, valid on both bank shapes. Raises
        DV10ProtocolError (result code 30) if the pass frequency can't be
        set in the current receive mode, or that list has already reached
        its documented maximum of 50 entries."""
        if all_banks and bank is not None:
            raise ValueError("pass bank=<n> and all_banks=True together - use one or the other")
        bank_token = "%%" if all_banks else (f"{int(bank):02d}" if bank is not None else None)
        freq_token = None if frequency_hz is None else _format_search_freq_mhz(frequency_hz)
        if bank_token is None and freq_token is None:
            self._chan.send("PW")
        else:
            self._chan.write("PW", (bank_token or "") + (freq_token or ""))

    def list_pass_frequencies(
        self, bank: Optional[int] = None, timeout: float = 5.0
    ) -> List[PassFrequencyEntry]:
        """Raw PR: list all 50 pass-frequency slots for VFO search
        (``bank=None``, bare "PR") or for a specific program-search bank
        ("PRbb"). Empty slots come back with ``frequency_hz=None`` (the
        spec's own "- - -" placeholder).

        Same multi-line shape as read_memory_bank() (MA bank-form): PR's
        result codes include 21 ("to be continued") alongside 20, reliably
        distinguishable only with RE on - so this temporarily forces RE on
        for the read and restores it, even on error. Same concurrency caveat
        as read_memory_bank(): not safe against another thread using this
        device during the read."""
        bank_i = None if bank is None else int(bank)
        code = "PR" if bank_i is None else f"PR{bank_i:02d}"
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            first = self._chan.send(code)
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"{code} reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)

        entries: List[PassFrequencyEntry] = []
        for resp in responses:
            text = (resp.value or "").strip()
            up = text.upper()
            if up.startswith("PR"):
                text, up = text[2:], up[2:]
            if bank_i is not None:
                bank_str = f"{bank_i:02d}"
                if up.startswith(bank_str):
                    text = text[2:]
            index_str, rest = text[:2], text[2:].strip()
            if not (index_str.isdigit() and len(index_str) == 2):
                continue  # not a slot line we recognise - skip rather than crash
            if rest in ("", "-", "- -", "- - -", "---"):
                freq_hz = None
            else:
                try:
                    freq_hz = round(float(rest) * 1_000_000)
                except ValueError:
                    freq_hz = None
            entries.append(
                PassFrequencyEntry(index=int(index_str), frequency_hz=freq_hz, bank=bank_i)
            )
        return entries

    def delete_pass_frequencies(
        self,
        *,
        bank: Optional[int] = None,
        index: Optional[int] = None,
        all_banks: bool = False,
    ) -> None:
        """Raw PD: delete pass frequencies. The 3 documented shapes:

        * ``bank=None, index=None`` (bare "PD"): delete every VFO-search
          pass frequency.
        * ``bank=<n>, index=None`` ("PDbb"), or ``all_banks=True`` ("PD%%"):
          delete every pass frequency in that bank, or in every bank.
        * ``bank=<n>, index=<i>`` ("PDbbnn"): delete one by list index.

        Raises ValueError for ``index`` without a ``bank`` - the spec has no
        "delete just index nn of the VFO-search list" form, only the whole
        list (bare PD)."""
        if all_banks and bank is not None:
            raise ValueError("pass bank=<n> and all_banks=True together - use one or the other")
        if index is not None and bank is None and not all_banks:
            raise ValueError(
                "PD has no form to delete a single VFO-search pass frequency by "
                "index alone - only the whole VFO-search list (bare PD)"
            )
        if index is not None and all_banks:
            raise ValueError(
                "PD has no form combining the %% (all banks) wildcard with a "
                "specific pass-frequency index - only PDbbnn (one bank, one index)"
            )
        if bank is None and not all_banks:
            self._chan.send("PD")
            return
        bank_token = "%%" if all_banks else f"{int(bank):02d}"
        if index is None:
            self._chan.write("PD", bank_token)
        else:
            self._chan.write("PD", f"{bank_token}{int(index):02d}")

    # -- priority reception -----------------------------------------------------

    def get_priority_enabled(self) -> str:
        """Raw PO value: priority-channel monitoring on/off - see manual 8."""
        return self._chan.read("PO").value or ""

    def set_priority_enabled(self, on: bool) -> None:
        self._chan.write("PO", "1" if on else "0")

    def get_priority_channel(self) -> str:
        """The priority channel as a "BANK-CH" pair (e.g. "00-01"), decoded
        from PP's raw "bbcc" 4-digit wire value - the hyphen is display-only,
        not part of what's sent/received."""
        raw = (self._chan.read("PP").value or "").strip()
        if len(raw) == 4 and raw.isdigit():
            return f"{raw[:2]}-{raw[2:]}"
        return raw

    def set_priority_channel(self, bank: int, channel: int) -> None:
        """Per the AR-DV1 wire spec's PP entry: ``PPbbcc`` - bank and channel
        run together with NO separator, unlike this project's original
        "bb-cc" guess (modelled on the manual's BANK-CH display notation,
        which is not the wire format). Every write the original
        set_priority_channel() sent would have been rejected by hardware."""
        self._chan.write("PP", f"{int(bank):02d}{int(channel):02d}")

    def get_priority_interval(self) -> str:
        """Raw TI value: priority-check interval, 1-99 seconds."""
        return self._chan.read("TI").value or ""

    def set_priority_interval(self, seconds: int) -> None:
        self._chan.write("TI", f"{int(seconds):02d}")

    # -- audio / gain / display settings ---------------------------------------

    def get_volume_limit(self) -> str:
        """Raw AV value, 00 (max) - 15 (most attenuated), default 05 - the
        front panel's "VOL ATT" (manual 5.2), which caps how loud the
        physical volume knob can go. Very likely the *actual* remotely
        controllable "volume": AG is confirmed non-functional on real
        hardware (see get_volume()) and the knob itself is analog, so AV
        only sets its ceiling."""
        return self._chan.read("AV").value or ""

    def set_volume_limit(self, level: int) -> None:
        self._write_with_hint("AV", f"{int(level):02d}")

    def get_digital_gain(self) -> str:
        """Raw DA value, 01.00 (normal) - 15.94 (loudest): extra digital
        audio gain, for when maximum volume with VOL ATT=00 still isn't
        loud enough (manual addendum, "Sound gain", since v.1812C)."""
        return self._chan.read("DA").value or ""

    def set_digital_gain(self, gain: float) -> None:
        self._chan.write("DA", f"{float(gain):05.2f}")

    def get_manual_gain(self) -> str:
        """Raw RG value: the manual-gain level used when AGC
        (get_agc_speed()) is "3"/RF-G. Range/default per the AR-DV1 wire
        spec's RG entry (``RGnnn``, 000 (min) - 110 (max), default 099); the
        3-digit zero-padded format already matched this project's
        manual-sourced guess but the range did not (AR-DV10 operating manual
        10.2 says 000-255, no default) - still unconfirmed against real
        AR-DV10 hardware which applies."""
        return self._chan.read("RG").value or ""

    def set_manual_gain(self, level: int) -> None:
        self._write_with_hint("RG", f"{int(level):03d}")

    def get_lcd_contrast(self) -> str:
        """Raw LN value. Range/default per the AR-DV1 wire spec's LN entry
        (``LNnn``, 00 (lightest) - 63 (darkest), default 25); the 2-digit
        zero-padded format already matched this project's manual-sourced
        guess (00-40, default 30, AR-DV10 operating manual 11.2) but the
        range did not - unconfirmed against real hardware which applies."""
        return self._chan.read("LN").value or ""

    def set_lcd_contrast(self, level: int) -> None:
        self._chan.write("LN", f"{int(level):02d}")

    def get_backlight_mode(self) -> str:
        """Raw LB value - see BACKLIGHT_MODES above (OFF/CONT/AUTO per the
        manual; sent/read as a single digit, unconfirmed)."""
        return self._chan.read("LB").value or ""

    def set_backlight_mode(self, mode: str) -> None:
        self._chan.write("LB", mode.strip())

    # -- misc device settings & actions -----------------------------------------

    def get_sleep_timer(self) -> str:
        """Raw SP value: sleep timer. Marked "No function" for DV10 in the
        official command summary table - kept for completeness since the
        operating manual doesn't likewise disclaim a sleep feature; may
        simply be unimplemented on this firmware, similar to AG."""
        return self._chan.read("SP").value or ""

    def set_sleep_timer(self, value: str) -> None:
        self._chan.write("SP", value.strip())

    def get_clock(self) -> str:
        """Raw DT value: system clock. The front panel's CLK menu (11.1)
        inputs/displays it as "YY-MM-DD HH:MM"; sent/read here as that same
        10-digit string with the punctuation stripped (e.g.
        "2601301500"), unconfirmed."""
        return self._chan.read("DT").value or ""

    def set_clock(self, yy: int, mm: int, dd: int, hh: int, minute: int) -> None:
        self._chan.write("DT", f"{yy:02d}{mm:02d}{dd:02d}{hh:02d}{minute:02d}")

    def write_recording_timer(self, timer: RecordingTimer) -> None:
        """Raw TR (write): configure the scheduled recording/alarm timer -
        see aor_dv10.timer's module docstring for the reconstruction/
        ambiguity caveats (the AR-DV1 spec PDF's TR entry is internally
        inconsistent: its syntax cell omits the XE sub-field entirely,
        recoverable only from the same entry's Remarks/Default prose).

        Modelled as a SINGLE, unnumbered timer - the spec never gives "n"
        (in "TRn") a range, and the read direction is bare "TR<CR>" with no
        index, unlike every genuinely numbered read here (SRbb, SGgg, PRbb).
        Read as "there is one timer", not confirmed fact.

        ``timer.action`` ("off"/"alarm"/"recording") is always sent (XE);
        every other RecordingTimer field is omitted when left at its default
        - see aor_dv10.timer's builders for ``receive_mode``/``start``/``end``."""
        self._chan.write("TR", format_timer_value(timer))

    def read_recording_timer(self) -> RecordingTimer:
        """Raw TR (bare read): the current scheduled recording/alarm timer
        configuration - see write_recording_timer()'s docstring and
        aor_dv10.timer's module docstring for the caveats, especially
        around ``timer_type`` (TY - the AR-DV1 spec never defines what its
        value means, this project passes it through as an opaque int) and
        ``weekdays`` (WE - the spec never states this field's wire
        width)."""
        resp = self._chan.read("TR")
        return parse_timer_response(resp.value or "")

    # -- SD card management ---------------------------------------------
    #
    # Notably SD DIR's per-file line shape (WAV vs. non-WAV), the "SYSYEM"
    # (sic) backup-kind token, and why SD LGR/SD TYP stay `raw`-only (the
    # spec's summary table marks them "No function" here and there is no
    # detailed page anywhere, unlike every other SD command).

    def _sd_action(self, code: str, value: Optional[str] = None) -> str:
        """Sends an SD-card "start something" command (SD REC/PLY/MMW/MMR)
        with RE temporarily forced on, restoring RE afterwards even on error.
        Reason: several of these commands' spec text says a *successful*
        start/stop produces "no response" at all, which would make
        CommandChannel.send() time out, attempt its resync-and-retry-once
        recovery, and raise DV10ResyncNeeded for a successful operation.
        Forcing RE on makes a parseable numeric-prefixed line likely, that
        being the confirmed RE-on behaviour everywhere else. Unconfirmed
        against real hardware."""
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            resp = self._chan.send(code, value)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)
        return _sd_value(resp, code)

    def sd_dir(self, timeout: float = 5.0) -> List[SdCardFile]:
        """Raw SD DIR: list every file on the SD card, one entry per file
        plus a trailing "nnnFILE(S)" count line this method consumes rather
        than returning (``len(result)`` gives the same count).

        Same 21-continuing multi-line shape as read_memory_bank(): forces RE
        on for the read and restores it, even on error - same concurrency
        caveat. Raises DV10ProtocolError for CARDBUSY/NOCARD/FAT12 (see
        _check_sd_error())."""
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            first = self._chan.send("SD DIR")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"SD DIR reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)

        files: List[SdCardFile] = []
        for resp in responses:
            text = _sd_value(resp, "SD DIR")
            if re.match(r"^\d+FILE\(S\)$", text, re.IGNORECASE):
                continue  # trailing file-count summary line, not a file entry
            parts = text.split()
            if len(parts) != 4:
                continue  # not a shape this project recognises - skip rather than crash
            name_ext, second, date_s, time_s = parts
            name, dot, ext = name_ext.rpartition(".")
            if not dot:
                name, ext = name_ext, ""
            entry = SdCardFile(name=name, extension=ext, timestamp=f"{date_s} {time_s}")
            if ext.upper() == "WAV":
                entry.duration = second
            else:
                try:
                    entry.size_bytes = int(second)
                except ValueError:
                    pass
            files.append(entry)
        return files

    def sd_info(self) -> SdCardInfo:
        """Raw SD INF: SD card capacity summary (free space, roughly how
        many hours of recording that represents at the card's current
        settings, and total capacity). Raises DV10ProtocolError for
        CARDBUSY/NOCARD/FAT12."""
        resp = self._chan.read("SD INF")
        text = _sd_value(resp, "SD INF")
        m = re.match(
            r"FREE:\s*(\d+)\s*KB\s*\(\s*([\d.]+)\s*H\s*\)\s*TOTAL:\s*(\d+)\s*KB",
            text,
            re.IGNORECASE,
        )
        if not m:
            raise DV10Error(f"unrecognised SD INF response: {text!r}")
        return SdCardInfo(
            free_kb=int(m.group(1)),
            free_hours=float(m.group(2)),
            total_kb=int(m.group(3)),
        )

    def sd_status(self) -> str:
        """Raw SD PST value ("0".."4") - see SD_CARD_STATUS above for the
        documented meaning of each digit. Unlike sd_dir()/sd_info(), SD PST
        has no documented CARDBUSY/NOCARD/FAT12 textual errors of its own -
        "4" already communicates "not found/unusable" as a status value,
        not an exception."""
        resp = self._chan.read("SD PST")
        text = (resp.value or "").strip()
        if text.upper().startswith("SD PST"):
            text = text[len("SD PST"):].strip()
        return text

    def sd_record_start(self) -> None:
        """Raw SD REC (bare): start recording to the SD card under an
        automatically-generated file name - the spec's own syntax cell for
        SD REC takes no argument at all in this direction. See
        sd_record_stop() for the documented "/" stop convention. Raises
        DV10ProtocolError for CARDBUSY/NOCARD/CARDFULL."""
        self._sd_action("SD REC")

    def sd_record_stop(self) -> None:
        """Raw SD REC with "/" as the file-name argument - the spec's own
        documented stop convention on AR-DV1/DV3 (see sd_record_start()'s
        docstring). NOTE: the AR-DV10 does NOT support this remote stop
        (it wedges the radio) - callers gate on device_family()=="DV10"
        and refuse it there."""
        self._sd_action("SD REC", "/")

    def sd_play(self, name: str) -> None:
        """Raw SD PLY<name>: start playback of ``name`` (no file extension).
        The spec documents "Alphabet (upper case) and numbers"; sent exactly
        as given, not case-folded, since the spec never says lowercase is
        rejected. See sd_play_stop() for the "/" stop convention. Raises
        DV10ProtocolError for CARDBUSY/NOCARD/NOFILE."""
        self._sd_action("SD PLY", name)

    def sd_play_stop(self) -> None:
        """Raw SD PLY with "/" as the file-name argument - the spec's own
        documented stop convention (see sd_play()'s docstring).
        Like SD REC /, the remote "/" stop is only documented for
        AR-DV1/DV3."""
        self._sd_action("SD PLY", "/")


    def sd_backup(self, kind: str) -> None:
        """Raw SD MMW<kind>: back up one category of receiver settings to the
        SD card. ``kind`` must be one of the five documented tokens - see the
        SD_BACKUP_KIND_* constants (SD_BACKUP_KIND_ALL is the literal
        "SYSYEM", a confirmed spec typo, not a mistake introduced here). This
        is the mechanism behind AOR's "serial backup" feature - no
        undocumented MY* command is needed. Raises DV10ProtocolError for
        CARDBUSY/NOCARD/CARDFULL."""
        kind_u = kind.strip().upper()
        if kind_u not in _SD_BACKUP_KINDS:
            raise ValueError(
                f"unknown SD backup kind {kind!r} - expected one of "
                f"{', '.join(sorted(_SD_BACKUP_KINDS))}"
            )
        self._sd_action("SD MMW", kind_u)

    def sd_restore(self, name: str) -> None:
        """Raw SD MMR<name>: restore receiver settings previously backed up
        with sd_backup(). ``name`` is documented as "original file name";
        unlike sd_backup()'s ``kind`` the spec doesn't constrain it to the 5
        known tokens, so it isn't validated (exactly what file name
        sd_backup() produces on the card is unconfirmed). No extension is
        given - "There is no need to specify the file extension" per the
        spec. Raises DV10ProtocolError for CARDBUSY/NOCARD/NOFILE."""
        self._sd_action("SD MMR", name.strip())

    def get_sd_squelch_skip(self) -> str:
        """Raw SD RSQ value ("0"=no skip, "1"=skip [default]) - whether
        squelched (no-signal) audio segments are skipped during SD
        playback."""
        resp = self._chan.read("SD RSQ")
        text = (resp.value or "").strip()
        if text.upper().startswith("SD RSQ"):
            text = text[len("SD RSQ"):].strip()
        return text

    def set_sd_squelch_skip(self, skip: bool) -> None:
        """Raw SD RSQn write - see get_sd_squelch_skip()."""
        self._chan.write("SD RSQ", "1" if skip else "0")

    # -- Frequency scope: FD / GL --------------------------------------
    #
    # IMPORTANT CAVEAT: both FD and GL only succeed while the receiver is
    # "in scope mode" (result code 30, "Not in scope mode", otherwise).
    # Every AR-DV10/AR-DV1 reference available to this project - including
    # the full AR-DV10 operating manual, which never mentions "scope" or
    # "bandscope" at all - was searched for a command or front-panel
    # procedure that enters scope mode, and NONE was found, so these two may
    # be unreachable on the AR-DV10. Implemented exactly as specified for
    # completeness (the simulator exercises the decoding via its test-only
    # ``scope_mode`` toggle); check against real hardware before relying on it.

    def read_scope_data_fast(self) -> List[int]:
        """FD: fast-speed frequency scope data - one line of concatenated
        3-digit dBm chunks (same convention as LM: dbm = -int(chunk)). A
        trailing incomplete chunk is dropped silently, the spec giving no
        guidance. Unlike GL, FD documents no 21 "continue" code, so this is a
        single-line read. See the section comment above for the "no known way
        to enter scope mode" caveat - expect result code 30 on real
        hardware."""
        resp = self._chan.read("FD")
        text = (resp.value or "").strip()
        if text.upper().startswith("FD"):
            text = text[2:].strip()
        n = len(text) - (len(text) % 3)
        return [-int(text[i : i + 3]) for i in range(0, n, 3)]

    def read_scope_data_normal(self, timeout: float = 5.0) -> List[ScopeLine]:
        """GL: normal-speed frequency scope data - one line per scan point,
        "Ffffff.fffffLkkc" (MHz frequency, 2-digit level, 1-digit squelch
        state; see ScopeLine on that level width being narrower than LM/FD's
        3 digits, unconfirmed).

        Same 21-continuing multi-line shape as sd_dir(): forces RE on for the
        read and restores it, even on error. A bare "/" line (seen in the
        spec's own worked examples) is treated as an extra terminator and
        skipped rather than parsed.

        See the section comment above for the "no known way to enter scope
        mode" caveat."""
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            first = self._chan.send("GL")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"GL reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)

        out: List[ScopeLine] = []
        for resp in responses:
            text = (resp.value or "").strip()
            if text.upper().startswith("GL"):
                text = text[2:].strip()
            if not text or text == "/":
                continue
            m = _GL_LINE_RE.match(text)
            if not m:
                continue
            freq_hz = int(round(float(m.group(1)) * 1_000_000))
            out.append(
                ScopeLine(
                    frequency_hz=freq_hz,
                    level_raw=m.group(2),
                    squelch_state=int(m.group(3)),
                )
            )
        return out

    def get_receiver_id(self) -> str:
        """Raw ZI value: a receiver identifier string."""
        return self._chan.read("ZI").value or ""

    def set_receiver_id(self, value: str) -> None:
        self._chan.write("ZI", value.strip())

    def get_write_protect(self) -> str:
        """Raw PT value. NOTE: the manual's PROTECT toggles for individual
        memory channels/banks/search banks (7.1/7.5/7.6/9.1) look to be
        per-record fields written as part of MX/MW/SE, not this top-level PT
        - PT is more likely MENU-CONFIG page 2's "auto-store on shutdown"
        PROTECT flag (11.2 item 7: ON=auto-store OFF). Unconfirmed."""
        return self._chan.read("PT").value or ""

    def set_write_protect(self, on: bool) -> None:
        self._chan.write("PT", "1" if on else "0")

    def reset(self, full: bool = False) -> None:
        """Raw RS: reset to factory defaults. ``full=False`` (system reset)
        keeps memory data; ``full=True`` (full reset) erases everything,
        per manual 11.2 items 4/5. DESTRUCTIVE - the argument encoding
        (guessed "0"/"1") is unconfirmed, so confirm on a unit you don't
        mind losing settings on before relying on this."""
        self._chan.write("RS", "1" if full else "0")

    def move_previous(self) -> None:
        """Raw ZJ: move to the previous frequency/bank/channel, i.e. the
        software equivalent of one counter-clockwise dial-knob click."""
        self._chan.send("ZJ")

    def move_next(self) -> None:
        """Raw ZK: move to the next frequency/bank/channel, i.e. the
        software equivalent of one clockwise dial-knob click."""
        self._chan.send("ZK")

    # -- proposal items 19-28: previously raw-console-only commands ---------
    #
    # All of these are registered in aor_dv10.protocol.commands (so "raw
    # <code> <value>" already reaches them) but had no typed wrapper, and no
    # confirmed field-format detail exists here beyond that registry's
    # one-line description. Rather than inventing digit counts/ranges, every
    # wrapper below is a literal passthrough: reads return the raw string,
    # writes send what they are given (stripped). Where the registry says
    # "ON/OFF" outright (AN, OX, ZS), this project's standard "1"/"0"
    # boolean encoding is used. EXPERIMENTAL: none of this has been
    # exercised against real hardware.

    def get_earphone_antenna(self) -> str:
        """Raw AN value: earphone antenna ON/OFF (FM 64-108MHz only, per
        aor_dv10.protocol.commands' one-line description) - EXPERIMENTAL,
        unconfirmed against real hardware."""
        return self._chan.read("AN").value or ""

    def set_earphone_antenna(self, on: bool) -> None:
        self._chan.write("AN", "1" if on else "0")

    def get_function_code(self) -> str:
        """Raw CT value ("Function") - EXPERIMENTAL: the command registry
        gives no field-format detail beyond that one word, so this is a
        completely literal passthrough - nothing about digit count, range,
        or meaning is assumed."""
        return self._chan.read("CT").value or ""

    def set_function_code(self, value: str) -> None:
        self._chan.write("CT", value.strip())

    def set_digital_data_output(self, value: str) -> None:
        """Raw DJ (write-only, no confirmed read form): "Digital data
        output" per the command registry - EXPERIMENTAL, purpose
        unconfirmed in any documentation available to this project. Sends
        whatever raw string is given; pairs with acquire_digital_data()
        (DK) for reading data back, though whether DJ's write actually
        needs to precede a DK read, and in what shape, is unconfirmed."""
        self._chan.write("DJ", value.strip())

    def acquire_digital_data(self) -> str:
        """Raw DK (read-only per the command registry): "Acquire digital
        data" - EXPERIMENTAL, purpose unconfirmed in any documentation
        available to this project. Returns whatever raw string the device
        sends."""
        return self._chan.read("DK").value or ""

    def get_freq_data_output(self) -> str:
        """Raw LC value: "Frequency data output" - a data-stream toggle
        per the command registry's RW access, EXPERIMENTAL. What toggling
        it on actually does to the wire (an unsolicited stream this
        project has no receive path for, or something else) is
        unconfirmed."""
        return self._chan.read("LC").value or ""

    def set_freq_data_output(self, on: bool) -> None:
        self._chan.write("LC", "1" if on else "0")

    def get_smeter_data_output(self) -> str:
        """Raw LT value: "S-meter data output" - same data-stream-toggle
        shape and caveats as get_freq_data_output() (LC), EXPERIMENTAL."""
        return self._chan.read("LT").value or ""

    def set_smeter_data_output(self, on: bool) -> None:
        self._chan.write("LT", "1" if on else "0")

    def get_monitor_offset(self) -> str:
        """Raw OX value: "Monitor offset" ON/OFF per the command
        registry's own description - EXPERIMENTAL, unconfirmed against
        real hardware, and what it actually does (monitor the configured
        repeater offset frequency? something else?) is not documented
        anywhere available to this project."""
        return self._chan.read("OX").value or ""

    def set_monitor_offset(self, on: bool) -> None:
        self._chan.write("OX", "1" if on else "0")

    def get_ttc_slot_number(self) -> str:
        """Raw TS value: "T-TC mode slot number" (TETRA T-TC) per the
        command registry - EXPERIMENTAL, no confirmed digit count/range,
        literal passthrough."""
        return self._chan.read("TS").value or ""

    def set_ttc_slot_number(self, value: str) -> None:
        self._chan.write("TS", value.strip())

    def get_voice_squelch(self) -> str:
        """Raw VQ value: "Voice squelch", described by the command
        registry as independent of CI/DI (tone/DCS squelch type) -
        EXPERIMENTAL. Not assumed to be a simple on/off despite the name -
        literal passthrough, since neither shape is confirmed."""
        return self._chan.read("VQ").value or ""

    def set_voice_squelch(self, value: str) -> None:
        self._chan.write("VQ", value.strip())

    def get_power_save(self) -> str:
        """Raw ZS value: power save ON/OFF per the command registry -
        EXPERIMENTAL, unconfirmed against real hardware. Pairs with
        get_power_save_silent_time() (ZT)."""
        return self._chan.read("ZS").value or ""

    def set_power_save(self, on: bool) -> None:
        self._chan.write("ZS", "1" if on else "0")

    def get_power_save_silent_time(self) -> str:
        """Raw ZT value: power save's "silent time" setting - EXPERIMENTAL,
        no confirmed digit count/range/units, literal passthrough."""
        return self._chan.read("ZT").value or ""

    def set_power_save_silent_time(self, value: str) -> None:
        self._chan.write("ZT", value.strip())

    def get_receiver_status_output(self) -> str:
        """Raw RT value: "Receiver status output" - a data-stream toggle,
        same shape/caveats as get_freq_data_output() (LC), EXPERIMENTAL.
        Pairs with get_receiver_status() (RX) for reading status back."""
        return self._chan.read("RT").value or ""

    def set_receiver_status_output(self, on: bool) -> None:
        self._chan.write("RT", "1" if on else "0")

    def get_receiver_status(self) -> str:
        """Raw RX (read-only per the command registry): "Receiver status" -
        EXPERIMENTAL, returns whatever raw string the device sends."""
        return self._chan.read("RX").value or ""

    def get_comm_speed(self) -> str:
        """Raw SB value: "Communication speed (baud)" - EXPERIMENTAL,
        literal passthrough, no confirmed value set. DANGEROUS to write
        remotely: if SB really changes the serial link's own baud rate,
        changing it over that link severs the connection this app is using
        and needs physical access to recover - see set_comm_speed()."""
        return self._chan.read("SB").value or ""

    def set_comm_speed(self, value: str) -> None:
        """See get_comm_speed()'s docstring for why this is dangerous to
        call over a remote/serial connection - if SB really does change
        the link's own baud rate, this call's own response may never be
        received at the old rate."""
        self._chan.write("SB", value.strip())

    def register_last_channel(self, completion_timeout: float = 5.0) -> int:
        """Raw MM (write-only, no value): register the currently-tuned
        VFO/bank/channel as the receiver's "last channel memory" (what it
        powers back up on) - see PT's write-protect remark ("MM command will
        also become invalid" when write protect is on).

        Per the AR-DV1 spec, MM is the one command here whose single request
        provokes TWO response lines: an immediate 21 ("registration started")
        then 20 on completion. CommandChannel.send() assumes one line, so a
        naive send("MM") would leave the 20 unread in the transport buffer
        and silently corrupt the NEXT command's response. This sends MM once
        and, if the result is 21, follows with exactly one read_pending()
        bounded by ``completion_timeout``.

        Returns the final result code (20 on success). Raises
        DV10ProtocolError on 30 (write protect - see PT) or 50 (format
        error), DV10ResyncNeeded if a 21 was seen but no completion line
        arrived in time.

        UNCONFIRMED against real hardware: whether the 20 truly arrives
        unprompted (as modelled) or only in answer to re-sending MM, and how
        long registration takes. Because MM has a real side effect this
        deliberately does NOT poll or resend beyond the one follow-up read -
        a speculative resend risks a second, unintended registration. With RE
        off, 20 and 21 are both a bare ack and indistinguishable, so this
        just returns after the one line it gets."""
        first = self._chan.send("MM")
        code = first.result_code
        if code != 21:
            # Either a definitive 20/30/50 (30/50 already raised by send()),
            # or RE is off and there's nothing left to disambiguate.
            return code if code is not None else 20
        second = self._chan.read_pending(timeout=completion_timeout)
        if second is None:
            raise DV10ResyncNeeded(
                f"MM reported 21 (registration started) but no completion "
                f"line arrived within {completion_timeout}s"
            )
        return second.result_code if second.result_code is not None else 20

    def read_vfo_info(self, timeout: float = 5.0) -> List[VfoInfo]:
        """Raw VI: read all three VFOs (A/B/Z) in one call - a 3-line
        multi-response terminated by result code 20, continuation lines
        flagged 21, same shape as MA's bank form and PR (see
        read_memory_bank() for the RE caveat; RE is forced on for the read
        and restored after, even on error).

        The AR-DV1 spec PDF's VI table has a corrupted second column: a
        verbatim copy of the VE entry above it ("VE DLmm FRpp ASn") - a THIRD
        instance of this corruption in the same document, alongside SE's and
        TR's dropped XE sub-field. VI's real shape comes from its "Details"
        prose: "VI VFA RFffff.fffff STggg.gg SHhhh.hh MDdan" (then VFB, VFZ).
        The request is inferred to be bare "VI<CR>" (the summary table lists
        VI read-only) - not confirmed, that table's request cell being
        unusable."""
        prev_re = (self._chan.read("RE").value or "0").strip()
        restore_re = prev_re != "1"
        if restore_re:
            self._chan.write("RE", "1")
        try:
            first = self._chan.send("VI")
            responses = [first]
            while responses[-1].result_code == 21:
                nxt = self._chan.read_pending(timeout=timeout)
                if nxt is None:
                    raise DV10ResyncNeeded(
                        f"VI reported more lines were coming (21) but none "
                        f"arrived within {timeout}s"
                    )
                responses.append(nxt)
        finally:
            if restore_re:
                self._chan.write("RE", prev_re)

        entries: List[VfoInfo] = []
        for resp in responses:
            text_ = (resp.value or "").strip()
            up = text_.upper()
            if up.startswith("VI"):
                text_, up = text_[2:].strip(), up[2:].strip()
            vfo_token, _, rest = text_.partition(" ")
            vfo_token = vfo_token.upper()
            if not (vfo_token.startswith("VF") and len(vfo_token) == 3):
                continue  # not a VFO line we recognise - skip rather than crash
            fields = _parse_composite_fields(rest)
            rf_raw = fields.get("RF")
            st_raw = fields.get("ST")
            sh_raw = fields.get("SH")
            entries.append(
                VfoInfo(
                    vfo=vfo_token[2],
                    frequency_hz=round(float(rf_raw) * 1_000_000) if rf_raw else None,
                    step_hz=round(float(st_raw) * 1000) if st_raw else None,
                    step_adjust_hz=round(float(sh_raw) * 1000) if sh_raw else None,
                    mode=fields.get("MD"),
                )
            )
        return entries

    # -- diagnostics ---------------------------------------------------

    def set_result_code_prefixing(self, on: bool) -> None:
        """Toggle RE: when on, the device prefixes responses with a numeric
        result code (10=unrelated message, 20=OK, +1=more lines follow,
        30=cannot set in current conditions, 40=format error, 50=out of
        range, 60=command does not exist) instead of a bare "?" on failure -
        per the AR-DV3 spec. Confirmed usable on real hardware (an RE-on read
        gave result code 60 for AG)."""
        self._chan.write("RE", "1" if on else "0")

    # -- power -----------------------------------------------------------

    def power_on(self) -> Response:
        """Send ZP (power on/connect). Confirmed on real hardware:
        message-only response ``"AOR AR-DV10"`` (no code echo - same shape
        as WI, see PROTOCOL.md's "WI/ZP message-only responses" note).
        Returns the full Response so callers can see the real reply
        instead of it being silently discarded."""
        return self._chan.send("ZP")

    def power_off(self) -> Response:
        """Send QP (power off/disconnect). Unlike ZP, QP's real-hardware
        response has never been confirmed - PROTOCOL.md documents no reply
        shape, and the simulator's empty ack (grouped with EX) is a guess.
        Returns the full Response so callers can surface whatever the device
        actually sends."""
        return self._chan.send("QP")

    # -- snapshot ----------------------------------------------------------

    def status(self) -> Status:
        def _try(fn):
            try:
                return fn()
            except (DV10Error, ValueError, TypeError):
                # DV10Error: the command failed. ValueError/TypeError: an
                # unexpected value for this field (e.g. reading RF while
                # browsing a memory channel returns an "MX...." record).
                # Either way the field reads as "unknown" instead of taking
                # down the whole status poll.
                return None

        return Status(
            frequency_hz=_try(self.get_frequency_hz),
            mode=_try(self.get_mode),
            squelch=_try(self.get_squelch_mode),
            volume=_try(self.get_volume),
            smeter=_try(self.get_smeter),
            agc_on=_try(self.get_agc),
            mode_info=_try(self.get_mode_info),
            smeter_reading=_try(self.get_smeter_reading),
            agc_speed=_try(self.get_agc_speed),
            attenuator_state=_try(self.get_attenuator_state),
        )

    # -- escape hatch ------------------------------------------------------

    def raw(self, code: str, value: Optional[str] = None):
        """Send any command from the full mnemonic table directly.

        Useful for the many commands that don't yet have a typed helper
        above (memory/scan/search banks, SD-card operations, digital-mode
        parameters, etc.) - see aor_dv10.protocol.commands.COMMANDS for the
        full list. Write attempts (``value`` given) to a command in
        _VFO_MODE_WRITE_CODES get the same VFO-mode hint on a ``?`` error as
        the typed setters above.
        """
        code = code.upper()
        try:
            return self._chan.send(code, value)
        except DV10ProtocolError as exc:
            if (
                value is not None
                and exc.code == "?"
                and exc.hint is None
                and code in _VFO_MODE_WRITE_CODES
            ):
                raise DV10ProtocolError(exc.code, exc.raw_response, hint=_VFO_MODE_HINT) from exc
            raise

    def describe(self, code: str) -> str:
        """Human-readable description of any command code, from the registry."""
        return self._chan.describe(code)

    def describe_result_code(self, code: int) -> str:
        """Human-readable meaning of a numeric RE result code - see
        aor_dv10.protocol.codec.RESULT_CODES and
        DV10ProtocolError.result_code."""
        return describe_result_code(code)

    # -- protocol tracing ---------------------------------------------------
    # Thin passthroughs to CommandChannel's always-on trace ring buffer - see
    # codec.CommandChannel._log_trace() for why every TX/RX line is recorded
    # unconditionally. Every call on this device shares one CommandChannel,
    # so the CLI's "debug" verb and the web panel's debug forwarding see the
    # same trace whichever interface issued a given command.

    def set_trace_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        """Register (``None`` to unregister) a callback that receives every
        raw TX/RX line live, formatted as
        ``"[HH:MM:SS.mmm] TX|RX b'...'"`` (the ``repr()`` of the exact bytes
        sent/received - CR, stray spaces, and any non-ASCII byte a real
        unit sends back are all visible, not silently stripped)."""
        self._chan.set_trace_sink(sink)

    def trace_lines(self, n: Optional[int] = None) -> List[str]:
        """The most recent ``n`` trace lines (all recorded ones, oldest
        first, if ``n`` is None) - available even if no sink was ever
        registered, since every line is always recorded."""
        return self._chan.trace_lines(n)

    def save_trace(self, path: str, n: Optional[int] = None) -> int:
        """Write trace_lines(n) to ``path``, one per line; returns the
        count written. Meant for "reproduce the issue, then hand me the
        file" - see the CLI's "debug save <path>" verb."""
        lines = self.trace_lines(n)
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return len(lines)

    # -- Smaller typed commands: KL/IF/DL/FR/RN ------------------------------
    # KL (key backlight color), IF (per-mode IF bandwidth), DL/FR (the
    # standalone delay/free-time commands - distinct from the same-named
    # sub-fields inside the SG/MG composites), and RN (AR-DV1 serial number,
    # with an access correction - see get_serial_number()).

    def get_key_backlight_color(self) -> str:
        """Raw KL value (0-7) - see KEY_BACKLIGHT_COLORS for the
        spec's per-value color labels (including the "MAGENDA" [sic]
        spec typo, kept literal)."""
        return (self._chan.read("KL").value or "").strip()

    def set_key_backlight_color(self, n) -> None:
        """Raw KLn write (0-7) - see get_key_backlight_color()."""
        self._chan.write("KL", str(int(n)))

    def get_if_bandwidth(self) -> str:
        """Raw IF value - a bare digit string whose meaning depends on the
        active demodulation mode (see IF_BANDWIDTH_HZ). Kept as a string,
        not int(): the spec documents the response as "IFn, IFnn" - possibly
        2 digits - so always parsing exactly 1 digit risks mis-parsing a real
        reply. Result code 30 ("Invalid decode mode") is documented, implying
        some demodulation mode has no IF-bandwidth concept - unconfirmed
        which."""
        return (self._chan.read("IF").value or "").strip()

    def set_if_bandwidth(self, n) -> None:
        """Raw IFn write - see get_if_bandwidth()."""
        self._chan.write("IF", str(n))

    def get_if_bandwidth_options_hz(self) -> dict:
        """The IF bandwidth choices - ``{raw_digit: hz}`` - valid for the
        analog demodulation type MD currently has selected
        (``get_mode_info().analog_select``), from IF_BANDWIDTH_HZ. Empty if
        that mode isn't recognised, has no table, OR a digital mode is
        selected, so a UI that just asks "any choices at all?" (the web
        panel's bandwidth <select>) behaves correctly in every case.

        The DV10's IF selector is one register shared across every
        demodulation type (see set_mode()), so this is "what makes sense to
        offer right now", not "what IF itself offers" - e.g. raw digit "3"
        means 15 kHz in FM but 3.8 kHz in AM.

        Digital modes: confirmed against real hardware (see IF_BANDWIDTH_HZ)
        that IF is not user-settable while digital_select is anything but
        "Digital off" - the receiver auto-selects the filter and rejects a
        manual write with result code 30. Returns {} rather than the manual's
        digital table (6/15/30 kHz): no live test has ever gotten a manual
        write to succeed while digital is active."""
        info = self.get_mode_info()
        if info.digital_select and info.digital_select != "Digital off":
            return {}
        demod = info.analog_select
        return dict(IF_BANDWIDTH_HZ.get(demod, {})) if demod else {}

    def get_if_bandwidth_hz(self) -> Optional[int]:
        """Currently selected IF bandwidth in Hz, decoded against the
        currently active analog mode's table
        (``get_if_bandwidth_options_hz()``). ``None`` if the raw IF digit
        isn't one of that table's known choices - e.g. a mode with no
        known table, or a raw value set directly via
        ``set_if_bandwidth()`` that IF_BANDWIDTH_HZ doesn't list."""
        raw = self.get_if_bandwidth()
        return self.get_if_bandwidth_options_hz().get(raw)

    def set_if_bandwidth_hz(self, hz) -> None:
        """Select the IF bandwidth by its Hz value instead of the raw
        digit ``set_if_bandwidth()`` takes - looks up which digit means
        ``hz`` for the CURRENTLY ACTIVE analog mode
        (``get_if_bandwidth_options_hz()``) and writes that digit.
        Raises ``ValueError`` up front (no wire write at all) if ``hz``
        isn't one of that mode's valid choices, so a caller/UI can't
        silently ask for a bandwidth value that's actually meaningless
        for the current mode - e.g. FM has no 3800 Hz option even though
        AM does."""
        options = self.get_if_bandwidth_options_hz()
        hz = int(hz)
        for digit, value in options.items():
            if value == hz:
                self.set_if_bandwidth(digit)
                return
        info = self.get_mode_info()
        if info.digital_select and info.digital_select != "Digital off":
            raise ValueError(
                f"IF bandwidth is not user-settable while a digital mode "
                f"is selected ({info.digital_select}) - confirmed against "
                f"real hardware: the receiver auto-selects the filter and "
                f"rejects any manual IF write with result code 30 while "
                f"digital reception is active"
            )
        demod = info.analog_select or "the current mode"
        choices = ", ".join(str(v) for v in sorted(options.values())) or "none known"
        raise ValueError(
            f"{hz} Hz is not a valid IF bandwidth for {demod} - choices: {choices}"
        )

    def get_delay_time_ds(self) -> int:
        """Raw DL value in deciseconds (0.1s ticks; 000-099, or the special
        value 100 meaning "unlimited" per the spec, returned as-is). The
        standalone DL command - distinct from the DL sub-field inside the
        SG/MG scan-group composites."""
        return int((self._chan.read("DL").value or "0").strip())

    def set_delay_time_ds(self, deciseconds) -> None:
        """Raw DLnnn write (000-099, or 100 for unlimited) - see
        get_delay_time_ds()."""
        self._chan.write("DL", f"{int(deciseconds):03d}")

    def get_free_time_s(self) -> int:
        """Raw FR value in seconds (00-60; 0 means OFF). The standalone FR
        command - distinct from the FR sub-field inside the SG/MG
        scan-group composites."""
        return int((self._chan.read("FR").value or "0").strip())

    def set_free_time_s(self, seconds) -> None:
        """Raw FRnn write - see get_free_time_s()."""
        self._chan.write("FR", f"{int(seconds):02d}")

    def get_serial_number(self) -> str:
        """Raw RN value: an AR-DV1 serial-number string (spec example
        "RN0952zzzz" - an 8-character body after the code echo; the
        characters' meaning is undocumented, so it is returned opaque, same
        convention as get_receiver_id()/ZI).

        CORRECTED: the AR-DV1 summary table lists RN as R/W, but its own
        detailed section documents only a read ("To read: RN<CR>",
        "Response: RN0952zzzz") - no write syntax, none of the format/range
        result codes every writable command lists. Implemented read-only,
        trusting the detailed section over the summary table (same precedent
        as SE's access correction).

        "SN" ("Output serial number") was deliberately NOT given a typed
        method: no detailed section in any available document, and its
        summary-table row lacks even a page reference. It stays `raw`-only."""
        return (self._chan.read("RN").value or "").strip()
