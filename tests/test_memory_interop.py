
from __future__ import annotations

import json

import pytest

from aor_dv10.memory import (
    backup_from_json,
    backup_to_json,
    empty_bank_set,
    parse_chirp_csv,
    parse_generic_freq_csv,
    write_chirp_csv,
)


def _programmed_set():
    banks, channels = empty_bank_set()
    by = {(c.bank, c.channel): c for c in channels}
    c = by[(0, 0)]
    c.frequency_hz = 145_500_000
    c.step_hz = 12_500
    c.mode = "0F0"
    c.name = "CALL"
    c.pass_flag = True
    c2 = by[(3, 7)]
    c2.frequency_hz = 7_030_000
    c2.step_hz = 5_000
    c2.mode = "0F6"
    c2.name = "CW QRP"
    return banks, channels


def test_chirp_export_has_header_and_only_programmed_rows():
    _, channels = _programmed_set()
    text = write_chirp_csv(channels)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[0].startswith("Location,Name,Frequency")
    assert len(lines) == 3
    assert "CALL" in text
    assert "145.500000" in text
    assert "7.030000" in text


def test_chirp_export_skip_flag_and_mode():
    _, channels = _programmed_set()
    text = write_chirp_csv(channels)
    rows = {r.split(",")[1]: r for r in text.splitlines()[1:] if r.strip()}
    call = rows["CALL"]
    assert ",FM," in call
    assert call.rstrip().endswith(",S") or ",S," in call
    assert ",CW," in rows["CW QRP"]


def test_chirp_round_trip_preserves_programmed_channels():
    _, channels = _programmed_set()
    text = write_chirp_csv(channels)
    banks, back = parse_chirp_csv(text)
    assert len(banks) == 40
    assert len(back) == 40 * 50
    by_name = {c.name: c for c in back if not c.is_empty}
    assert set(by_name) == {"CALL", "CW QRP"}
    assert by_name["CALL"].frequency_hz == 145_500_000
    assert by_name["CALL"].step_hz == 12_500
    assert by_name["CALL"].mode == "0F0"
    assert by_name["CALL"].pass_flag is True
    assert by_name["CW QRP"].frequency_hz == 7_030_000
    assert by_name["CW QRP"].mode == "0F6"


def test_chirp_name_truncated_to_eight_chars():
    _, channels = _programmed_set()
    channels[0].name = "VERYLONGNAME"
    text = write_chirp_csv(channels)
    assert "VERYLONG" in text
    assert "VERYLONGN" not in text


def test_chirp_import_rejects_non_chirp_csv():
    with pytest.raises(ValueError):
        parse_chirp_csv("some,other,header\n1,2,3\n")


def test_chirp_import_locations_map_to_bank_channel():
    header = "Location,Name,Frequency,Mode,TStep,Skip\n"
    row = "51,EDGE,145.500000,FM,5.00,\n"
    _, channels = parse_chirp_csv(header + row)
    by = {(c.bank, c.channel): c for c in channels}
    assert by[(1, 1)].frequency_hz == 145_500_000


def test_json_round_trip_is_lossless():
    banks, channels = _programmed_set()
    banks[2].title = "BANK TWO"
    banks[2].protect = True
    text = backup_to_json(banks, channels)
    assert json.loads(text)["format"] == "aor-dv10-suite.memory"
    banks2, channels2 = backup_from_json(text)
    assert len(banks2) == 40
    assert len(channels2) == 40 * 50
    b2 = {b.index: b for b in banks2}
    assert b2[2].title == "BANK TWO"
    assert b2[2].protect is True
    by = {(c.bank, c.channel): c for c in channels2}
    assert by[(0, 0)].frequency_hz == 145_500_000
    assert by[(0, 0)].pass_flag is True
    assert by[(3, 7)].mode == "0F6"


def test_json_partial_snapshot_still_yields_full_layout():
    text = json.dumps({
        "format": "aor-dv10-suite.memory",
        "version": 1,
        "banks": [{"index": 0, "protect": False, "title": "X"}],
        "channels": [{"bank": 0, "channel": 0, "frequency_hz": 100_000_000,
                      "step_hz": None, "offset_khz": None, "mode": "0F0",
                      "pass_flag": False, "name": "ONLY", "protect": False}],
    })
    banks, channels = backup_from_json(text)
    assert len(banks) == 40 and len(channels) == 40 * 50
    by = {(c.bank, c.channel): c for c in channels}
    assert by[(0, 0)].name == "ONLY"
    assert by[(39, 49)].is_empty


def test_json_rejects_foreign_format():
    with pytest.raises(ValueError):
        backup_from_json('{"format": "something-else"}')
    with pytest.raises(ValueError):
        backup_from_json("not json at all")




def test_generic_freq_csv_with_header():
    text = "Frequency,Name,Mode,Step\n145.500000,CALL,FM,12.5\n7.030000,QSO,CW,5\n"
    _banks, channels = parse_generic_freq_csv(text)
    prog = [c for c in channels if not c.is_empty]
    assert len(prog) == 2
    assert prog[0].frequency_hz == 145_500_000
    assert prog[0].name == "CALL"
    assert prog[0].mode == "0F0"
    assert prog[0].step_hz == 12_500
    assert prog[1].frequency_hz == 7_030_000
    assert prog[1].mode == "0F6"


def test_generic_freq_csv_headerless_positional():
    text = "145.500000,CALL,FM,12.5\n433.500000,70cm,FM,25\n"
    _banks, channels = parse_generic_freq_csv(text)
    prog = [c for c in channels if not c.is_empty]
    assert [c.name for c in prog] == ["CALL", "70cm"]
    assert prog[1].frequency_hz == 433_500_000


def test_generic_freq_csv_accepts_hz_values():
    text = "frequency,name\n145500000,IN HZ\n"
    _banks, channels = parse_generic_freq_csv(text)
    prog = [c for c in channels if not c.is_empty]
    assert prog[0].frequency_hz == 145_500_000


def test_generic_freq_csv_aliases_case_insensitive():
    text = "MHz,Label,Modulation\n145.5,hi,USB\n"
    _banks, channels = parse_generic_freq_csv(text)
    prog = [c for c in channels if not c.is_empty]
    assert prog[0].name == "hi"
    assert prog[0].mode == "0F4"


def test_generic_freq_csv_rejects_empty():
    with pytest.raises(ValueError):
        parse_generic_freq_csv("")
    with pytest.raises(ValueError):
        parse_generic_freq_csv("name,note\nfoo,bar\n")
