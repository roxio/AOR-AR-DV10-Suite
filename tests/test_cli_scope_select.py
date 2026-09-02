"""Regression tests for the CLI additions: the "scope"
and "select" verb families, and the "rmem find" extension. See
tests/test_scope.py and tests/test_selectscan.py for the underlying
device.py/aor_dv10.selectscan APIs these wrap. All against the simulator;
nothing here has been checked against real hardware.
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


# -- scope ------------------------------------------------------------------


def test_cli_scope_requires_a_subcommand():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("scope")


def test_cli_scope_bad_subcommand_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("scope bogus")


def test_cli_scope_fast_raises_when_not_in_scope_mode():
    repl = make_repl()
    with pytest.raises(DV10ProtocolError):
        repl.dispatch("scope fast")


def test_cli_scope_normal_raises_when_not_in_scope_mode():
    repl = make_repl()
    with pytest.raises(DV10ProtocolError):
        repl.dispatch("scope normal")


def test_cli_scope_fast_and_normal_succeed_in_scope_mode():
    repl = make_repl()
    repl.device._transport.scope_mode = True  # noqa: SLF001
    assert repl.dispatch("scope fast") is True
    assert repl.dispatch("scope normal") is True


# -- select -------------------------------------------------------------


def test_cli_select_requires_a_subcommand():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("select")


def test_cli_select_bad_subcommand_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("select bogus")


def test_cli_select_add_list_remove_clear_roundtrip():
    repl = make_repl()
    assert repl.dispatch("select add 0 1") is True
    assert repl.dispatch("select add 0 2") is True
    assert len(repl.select_scan_list) == 2
    assert repl.dispatch("select list") is True
    assert repl.dispatch("select remove 0 1") is True
    assert len(repl.select_scan_list) == 1
    assert repl.dispatch("select clear") is True
    assert len(repl.select_scan_list) == 0


def test_cli_select_add_requires_two_args():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("select add 0")


def test_cli_select_run_empty_list_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("select run")


def test_cli_select_run_tunes_every_entry():
    repl = make_repl()
    repl.device.write_memory_channel(0, 1, frequency_hz=145_500_000, mode="F0", tag="A")
    repl.device.write_memory_channel(0, 2, frequency_hz=146_000_000, mode="F0", tag="B")
    repl.dispatch("select add 0 1")
    repl.dispatch("select add 0 2")
    assert repl.dispatch("select run 1 0") is True


# -- rmem find ------------------------------------------------------------


def test_cli_rmem_find_requires_an_argument():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("rmem find")


def test_cli_rmem_find_no_matches():
    repl = make_repl()
    assert repl.dispatch("rmem find nosuchtag 0") is True


def test_cli_rmem_find_matches_within_one_bank():
    repl = make_repl()
    repl.device.write_memory_channel(0, 5, frequency_hz=145_500_000, mode="F0", tag="WEATHER")
    assert repl.dispatch("rmem find weather 0") is True


def test_cli_rmem_find_searches_all_banks_when_none_given():
    repl = make_repl()
    repl.device.write_memory_channel(3, 7, frequency_hz=445_000_000, mode="F0", tag="REPEATER")
    assert repl.dispatch("rmem find repeater") is True
