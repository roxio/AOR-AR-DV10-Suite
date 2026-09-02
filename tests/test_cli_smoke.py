"""Smoke tests for the CLI dispatcher against the simulator (no real hardware
and no interactive terminal required)."""

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_repl_frequency_and_mode_roundtrip():
    repl = make_repl()
    assert repl.dispatch("f 145.500000") is True
    assert repl.device.get_frequency_hz() == 145_500_000
    assert repl.dispatch("m F0") is True  # digital off, analog FM
    assert repl.device.get_mode() == "0F0"


def test_repl_quit_returns_false():
    repl = make_repl()
    assert repl.dispatch("quit") is False


def test_repl_raw_and_describe_do_not_raise():
    repl = make_repl()
    assert repl.dispatch("raw LM") is True
    assert repl.dispatch("describe RF") is True


def test_repl_unknown_command_does_not_raise():
    repl = make_repl()
    assert repl.dispatch("bogus") is True


def _fixture_path() -> str:
    from pathlib import Path
    return str(Path(__file__).parent / "fixtures" / "ARDV10_ConnectExport_sample.csv")


def test_repl_mem_requires_load_first():
    import pytest
    repl = make_repl()
    with pytest.raises(ValueError, match="no memory database loaded"):
        repl.dispatch("mem find CH-001")


def test_repl_mem_load_find_and_goto_against_real_export():
    """End-to-end: load the real backup CSV, find a known channel by
    name, and "goto" it - confirming the loaded frequency/mode land on
    the simulator through the ordinary f/m writes (mem.py never touches
    MX/MA directly, see its module docstring)."""
    repl = make_repl()
    repl.dispatch(f"mem load {_fixture_path()}")
    assert len(repl.memory_channels) == 2000
    assert sum(1 for c in repl.memory_channels if not c.is_empty) == 469

    repl.dispatch("vfo A")
    repl.dispatch("mem goto 00-00")
    assert repl.device.get_frequency_hz() == 145_500_000
    assert repl.device.get_mode() == "000"


def test_repl_mem_goto_unknown_channel_raises():
    import pytest
    repl = make_repl()
    repl.dispatch(f"mem load {_fixture_path()}")
    with pytest.raises(ValueError, match="unprogrammed"):
        repl.dispatch("mem goto 04-00")  # confirmed empty in the fixture


def test_repl_mem_export_roundtrips(tmp_path):
    repl = make_repl()
    repl.dispatch(f"mem load {_fixture_path()}")
    out_path = tmp_path / "export.csv"
    repl.dispatch(f"mem export {out_path}")

    from aor_dv10.memory import parse_backup_csv
    reloaded_banks, reloaded_channels = parse_backup_csv(out_path.read_text(encoding="utf-8"))
    assert len(reloaded_banks) == 40
    assert len(reloaded_channels) == 2000
    assert sum(1 for c in reloaded_channels if not c.is_empty) == 469
