"""Command/response framing on top of a :class:`~aor_dv10.transport.base.Transport`.

Framing confirmed against real AR-DV10 hardware - see
:meth:`CommandChannel.send`'s docstring for the details (no space between a
command's code and its value, ``?`` as the error indicator, some responses
omitting the code echo, and a numeric-result-code prefix applied to *every*
response - not just errors - once ``RE`` prefixing is turned on), including
the separately-confirmed finding that writes to tuning/level parameters
(``RF``, ``AC``, ``SQ``, ``AT``, ...) are rejected with ``?`` unless the
receiver is in VFO mode rather than browsing a memory channel.

**Real-hardware bug**: a user hit ``ValueError: could not convert string to
float: '20RF0145.50000'`` running ``dv10-cli``/``dv10-web`` against real
hardware, because ``RE`` had been left switched on from an earlier
debugging session (it's device-side state - it doesn't reset when the
CLI/web panel restarts) and this module didn't yet know that ``RE``
prefixes *every* response, not just error ones. See
:func:`CommandChannel.send`'s docstring for the corrected understanding
(RE prefixes every response, not just errors).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

from ..transport.base import Transport, TransportTimeout
from .commands import COMMANDS

DEFAULT_TIMEOUT = 1.5

# Result codes from the AR-DV3 command spec, controlled by the ``RE``
# command (0=off/default, 1=on: prefix every response with one of these).
# Confirmed against real AR-DV10 hardware in two rounds: first that
# rejections come back as ``"<code>?"`` (e.g. ``"60?"`` for a bare ``AG``
# read, ``"40?"`` for ``VF 1``), then - from a real crash caused by ``RE``
# being left on from an earlier session - that *successful* responses are
# ALSO prefixed, e.g. a plain ``RF`` read came back as ``"20RF0145.50000"``
# (``20`` = OK, then the completely normal ``RF0145.50000`` response).
# The "+1 continue" variants (11, 21, 31, ...) aren't independently
# confirmed; decoded here by subtracting 1 down to the nearest base code.
RESULT_CODES = {
    10: "PC_RESULT_SEND (unrelated message)",
    20: "PC_RESULT_OK",
    30: "PC_RESULT_CAN_NOT_SET_ERR (cannot set given current conditions)",
    40: "PC_RESULT_FORMAT_ERR (malformed command/value)",
    50: "PC_RESULT_OUT_RANGE_ERR (value out of range)",
    60: "PC_RESULT_NONE (command does not exist / not supported)",
}

# Only these are actually error conditions - 10/20 (and their +1 "continue"
# variants, 11/21) are success/informational.
_RESULT_ERROR_CODES = {30, 31, 40, 41, 50, 51, 60, 61}

# Every code we know about, error or not - used to recognise the numeric
# prefix at the front of a response. Deliberately matched unconditionally
# (not gated on some "is RE on?" flag this module would have to track):
# every response this project has ever seen from the DV10 with RE *off*
# starts with a letter (a command code echo, or text like "AOR AR-DV10"),
# or is the bare "?" handled separately above - never with a digit. So a
# response starting with exactly one of these two-digit codes is an
# unambiguous signal that RE-style prefixing is active on *this* response,
# regardless of whether this library happens to know that already.
_KNOWN_RESULT_CODES = _RESULT_ERROR_CODES | {10, 11, 20, 21}

_RESULT_CODE_PREFIX_RE = re.compile(r"^(\d{2})(.*)$", re.DOTALL)


def describe_result_code(code: int) -> str:
    """Human-readable meaning of a numeric RE result code, decoding the "+1
    continue" variant (e.g. 31) down to its base code's description (30)."""
    base = code
    suffix = ""
    if base not in RESULT_CODES and (base - 1) in RESULT_CODES:
        base -= 1
        suffix = " (+1: PC_RESULT_CONTINUE, more lines follow)"
    return RESULT_CODES.get(base, f"unknown result code {code}") + suffix


class DV10Error(RuntimeError):
    """Base class for protocol-level errors talking to the DV10."""


