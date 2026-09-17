
from __future__ import annotations

from .timer import RecordingTimer, format_timer_value, parse_timer_response


class SettingsMixin:


    def get_volume_limit(self) -> str:
        return self._chan.read("AV").value or ""

    def set_volume_limit(self, level: int) -> None:
        self._write_with_hint("AV", f"{int(level):02d}")

    def get_digital_gain(self) -> str:
        return self._chan.read("DA").value or ""

    def set_digital_gain(self, gain: float) -> None:
        self._chan.write("DA", f"{float(gain):05.2f}")

    def get_manual_gain(self) -> str:
        return self._chan.read("RG").value or ""

    def set_manual_gain(self, level: int) -> None:
        self._write_with_hint("RG", f"{int(level):03d}")

    def get_lcd_contrast(self) -> str:
        return self._chan.read("LN").value or ""

    def set_lcd_contrast(self, level: int) -> None:
        self._chan.write("LN", f"{int(level):02d}")

    def get_backlight_mode(self) -> str:
        return self._chan.read("LB").value or ""

    def set_backlight_mode(self, mode: str) -> None:
        self._chan.write("LB", mode.strip())


    def get_sleep_timer(self) -> str:
        return self._chan.read("SP").value or ""

    def set_sleep_timer(self, value: str) -> None:
        self._chan.write("SP", value.strip())

    def get_clock(self) -> str:
        return self._chan.read("DT").value or ""

    def set_clock(self, yy: int, mm: int, dd: int, hh: int, minute: int) -> None:
        self._chan.write("DT", f"{yy:02d}{mm:02d}{dd:02d}{hh:02d}{minute:02d}")

    def write_recording_timer(self, timer: RecordingTimer) -> None:
        self._chan.write("TR", format_timer_value(timer))

    def read_recording_timer(self) -> RecordingTimer:
        resp = self._chan.read("TR")
        return parse_timer_response(resp.value or "")

    def get_receiver_id(self) -> str:
        return self._chan.read("ZI").value or ""

    def set_receiver_id(self, value: str) -> None:
        self._chan.write("ZI", value.strip())

    def get_write_protect(self) -> str:
        return self._chan.read("PT").value or ""

    def set_write_protect(self, on: bool) -> None:
        self._chan.write("PT", "1" if on else "0")

    def reset(self, full: bool = False) -> None:
        self._chan.write("RS", "1" if full else "0")

    def move_previous(self) -> None:
        self._chan.send("ZJ", retry=False)

    def move_next(self) -> None:
        self._chan.send("ZK", retry=False)
