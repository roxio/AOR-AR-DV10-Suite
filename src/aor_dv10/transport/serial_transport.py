"""Real USB-CDC serial transport for a physical AOR AR-DV10.

The DV10 enumerates over USB as a CDC-ACM device (Windows uses the built-in
``usbser.sys`` driver, no vendor driver needed; Linux exposes it as
``/dev/ttyACM*`` via the kernel ``cdc_acm`` driver):

    VID 0x08D0  (AOR, LTD.)
    PID 0x0101  (AR-DV10)

Because it's a *virtual* COM port riding over USB (not a physical RS232
level-shifter), the baud rate configured on the host side generally does not
affect the actual USB transfer rate the way it would on real RS232 - the
device's CDC firmware decides how fast it drains the endpoint. We still set
one for pyserial's sake, and expose it as a constructor argument in case a
particular firmware revision cares. The receiver's own communication speed
(baud, for anyone bridging to genuine RS232 elsewhere) is independently
queryable/settable through the ``SB`` command once connected.

None of this has been validated against real hardware yet. Flag anything
that turns out to be wrong once you test.
"""

from __future__ import annotations

import time
from typing import Optional

from .base import Transport, TransportError, TransportTimeout

DV10_VID = 0x08D0
DV10_PID = 0x0101

LINE_TERMINATOR = b"\r"  # AOR family accepts CR or CRLF; we send CR and accept either on read.


def find_dv10_port() -> Optional[str]:
    """Best-effort auto-detection of the DV10's virtual COM port by VID/PID.

    Returns a device path (e.g. ``COM7`` or ``/dev/ttyACM0``) or ``None`` if
    no matching device is currently plugged in / enumerated. Requires
    ``pyserial``'s ``list_ports`` submodule, which ships with pyserial.
    """
    try:
        from serial.tools import list_ports
    except ImportError as exc:  # pragma: no cover - environment issue
        raise TransportError("pyserial is not installed") from exc

    for port in list_ports.comports():
        if port.vid == DV10_VID and port.pid == DV10_PID:
            return port.device
    return None


class SerialTransport(Transport):
    """pyserial-backed transport talking to a real DV10 over USB."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 115200,
        *,
        autodetect: bool = True,
    ) -> None:
        """
        Args:
            port: Explicit device path (``COM7``, ``/dev/ttyACM0``, ...). If
                ``None`` and ``autodetect`` is True, we try to find the DV10
                by VID/PID at :meth:`open` time.
            baudrate: Serial baud to configure on the host side. Largely
                irrelevant for USB-CDC (see module docstring) but required by
                pyserial's API.
            autodetect: Whether to auto-discover the port by VID/PID when
                ``port`` is not given.
        """
        self._port_arg = port
        self._baudrate = baudrate
        self._autodetect = autodetect
        self._serial = None  # type: ignore[assignment]

    def open(self) -> None:
        if self.is_open:
            return
        try:
            import serial  # pyserial
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
                timeout=0.2,  # short internal poll; per-call timeout enforced in read_line
                write_timeout=2.0,
            )
        except Exception as exc:  # serial.SerialException et al.
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
                continue  # swallow leading/duplicate terminators (CRLF pairs)
            buf.extend(chunk)
        if buf:
            return bytes(buf)
        return None
