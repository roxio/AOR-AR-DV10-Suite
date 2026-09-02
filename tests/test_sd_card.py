"""Regression tests for SD card management - SD
DIR/INF/PST/REC/PLY/RSQ/MMW/MMR. See src/aor_dv10/device.py's "SD card
management" section for the significant spec-reconstruction caveats this
carries (notably the
"SYSYEM" [sic] backup-kind token, confirmed as a real spec typo via two
independent extraction methods, and why SD LGR/SD TYP are deliberately
left `raw`-only - the spec's own summary table marks both "No function"
on this receiver). All against the simulator; nothing here has been
checked against real hardware.
"""

import pytest

from aor_dv10.device import (
    DV10Device,
    SD_BACKUP_KIND_ALL,
    SD_BACKUP_KIND_MEMORY_CHANNEL,
    SD_BACKUP_KIND_SCAN_GROUP,
    SD_BACKUP_KIND_SEARCH_BANK,
    SD_BACKUP_KIND_SEARCH_GROUP,
    SD_CARD_STATUS,
)
from aor_dv10.protocol.codec import DV10ProtocolError


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


# -- SD DIR / SD INF / SD PST --------------------------------------------


def test_sd_dir_empty_card(dev):
    assert dev.sd_dir() == []


def test_sd_info_returns_capacity_summary(dev):
    info = dev.sd_info()
    assert info.free_kb == 967872
    assert info.free_hours == 7.8
    assert info.total_kb == 30517578


def test_sd_status_idle_by_default(dev):
    assert dev.sd_status() == "0"
    assert SD_CARD_STATUS["0"] == "card present, no access"


def test_sd_status_meanings_cover_all_documented_digits():
    assert set(SD_CARD_STATUS) == {"0", "1", "2", "3", "4"}


# -- SD REC / SD PLY -------------------------------------------------------


def test_sd_record_start_then_stop_creates_a_wav_file(dev):
    dev.sd_record_start()
    assert dev.sd_status() == "1"
    dev.sd_record_stop()
    assert dev.sd_status() == "0"
    files = dev.sd_dir()
    assert len(files) == 1
    assert files[0].extension.upper() == "WAV"
    assert files[0].duration is not None
    assert files[0].size_bytes is None


def test_sd_record_start_twice_produces_two_distinct_files(dev):
    dev.sd_record_start()
    dev.sd_record_stop()
    dev.sd_record_start()
    dev.sd_record_stop()
    files = dev.sd_dir()
    assert len(files) == 2
    assert files[0].name != files[1].name


def test_sd_record_stop_when_idle_is_a_benign_no_op(dev):
    dev.sd_record_stop()  # nothing recording - should not raise
    assert dev.sd_dir() == []


def test_sd_play_and_stop_updates_status(dev):
    dev.sd_record_start()
    dev.sd_record_stop()
    name = dev.sd_dir()[0].name
    dev.sd_play(name)
    assert dev.sd_status() == "2"
    dev.sd_play_stop()
    assert dev.sd_status() == "0"


def test_sd_play_unknown_file_raises_nofile(dev):
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.sd_play("NOSUCHFILE")
    assert exc_info.value.code == "NOFILE"


def test_sd_play_stop_when_idle_is_a_benign_no_op(dev):
    dev.sd_play_stop()  # nothing playing - should not raise


# -- SD RSQ -----------------------------------------------------------------


def test_sd_squelch_skip_default_matches_spec_default(dev):
    # AR-DV1 spec: "n:1 --- Skip (default)".
    assert dev.get_sd_squelch_skip() == "1"


def test_sd_squelch_skip_roundtrip(dev):
    dev.set_sd_squelch_skip(False)
    assert dev.get_sd_squelch_skip() == "0"
    dev.set_sd_squelch_skip(True)
    assert dev.get_sd_squelch_skip() == "1"


# -- SD MMW / SD MMR (backup/restore) ---------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        SD_BACKUP_KIND_SEARCH_BANK,
        SD_BACKUP_KIND_SEARCH_GROUP,
        SD_BACKUP_KIND_MEMORY_CHANNEL,
        SD_BACKUP_KIND_SCAN_GROUP,
        SD_BACKUP_KIND_ALL,
    ],
)
def test_sd_backup_accepts_every_documented_kind(dev, kind):
    dev.sd_backup(kind)
    files = dev.sd_dir()
    assert any(f.name == kind for f in files)


def test_sd_backup_kind_all_is_the_misspelled_wire_token(dev):
    # Confirmed as a genuine AR-DV1 spec typo (not an OCR artifact) via
    # both the rendered PDF image and pdftotext's raw text layer.
    assert SD_BACKUP_KIND_ALL == "SYSYEM"


def test_sd_backup_rejects_unknown_kind(dev):
    with pytest.raises(ValueError):
        dev.sd_backup("SYSTEM")  # the correctly-spelled, wrong token


def test_sd_backup_then_restore_roundtrip(dev):
    dev.sd_backup(SD_BACKUP_KIND_SEARCH_BANK)
    dev.sd_restore(SD_BACKUP_KIND_SEARCH_BANK)  # should not raise


def test_sd_restore_unknown_name_raises_nofile(dev):
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.sd_restore("NEVERBACKEDUP")
    assert exc_info.value.code == "NOFILE"


def test_sd_restore_does_not_validate_against_the_kind_enum(dev):
    # Unlike sd_backup()'s kind, sd_restore()'s name is documented as an
    # arbitrary "original file name" - so an arbitrary (existing) name
    # must be accepted, not just the 5 known kind tokens.
    dev.sd_backup(SD_BACKUP_KIND_SEARCH_BANK)
    dev.sd_restore("srchbk")  # case-insensitive, and not kind-validated


# -- error-token handling (task 13 item 32) ----------------------------------


@pytest.mark.parametrize(
    "token", ["CARDBUSY", "NOCARD", "FAT12", "NOFILE", "CARDFULL"]
)
def test_sd_info_surfaces_every_documented_error_token(dev, token):
    dev._transport.sd_error_injection = token  # noqa: SLF001
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.sd_info()
    assert exc_info.value.code == token


def test_sd_error_injection_is_one_shot(dev):
    dev._transport.sd_error_injection = "CARDBUSY"  # noqa: SLF001
    with pytest.raises(DV10ProtocolError):
        dev.sd_info()
    # the injected error should have been consumed - a normal call now
    # succeeds again.
    info = dev.sd_info()
    assert info.total_kb == 30517578


def test_sd_dir_surfaces_error_tokens_too(dev):
    dev._transport.sd_error_injection = "NOCARD"  # noqa: SLF001
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.sd_dir()
    assert exc_info.value.code == "NOCARD"
