import pytest
from aor_dv10.device import DV10Device
from aor_dv10.protocol.codec import DV10ProtocolError


def test_device_lifecycle_and_frequency_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        assert dev.connected
        dev.set_frequency_hz(145_500_000)
        assert dev.get_frequency_hz() == 145_500_000

        dev.set_mode("F0")
        assert dev.get_mode() == "0F0"

        dev.set_squelch("5")
        assert dev.get_squelch() == "5"

        dev.set_agc(True)
        assert dev.get_agc() is True
        dev.set_agc(False)
        assert dev.get_agc() is False

    assert not dev.connected


def test_status_snapshot_reads_all_fields():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(433_000_000)
        dev.set_mode("F0")
        status = dev.status()
        assert status.frequency_hz == 433_000_000
        assert status.mode == "0F0"
        assert status.smeter is not None


def test_frequency_wire_format_matches_confirmed_backup_format():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(145_500_000)
        assert dev._transport.state["RF"] == "0145.50000"  # noqa: SLF001

        dev.set_frequency_hz(433_925_000)
        assert dev._transport.state["RF"] == "0433.92500"  # noqa: SLF001


def test_vfo_mode_write_rejection_gets_helpful_hint():
    dev = DV10Device.open_simulator()
    with dev:
        dev._transport.vfo_mode = False  # noqa: SLF001

        for call in (
            lambda: dev.set_frequency_hz(145_500_000),
            lambda: dev.set_squelch("0"),
            lambda: dev.set_agc(True),
            lambda: dev.set_attenuator(True),
            lambda: dev.raw("RF", "0145.50000"),
        ):
            try:
                call()
            except DV10ProtocolError as exc:
                assert exc.code == "?"
                assert "VFO mode" in (exc.hint or "")
                assert "VFO mode" in str(exc)
            else:
                raise AssertionError("expected DV10ProtocolError")

        dev.set_beep(True)


def test_vfo_mode_hint_not_added_for_unrelated_commands():
    dev = DV10Device.open_simulator()
    with dev:
        try:
            dev.raw("ZZ", "1")
        except DV10ProtocolError as exc:
            assert exc.hint is None
        else:
            raise AssertionError("expected DV10ProtocolError")


def test_raw_escape_hatch_reaches_undocumented_helpers():
    dev = DV10Device.open_simulator()
    with dev:
        resp = dev.raw("AT", "1")
        assert resp.value is None
        resp = dev.raw("AT")
        assert resp.value == "1"


def test_mode_info_decodes_confirmed_fm_digital_off():
    dev = DV10Device.open_simulator()
    with dev:
        info = dev.get_mode_info()
        assert info.raw == "0F0"
        assert info.receiving_digital == "Auto"
        assert info.digital_select == "Digital off"
        assert info.analog_select == "FM"
        assert "FM" in dev.describe_mode()


def test_set_mode_reverses_field_order_for_the_wire_and_round_trips():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        info = dev.get_mode_info()
        assert info.raw == "0F0"
        assert info.digital_select == "Digital off"
        assert info.analog_select == "FM"

        dev.set_mode("F1")
        info = dev.get_mode_info()
        assert info.digital_select == "Digital off"
        assert info.analog_select == "AM"


def test_set_mode_rejects_unknown_codes_before_touching_the_wire():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(ValueError):
            dev.set_mode("X0")
        with pytest.raises(ValueError):
            dev.set_mode("0X")
        with pytest.raises(ValueError):
            dev.set_mode("F")
        with pytest.raises(ValueError):
            dev.set_mode("F00")


def test_smeter_reading_decodes_confirmed_vvvq_format():
    dev = DV10Device.open_simulator()
    with dev:
        reading = dev.get_smeter_reading()
        assert reading.dbm == -100
        assert reading.squelch_state == 1
        assert reading.squelch_open is True
        assert "-100" in reading.describe()


def test_squelch_mode_vs_level_are_distinct_commands():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_squelch_mode("2")
        assert dev.get_squelch_mode() == "2"
        assert dev.get_squelch() == "2"

        dev.set_squelch_level("42")
        assert dev.get_squelch_level() == "42"

        dev.set_noise_squelch_level("15")
        assert dev.get_noise_squelch_level() == "15"


def test_attenuator_state_is_tri_state_not_boolean():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_attenuator_state("2")
        assert dev.get_attenuator_state() == "2"

        dev.set_attenuator(True)
        assert dev.get_attenuator_state() == "1"
        dev.set_attenuator(False)
        assert dev.get_attenuator_state() == "0"


def test_agc_speed_is_four_state_not_boolean():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_agc_speed("3")
        assert dev.get_agc_speed() == "3"

        dev.set_agc(True)
        assert dev.get_agc() is True
        dev.set_agc(False)
        assert dev.get_agc() is False


def test_result_code_prefixing_toggle_sends_re():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_result_code_prefixing(True)
        assert dev._transport.state["RE"] == "1"  # noqa: SLF001
        dev.set_result_code_prefixing(False)
        assert dev._transport.state["RE"] == "0"  # noqa: SLF001


def test_status_snapshot_includes_richer_decoded_fields():
    dev = DV10Device.open_simulator()
    with dev:
        status = dev.status()
        assert status.mode_info is not None
        assert status.smeter_reading is not None
        assert status.agc_speed is not None
        assert status.attenuator_state is not None


def test_enter_vfo_mode_confirmed_working():
    dev = DV10Device.open_simulator()
    with dev:
        dev._transport.vfo_mode = False  # noqa: SLF001
        dev.enter_vfo_mode("A")
        assert dev._transport.vfo_mode is True  # noqa: SLF001

        dev.set_frequency_hz(146_520_000)
        assert dev.get_frequency_hz() == 146_520_000


def test_get_volume_bare_read_matches_confirmed_real_hardware_failure():
    dev = DV10Device.open_simulator()
    with dev:
        try:
            dev.get_volume()
        except DV10ProtocolError as exc:
            assert exc.raw_response == "?"
        else:
            raise AssertionError("expected DV10ProtocolError")

        status = dev.status()
        assert status.volume is None


def test_set_volume_also_matches_confirmed_real_hardware_failure():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.set_volume("50")
