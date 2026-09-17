
from __future__ import annotations


class TuningMixin:

    def get_frequency_step_hz(self) -> int | None:
        raw = self._chan.read("ST").value
        return round(float(raw) * 1000) if raw else None

    def set_frequency_step_hz(self, hz: int) -> None:
        self._write_with_hint("ST", f"{float(hz) / 1000:06.2f}")

    def get_step_adjust_hz(self) -> int | None:
        raw = self._chan.read("SH").value
        return round(float(raw) * 1000) if raw else None

    def set_step_adjust_hz(self, hz: int) -> None:
        self._write_with_hint("SH", f"{float(hz) / 1000:06.2f}")
