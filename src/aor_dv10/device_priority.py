
from __future__ import annotations


class PriorityMixin:

    def get_priority_enabled(self) -> str:
        return self._chan.read("PO").value or ""

    def set_priority_enabled(self, on: bool) -> None:
        self._chan.write("PO", "1" if on else "0")

    def get_priority_channel(self) -> str:
        raw = (self._chan.read("PP").value or "").strip()
        if len(raw) == 4 and raw.isdigit():
            return f"{raw[:2]}-{raw[2:]}"
        return raw

    def set_priority_channel(self, bank: int, channel: int) -> None:
        self._chan.write("PP", f"{int(bank):02d}{int(channel):02d}")

    def get_priority_interval(self) -> str:
        return self._chan.read("TI").value or ""

    def set_priority_interval(self, seconds: int) -> None:
        self._chan.write("TI", f"{int(seconds):02d}")
