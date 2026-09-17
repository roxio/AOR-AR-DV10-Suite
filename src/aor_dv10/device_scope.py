
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .protocol.codec import DV10ResyncNeeded


@dataclass
class ScopeLine:

    frequency_hz: int
    level_raw: str
    squelch_state: int

    @property
    def squelch_open(self) -> bool:
        return self.squelch_state != 0


_GL_LINE_RE = re.compile(r"^F(\d{4,5}\.\d{5})L(\d{2})(\d)$")


class ScopeMixin:

    def read_scope_data_fast(self) -> List[int]:
        resp = self._chan.read("FD")
        text = (resp.value or "").strip()
        if text.upper().startswith("FD"):
            text = text[2:].strip()
        n = len(text) - (len(text) % 3)
        return [-int(text[i : i + 3]) for i in range(0, n, 3)]

    def read_scope_data_normal(self, timeout: float = 5.0) -> List[ScopeLine]:
        with self._forced_re():
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
