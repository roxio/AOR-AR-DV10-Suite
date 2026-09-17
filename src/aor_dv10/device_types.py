
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .protocol.parsing import parse_composite_fields


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

ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY = {
    "DV10": {"2", "3"},
}


def _validate_mode_pair(mode: str) -> str:
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


ATTENUATOR_STATES = {
    "0": "ATT OFF",
    "1": "ATT ON",
    "2": "10dB ATT",
}

AGC_SPEEDS = {
    "0": "Fast",
    "1": "Mid",
    "2": "Slow",
    "3": "RF-G",
}

KEY_BACKLIGHT_COLORS = {
    "0": "OFF",
    "1": "BLUE",
    "2": "RED",
    "3": "MAGENDA",
    "4": "GREEN",
    "5": "CYAN",
    "6": "YELLOW",
    "7": "ORANGE",
}

IF_BANDWIDTH_HZ = {
    "FM": {"1": 100_000, "2": 30_000, "3": 15_000, "4": 6_000},
    "AM": {"0": 15_000, "1": 8_000, "2": 5_500, "3": 3_800},
    "SAH": {"0": 5_500, "1": 3_800},
    "SAL": {"0": 5_500, "1": 3_800},
    "USB": {"0": 2_600, "1": 1_800},
    "LSB": {"0": 2_600, "1": 1_800},
    "CW": {"0": 500, "1": 200},
}

SQUELCH_MODES = {
    "0": "Auto",
    "1": "Noise",
    "2": "Level",
}

TONE_SQUELCH_TYPES = {
    "0": "OFF",
    "1": "CTCSS",
    "2": "Reverse Tone",
}

SQUELCH_STATES = {
    0: "closed",
    1: "open (noise/level squelch)",
    2: "open (tone/DCS/reverse squelch)",
    3: "detecting digital mode",
}



BACKLIGHT_MODES = {"0": "Off (default)", "1": "Continuous", "2": "Auto"}

CTCSS_TONES_HZ = [
    "60.0", "67.0", "69.3", "71.9", "74.4", "77.0", "79.7", "82.5", "85.4", "88.5",
    "91.5", "94.8", "97.4", "100.0", "103.5", "107.2", "110.9", "114.8", "118.8",
    "120.0", "123.0", "127.3", "131.8", "136.5", "141.3", "146.2", "151.4", "156.7",
    "159.8", "162.2", "165.5", "167.9", "171.3", "173.8", "177.3", "179.9", "183.5",
    "186.2", "189.9", "192.8", "196.6", "199.5", "203.5", "206.5", "210.7", "218.1",
    "225.7", "229.1", "233.6", "241.8", "250.3", "254.1",
]


def _decode_cn(raw: str) -> str:
    raw = raw.strip()
    if len(raw) == 4 and raw.startswith("99"):
        raw = raw[2:]
    if raw in ("", "00"):
        return ""
    if raw == "99":
        return "SRCH"
    try:
        index = int(raw)
    except ValueError:
        return raw
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


@dataclass
class ModeInfo:

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
    return parse_composite_fields(text, tag_field=tag_field)


@dataclass
class MemoryChannelInfo:

    bank: int
    channel: int
    registered: bool
    pass_channel: bool = False
    frequency_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None
    write_protect: bool = False
    tag: str = ""


@dataclass
class MemoryBankInfo:

    bank: int
    channel_count: Optional[int] = None
    protect: bool = False
    tag: str = ""


def _format_search_freq_mhz(hz: int) -> str:
    return f"{hz / 1_000_000:09.4f}"


def _format_rf_freq_mhz(hz: int) -> str:
    return f"{hz / 1_000_000:010.5f}"


def _format_bank_link(banks: Optional[List[int]]) -> str:
    if not banks:
        return "99"
    return "".join(f"{int(b):02d}" for b in banks)


def _parse_bank_link(raw: str) -> List[int]:
    raw = raw.strip()
    if not raw or raw == "99":
        return []
    if len(raw) % 2 != 0 or not raw.isdigit():
        return []
    return [int(raw[i : i + 2]) for i in range(0, len(raw), 2)]


@dataclass
class SearchBankInfo:

    bank: int
    registered: bool
    lower_limit_hz: Optional[int] = None
    upper_limit_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None
    write_protect: bool = False
    tag: str = ""


@dataclass
class ScanGroupInfo:

    group: int
    delay_ds: Optional[int] = None
    free_time_s: Optional[int] = None
    auto_store: Optional[bool] = None
    bank_link: tuple = ()


@dataclass
class PassFrequencyEntry:

    index: int
    frequency_hz: Optional[int]
    bank: Optional[int] = None


@dataclass
class VfoInfo:

    vfo: str
    frequency_hz: Optional[int] = None
    step_hz: Optional[int] = None
    step_adjust_hz: Optional[int] = None
    mode: Optional[str] = None


@dataclass
class VfoSearchSettings:

    delay_ds: Optional[int] = None
    free_time_s: Optional[int] = None
    auto_store: Optional[bool] = None


@dataclass
class SMeterReading:

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
    mode_info: Optional[ModeInfo] = None
    smeter_reading: Optional[SMeterReading] = None
    agc_speed: Optional[str] = None
    attenuator_state: Optional[str] = None


_VFO_MODE_WRITE_CODES = {"RF", "AC", "SQ", "AT", "RG", "ST", "SH"}

_VFO_MODE_HINT = (
    "the receiver needs to be in VFO mode (not browsing a memory channel) "
    "for this to work - confirmed against real hardware"
)