class DV10ProtocolError(DV10Error):
    """The device rejected the command.

    Confirmed to be signalled by a bare ``?`` on real hardware with ``RE``
    (result-code prefixing) off - the default. With ``RE`` on, confirmed
    instead to be signalled by ``"<code>?"`` where ``code`` is one of the
    numeric values in :data:`RESULT_CODES`. ``result_code`` carries that
    number when known, else ``None`` for the plain ``?`` case."""

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
    """No response even after sending a resync [CR] and retrying once."""


@dataclass
class Response:
    code: str
    value: Optional[str]
    raw: str
    # The numeric RE prefix stripped from this response, when present (see
    # CommandChannel.send()) - None if RE-style prefixing wasn't detected
    # on this particular response (typically because RE is off).
    result_code: Optional[int] = None


class CommandChannel:
    """Turns a byte-oriented :class:`Transport` into a command/response API.

    Thread-safe: :meth:`send` is guarded by a lock, so it's safe to share
    one channel (and the :class:`~aor_dv10.device.DV10Device` built on it)
    between multiple threads - e.g. ``dv10-cli --web`` runs the interactive
    REPL and the web panel's request handling in different threads against
    the same device/serial connection (see ``cli/__main__.py`` and
    ``web/server.py``'s ``start_in_thread()``). Without this, a command
    issued from one thread could interleave on the wire with a command from
    another (write half of one, write half of another, then both trying to
    read a response that belongs to the other), silently corrupting both.
    """

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT):
        self.transport = transport
        self.timeout = timeout
        self._lock = threading.RLock()  # RLock: send() calls itself once on resync/retry
        # -- protocol tracing ----------------------------------------------
        # Every TX/RX line (byte-exact, via repr() - so a stray space, an
        # unexpected CR/LF, or a non-ASCII byte from a misbehaving real
        # unit is visible rather than silently stripped/decoded away) is
        # ALWAYS recorded here, regardless of whether anything is watching
        # live - so "what actually happened right before that weird
        # error?" is answerable after the fact via trace_lines(), not just
        # by remembering to turn tracing on beforehand. A bounded deque
        # keeps memory flat during a long session. ``_trace_sink``, when
        # set via set_trace_sink(), additionally gets each line live (the
        # CLI's "debug on" echoes it to the console; the web panel forwards
        # it to connected browser tabs) - see DV10Device.set_trace_sink()/
        # trace_lines()/save_trace() for the public-facing wrappers.
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
                pass  # a broken/slow sink must never take the protocol layer down with it

    def set_trace_sink(self, sink: Optional[Callable[[str], None]]) -> None:
        """Register (or, with ``None``, unregister) a callback that receives
        every trace line live, in addition to it always being recorded into
        the ring buffer - see the docstring on the buffer above."""
        self._trace_sink = sink

    def trace_lines(self, n: Optional[int] = None) -> List[str]:
        """The most recent ``n`` trace lines (all of them, oldest first, if
        ``n`` is None), regardless of whether a sink is/was registered."""
        lines = list(self._trace)
        return lines if n is None else lines[-n:]

    def send(self, code: str, value: Optional[str] = None, *, retry: bool = True) -> Response:
        """Send a single command and wait for its response line.

        Framing confirmed against real AR-DV10 hardware:

        * Request: ``CODE`` + value with **no separating space** (e.g.
          ``RF0145.50000``), terminated by CR. The originally-assumed
          ``"CODE value"`` (space-separated) form was tried first and the
          device silently ignored it (a set-frequency command sent that way
          produced no change) - this is why the fix mattered.
        * Response: normally ``CODE`` immediately followed by the value with
          **no space** (e.g. ``RF0149.06250``, ``VRP2504B``) - but at least
          one command (``WI``) responds with *only* the value and no code
          echo at all (``AOR AR-DV10``, not ``WIAOR AR-DV10``). We handle
          both: if the response starts with the command code we sent, we
          strip that prefix; otherwise we treat the whole response as the
          value.
        * Error/unsupported, ``RE`` off (default): a bare ``?``.
        * Error/unsupported, ``RE`` on: the response becomes ``"<code>?"``,
          e.g. ``AG`` with no argument returned ``"60?"``
          (PC_RESULT_NONE - "command does not exist") and ``VF 1`` returned
          ``"40?"`` (PC_RESULT_FORMAT_ERR).
        * **Every other response, ``RE`` on**: also prefixed with a numeric
          code, e.g. a plain ``RF`` read came back ``"20RF0145.50000"``
          (``20`` = PC_RESULT_OK, then the ordinary ``RF0145.50000``
          response) - confirmed the hard way, via a real crash: this
          project initially only handled the *error* shape
          (``"<code>?"``) and didn't realise ``RE`` prefixes successful
          responses too, so a plain frequency read came back as
          unparseable garbage once ``RE`` had been left on from an earlier
          session (``RE`` is device-side state - it doesn't reset when the
          CLI/web panel restarts). Fixed by always checking for - and
          stripping - a leading two-digit known result code before doing
          anything else with the response, regardless of whether this
          library thinks ``RE`` is currently on (it doesn't track that
          state at all; see :data:`_KNOWN_RESULT_CODES` for why that's
          safe). Confirmed: RE prefixes every response, not just errors.

        Raises:
            DV10ProtocolError: the device replied with ``?`` (error/unsupported),
                or a "<code>?"/prefixed-error response with RE on.
            DV10ResyncNeeded: no reply, even after a resync attempt.
        """
        with self._lock:
            line = code if value is None else f"{code}{value}"
            tx_bytes = line.encode("ascii") + b"\r"
            self.transport.write_line(tx_bytes)
            self._log_trace("TX", tx_bytes)

            raw = self.transport.read_line(self.timeout)
            if raw is None:
                self._log_trace("RX", b"<no response / timeout>")
                if not retry:
                    raise DV10ResyncNeeded(
                        f"No response to {code!r} even after resync; device may be busy or off."
                    )
                # Documented recovery: send a bare CR, then retry the command once.
                resync_bytes = b"\r"
                self.transport.write_line(resync_bytes)
                self._log_trace("TX", resync_bytes)
                discarded = self.transport.read_line(self.timeout)  # whatever that produced, if anything
                self._log_trace("RX", discarded if discarded is not None else b"<no response / timeout>")
                return self.send(code, value, retry=False)

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
                # An informational/OK prefix (10/11/20/21): strip it and keep
                # parsing the remainder exactly like a normal, unprefixed
                # response - it may be empty (a plain write ack), "?" (unlikely
                # but handled defensively), or a full CODE+value/message body.
                text = prefix_match.group(2)
                if text == "?" or text.startswith("?"):
                    raise DV10ProtocolError("?", raw_text)

            code_upper = code.upper()
            if text.upper().startswith(code_upper):
                resp_value = text[len(code_upper):] or None
            else:
                # Some commands (observed: WI) omit the code echo entirely and
                # respond with just the value.
                resp_value = text or None

            return Response(code=code_upper, value=resp_value, raw=raw_text, result_code=result_code)

    def read_pending(self, timeout: Optional[float] = None) -> Optional[Response]:
        """Read one already-in-flight response line WITHOUT sending anything
        first.

        Exists for MM ("last channel memory registration"), confirmed
        from the AR-DV1 wire-protocol spec to be the one command in this
        project's command set whose single request provokes TWO response
        lines: an immediate "21" (registration started) followed, once
        registration actually finishes, by "20" (registration completed)
        - see DV10Device.register_last_channel(). Every other command
        here gets exactly one response line per send(); without an
        explicit second read like this one, that second line would sit
        unconsumed in the transport's receive buffer and get silently
        mis-attributed as the response to whatever command is sent next -
        the exact "two-phase-async gap" this method exists to close.

        Returns None on timeout (nothing arrived within ``timeout``,
        defaulting to this channel's normal command timeout). Parsed the
        same way send() parses a response (RE-prefix stripping, "?" error
        detection) but - since nothing was sent, so there's no command
        code to compare the echo against - ``Response.code`` is always
        ``""`` here rather than inferred."""
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

    def read(self, code: str) -> Response:
        """Send a read (no-argument) command."""
        return self.send(code, None)

    def write(self, code: str, value: str) -> Response:
        """Send a write command with a value."""
        return self.send(code, value)

    def describe(self, code: str) -> str:
        cmd = COMMANDS.get(code.upper())
        if cmd is None:
            return f"{code}: (not in known command table)"
        return f"{cmd.code}: {cmd.description} [{cmd.access.value}]" + (
            f" - {cmd.notes}" if cmd.notes else ""
        )
