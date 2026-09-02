"""Tests for live memory-channel control (MX/MA/MR) and bank management
(MW/MB/MQ), implemented against the
AR-DV1 wire spec's own "5-11 MEMORY CHANNEL" section (the first real
documented field layout this project has had for these - see
device.MemoryChannelInfo's docstring for how this differs from
aor_dv10.memory's backup-CSV format).
"""

import pytest

from aor_dv10.device import DV10Device, MemoryBankInfo, MemoryChannelInfo
from aor_dv10.protocol.codec import DV10ProtocolError, DV10ResyncNeeded


def test_reading_an_unregistered_channel():
    dev = DV10Device.open_simulator()
    with dev:
        info = dev.read_memory_channel(5, 12)
        assert info == MemoryChannelInfo(bank=5, channel=12, registered=False)


def test_write_then_read_memory_channel_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(
            5, 12,
            frequency_hz=145_500_000,
            step_hz=12_500,
            step_adjust_hz=500,
            mode="F0",  # digital off, FM
            tag="TESTCH",
            pass_channel=True,
            write_protect=True,
        )
        info = dev.read_memory_channel(5, 12)
        assert info.registered is True
        assert info.frequency_hz == 145_500_000
        assert info.step_hz == 12_500
        assert info.step_adjust_hz == 500
        assert info.pass_channel is True
        assert info.write_protect is True
        assert info.tag == "TESTCH"
        # Unlike standalone MD (confirmed reversed on the wire - see
        # set_mode()), MX's own embedded MD sub-field is sent/read in
        # NATURAL "<digital><analog>" order - see
        # write_memory_channel()'s "safety-critical distinction"
        # docstring note for why these two must
        # not be conflated.
        assert info.mode == "F0"


def test_write_memory_channel_omitted_fields_keep_previous_except_mp_pt():
    """Per the spec: RF/ST/SH/MD/TT keep their previous value when
    omitted from a write; MP/PT do NOT - they reset to 0."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(1, 1, frequency_hz=100_000_000, pass_channel=True, write_protect=True)
        first = dev.read_memory_channel(1, 1)
        assert first.pass_channel is True and first.write_protect is True

        # a second write with nothing but RF given: MP/PT reset, RF changes
        dev.write_memory_channel(1, 1, frequency_hz=200_000_000)
        second = dev.read_memory_channel(1, 1)
        assert second.frequency_hz == 200_000_000
        assert second.pass_channel is False
        assert second.write_protect is False


def test_tune_memory_channel_changes_receive_state():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(2, 3, frequency_hz=433_000_000, mode="10")
        dev.tune_memory_channel(2, 3)
        assert dev.get_frequency_hz() == 433_000_000
        # the simulator copies MX's stored (natural-order) MD field
        # straight into the live MD state on tune - see
        # SimulatorTransport's MR handling.
        assert dev.get_mode() == "10"


def test_tune_unregistered_channel_raises():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.tune_memory_channel(9, 9)


def test_read_memory_bank_returns_all_fifty_slots():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(4, 0, frequency_hz=100_000_000)
        dev.write_memory_channel(4, 49, frequency_hz=200_000_000)
        channels = dev.read_memory_bank(4)
        assert len(channels) == 50
        assert channels[0].registered and channels[0].frequency_hz == 100_000_000
        assert channels[49].registered and channels[49].frequency_hz == 200_000_000
        assert not channels[25].registered


def test_read_memory_bank_multiline_response_with_re_on():
    """The main protocol-level thing this exercises: read_memory_bank()
    must consume all 50 continuation lines (21-prefixed, final one 20)
    without leaving anything stray for the next command - the same class
    of hazard this project fixed for MM (see test_ardv1_spec_fixes.py)."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_result_code_prefixing(True)
        channels = dev.read_memory_bank(7)
        assert len(channels) == 50
        # nothing left dangling in the transport buffer afterwards
        assert dev._chan.read_pending(timeout=0.05) is None
        dev.set_beep_level(3)
        assert dev.get_beep_level() == "3"


def test_delete_memory_channel():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(5, 12, frequency_hz=145_500_000)
        dev.delete_memory_channel(5, 12)
        assert dev.read_memory_channel(5, 12).registered is False


