import threading
import time

from aor_dv10.protocol.codec import CommandChannel, DV10ProtocolError, describe_result_code
from aor_dv10.protocol.commands import COMMANDS, Access
from aor_dv10.transport.simulator import SimulatorTransport


def test_command_table_covers_documented_mnemonics():
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
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    resp = chan.read("WI")
    assert resp.value == "AR-DV10"


def test_bare_question_mark_is_the_error_indicator():
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
    t = SimulatorTransport()
    t.open()
    t.vfo_mode = False
    chan = CommandChannel(t, timeout=1.0)

    resp = chan.write("VF", "A")
    assert resp.value is None
    assert t.vfo_mode is True


def test_vf_digit_write_fails_as_format_error_under_re():
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
    t = SimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=1.0)
    chan.write("RE", "1")

    resp = chan.read("RF")
    assert resp.value == "0145.50000"
    assert resp.result_code == 20
    assert resp.raw == "20RF0145.50000"


def test_re_prefix_stripping_survives_through_dv10device_get_frequency_hz():
    from aor_dv10.device import DV10Device

    dev = DV10Device.open_simulator()
    with dev:
        dev.raw("RE", "1")
        assert dev.get_frequency_hz() == 145_500_000
        status = dev.status()
        assert status.frequency_hz == 145_500_000


class _SlowSimulatorTransport(SimulatorTransport):

    def write_line(self, data: bytes) -> None:
        time.sleep(0.002)
        super().write_line(data)

    def read_line(self, timeout: float):
        time.sleep(0.002)
        return super().read_line(timeout)


def test_command_channel_is_thread_safe_across_concurrent_callers():
    t = _SlowSimulatorTransport()
    t.open()
    chan = CommandChannel(t, timeout=2.0)
    errors = []
    stop = threading.Event()

    def hammer_unrelated_writes():
        i = 0
        while not stop.is_set():
            chan.write("RG", str(i % 1000).zfill(3))
            i += 1

    def read_static_value():
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
