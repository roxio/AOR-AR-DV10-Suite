"""Transport abstraction: anything that can send a line and read a line back.

Keeping this as a narrow interface means the protocol layer never needs to
know whether it's talking to a real DV10 over a USB-CDC virtual COM port or
to the in-process :class:`~aor_dv10.transport.simulator.SimulatorTransport`
used for development and tests.
"""

from __future__ import annotations

import abc


class TransportError(RuntimeError):
    """Raised for any transport-level failure (I/O error, not connected, ...)."""


class TransportTimeout(TransportError):
    """Raised when no response line arrived within the configured timeout.

    Per AOR's documented behaviour for this receiver family (confirmed on the
    sibling AR8600 RS232 protocol, which the DV10's command set follows): if
    no response arrives, the receiver likely failed to parse the previous
    command. The documented recovery is to send a bare [CR] and re-send.
    :class:`aor_dv10.protocol.codec.CommandChannel` does this automatically.
    """


class Transport(abc.ABC):
    """Minimal line-oriented transport interface."""

    @abc.abstractmethod
    def open(self) -> None:
        """Open the underlying connection. Safe to call once before use."""

    @abc.abstractmethod
    def close(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        ...

    @abc.abstractmethod
    def write_line(self, data: bytes) -> None:
        """Write raw bytes (already including any terminator) to the device."""

    @abc.abstractmethod
    def read_line(self, timeout: float) -> bytes | None:
        """Read a single terminated line, or return None on timeout.

        ``timeout`` is a per-call override in seconds; implementations should
        not block longer than this waiting for a line terminator.
        """

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