def test_delete_memory_channel_not_registered_raises():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.delete_memory_channel(8, 8)


def test_write_memory_bank_and_read_it_back():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_bank(3, channel_count=10, protect=True, tag="MYBANK")
        info = dev.get_memory_bank_info(3)
        assert info == MemoryBankInfo(bank=3, channel_count=10, protect=True, tag="MYBANK")


def test_get_memory_bank_info_on_a_never_written_bank_returns_defaults():
    dev = DV10Device.open_simulator()
    with dev:
        info = dev.get_memory_bank_info(11)
        assert info.channel_count == 50
        assert info.protect is False


def test_delete_memory_bank_removes_its_channels_too():
    dev = DV10Device.open_simulator()
    with dev:
        dev.write_memory_channel(6, 1, frequency_hz=100_000_000)
        dev.write_memory_channel(6, 2, frequency_hz=200_000_000)
        dev.delete_memory_bank(6)
        assert dev.read_memory_channel(6, 1).registered is False
        assert dev.read_memory_channel(6, 2).registered is False


def test_delete_memory_bank_not_registered_raises():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.delete_memory_bank(15)


def test_read_memory_bank_accepts_mx_prefixed_real_dv10_lines():
    """Regression for '0 registered of 0 slots': a real DV10 returns the
    MAbb bank dump lines prefixed with "MX" (e.g. "MX0418 MP0 RF0439.10000
    ST012.50 ..."), not the "MA" prefix the simulator models. read_memory_bank()
    must accept both and normalise the result to the bank's 50-slot capacity,
    otherwise every programmed channel is dropped on the floor."""
    from aor_dv10.protocol.codec import Response

    dev = DV10Device.open_simulator()
    mx_lines = [
        "MX0418 MP0 RF0439.10000 ST012.50 SH000.00 MD000 PT0 TTSR2BT AU Bor",
        "MX0419 MP0 RF0438.70000 ST012.50 SH000.00 MD000 PT0 TTSR2BW AU Byt",
        "MX0420 MP0 RF0145.60000 ST012.50 SH000.00 MD000 PT0 TTSR2C AV Chwa",
    ]
    pending = list(mx_lines)  # send() peeks the first, read_pending() the rest

    def fake_send(code, value=None, *, retry=True):
        # read_memory_bank() first re-reads RE to restore it afterwards.
        if code.upper() == "RE":
            return Response(code="RE", value="0", raw="0", result_code=20)
        body = pending[0] if pending else ""
        # last remaining real line is the final (20) response; earlier ones 21
        result_code = 20 if len(pending) == 1 else 21
        return Response(code="MA", value=body, raw=body, result_code=result_code)

    def fake_pending(timeout=None):
        if len(pending) <= 1:
            return None
        pending.pop(0)
        body = pending[0]
        result_code = 20 if len(pending) == 1 else 21
        return Response(code="", value=body, raw=body, result_code=result_code)

    dev._chan.send = fake_send  # noqa: SLF001
    dev._chan.read_pending = fake_pending  # noqa: SLF001

    with dev:
        channels = dev.read_memory_bank(4)
    assert len(channels) == 50
    assert channels[18].registered and channels[18].frequency_hz == 439_100_000
    assert channels[19].registered and channels[19].frequency_hz == 438_700_000
    assert channels[20].registered and channels[20].frequency_hz == 145_600_000
    # unprogrammed slots in between are reported as unregistered
    assert not channels[0].registered
    assert not channels[21].registered


def test_status_survives_memory_mode_frequency_read():
    """A real DV10 browsing a memory channel returns an 'MX....' record when
    asked for the frequency (rather than a bare RF value); device.status()
    / /api/status must not blow up on that - the field just becomes None.
    Regression for the ValueError in get_frequency_hz taken from a live log."""
    dev = DV10Device.open_simulator()
    with dev:
        def boom():
            raise ValueError("could not convert: 'MX0418 MP0 RF0439.10000 ...'")
        dev.get_frequency_hz = boom  # noqa: SLF001
        status = dev.status()
    assert status.frequency_hz is None
    # other status fields still populate normally
    assert status.mode is not None
