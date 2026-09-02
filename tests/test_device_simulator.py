import pytest
from aor_dv10.device import DV10Device
from aor_dv10.protocol.codec import DV10ProtocolError


def test_device_lifecycle_and_frequency_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        assert dev.connected
        dev.set_frequency_hz(145_500_000)
        assert dev.get_frequency_hz() == 145_500_000

        # "F0" = digital off, analog FM - the well-known real-hardware
        # default reading, "0F0" (receiving=Auto/digital=off/analog=FM).
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
        dev.set_mode("F0")  # digital off, analog FM - see set_mode() docstring
        status = dev.status()
        assert status.frequency_hz == 433_000_000
        assert status.mode == "0F0"
        assert status.smeter is not None


def test_frequency_wire_format_matches_confirmed_backup_format():
    """RF must go over the wire as decimal MHz, e.g. "0145.50000" - the
    format confirmed from a real AR-DV10 Connect memory-bank backup
    export, not as a raw Hz integer."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(145_500_000)
        assert dev._transport.state["RF"] == "0145.50000"  # noqa: SLF001

        dev.set_frequency_hz(433_925_000)
        assert dev._transport.state["RF"] == "0433.92500"  # noqa: SLF001


def test_vfo_mode_write_rejection_gets_helpful_hint():
    """Confirmed against real hardware: RF/AC/SQ/AT writes are rejected with
    "?" while the receiver is browsing a memory channel instead of being in
    VFO mode. DV10Device should enrich that error with a hint rather than
    just surfacing a bare "?"."""
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

        # BP (beep) is confirmed to work regardless of VFO/memory mode - no
        # hint should be attached because there's no error to attach it to.
        dev.set_beep(True)


def test_vfo_mode_hint_not_added_for_unrelated_commands():
    """The VFO-mode hint is specifically for the RF/AC/SQ/AT-family write
    rejection (_VFO_MODE_WRITE_CODES) - an unrelated "?" (e.g. an unknown
    command, or AG's own separate, unresolved bare-read mystery) must not
    be mislabeled with it."""
    dev = DV10Device.open_simulator()
    with dev:
        try:
            dev.raw("ZZ", "1")  # unknown command -> "?", unrelated to VFO mode
        except DV10ProtocolError as exc:
            assert exc.hint is None
        else:
            raise AssertionError("expected DV10ProtocolError")


def test_raw_escape_hatch_reaches_undocumented_helpers():
    dev = DV10Device.open_simulator()
    with dev:
        # Confirmed against real hardware: a successful write's ack body is
        # EMPTY (not an echo of the argument, and not even a bare code
        # echo - see aor_dv10.transport.simulator's module docstring), so
        # resp.value is None here even though the
        # write itself took effect (checked via the follow-up read).
        resp = dev.raw("AT", "1")
        assert resp.value is None
        resp = dev.raw("AT")
        assert resp.value == "1"


def test_mode_info_decodes_confirmed_fm_digital_off():
    """"0F0" is what's actually been observed on real DV10 hardware: plain
    FM, digital off. Confirmed via the AR-DV3 spec's MD decode table."""
    dev = DV10Device.open_simulator()
    with dev:
        info = dev.get_mode_info()
        assert info.raw == "0F0"
        assert info.receiving_digital == "Auto"
        assert info.digital_select == "Digital off"
        assert info.analog_select == "FM"
        assert "FM" in dev.describe_mode()


def test_set_mode_reverses_field_order_for_the_wire_and_round_trips():
    """Regression test for two real-hardware bugs found in sequence.

    First: "m F1" (digital=F off, analog=1 AM - both valid codes) was
    rejected by the real DV10 with result code 40 (format error), because
    a bare "<digital><analog>" 2-char write isn't the wire's natural
    order. A reversed 2-char "<analog><digital>" write was tried next and
    stopped producing the format-40 error - but a later, more thorough
    live test (checking the read-back, not just the absence of an error)
    showed that a 2-char write in *either* order is silently accepted and
    never actually applied. The real wire format is a 3-character value
    in the SAME "dan" shape MD itself reads back - see
    aor_dv10.device._mode_write_value(). set_mode() takes the natural
    2-character "<digital><analog>" convention from callers and pads it
    into that 3-char wire shape internally, so "F1" (and the round trip
    below) succeed and actually take effect."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_mode("F0")
        info = dev.get_mode_info()
        assert info.raw == "0F0"
        assert info.digital_select == "Digital off"
        assert info.analog_select == "FM"

        # The exact input that failed on real hardware before this fix.
        dev.set_mode("F1")
        info = dev.get_mode_info()
        assert info.digital_select == "Digital off"
        assert info.analog_select == "AM"


def test_set_mode_rejects_unknown_codes_before_touching_the_wire():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(ValueError):
            dev.set_mode("X0")  # unknown digital code
        with pytest.raises(ValueError):
            dev.set_mode("0X")  # unknown analog code
        with pytest.raises(ValueError):
            dev.set_mode("F")  # wrong length
        with pytest.raises(ValueError):
            dev.set_mode("F00")  # wrong length


def test_smeter_reading_decodes_confirmed_vvvq_format():
    """LM's real format is vvvq: 3-digit -vvv dB level + 1-digit squelch
    state. "1001" (the simulator's default, matching values seen on real
    DV10) decodes to -100 dB with squelch open."""
    dev = DV10Device.open_simulator()
    with dev:
        reading = dev.get_smeter_reading()
        assert reading.dbm == -100
        assert reading.squelch_state == 1
        assert reading.squelch_open is True
        assert "-100" in reading.describe()


def test_squelch_mode_vs_level_are_distinct_commands():
    """SQ is the squelch *mode* selector (0=Auto,1=Noise,2=Level), not a
    level - LQ (level squelch) and NQ (noise squelch) carry the actual
    thresholds. Confirmed via the AR-DV3 spec."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_squelch_mode("2")
        assert dev.get_squelch_mode() == "2"
        # legacy aliases still work and hit the same SQ command
        assert dev.get_squelch() == "2"

        dev.set_squelch_level("42")
        assert dev.get_squelch_level() == "42"

        dev.set_noise_squelch_level("15")
        assert dev.get_noise_squelch_level() == "15"


def test_attenuator_state_is_tri_state_not_boolean():
    """AT is a 3-state selector (0=ATT OFF,1=ATT ON,2=10dB ATT) - the labels
    follow the real DV10's effect (1 engages the ~10dB signal attenuator),
    per user report, rather than the AR-DV3 spec's "AMP ON/AMP OFF" wording.
    Not a simple on/off boolean."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_attenuator_state("2")
        assert dev.get_attenuator_state() == "2"

        # legacy boolean wrapper maps onto two of the three real states:
        # on -> ATT ON (1), off -> ATT OFF (0)
        dev.set_attenuator(True)
        assert dev.get_attenuator_state() == "1"
        dev.set_attenuator(False)
        assert dev.get_attenuator_state() == "0"


def test_agc_speed_is_four_state_not_boolean():
    """AC is a 4-state AGC speed selector (0=Fast,1=Mid,2=Slow,3=RF-G),
    confirmed via the AR-DV3 spec - not a simple on/off boolean."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_agc_speed("3")
        assert dev.get_agc_speed() == "3"

        # legacy boolean wrapper still round-trips through the same command
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
    """Confirmed against real DV10 hardware: "raw VF A"
    succeeds where the earlier "VF 0"/"VF 1" digit guesses both failed.
    DV10Device.enter_vfo_mode() wraps this."""
    dev = DV10Device.open_simulator()
    with dev:
        dev._transport.vfo_mode = False  # noqa: SLF001
        dev.enter_vfo_mode("A")
        assert dev._transport.vfo_mode is True  # noqa: SLF001

        # and now a tuning write that needs VFO mode should go through
        dev.set_frequency_hz(146_520_000)
        assert dev.get_frequency_hz() == 146_520_000


def test_get_volume_bare_read_matches_confirmed_real_hardware_failure():
    """Confirmed against real DV10 hardware (via RE 1): a
    bare AG read returns result code 60 (command does not exist) - the
    simulator now models this as a real failure instead of quietly
    returning a stored value, matching status().volume coming back None on
    real hardware."""
    dev = DV10Device.open_simulator()
    with dev:
        try:
            dev.get_volume()
        except DV10ProtocolError as exc:
            assert exc.raw_response == "?"  # RE is off by default
        else:
            raise AssertionError("expected DV10ProtocolError")

        status = dev.status()
        assert status.volume is None


def test_set_volume_also_matches_confirmed_real_hardware_failure():
    """Confirmed against real DV10 hardware: it's not just the bare AG
    read that fails - AG *writes* are rejected with the same result code
    60 (command does not exist). This unit's firmware doesn't support AG
    at all remotely."""
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.set_volume("50")
