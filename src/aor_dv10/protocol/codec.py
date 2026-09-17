
from __future__ import annotations

import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

from ..transport.base import Transport, TransportTimeout
from .commands import COMMANDS

DEFAULT_TIMEOUT = 1.5

RESULT_CODES = {
    10: "PC_RESULT_SEND (unrelated message)",
    20: "PC_RESULT_OK",
    30: "PC_RESULT_CAN_NOT_SET_ERR (cannot set given current conditions)",
    40: "PC_RESULT_FORMAT_ERR (malformed command/value)",
    50: "PC_RESULT_OUT_RANGE_ERR (value out of range)",
    60: "PC_RESULT_NONE (command does not exist / not supported)",
}

_RESULT_ERROR_CODES = {30, 31, 40, 41, 50, 51, 60, 61}

_KNOWN_RESULT_CODES = _RESULT_ERROR_CODES | {10, 11, 20, 21}

_RESULT_CODE_PREFIX_RE = re.compile(r"^(\d{2})(.*)$", re.DOTALL)


def describe_result_code(code: int) -> str:
    base = code
    suffix = ""
    if base not in RESULT_CODES and (base - 1) in RESULT_CODES:
        base -= 1
        suffix = " (+1: PC_RESULT_CONTINUE, more lines follow)"
    return RESULT_CODES.get(base, f"unknown result code {code}") + suffix


class DV10Error(RuntimeError):
    pass


class DV10ProtocolError(DV10Error):

    def __init__(
        self,
        code: str,
        raw_response: str,
        hint: Optional[str] = None,
        result_code: Optional[int] = None,
    ):
        msg = f"Device returned error code {code!r} (raw: {raw_response!r})"
        if hint:
            msg += f" - {hint}"
        super().__init__(msg)
        self.code = code
        self.raw_response = raw_response
        self.hint = hint
        self.result_code = result_code


class DV10ResyncNeeded(DV10Error):
    pass


@dataclass
class Response:
    code: str
    value: Optional[str]
    raw: str
    result_code: Optional[int] = None


class CommandChannel:

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT):
        self.transport = transport
        self.timeout = timeout
        self._lock = threading.RLock()
        self._trace: Deque[str] = deque(maxlen=2000)
        self._trace_sink: Optional[Callable[[str], None]] = None

    def _log_trace(self, direction: str, data: bytes) -> None:
        ts = time.strftime("%H:%M:%S", time.localtime()) + f".{int(time.time() * 1000) % 1000:03d}"
        line = f"[{ts}] {direction} {data!r}"
        self._trace.append(line)
        sink = self._trace_sink
        if sink is not None:
            try:
                sink(line)
            except Exception:
                pass

    def set_trace_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        self._trace_sink = sink

    def trace_lines(self, n: Optional[int] = None) -> List[str]:
        lines = list(self._trace)
        return lines if n is None else lines[-n:]

    def send(
        self,
        code: str,
        value: Optional[str] = None,
        *,
        retry: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> Response:
        with self._lock:
            if retry is None:
                retry = value is None
            wait = self.timeout if timeout is None else timeout
            line = code if value is None else f"{code}{value}"
            tx_bytes = line.encode("ascii") + b"\r"
            self.transport.write_line(tx_bytes)
            self._log_trace("TX", tx_bytes)

            raw = self.transport.read_line(wait)
            if raw is None:
                self._log_trace("RX", b"<no response / timeout>")
                resync_bytes = b"\r"
                self.transport.write_line(resync_bytes)
                self._log_trace("TX", resync_bytes)
                discarded = self.transport.read_line(wait)
                self._log_trace("RX", discarded if discarded is not None else b"<no response / timeout>")
                if not retry:
                    raise DV10ResyncNeeded(
                        f"No response to {code!r}; not resending a command with a "
                        f"possible side effect. Device may be busy or off."
                    )
                return self.send(code, value, retry=False, timeout=timeout)

            self._log_trace("RX", raw)
            text = raw.decode("ascii", errors="replace").strip()

            if text == "?" or text.startswith("?"):
                raise DV10ProtocolError("?", text)

            raw_text = text
            result_code: Optional[int] = None
            prefix_match = _RESULT_CODE_PREFIX_RE.match(text)
            if prefix_match and int(prefix_match.group(1)) in _KNOWN_RESULT_CODES:
                result_code = int(prefix_match.group(1))
                if result_code in _RESULT_ERROR_CODES:
                    raise DV10ProtocolError(
                        str(result_code), raw_text, hint=describe_result_code(result_code),
                        result_code=result_code,
                    )
                text = prefix_match.group(2)
                if text == "?" or text.startswith("?"):
                    raise DV10ProtocolError("?", raw_text)

            code_upper = code.upper()
            if text.upper().startswith(code_upper):
                resp_value = text[len(code_upper):] or None
            else:
                resp_value = text or None

            return Response(code=code_upper, value=resp_value, raw=raw_text, result_code=result_code)

    def read_pending(self, timeout: Optional[float] = None) -> Optional[Response]:
        with self._lock:
            raw = self.transport.read_line(timeout if timeout is not None else self.timeout)
            if raw is None:
                self._log_trace("RX", b"<no response / timeout>")
                return None
            self._log_trace("RX", raw)
            text = raw.decode("ascii", errors="replace").strip()
            raw_text = text

            if text == "?" or text.startswith("?"):
                raise DV10ProtocolError("?", raw_text)

            result_code: Optional[int] = None
            prefix_match = _RESULT_CODE_PREFIX_RE.match(text)
            if prefix_match and int(prefix_match.group(1)) in _KNOWN_RESULT_CODES:
                result_code = int(prefix_match.group(1))
                if result_code in _RESULT_ERROR_CODES:
                    raise DV10ProtocolError(
                        str(result_code), raw_text, hint=describe_result_code(result_code),
                        result_code=result_code,
                    )
                text = prefix_match.group(2)
                if text == "?" or text.startswith("?"):
                    raise DV10ProtocolError("?", raw_text)

            return Response(code="", value=text or None, raw=raw_text, result_code=result_code)

    def read(self, code: str, *, timeout: Optional[float] = None) -> Response:
        return self.send(code, None, timeout=timeout)

    def write(self, code: str, value: str, *, timeout: Optional[float] = None) -> Response:
        return self.send(code, value, retry=False, timeout=timeout)

    def describe(self, code: str) -> str:
        cmd = COMMANDS.get(code.upper())
        if cmd is None:
            return f"{code}: (not in known command table)"
        return f"{cmd.code}: {cmd.description} [{cmd.access.value}]" + (
            f" - {cmd.notes}" if cmd.notes else ""
        )

    @contextmanager
    def transaction(self):
        with self._lock:
            yield
