"""Regression tests for six correctness issues, fixed against the AR-DV1
wire-protocol spec (via direct PDF verification): CN index-based not
literal freq, PP no-hyphen bbcc,
OF/OL combined-write rework, BP/LN/RG range+default corrections, LM
squelch-state table, and MM's two-phase CommandChannel-level response.

Each test here exists specifically to catch a regression back to the
*previous*, now-known-wrong behaviour - not just to check today's
behaviour is self-consistent.
"""

import pytest

from aor_dv10.device import CTCSS_TONES_HZ, DV10Device, SQUELCH_STATES
from aor_dv10.protocol.codec import DV10ProtocolError


# -- 1. CN: index-based, not literal frequency --------------------------------

def test_cn_is_sent_as_a_table_index_not_a_literal_frequency():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_tone_squelch_freq("100.0")
        # "100.0" is CTCSS_TONES_HZ[13] (0-based) -> wire index "14"
        assert CTCSS_TONES_HZ[13] == "100.0"
        raw = dev._chan.read("CN").value
        assert raw == "14", f"expected index '14' on the wire, got {raw!r}"
        # and it decodes back to the human-readable tone via the public API
        assert dev.get_tone_squelch_freq() == "100.0"


def test_cn_search_and_no_tone_roundtrip():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_tone_squelch_freq("SRCH")
        assert dev._chan.read("CN").value == "99"
        assert dev.get_tone_squelch_freq() == "SRCH"


def test_cn_rejects_off_and_unknown_tones():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(ValueError):
            dev.set_tone_squelch_freq("OFF")
        with pytest.raises(ValueError):
            dev.set_tone_squelch_freq("999.9")


def test_cn_decodes_the_mid_search_4digit_shape():
    from aor_dv10.device import _decode_cn

    assert _decode_cn("9901") == CTCSS_TONES_HZ[0]
    assert _decode_cn("9900") == ""
    assert _decode_cn("99") == "SRCH"
    assert _decode_cn("00") == ""


# -- DS: SRCH must map to the wire value, not the literal string --------------

def test_ds_search_maps_to_999_not_the_literal_string():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_dcs_code("SRCH")
        assert dev._chan.read("DS").value == "999"
        assert dev.get_dcs_code() == "SRCH"
        with pytest.raises(ValueError):
            dev.set_dcs_code("OFF")


# -- 2. PP: bbcc, no hyphen on the wire ----------------------------------------

def test_pp_is_sent_with_no_separator_on_the_wire():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_priority_channel(3, 12)
        raw = dev._chan.read("PP").value
        assert raw == "0312", f"expected 'bbcc' with no hyphen on the wire, got {raw!r}"
        # display form still shows the hyphen for readability
        assert dev.get_priority_channel() == "03-12"


# -- 3. OF/OL: direction sign + combined slot/frequency write -----------------

def test_of_carries_an_explicit_direction_sign():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_offset_slot(5, "+")
        assert dev._chan.read("OF").value == "+05"
        dev.set_offset_slot(6, "-")
        assert dev._chan.read("OF").value == "-06"
        # slot 00 omits the sign entirely
        dev.set_offset_slot(0)
        assert dev._chan.read("OF").value == "00"
        with pytest.raises(ValueError):
            dev.set_offset_slot(5, "x")


def test_ol_write_combines_slot_and_frequency_and_read_requires_a_slot():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_offset_freq(7, 0.6)
        assert dev.get_offset_freq(7) == "0000.60000"
        dev.set_offset_freq(1, 12.5)
        assert dev.get_offset_freq(1) == "0012.50000"
        # unrelated slots are untouched
        assert dev.get_offset_freq(2) == "0000.00000"


def test_ol_frequency_field_is_unsigned():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(ValueError):
            dev.set_offset_freq(5, -0.6)


def test_ol_factory_preset_slots_reject_writes():
    dev = DV10Device.open_simulator()
    with dev:
        with pytest.raises(DV10ProtocolError):
            dev.set_offset_freq(20, 1.0)


# -- 4. BP/LN/RG: range and wire-format corrections ----------------------------

def test_bp_is_a_single_digit_0_to_7_not_two_digit_00_to_15():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_beep_level(7)
        assert dev._chan.read("BP").value == "7"
        # the old 00-15 range's upper half is now out of range and rejected
        with pytest.raises(DV10ProtocolError):
            dev.set_beep_level(9)


def test_ln_default_and_range_match_the_ar_dv1_spec():
    # Format (2-digit) is unchanged; this just exercises the corrected
    # 00-63 range's new upper bound (the old 00-40 range topped out at 40).
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_lcd_contrast(63)
        assert dev.get_lcd_contrast() == "63"


def test_rg_default_and_range_match_the_ar_dv1_spec():
    # Format (3-digit) is unchanged; this exercises the corrected 000-110
    # range's new upper bound (the old assumption topped out at 255).
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_manual_gain(110)
        assert dev.get_manual_gain() == "110"


# -- 5. LM: corrected squelch-state digit meaning ------------------------------

def test_squelch_states_table_matches_the_ar_dv1_spec():
    assert SQUELCH_STATES[0] == "closed"
    assert "noise" in SQUELCH_STATES[1] and "level" in SQUELCH_STATES[1]
    assert "tone" in SQUELCH_STATES[2] and "dcs" in SQUELCH_STATES[2].lower()
    assert "digital" in SQUELCH_STATES[3]
    # the previous (wrong) table claimed state 3 was another squelch-open
    # variant ("LevelSQ/NoiseSQ") rather than "detecting digital mode" -
    # make sure that meaning is gone.
    assert "levelsq" not in SQUELCH_STATES[3].lower()


def test_smeter_reading_describe_uses_the_corrected_table():
    dev = DV10Device.open_simulator()
    with dev:
        dev._chan.write("LM", "1003")  # -100dB, state 3 = detecting digital mode
        reading = dev.get_smeter_reading()
        assert reading.dbm == -100
        assert reading.squelch_state == 3
        assert "digital" in reading.describe()


# -- 6. MM: two-phase (21 then 20) response, CommandChannel awareness ---------

def test_mm_two_phase_response_is_fully_consumed():
    """The main scenario: register_last_channel() must return the final
    20 (not the intermediate 21), and must leave nothing stray behind for
    the next command to accidentally consume."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_result_code_prefixing(True)
        result = dev.register_last_channel()
        assert result == 20
        # if the "20" completion line had been left unconsumed, THIS read
        # would get it instead of BP's real value, and fail to parse as a
        # valid beep level.
        dev.set_beep_level(3)
        assert dev.get_beep_level() == "3"


def test_mm_leaves_a_second_line_that_a_naive_single_read_would_miss():
    """Demonstrates the exact bug this project's CommandChannel used to be
    exposed to: send()-ing "MM" alone only ever consumes ONE line, so
    without read_pending() the "20" completion is left sitting in the
    transport buffer."""
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_result_code_prefixing(True)
        first = dev._chan.send("MM")
        assert first.result_code == 21
        leftover = dev._chan.read_pending(timeout=0.2)
        assert leftover is not None
        assert leftover.result_code == 20
        # and now nothing is left pending
        assert dev._chan.read_pending(timeout=0.05) is None


def test_mm_with_re_off_returns_after_the_single_available_line():
    dev = DV10Device.open_simulator()
    with dev:
        result = dev.register_last_channel()
        assert result == 20  # nothing to disambiguate; treated as done
        # and nothing was left dangling for the next command
        dev.set_beep_level(4)
        assert dev.get_beep_level() == "4"
