
from __future__ import annotations

from typing import Callable, List, Optional

from .device_types import (
    IF_BANDWIDTH_HZ,
    KEY_BACKLIGHT_COLORS,
    Status,
    _VFO_MODE_HINT,
    _VFO_MODE_WRITE_CODES,
)
from .protocol.codec import DV10Error, DV10ProtocolError, Response, describe_result_code


class SystemMixin:

    def set_result_code_prefixing(self, on: bool) -> None:
        self._chan.write("RE", "1" if on else "0")


    def power_on(self) -> Response:
        return self._chan.send("ZP", retry=False)

    def power_off(self) -> Response:
        return self._chan.send("QP", retry=False)


    def status(self) -> Status:
        def _try(fn):
            try:
                return fn()
            except (DV10Error, ValueError, TypeError):
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


    def raw(self, code: str, value: Optional[str] = None):
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
        return self._chan.describe(code)

    def describe_result_code(self, code: int) -> str:
        return describe_result_code(code)


    def set_trace_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        self._chan.set_trace_sink(sink)

    def trace_lines(self, n: Optional[int] = None) -> List[str]:
        return self._chan.trace_lines(n)

    def save_trace(self, path: str, n: Optional[int] = None) -> int:
        lines = self.trace_lines(n)
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        return len(lines)


    def get_key_backlight_color(self) -> str:
        return (self._chan.read("KL").value or "").strip()

    def set_key_backlight_color(self, n) -> None:
        self._chan.write("KL", str(int(n)))

    def get_if_bandwidth(self) -> str:
        return (self._chan.read("IF").value or "").strip()

    def set_if_bandwidth(self, n) -> None:
        self._chan.write("IF", str(n))

    def get_if_bandwidth_options_hz(self) -> dict:
        info = self.get_mode_info()
        if info.digital_select and info.digital_select != "Digital off":
            return {}
        demod = info.analog_select
        return dict(IF_BANDWIDTH_HZ.get(demod, {})) if demod else {}

    def get_if_bandwidth_hz(self) -> Optional[int]:
        raw = self.get_if_bandwidth()
        return self.get_if_bandwidth_options_hz().get(raw)

    def set_if_bandwidth_hz(self, hz) -> None:
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
        return int((self._chan.read("DL").value or "0").strip())

    def set_delay_time_ds(self, deciseconds) -> None:
        self._chan.write("DL", f"{int(deciseconds):03d}")

    def get_free_time_s(self) -> int:
        return int((self._chan.read("FR").value or "0").strip())

    def set_free_time_s(self, seconds) -> None:
        self._chan.write("FR", f"{int(seconds):02d}")

    def get_serial_number(self) -> str:
        return (self._chan.read("RN").value or "").strip()
