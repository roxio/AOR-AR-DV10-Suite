
from __future__ import annotations

from typing import List, Optional

from .device_types import VfoInfo, _parse_composite_fields
from .protocol.codec import DV10ResyncNeeded


class ExtraMixin:

    def get_earphone_antenna(self) -> str:
        return self._chan.read("AN").value or ""

    def set_earphone_antenna(self, on: bool) -> None:
        self._chan.write("AN", "1" if on else "0")

    def get_function_code(self) -> str:
        return self._chan.read("CT").value or ""

    def set_function_code(self, value: str) -> None:
        self._chan.write("CT", value.strip())

    def set_digital_data_output(self, value: str) -> None:
        self._chan.write("DJ", value.strip())

    def acquire_digital_data(self) -> str:
        return self._chan.read("DK").value or ""

    def get_freq_data_output(self) -> str:
        return self._chan.read("LC").value or ""

    def set_freq_data_output(self, on: bool) -> None:
        self._chan.write("LC", "1" if on else "0")

    def get_smeter_data_output(self) -> str:
        return self._chan.read("LT").value or ""

    def set_smeter_data_output(self, on: bool) -> None:
        self._chan.write("LT", "1" if on else "0")

    def get_monitor_offset(self) -> str:
        return self._chan.read("OX").value or ""

    def set_monitor_offset(self, on: bool) -> None:
        self._chan.write("OX", "1" if on else "0")

    def get_ttc_slot_number(self) -> str:
        return self._chan.read("TS").value or ""

    def set_ttc_slot_number(self, value: str) -> None:
        self._chan.write("TS", value.strip())

    def get_voice_squelch(self) -> str:
        return self._chan.read("VQ").value or ""

    def set_voice_squelch(self, value: str) -> None:
        self._chan.write("VQ", value.strip())

    def get_power_save(self) -> str:
        return self._chan.read("ZS").value or ""

    def set_power_save(self, on: bool) -> None:
        self._chan.write("ZS", "1" if on else "0")

    def get_power_save_silent_time(self) -> str:
        return self._chan.read("ZT").value or ""

    def set_power_save_silent_time(self, value: str) -> None:
        self._chan.write("ZT", value.strip())

    def get_receiver_status_output(self) -> str:
        return self._chan.read("RT").value or ""

    def set_receiver_status_output(self, on: bool) -> None:
        self._chan.write("RT", "1" if on else "0")

    def get_receiver_status(self) -> str:
        return self._chan.read("RX").value or ""

    def get_comm_speed(self) -> str:
        return self._chan.read("SB").value or ""

    def set_comm_speed(self, value: str) -> None:
        self._chan.write("SB", value.strip())

    def register_last_channel(self, completion_timeout: float = 5.0) -> int:
        first = self._chan.send("MM", retry=False)
        code = first.result_code
        if code != 21:
            return code if code is not None else 20
        second = self._chan.read_pending(timeout=completion_timeout)
        if second is None:
            raise DV10ResyncNeeded(
                f"MM reported 21 (registration started) but no completion "
                f"line arrived within {completion_timeout}s"
            )
        return second.result_code if second.result_code is not None else 20

    def read_vfo_info(self, timeout: float = 5.0) -> List[VfoInfo]:
        with self._forced_re():
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

        entries: List[VfoInfo] = []
        for resp in responses:
            text_ = (resp.value or "").strip()
            up = text_.upper()
            if up.startswith("VI"):
                text_, up = text_[2:].strip(), up[2:].strip()
            vfo_token, _, rest = text_.partition(" ")
            vfo_token = vfo_token.upper()
            if not (vfo_token.startswith("VF") and len(vfo_token) == 3):
                continue
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

