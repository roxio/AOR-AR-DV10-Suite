import threading
import time

from aor_dv10.protocol.codec import CommandChannel, DV10ProtocolError, describe_result_code
from aor_dv10.protocol.commands import COMMANDS, Access
from aor_dv10.transport.simulator import SimulatorTransport


def test_command_table_covers_documented_mnemonics():
    # Spot-check a handful of the officially documented commands are present.
    for code in ("RF", "MD", "SQ", "AG", "LM", "AC", "BP", "VR", "WI", "EX", "ZP", "QP"):
        assert code in COMMANDS
    assert COMMANDS["LM"].access == Access.READ
    assert COMMANDS["RF"].access == Access.READ_WRITE


def test_channel_write_then_read_roundtrip():
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)

    chan.write("RF", "0145.50000")
    resp = chan.read("RF")
    assert resp.value == "0145.50000"


def test_no_space_between_code_and_value_on_the_wire():
    """Confirmed against real AR-DV10 hardware: requests and
    responses have NO space between the command code and its value, e.g.
    "RF0145.50000" not "RF 0145.50000". The original space-separated
    assumption caused a real set-frequency command to be silently ignored
    by the device."""
    sent = []

    class RecordingTransport(SimulatorTransport):
        def write_line(self, data: bytes) -> None:
            sent.append(data)
            super().write_line(data)

    t = RecordingTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    chan.write("RF", "0145.50000")
    assert sent[-1] == b"RF0145.50000\r"


def test_response_without_code_echo_is_handled():
    """Confirmed against real hardware: WI responds with just the value
    ("AOR AR-DV10"), not "WIAOR AR-DV10". The channel must fall back to
    treating the whole response as the value when it doesn't start with
    the command code."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    resp = chan.read("WI")
    assert resp.value == "AR-DV10"


def test_bare_question_mark_is_the_error_indicator():
    """Confirmed against real hardware: the error/unsupported response is a
    bare "?", not an "RE ..." result code."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    try:
        chan.read("ZZ")
    except DV10ProtocolError as exc:
        assert exc.code == "?"
    else:
        raise AssertionError("expected DV10ProtocolError")


def test_channel_raises_protocol_error_on_unknown_write():
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    try:
        chan.write("ZZ", "1")
    except DV10ProtocolError:
        pass
    else:
        raise AssertionError("expected DV10ProtocolError for an unhandled command")


def test_re_enabled_error_responses_decode_to_numeric_result_code():
    """Confirmed against real DV10 hardware: once "RE 1" is
    active, a rejected command comes back as "<code>?" (e.g. "60?" for a
    bare AG read, "40?" for "VF 1") instead of a bare "?" - and this must
    be raised as an error with the decoded meaning, not silently treated as
    a successful read with a garbled value."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    chan.write("RE", "1")

    try:
        chan.read("AG")
    except DV10ProtocolError as exc:
        assert exc.result_code == 60
        assert "does not exist" in exc.hint or "not supported" in exc.hint
    else:
        raise AssertionError("expected DV10ProtocolError for AG's bare read under RE 1")

    try:
        chan.write("VF", "1")
    except DV10ProtocolError as exc:
        assert exc.result_code == 40
        assert "FORMAT_ERR" in exc.hint
    else:
        raise AssertionError("expected DV10ProtocolError for VF 1 (a digit) under RE 1")


def test_re_write_ack_carries_ok_result_code():
    """Confirmed against real hardware (via a real crash - see
    codec.py's module docstring: RE prefixes every response, not just
    errors): once RE-style prefixing is
    active, EVERY response gets a numeric prefix, not just error ones - a
    successful write's ack (an empty body under RE off) comes back as just
    "20" (PC_RESULT_OK) with RE on. Response.result_code carries the
    decoded 20; Response.value is None since the underlying ack body is
    empty, same as any other successful write."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    resp = chan.write("RE", "1")
    assert resp.value is None
    assert resp.result_code == 20
    assert resp.raw == "20"


def test_describe_result_code_decodes_base_and_continue_variants():
    assert "PC_RESULT_OK" in describe_result_code(20)
    assert "PC_RESULT_FORMAT_ERR" in describe_result_code(40)
    assert "CONTINUE" in describe_result_code(41)


