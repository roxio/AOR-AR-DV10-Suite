
from __future__ import annotations

import pytest

from aor_dv10.command_utils import (
    WEEKDAY_BITS,
    on_off,
    parse_bank_link_tokens,
    parse_clock_digits,
    split_command,
)


def test_on_off_accepts_common_forms():
    assert on_off("on") is True
    assert on_off("1") is True
    assert on_off("TRUE") is True
    assert on_off("off") is False
    assert on_off("0") is False
    with pytest.raises(ValueError):
        on_off("maybe")


def test_split_command_preserves_windows_backslashes():
    assert split_command(r'load C:\Users\me\file.csv') == ["load", r"C:\Users\me\file.csv"]
    assert split_command('mem export "C:\\Program Files\\x.csv"') == ["mem", "export", r"C:\Program Files\x.csv"]


def test_parse_clock_digits_raw_and_friendly():
    assert parse_clock_digits("2601301500") == (26, 1, 30, 15, 0)
    assert parse_clock_digits("26-01-30 15:00") == (26, 1, 30, 15, 0)
    with pytest.raises(ValueError):
        parse_clock_digits("123")


def test_parse_bank_link_tokens_clear_vs_list():
    assert parse_bank_link_tokens(["clear"]) == []
    assert parse_bank_link_tokens(["0", "3", "39"]) == [0, 3, 39]


def test_weekday_bits_are_powers_of_two():
    assert WEEKDAY_BITS["sun"] == 1
    assert WEEKDAY_BITS["sat"] == 64
    assert sorted(WEEKDAY_BITS.values()) == [1, 2, 4, 8, 16, 32, 64]
