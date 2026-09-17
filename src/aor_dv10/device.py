
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, List, Optional

from .constants import CHANNELS_PER_BANK, TAG_WIDTH
from .device_scope import ScopeLine, ScopeMixin
from .device_sd import (
    SD_BACKUP_KIND_ALL,
    SD_BACKUP_KIND_MEMORY_CHANNEL,
    SD_BACKUP_KIND_SCAN_GROUP,
    SD_BACKUP_KIND_SEARCH_BANK,
    SD_BACKUP_KIND_SEARCH_GROUP,
    SD_CARD_STATUS,
    SdCardFile,
    SdCardInfo,
    SdMixin,
)
from .device_priority import PriorityMixin
from .device_settings import SettingsMixin
from .device_tuning import TuningMixin
from .protocol.codec import (
    CommandChannel,
    DV10Error,
    DV10ProtocolError,
    DV10ResyncNeeded,
    Response,
    describe_result_code,
)
from .transport.base import Transport
from .transport.serial_transport import SerialTransport, find_dv10_port
from .transport.simulator import SimulatorTransport


from .device_types import (
    DIGITAL_MODES,
    ANALOG_MODES,
    ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY,
    _validate_mode_pair as _validate_mode_pair,
    _mode_write_value as _mode_write_value,
    ATTENUATOR_STATES,
    AGC_SPEEDS,
    KEY_BACKLIGHT_COLORS,
    IF_BANDWIDTH_HZ,
    SQUELCH_MODES,
    TONE_SQUELCH_TYPES,
    SQUELCH_STATES,
    BACKLIGHT_MODES,
    CTCSS_TONES_HZ,
    _decode_cn as _decode_cn,
    DCS_CODES,
    ModeInfo,
    _parse_composite_fields as _parse_composite_fields,
    MemoryChannelInfo,
    MemoryBankInfo,
    _format_search_freq_mhz as _format_search_freq_mhz,
    _format_rf_freq_mhz as _format_rf_freq_mhz,
    _format_bank_link as _format_bank_link,
    _parse_bank_link as _parse_bank_link,
    SearchBankInfo,
    ScanGroupInfo,
    PassFrequencyEntry,
    VfoInfo,
    VfoSearchSettings,
    SMeterReading,
    Status,
    _VFO_MODE_WRITE_CODES as _VFO_MODE_WRITE_CODES,
    _VFO_MODE_HINT as _VFO_MODE_HINT,
)

from .device_system import SystemMixin

from .device_signals import SignalsMixin

from .device_memory import MemoryMixin

from .device_extra import ExtraMixin

class DV10Device(ScopeMixin, SdMixin, SettingsMixin, TuningMixin, PriorityMixin, SystemMixin, SignalsMixin, MemoryMixin, ExtraMixin):

    def __init__(self, transport: Transport, timeout: float = 1.5):
        self._transport = transport
        self._chan = CommandChannel(transport, timeout=timeout)
        self._connected = False
        self._digital_active = False
        self._pre_digital_if_bandwidth: Optional[str] = None
        self._model_cache: Optional[str] = None
        self._firmware_cache: Optional[str] = None


    @classmethod
    def open_serial(cls, port: Optional[str] = None, baudrate: int = 115200) -> "DV10Device":
        return cls(SerialTransport(port=port, baudrate=baudrate))

    @classmethod
    def open_simulator(cls) -> "DV10Device":
        return cls(SimulatorTransport())

    def connect(self) -> None:
        self._transport.open()
        self._connected = True

    def disconnect(self) -> None:
        if self._connected:
            try:
                self._chan.send("EX", retry=False)
            except DV10Error:
                pass
        self._transport.close()
        self._connected = False
        self._model_cache = None
        self._firmware_cache = None

    def reconnect(self) -> None:
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001 - closing a dead handle is best-effort
            pass
        self._connected = False
        self._model_cache = None
        self._firmware_cache = None
        self.connect()

    @property
    def connected(self) -> bool:
        return self._connected

    def _write_with_hint(self, code: str, value: str):
        try:
            return self._chan.write(code, value)
        except DV10ProtocolError as exc:
            if exc.code == "?" and exc.hint is None and code.upper() in _VFO_MODE_WRITE_CODES:
                raise DV10ProtocolError(exc.code, exc.raw_response, hint=_VFO_MODE_HINT) from exc
            raise

    @contextmanager
    def _forced_re(self):
        with self._chan.transaction():
            prev_re = (self._chan.read("RE").value or "0").strip()
            restore_re = prev_re != "1"
            if restore_re:
                self._chan.write("RE", "1")
            try:
                yield
            finally:
                if restore_re:
                    self._chan.write("RE", prev_re)

    def __enter__(self) -> "DV10Device":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.disconnect()


    def firmware_version(self) -> str:
        if self._firmware_cache is None:
            self._firmware_cache = self._chan.read("VR").value or ""
        return self._firmware_cache

    def model(self) -> str:
        if self._model_cache is None:
            self._model_cache = self._chan.read("WI").value or ""
        return self._model_cache

    def device_family(self) -> str:
        raw = self.model().upper()
        if "DV10" in raw:
            return "DV10"
        if "DV3" in raw:
            return "DV3"
        if "DV1" in raw:
            return "DV1"
        return ""

    def analog_modes_without_distinction(self) -> set:
        return set(ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY.get(self.device_family(), ()))

    def serial_number(self) -> str:
        return self._chan.read("SN").value or ""


    def get_frequency_hz(self) -> int:
        raw = self._chan.read("RF").value or "0"
        return round(float(raw) * 1_000_000)

    def set_frequency_hz(self, hz: int) -> None:
        mhz = hz / 1_000_000
        self._write_with_hint("RF", f"{mhz:010.5f}")

    def get_mode(self) -> str:
        return self._chan.read("MD").value or ""

    def get_mode_info(self) -> ModeInfo:
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
        return self.get_mode_info().describe()

    def set_mode(self, mode: str) -> None:
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
        self._chan.send("VS", retry=False)

    def read_vfo_search_settings(self) -> VfoSearchSettings:
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
        parts = []
        if delay_ds is not None:
            parts.append(f"DL{int(delay_ds):02d}")
        if free_time_s is not None:
            parts.append(f"FR{int(free_time_s):02d}")
        if auto_store is not None:
            parts.append(f"AS{1 if auto_store else 0}")
        self._chan.write("VE", " ".join(parts) if parts else "")

