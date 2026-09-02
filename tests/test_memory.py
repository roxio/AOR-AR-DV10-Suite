"""Tests for aor_dv10.memory - the "AR-DV10 Connect" backup CSV parser/
writer - against a real 2041-line export
(tests/fixtures/ARDV10_ConnectExport_sample.csv). This is a pure
file-format feature with no live-device interaction: see memory.py's
module docstring for why that split matters here.
"""

from pathlib import Path

import pytest

from aor_dv10.memory import (
    MemoryBank,
    MemoryChannel,
    empty_bank_set,
    parse_backup_csv,
    write_backup_csv,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ARDV10_ConnectExport_sample.csv"


def _load_fixture_text() -> str:
    return FIXTURE.read_bytes().decode("utf-8-sig")


def test_parses_real_export_counts():
    banks, channels = parse_backup_csv(_load_fixture_text())
    assert len(banks) == 40
    assert len(channels) == 2000
    # every bank index 0-39 present exactly once
    assert sorted(b.index for b in banks) == list(range(40))
    # every (bank, channel) slot 0-39 x 0-49 present exactly once
    assert sorted((c.bank, c.channel) for c in channels) == [
        (b, c) for b in range(40) for c in range(50)
    ]


def test_bank_zero_title_and_unnamed_bank():
    banks, _ = parse_backup_csv(_load_fixture_text())
    by_index = {b.index: b for b in banks}
    assert by_index[0].title == "---"
    assert by_index[0].protect is False
    assert by_index[1].title == ""


def test_known_programmed_channel_fields():
    """Bank 00, channel 00 - the first programmed channel in the real
    export: 145.5 MHz, 12.5 kHz step, no offset, analog FM (mode "000"),
    named "CH-001"."""
    _, channels = parse_backup_csv(_load_fixture_text())
    ch = next(c for c in channels if c.bank == 0 and c.channel == 0)
    assert ch.is_empty is False
    assert ch.frequency_hz == 145_500_000
    assert ch.frequency_mhz == pytest.approx(145.5)
    assert ch.step_hz == 12_500
    assert ch.offset_khz == 0.0
    assert ch.mode == "000"
    assert ch.protect is False
    assert ch.pass_flag is False
    assert ch.name == "CH-001"
    assert ch.bank_channel == "00-00"


def test_unprogrammed_channel_is_empty():
    _, channels = parse_backup_csv(_load_fixture_text())
    # bank 04, channel 00 is one of the 1531 unprogrammed slots in the
    # real export - still present as a row (per the module docstring),
    # but every field but bank/channel/name is blank
    ch = next(c for c in channels if c.bank == 4 and c.channel == 0)
    assert ch.is_empty is True
    assert ch.frequency_hz is None
    assert ch.frequency_mhz is None
    assert ch.name == ""

    empties = [c for c in channels if c.is_empty]
    assert len(empties) == 1531


def test_protected_channels_and_digital_mode_variant():
    """The real export has exactly 2 protect=1 channels and 2 distinct
    mode codes ("000" analog-only, "0F0" one digital variant) - pinning
    both so a fixture regeneration would be noticed."""
    _, channels = parse_backup_csv(_load_fixture_text())
    programmed = [c for c in channels if not c.is_empty]
    assert len(programmed) == 469

    protected = [c for c in channels if c.protect]
    assert len(protected) == 2
    assert {c.bank_channel for c in protected} == {"02-00", "03-16"}

    modes = {c.mode for c in programmed}
    assert modes == {"000", "0F0"}

    # no pass_flag observed anywhere in this sample - documented as an
    # open question in memory.py, not asserted as a general truth
    assert all(c.pass_flag is False for c in channels)


def test_roundtrip_is_byte_exact_against_real_export():
    """write_backup_csv(parse_backup_csv(x)) must reproduce the original
    file line-for-line (modulo the BOM, which write_backup_csv leaves to
    the caller - see its docstring). This is the real correctness bar for
    a backup-file feature: a lossy round-trip could silently drop a
    user's programmed channels on re-export."""
    text = _load_fixture_text()
    orig_lines = text.split("\r\n")
    if orig_lines and orig_lines[-1] == "":
        orig_lines = orig_lines[:-1]

    banks, channels = parse_backup_csv(text)
    timestamp = orig_lines[0].split(",", 4)[4]
    out = write_backup_csv(banks, channels, timestamp=timestamp)
    out_lines = out.split("\r\n")
    if out_lines and out_lines[-1] == "":
        out_lines = out_lines[:-1]

    assert out_lines == orig_lines


def test_write_backup_csv_is_crlf_terminated():
    banks, channels = empty_bank_set()
    out = write_backup_csv(banks, channels, timestamp="01.01.2026 00:00:00")
    assert out.startswith("DEPMICRO-BACKUP,MEM BANK,AR-DV10,P,01.01.2026 00:00:00\r\n")
    assert out.endswith("\r\n")
    assert "\n\n" not in out.replace("\r\n", "\n")  # no bare LF anywhere
    assert "\r\n" in out


def test_empty_bank_set_shape():
    banks, channels = empty_bank_set()
    assert len(banks) == 40
    assert len(channels) == 2000
    assert all(c.is_empty for c in channels)
    assert all(b.title == "" and b.protect is False for b in banks)


def test_describe_mode():
    ch = MemoryChannel(bank=0, channel=0, frequency_hz=145_000_000, mode="0F0")
    # "d a n" positions: d=receiving flag (ignored here), a=digital
    # select, n=analog select - describe_mode() looks up a/n only
    described = ch.describe_mode()
    assert " / " in described
    assert MemoryChannel(bank=0, channel=0).describe_mode() == "?"  # no mode set


def test_bad_header_raises():
    with pytest.raises(ValueError, match="AR-DV10 Connect"):
        parse_backup_csv("NOT,A,VALID,HEADER\r\n")


def test_bad_field_count_raises():
    text = "DEPMICRO-BACKUP,MEM BANK,AR-DV10,P,01.01.2026\r\nMB,00,0\r\n"
    with pytest.raises(ValueError, match="MB record"):
        parse_backup_csv(text)


def test_unrecognised_record_type_raises():
    text = "DEPMICRO-BACKUP,MEM BANK,AR-DV10,P,01.01.2026\r\nXX,00,0,foo\r\n"
    with pytest.raises(ValueError, match="unrecognised record type"):
        parse_backup_csv(text)


def test_bank_and_channel_to_csv_row_padding():
    bank = MemoryBank(index=5, protect=True, title="TEST")
    assert bank.to_csv_row() == "MB,05,1,TEST        "

    empty = MemoryChannel(bank=1, channel=2)
    assert empty.to_csv_row() == "MC,0102,,,,,,,            "

    full = MemoryChannel(
        bank=1,
        channel=2,
        protect=True,
        frequency_hz=433_500_000,
        step_hz=25_000,
        offset_khz=-0.6,
        mode="000",
        pass_flag=True,
        name="TEST",
    )
    assert full.to_csv_row() == "MC,0102,1,0433.50000,025.00,-00.60,000,1,TEST        "
