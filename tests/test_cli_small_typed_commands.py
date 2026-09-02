"""Regression tests for the CLI additions: "klcolor",
"ifbw", "delay", "freetime", "serial", plus "backlight" (LB - resolving a
real naming collision: the web panel's terminal dispatcher already had a
"backlight" verb bound to LB from the manual-sourced expansion, predating
the KL command's own "backlight" name. Resolved by naming the KL verb
"klcolor" and giving the CLI its own LB-backed "backlight" to match the
web panel). See
tests/test_small_typed_commands.py for the underlying device.py API these
wrap. All against the simulator; nothing here has been checked against
real hardware.
"""

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_cli_backlight_lb_show_and_set():
    repl = make_repl()
    assert repl.dispatch("backlight") is True
    assert repl.dispatch("backlight 2") is True
    assert repl.device.get_backlight_mode() == "2"


def test_cli_klcolor_show_and_set():
    repl = make_repl()
    assert repl.dispatch("klcolor") is True
    assert repl.dispatch("klcolor 4") is True
    assert repl.device.get_key_backlight_color() == "4"


def test_cli_backlight_and_klcolor_are_independent():
    # The real bug this project caught: LB and KL must not share storage
    # or a dispatch branch - writing one must not affect the other.
    repl = make_repl()
    repl.dispatch("backlight 1")
    repl.dispatch("klcolor 5")
    assert repl.device.get_backlight_mode() == "1"
    assert repl.device.get_key_backlight_color() == "5"


def test_cli_ifbw_show_and_set():
    repl = make_repl()
    assert repl.dispatch("ifbw") is True
    assert repl.dispatch("ifbw 1") is True
    assert repl.device.get_if_bandwidth() == "1"


def test_cli_bw_show_and_set_by_hz():
    # "bw" is the mode-aware Hz-based counterpart to "ifbw"'s raw digit.
    repl = make_repl()
    assert repl.dispatch("bw") is True
    assert repl.dispatch("bw 100000") is True  # FM/IF1 = 100 kHz
    assert repl.device.get_if_bandwidth() == "1"
    assert repl.device.get_if_bandwidth_hz() == 100_000


def test_cli_id_shows_model_firmware_and_family():
    repl = make_repl()
    assert repl.dispatch("id") is True
    assert repl.device.device_family() == "DV10"


def test_cli_delay_show_and_set():
    repl = make_repl()
    assert repl.dispatch("delay") is True
    assert repl.dispatch("delay 60") is True
    assert repl.device.get_delay_time_ds() == 60


def test_cli_freetime_show_and_set():
    repl = make_repl()
    assert repl.dispatch("freetime") is True
    assert repl.dispatch("freetime 15") is True
    assert repl.device.get_free_time_s() == 15


def test_cli_serial_shows_value():
    repl = make_repl()
    assert repl.dispatch("serial") is True