def test_vf_letter_write_succeeds_and_enters_vfo_mode():
    """Confirmed against real DV10 hardware: "raw VF A"
    succeeds (bare "VF" ack, no value) - unlike the earlier "VF 0"/"VF 1"
    guesses, which both failed. VF is presumed to be the way into VFO mode,
    modelled here by flipping the simulator's
    vfo_mode flag."""
    t = SimulatorTransport()
    t.open()
    t.vfo_mode = False
    chan = CommandChannel(t, timeout=1.0)

    resp = chan.write("VF", "A")
    assert resp.value is None
    assert t.vfo_mode is True


def test_vf_digit_write_fails_as_format_error_under_re():
    """Confirmed against real hardware: "VF 1" (the old digit guess) fails
    with result code 40 (PC_RESULT_FORMAT_ERR) once RE is on."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    chan.write("RE", "1")
    try:
        chan.write("VF", "1")
    except DV10ProtocolError as exc:
        assert exc.result_code == 40
    else:
        raise AssertionError("expected DV10ProtocolError")


def test_re_prefixes_a_normal_read_and_is_stripped_correctly():
    """Reproduces a real crash reported against real hardware: with RE
    left on from an earlier session, a plain
    "RF" read comes back as "20RF0145.50000" (20 = OK, then the normal
    RF0145.50000 response) instead of just "RF0145.50000". Before this was
    understood, the codec only recognised the numeric prefix on ERROR
    responses ("<code>?") and treated everything else as a normal
    response - so this prefixed-but-successful read fell through to
    "resp.value = whole raw text", i.e. "20RF0145.50000", which then blew
    up float("20RF0145.50000") in DV10Device.get_frequency_hz(). The fix:
    always check for and strip a leading known result code, regardless of
    whether RE is a success or error code - see codec.py's module
    docstring."""
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    chan.write("RE", "1")

    resp = chan.read("RF")
    assert resp.value == "0145.50000"
    assert resp.result_code == 20
    assert resp.raw == "20RF0145.50000"


def test_re_prefix_stripping_survives_through_dv10device_get_frequency_hz():
    """End-to-end regression test for the exact crash from the bug report:
    DV10Device.get_frequency_hz() (and therefore .status()) must not raise
    ValueError just because RE was left on from an earlier session."""
    from aor_dv10.device import DV10Device

    dev = DV10Device.open_simulator()
    with dev:
        dev.raw("RE", "1")
        assert dev.get_frequency_hz() == 145_500_000
        status = dev.status()  # must not raise
        assert status.frequency_hz == 145_500_000


class _SlowSimulatorTransport(SimulatorTransport):
    """SimulatorTransport with a tiny artificial delay inserted between the
    write and read halves of a command, to widen the race window a missing
    lock would need to actually manifest as cross-talk in a test that has
    to run fast and reliably in CI."""

    def write_line(self, data: bytes) -> None:
        time.sleep(0.002)
        super().write_line(data)

    def read_line(self, timeout: float):
        time.sleep(0.002)
        return super().read_line(timeout)


def test_command_channel_is_thread_safe_across_concurrent_callers():
    """Guards against a real class of bug this project just added
    cross-thread device sharing for: "dv10-cli --web" (see cli/__main__.py)
    runs the interactive REPL and the web panel's request handling in
    different threads against the SAME DV10Device / CommandChannel / serial
    connection (see web/server.py's start_in_thread()). Without a lock
    around each whole write-then-read cycle in CommandChannel.send(), one
    thread's request could interleave with another's on the wire, causing a
    caller to receive a response that actually belongs to a different
    thread's command - see CommandChannel's class docstring."""
    t = _SlowSimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=2.0)
    errors = []
    stop = threading.Event()

    def hammer_unrelated_writes():
        # Continuously write to a different command, to create interleaving
        # opportunities for the reader below if send() weren't atomic.
        i = 0
        while not stop.is_set():
            chan.write("RG", str(i % 1000).zfill(3))
            i += 1

    def read_static_value():
        # VR is never written by anything in this test, so every read of
        # it must come back "1.00" - any other value means this thread's
        # read got a response that actually belonged to a concurrent RG
        # write instead.
        for _ in range(25):
            try:
                resp = chan.read("VR")
                if resp.value != "1.00":
                    errors.append(resp.value)
            except Exception as exc:  # noqa: BLE001 - want to catch and report, not crash a thread
                errors.append(repr(exc))

    writers = [threading.Thread(target=hammer_unrelated_writes, daemon=True) for _ in range(3)]
    for w in writers:
        w.start()
    reader = threading.Thread(target=read_static_value)
    reader.start()
    reader.join(timeout=15)
    stop.set()
    for w in writers:
        w.join(timeout=2)

    assert not errors, f"cross-talk detected between concurrent threads: {errors}"
