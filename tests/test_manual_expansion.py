"""Round-trip tests for the manual-sourced expansion (tuning
step, advanced squelch, digital selective codes, offset/priority
reception, and the audio/display/misc settings) - see
aor_dv10.device's manual-sourced tables for the confidence caveats.
These pin the simulator's/device's *current* best-guess wire encoding so a
future real-hardware correction shows up as a clear, intentional diff
here rather than a silent behaviour change.
"""

import pytest

from aor_dv10.device import DV10Device, TONE_SQUELCH_TYPES


def test_tuning_step_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        # ST and SH share the same kHz-decimal wire format ("nnn.nn"),
        # confirmed against real hardware for both - see
        # DV10Device.get_frequency_step_hz()/get_step_adjust_hz().
        dev.set_frequency_step_hz(25000)
        assert dev.get_frequency_step_hz() == 25000

        dev.set_step_adjust_hz(500)
        assert dev.get_step_adjust_hz() == 500


def test_ctcss_and_dcs_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_tone_squelch_enabled(True)
        assert dev.get_tone_squelch_enabled() == "1"
        dev.set_tone_squelch_freq("100.0")
        assert dev.get_tone_squelch_freq() == "100.0"

        dev.set_dcs_enabled(True)
        assert dev.get_dcs_enabled() == "1"
        dev.set_dcs_code("023")
        assert dev.get_dcs_code() == "023"


# -- CI (tone squelch type): confirmed 3-value, not a boolean -----------
#
# Live-tested against a real DV10: the front panel's SQL TYPE menu
# showing "REV.T" (Reverse Tone) read back as CI="2" (DI="0"); showing
# "DCS" read back as CI="0" (DI="1") - confirming DCS is DI's own
# independent flag, not one of CI's values. "1"=CTCSS is inferred by
# elimination (SQL TYPE's remaining choice), not independently read back
# from the front panel - see TONE_SQUELCH_TYPES's comment in device.py.


def test_squelch_tone_type_roundtrips_every_confirmed_value():
    dev = DV10Device.open_simulator()
    with dev:
        for value, label in TONE_SQUELCH_TYPES.items():
            dev.set_squelch_tone_type(value)
            assert dev.get_squelch_tone_type() == value, label


def test_squelch_tone_type_rejects_unknown_value():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(ValueError):
            dev.set_squelch_tone_type("9")


def test_squelch_tone_type_and_dcs_enabled_are_independent_fields():
    # The real-hardware finding this whole table is built on: selecting
    # DCS on the front panel's SQL TYPE menu flips DI, not CI - the two
    # commands are independent wire fields, confirmed by reading both
    # back at once (CI="0"/DI="1" while the panel showed "DCS").
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_squelch_tone_type("2")  # Reverse Tone
        dev.set_dcs_enabled(True)
        assert dev.get_squelch_tone_type() == "2"
        assert dev.get_dcs_enabled() == "1"


def test_digital_selective_codes_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_dmr_color_code(7)
        assert dev.get_dmr_color_code() == "07"
        dev.set_dmr_mute_by_color_code(True)
        assert dev.get_dmr_mute_by_color_code() == "1"
        dev.set_dmr_slot("1")
        assert dev.get_dmr_slot() == "1"

        dev.set_p25_nac("1a2")
        assert dev.get_p25_nac() == "1A2"
        dev.set_p25_mute_by_nac(True)
        assert dev.get_p25_mute_by_nac() == "1"

        dev.set_nxdn_ran(42)
        assert dev.get_nxdn_ran() == "42"
        dev.set_nxdn_mute_by_ran(True)
        assert dev.get_nxdn_mute_by_ran() == "1"

        dev.set_dcr_descramble_code(12345)
        assert dev.get_dcr_descramble_code() == "12345"


def test_analog_descrambler_and_offset_and_priority_roundtrip():
    # Offset (OF/OL), against the AR-DV1 wire spec: OF
    # carries an explicit slot + direction sign, OL carries an unsigned
    # frequency and always needs the slot number - see
    # DV10Device.set_offset_slot()/get_offset_freq().
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_voice_descrambler_enabled(True)
        assert dev.get_voice_descrambler_enabled() == "1"
        assert dev.get_voice_descrambler_freq() == "2000"

        dev.set_offset_slot(5, "+")
        assert dev.get_offset_slot() == "+05"
        dev.set_offset_freq(5, 0.6)
        assert dev.get_offset_freq(5) == "0000.60000"

        dev.set_offset_slot(6, "-")
        assert dev.get_offset_slot() == "-06"
        dev.set_offset_freq(6, 1.5)
        assert dev.get_offset_freq(6) == "0001.50000"

        # slot 00 disables offset reception and needs no sign
        dev.set_offset_slot(0)
        assert dev.get_offset_slot() == "00"

        # OL's frequency field is unsigned - a negative mhz is rejected
        # client-side rather than silently sent wrong.
        with pytest.raises(ValueError):
            dev.set_offset_freq(5, -0.6)

        dev.set_priority_enabled(True)
        assert dev.get_priority_enabled() == "1"
        dev.set_priority_channel(3, 12)
        assert dev.get_priority_channel() == "03-12"  # display form; wire form is "0312", see get_priority_channel()
        dev.set_priority_interval(30)
        assert dev.get_priority_interval() == "30"


def test_beep_level_replaces_boolean_assumption():
    """BP is a volume level, not on/off. Range/wire-format corrected
    against the AR-DV1 wire spec: a SINGLE digit 0-7 (not the two-digit
    00-15 originally assumed) - see DV10Device.get_beep_level()."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_beep_level(6)
        assert dev.get_beep_level() == "6"
        # legacy boolean wrapper still works, mapped to sensible levels
        dev.set_beep(True)
        assert dev.get_beep_level() == "2"
        dev.set_beep(False)
        assert dev.get_beep_level() == "0"


def test_audio_gain_and_display_settings_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_volume_limit(3)
        assert dev.get_volume_limit() == "03"
        dev.set_digital_gain(5.5)
        assert dev.get_digital_gain() == "05.50"
        dev.set_manual_gain(200)
        assert dev.get_manual_gain() == "200"
        dev.set_lcd_contrast(10)
        assert dev.get_lcd_contrast() == "10"
        dev.set_backlight_mode("2")
        assert dev.get_backlight_mode() == "2"


def test_misc_settings_and_actions():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_clock(26, 1, 30, 15, 0)
        assert dev.get_clock() == "2601301500"
        dev.set_receiver_id("ABCD")
        assert dev.get_receiver_id() == "ABCD"
        dev.set_write_protect(True)
        assert dev.get_write_protect() == "1"
        # actions should not raise
        dev.move_next()
        dev.move_previous()
        dev.reset(full=False)
        # get_vfo_info() was a placeholder stub returning the simulator's
        # old fixed "VFOA" state string - replaced by read_vfo_info(), now
        # that VI's real 3-line (A/B/Z) response shape is confirmed - see
        # tests/test_vfo.py for the dedicated coverage.
        vfos = dev.read_vfo_info()
        assert len(vfos) == 3
        assert {v.vfo for v in vfos} == {"A", "B", "Z"}
