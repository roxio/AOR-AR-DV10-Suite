
import os

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open(os.devnull, "w"))
    return Repl(dev, console)


def test_cli_vfo_bare_still_selects_vfo_only():
    repl = make_repl()
    repl.device._transport.vfo_mode = False  # noqa: SLF001
    assert repl.dispatch("vfo A") is True
    assert repl.device._transport.vfo_mode is True  # noqa: SLF001


def test_cli_vfo_atomic_frequency_and_mode():
    repl = make_repl()
    assert repl.dispatch("vfo B 446.00625 F0") is True
    assert repl.device.get_frequency_hz() == 446_006_250
    assert repl.device.get_mode() == "0F0"


def test_cli_vi_lists_all_three_vfos():
    repl = make_repl()
    repl.dispatch("vfo A 145.5")
    repl.dispatch("vfo B 446.00625")
    assert repl.dispatch("vi") is True


def test_cli_vs_does_not_raise():
    repl = make_repl()
    assert repl.dispatch("vs") is True


def test_cli_ve_roundtrip():
    repl = make_repl()
    assert repl.dispatch("ve 30 5 on") is True
    s = repl.device.read_vfo_search_settings()
    assert s.delay_ds == 30
    assert s.free_time_s == 5
    assert s.auto_store is True
    assert repl.dispatch("ve") is True
