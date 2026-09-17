
from __future__ import annotations

import pytest

from aor_dv10.adif import parse_adif, write_adif
from aor_dv10.memory import empty_bank_set


def _channels():
    _, channels = empty_bank_set()
    by = {(c.bank, c.channel): c for c in channels}
    a = by[(0, 0)]
    a.frequency_hz = 145_500_000
    a.mode = "0F0"
    a.name = "CALL"
    a.pass_flag = True
    b = by[(1, 2)]
    b.frequency_hz = 7_030_000
    b.mode = "0F6"
    b.name = "CW QRP"
    return channels


def test_write_adif_has_header_and_records():
    text = write_adif(_channels())
    assert "<EOH>" in text
    assert "<EOR>" in text
    assert "<FREQ:10>145.500000" in text
    assert "<MODE:2>FM" in text
    assert "<NAME:4>CALL" in text
    assert "<MODE:2>CW" in text


def test_write_adif_digital_modes_become_data():
    channels = _channels()
    channels[0].mode = "070"
    text = write_adif(channels)
    assert "<MODE:4>DATA" in text


def test_adif_round_trip_preserves_frequency_and_mode():
    text = write_adif(_channels())
    _banks, back = parse_adif(text)
    by_name = {c.name: c for c in back if not c.is_empty}
    assert set(by_name) == {"CALL", "CW QRP"}
    assert by_name["CALL"].frequency_hz == 145_500_000
    assert by_name["CALL"].mode == "0F0"
    assert by_name["CW QRP"].frequency_hz == 7_030_000
    assert by_name["CW QRP"].mode == "0F6"


def test_parse_adif_accepts_hz_values_and_unknown_fields():
    text = "<CALL:5>SP9AB<FREQ:9>145500000<MODE:2>FM<EOR>"
    _banks, channels = parse_adif(text)
    prog = [c for c in channels if not c.is_empty]
    assert prog[0].frequency_hz == 145_500_000


def test_parse_adif_rejects_no_frequency():
    with pytest.raises(ValueError):
        parse_adif("<EOH><NAME:3>abc<EOR>")
