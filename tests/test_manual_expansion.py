
import pytest

from aor_dv10.device import DV10Device, TONE_SQUELCH_TYPES


def test_tuning_step_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
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
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_squelch_tone_type("2")
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

        dev.set_offset_slot(0)
        assert dev.get_offset_slot() == "00"

        with pytest.raises(ValueError):
            dev.set_offset_freq(5, -0.6)

        dev.set_priority_enabled(True)
        assert dev.get_priority_enabled() == "1"
        dev.set_priority_channel(3, 12)
        assert dev.get_priority_channel() == "03-12"
        dev.set_priority_interval(30)
        assert dev.get_priority_interval() == "30"


def test_beep_level_replaces_boolean_assumption():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_beep_level(6)
        assert dev.get_beep_level() == "6"
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
        dev.move_next()
        dev.move_previous()
        dev.reset(full=False)
        vfos = dev.read_vfo_info()
        assert len(vfos) == 3
        assert {v.vfo for v in vfos} == {"A", "B", "Z"}
