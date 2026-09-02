"""Regression tests for the CLI "sd" verb family - SD
card management. See tests/test_sd_card.py and src/aor_dv10/device.py's "SD
card management" section for the underlying API this wraps. All against
the simulator; nothing here has been checked against real hardware.
"""

import pytest

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device
from aor_dv10.protocol.codec import DV10ProtocolError


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_cli_sd_dir_empty_card():
    repl = make_repl()
    assert repl.dispatch("sd dir") is True


def test_cli_sd_info():
    repl = make_repl()
    assert repl.dispatch("sd info") is True


def test_cli_sd_status():
    repl = make_repl()
    assert repl.dispatch("sd status") is True


def test_cli_sd_rec_start_stop_roundtrip():
    repl = make_repl()
    assert repl.dispatch("sd rec start") is True
    assert repl.device.sd_status() == "1"
    assert repl.dispatch("sd rec stop") is True
    assert repl.device.sd_status() == "0"
    assert len(repl.device.sd_dir()) == 1


def test_cli_sd_rec_bad_subcommand_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd rec bogus")


def test_cli_sd_play_and_stop():
    repl = make_repl()
    repl.dispatch("sd rec start")
    repl.dispatch("sd rec stop")
    name = repl.device.sd_dir()[0].name
    assert repl.dispatch(f"sd play {name}") is True
    assert repl.device.sd_status() == "2"
    assert repl.dispatch("sd play stop") is True
    assert repl.device.sd_status() == "0"


def test_cli_sd_play_unknown_file_raises():
    repl = make_repl()
    with pytest.raises(DV10ProtocolError):
        repl.dispatch("sd play NOSUCHFILE")


def test_cli_sd_rsq_show_and_set():
    repl = make_repl()
    assert repl.dispatch("sd rsq") is True
    assert repl.dispatch("sd rsq off") is True
    assert repl.device.get_sd_squelch_skip() == "0"
    assert repl.dispatch("sd rsq on") is True
    assert repl.device.get_sd_squelch_skip() == "1"


def test_cli_sd_rsq_bad_value_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd rsq bogus")


def test_cli_sd_backup_and_restore():
    repl = make_repl()
    assert repl.dispatch("sd backup SRCHBK") is True
    assert repl.dispatch("sd restore SRCHBK") is True
    files = repl.device.sd_dir()
    assert any(f.name == "SRCHBK" for f in files)


def test_cli_sd_backup_bad_kind_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd backup NOTAKIND")


def test_cli_sd_backup_requires_argument():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd backup")


def test_cli_sd_restore_requires_argument():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd restore")


def test_cli_sd_no_args_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd")


def test_cli_sd_unknown_subcommand_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("sd bogus")
