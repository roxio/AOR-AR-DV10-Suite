
from __future__ import annotations

import time
from typing import Optional

from .base import Transport, TransportError, TransportTimeout

DV10_VID = 0x08D0
DV10_PID = 0x0101

LINE_TERMINATOR = b"\r"


def find_dv10_port() -> Optional[str]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:  # pragma: no cover - environment issue
        raise TransportError("pyserial is not installed") from exc

    for port in list_ports.comports():
        if port.vid == DV10_VID and port.pid == DV10_PID:
            return port.device
    return None


class SerialTransport(Transport):

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 115200,
        *,
        autodetect: bool = True,
    ) -> None:
        self._port_arg = port
        self._baudrate = baudrate
        self._autodetect = autodetect
        self._serial = None  # type: ignore[assignment]

    def open(self) -> None:
        if self.is_open:
            return
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise TransportError(
                "pyserial is not installed. Install with: pip install pyserial"
            ) from exc

        port = self._port_arg
        if port is None:
            if not self._autodetect:
                raise TransportError("No port given and autodetect=False")
            port = find_dv10_port()
            if port is None:
                raise TransportError(
                    "Could not find a DV10 on USB (VID 0x08D0 / PID 0x0101). "
                    "Is it plugged in and powered on? You can also pass an "
                    "explicit port=... ."
                )

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,
                write_timeout=2.0,
            )
        except Exception as exc:
            raise TransportError(f"Failed to open serial port {port!r}: {exc}") from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write_line(self, data: bytes) -> None:
        if not self.is_open:
            raise TransportError("Transport is not open")
        assert self._serial is not None
        try:
            self._serial.write(data)
            self._serial.flush()
        except Exception as exc:
            raise TransportError(f"Write failed: {exc}") from exc

    def read_line(self, timeout: float) -> Optional[bytes]:
        if not self.is_open:
            raise TransportError("Transport is not open")
        assert self._serial is not None
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._serial.read(1)
            if not chunk:
                continue
            if chunk in (b"\r", b"\n"):
                if buf:
                    return bytes(buf)
                continue
            buf.extend(chunk)
        if buf:
            return bytes(buf)
        return None
