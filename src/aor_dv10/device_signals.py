
from __future__ import annotations

from typing import Optional

from .device_types import (
    AGC_SPEEDS,
    ATTENUATOR_STATES,
    CTCSS_TONES_HZ,
    DCS_CODES,
    SQUELCH_MODES,
    SQUELCH_STATES,
    TONE_SQUELCH_TYPES,
    ModeInfo,
    SMeterReading,
    _decode_cn,
)
from .protocol.codec import DV10Error


class SignalsMixin:

    def get_squelch_mode(self) -> str:
        return self._chan.read("SQ").value or ""

    def set_squelch_mode(self, mode: str) -> None:
        self._write_with_hint("SQ", str(mode))

    get_squelch = get_squelch_mode
    set_squelch = set_squelch_mode

    def get_squelch_level(self) -> str:
        return self._chan.read("LQ").value or ""

    def set_squelch_level(self, level: str) -> None:
        self._chan.write("LQ", str(level))

    def get_noise_squelch_level(self) -> str:
        return self._chan.read("NQ").value or ""

    def set_noise_squelch_level(self, level: str) -> None:
        self._chan.write("NQ", str(level))

    def get_volume(self) -> str:
        return self._chan.read("AG").value or ""

    def set_volume(self, level: str) -> None:
        self._chan.write("AG", str(level))

    def get_smeter(self) -> str:
        return self._chan.read("LM").value or ""

    def get_smeter_reading(self) -> SMeterReading:
        raw = self.get_smeter()
        dbm: Optional[int] = None
        state: Optional[int] = None
        if len(raw) >= 4 and raw[:3].isdigit() and raw[3].isdigit():
            dbm = -int(raw[:3])
            state = int(raw[3])
        return SMeterReading(raw=raw, dbm=dbm, squelch_state=state)

    def get_agc_speed(self) -> str:
        return self._chan.read("AC").value or ""

    def set_agc_speed(self, speed: str) -> None:
        self._write_with_hint("AC", str(speed))

    def get_agc(self) -> bool:
        return (self._chan.read("AC").value or "0") not in ("0", "")

    def set_agc(self, on: bool) -> None:
        self._write_with_hint("AC", "1" if on else "0")

    def get_beep_level(self) -> str:
        return self._chan.read("BP").value or ""

    def set_beep_level(self, level: int) -> None:
        self._chan.write("BP", f"{int(level):d}")

    def set_beep(self, on: bool) -> None:
        self.set_beep_level(2 if on else 0)

    def get_attenuator_state(self) -> str:
        return self._chan.read("AT").value or ""

    def set_attenuator_state(self, state: str) -> None:
        self._write_with_hint("AT", str(state))

    def set_attenuator(self, on: bool) -> None:
        self._write_with_hint("AT", "1" if on else "0")


    def get_tone_squelch_enabled(self) -> str:
        return self._chan.read("CI").value or ""

    def set_tone_squelch_enabled(self, on: bool) -> None:
        self._write_with_hint("CI", "1" if on else "0")

    def get_squelch_tone_type(self) -> str:
        return (self._chan.read("CI").value or "").strip()

    def set_squelch_tone_type(self, value: str) -> None:
        value = str(value).strip()
        if value not in TONE_SQUELCH_TYPES:
            raise ValueError(
                f"unknown squelch tone type {value!r} - expected one of "
                f"{', '.join(sorted(TONE_SQUELCH_TYPES))} ({', '.join(TONE_SQUELCH_TYPES.values())})"
            )
        self._write_with_hint("CI", value)

    def get_tone_squelch_freq(self) -> str:
        return _decode_cn(self._chan.read("CN").value or "")

    def set_tone_squelch_freq(self, tone: str) -> None:
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
        return self._chan.read("DI").value or ""

    def set_dcs_enabled(self, on: bool) -> None:
        self._write_with_hint("DI", "1" if on else "0")

    def get_dcs_code(self) -> str:
        raw = (self._chan.read("DS").value or "").strip()
        if raw == "999":
            return "SRCH"
        if raw in ("", "000"):
            return ""
        return raw

    def set_dcs_code(self, code: str) -> None:
        code = code.strip().upper()
        if code == "SRCH":
            self._write_with_hint("DS", "999")
            return
        if code == "OFF":
            raise ValueError(
                'DS has no "OFF" wire value - use set_dcs_enabled(False) instead'
            )
        self._write_with_hint("DS", code)


    def get_dmr_color_code(self) -> str:
        return self._chan.read("CC").value or ""

    def set_dmr_color_code(self, code: int) -> None:
        self._chan.write("CC", f"{int(code):02d}")

    def get_dmr_mute_by_color_code(self) -> str:
        return self._chan.read("CM").value or ""

    def set_dmr_mute_by_color_code(self, on: bool) -> None:
        self._chan.write("CM", "1" if on else "0")

    def get_dmr_slot(self) -> str:
        return self._chan.read("OT").value or ""

    def set_dmr_slot(self, slot: str) -> None:
        self._chan.write("OT", slot.strip())

    def get_p25_nac(self) -> str:
        return self._chan.read("PC").value or ""

    def set_p25_nac(self, nac: str) -> None:
        self._chan.write("PC", nac.strip().upper().zfill(3))

    def get_p25_mute_by_nac(self) -> str:
        return self._chan.read("PM").value or ""

    def set_p25_mute_by_nac(self, on: bool) -> None:
        self._chan.write("PM", "1" if on else "0")

    def get_nxdn_ran(self) -> str:
        return self._chan.read("NC").value or ""

    def set_nxdn_ran(self, ran: int) -> None:
        self._chan.write("NC", f"{int(ran):02d}")

    def get_nxdn_mute_by_ran(self) -> str:
        return self._chan.read("NM").value or ""

    def set_nxdn_mute_by_ran(self, on: bool) -> None:
        self._chan.write("NM", "1" if on else "0")

    def get_dcr_descramble_code(self) -> str:
        return self._chan.read("DC").value or ""

    def set_dcr_descramble_code(self, code: int) -> None:
        self._chan.write("DC", f"{int(code):05d}")


    def get_voice_descrambler_enabled(self) -> str:
        return self._chan.read("SI").value or ""

    def set_voice_descrambler_enabled(self, on: bool) -> None:
        self._write_with_hint("SI", "1" if on else "0")

    def get_voice_descrambler_freq(self) -> str:
        return self._chan.read("SC").value or ""


    def get_offset_slot(self) -> str:
        return self._chan.read("OF").value or ""

    def set_offset_slot(self, slot: int, direction: str = "+") -> None:
        slot = int(slot)
        if slot == 0:
            self._write_with_hint("OF", "00")
            return
        direction = direction.strip()
        if direction not in ("+", "-"):
            raise ValueError(f'direction must be "+" or "-", got {direction!r}')
        self._write_with_hint("OF", f"{direction}{slot:02d}")

    def get_offset_freq(self, slot: int) -> str:
        raw = (self._chan.read(f"OL{int(slot):02d}").value or "").strip()
        if raw.upper().startswith("RF"):
            raw = raw[2:]
        return raw

    def set_offset_freq(self, slot: int, mhz: float) -> None:
        slot = int(slot)
        mhz = float(mhz)
        if mhz < 0:
            raise ValueError(
                "OL's frequency field is unsigned - use set_offset_slot(slot, direction) "
                "for the sign, not a negative mhz here"
            )
        self._write_with_hint("OL", f"{slot:02d} RF{mhz:010.5f}")

