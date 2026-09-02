"""Regression tests for the TR scheduled
recording/alarm timer - both the standalone encode/decode helpers in
aor_dv10.timer and the device.py glue
(write_recording_timer()/read_recording_timer()). See aor_dv10.timer's
module docstring for the significant spec-reconstruction caveats this
command carries (the AR-DV1 spec PDF's own table entry for TR is
internally inconsistent) before trusting any particular field, especially
``timer_type``/TY (its meaning is never defined anywhere in the spec) and
``weekdays``/WE (the spec never states this field's wire width). All
against the simulator; nothing here has been checked against real
hardware.
"""

import pytest

from aor_dv10.device import DV10Device
from aor_dv10.timer import (
    RecordingTimer,
    SATURDAY,
    SUNDAY,
    WEDNESDAY,
    format_once_time,
    format_timer_value,
    format_weekday_mask,
    format_weekly_time,
    parse_timer_response,
    parse_timer_time,
    parse_weekday_mask,
    receive_mode_memory_channel,
    receive_mode_memory_scan,
    receive_mode_search_bank,
    receive_mode_vfo,
    receive_mode_vfo_search,
)


# -- aor_dv10.timer standalone helpers ---------------------------------------


def test_receive_mode_helpers_build_expected_tokens():
    assert receive_mode_vfo("a") == "VFA"
    assert receive_mode_vfo_search() == "VS"
    assert receive_mode_search_bank(3) == "SS03"
    assert receive_mode_memory_channel(1, 5) == "MR0105"
    assert receive_mode_memory_scan(7) == "MS07"


def test_receive_mode_vfo_rejects_invalid_letter():
    with pytest.raises(ValueError):
        receive_mode_vfo("Q")


def test_format_and_parse_once_time_roundtrip():
    raw = format_once_time(3, 15, 9, 30)
    assert raw == "03150930"
    assert parse_timer_time("once", raw) == {"month": 3, "day": 15, "hour": 9, "minute": 30}


def test_format_and_parse_weekly_time_roundtrip():
    raw = format_weekly_time(8, 0)
    assert raw == "0800"
    assert parse_timer_time("weekly", raw) == {"hour": 8, "minute": 0}


def test_parse_timer_time_returns_empty_dict_for_unparseable_input():
    assert parse_timer_time("once", "bad") == {}
    assert parse_timer_time("weekly", "12345") == {}


def test_format_and_parse_weekday_mask_roundtrip():
    raw = format_weekday_mask((SUNDAY, WEDNESDAY, SATURDAY))
    assert raw == str(1 + 8 + 64)
    assert parse_weekday_mask(raw) == (SUNDAY, WEDNESDAY, SATURDAY)


def test_parse_weekday_mask_rejects_non_digit():
    assert parse_weekday_mask("abc") == ()


def test_format_timer_value_action_always_present():
    v = format_timer_value(RecordingTimer(action="off"))
    assert v == "XE0"


def test_format_timer_value_rejects_invalid_action():
    with pytest.raises(ValueError):
        format_timer_value(RecordingTimer(action="bogus"))


def test_format_timer_value_full_fields_in_spec_order():
    t = RecordingTimer(
        action="recording",
        timer_type=1,
        repeat="once",
        receive_mode="VFA",
        start="03150900",
        end="03150930",
        weekdays=(SUNDAY,),
        alarm_volume=50,
    )
    assert format_timer_value(t) == "XE2 TY1 RP0 RMVFA TS03150900 TE03150930 WE1 AG50"


def test_parse_timer_response_roundtrips_format_timer_value():
    t = RecordingTimer(
        action="alarm",
        repeat="weekly",
        receive_mode=receive_mode_search_bank(2),
        start="0800",
        end="0830",
        weekdays=(SUNDAY, WEDNESDAY),
        alarm_volume=10,
    )
    parsed = parse_timer_response(format_timer_value(t))
    assert parsed.action == "alarm"
    assert parsed.repeat == "weekly"
    assert parsed.receive_mode == "SS02"
    assert set(parsed.weekdays) == {SUNDAY, WEDNESDAY}
    assert parsed.alarm_volume == 10


# -- device.py glue -----------------------------------------------------------


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


def test_read_recording_timer_default_matches_spec_default_line(dev):
    # AR-DV1 spec's own "Default: TRn XE0 TY0 RMVFA TS01010000 TE01010000".
    t = dev.read_recording_timer()
    assert t.action == "off"
    assert t.receive_mode == "VFA"
    assert t.start == "01010000"
    assert t.end == "01010000"


def test_write_then_read_recording_timer_roundtrip(dev):
    dev.write_recording_timer(
        RecordingTimer(
            action="recording",
            repeat="once",
            receive_mode=receive_mode_vfo("B"),
            start=format_once_time(3, 15, 9, 0),
            end=format_once_time(3, 15, 9, 30),
            alarm_volume=50,
        )
    )
    t = dev.read_recording_timer()
    assert t.action == "recording"
    assert t.receive_mode == "VFB"
    assert t.start == "03150900"
    assert t.alarm_volume == 50


def test_write_recording_timer_omitted_fields_keep_previous(dev):
    dev.write_recording_timer(
        RecordingTimer(action="recording", receive_mode=receive_mode_vfo("B"), start="03150900")
    )
    dev.write_recording_timer(RecordingTimer(action="alarm"))  # everything else omitted
    t = dev.read_recording_timer()
    assert t.action == "alarm"
    assert t.receive_mode == "VFB"  # kept
    assert t.start == "03150900"  # kept


def test_recording_timer_deactivate(dev):
    dev.write_recording_timer(RecordingTimer(action="recording"))
    dev.write_recording_timer(RecordingTimer(action="off"))
    assert dev.read_recording_timer().action == "off"


def test_weekly_schedule_with_memory_channel_receive_mode(dev):
    dev.write_recording_timer(
        RecordingTimer(
            action="recording",
            repeat="weekly",
            receive_mode=receive_mode_memory_channel(1, 5),
            start=format_weekly_time(8, 0),
            end=format_weekly_time(8, 30),
            weekdays=(SUNDAY, WEDNESDAY, SATURDAY),
        )
    )
    t = dev.read_recording_timer()
    assert t.repeat == "weekly"
    assert t.receive_mode == "MR0105"
    assert set(t.weekdays) == {SUNDAY, WEDNESDAY, SATURDAY}
