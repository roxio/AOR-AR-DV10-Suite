"""Regression tests for the CLI "timer" verb - TR,
the scheduled recording/alarm timer. See src/aor_dv10/cli/repl.py's
dispatch()/_dispatch_timer() and tests/test_timer.py for the underlying
aor_dv10.timer/device.py API this wraps, and aor_dv10.timer's module
docstring for the significant spec-reconstruction caveats (the AR-DV1
spec PDF's own TR table entry is internally inconsistent) before trusting
any particular field. All against the simulator; nothing here has been
checked against real hardware.
"""

import pytest

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_cli_timer_bare_shows_default():
    repl = make_repl()
    assert repl.dispatch("timer") is True
    t = repl.device.read_recording_timer()
    assert t.action == "off"
    assert t.receive_mode == "VFA"


def test_cli_timer_set_vfo_once():
    repl = make_repl()
    assert repl.dispatch("timer set vfo:B once 03150900 03150930 recording - 50") is True
    t = repl.device.read_recording_timer()
    assert t.action == "recording"
    assert t.repeat == "once"
    assert t.receive_mode == "VFB"
    assert t.start == "03150900"
    assert t.end == "03150930"
    assert t.alarm_volume == 50


def test_cli_timer_set_bank_weekly_with_weekdays():
    repl = make_repl()
    assert repl.dispatch("timer set bank:1 weekly 0800 0830 alarm sun,wed 20") is True
    t = repl.device.read_recording_timer()
    assert t.action == "alarm"
    assert t.repeat == "weekly"
    assert t.receive_mode == "SS01"
    assert set(t.weekdays) == {1, 8}  # SUNDAY, WEDNESDAY
    assert t.alarm_volume == 20


def test_cli_timer_set_defaults_action_to_recording_when_omitted():
    repl = make_repl()
    assert repl.dispatch("timer set vfo:A once 01010000 01010030") is True
    assert repl.device.read_recording_timer().action == "recording"


def test_cli_timer_set_scan_and_memory_channel_targets():
    repl = make_repl()
    assert repl.dispatch("timer set scan:2 weekly 0900 0930") is True
    assert repl.device.read_recording_timer().receive_mode == "MS02"
    assert repl.dispatch("timer set ch:1-5 weekly 0900 0930") is True
    assert repl.device.read_recording_timer().receive_mode == "MR0105"
    assert repl.dispatch("timer set vs once 01010000 01010030") is True
    assert repl.device.read_recording_timer().receive_mode == "VS"


def test_cli_timer_off_deactivates():
    repl = make_repl()
    repl.dispatch("timer set vfo:A once 01010000 01010030 recording")
    assert repl.dispatch("timer off") is True
    assert repl.device.read_recording_timer().action == "off"


def test_cli_timer_set_rejects_unknown_target():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("timer set bogus:1 once 1 2")


def test_cli_timer_set_rejects_unknown_weekday():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("timer set vfo:A once 1 2 recording notaday")


def test_cli_timer_set_rejects_bad_repeat():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("timer set vfo:A daily 1 2")


def test_cli_timer_set_requires_minimum_args():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("timer set vfo:A once 1")


def test_cli_timer_unknown_subcommand_raises():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("timer bogus")
