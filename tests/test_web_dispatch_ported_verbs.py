"""Regression tests for the CLI-only verb families ported into the web
panel's _dispatch_plain(): the small typed commands (vi/vs/ve/klcolor/
ifbw/delay/freetime/serial) plus the eight sub-dispatched families
(rmem/search/scan/pass/timer/sd/scope/select). These existed in the
desktop CLI (aor_dv10.cli.repl.Repl._dispatch_*) but were not previously
reachable from the web panel's WebSocket terminal - this file
closes that gap on the web side, mirroring tests/test_cli_*.py's coverage
of the same underlying device.py behaviour.

Talks to _dispatch_plain() directly (same style as the CLI tests talk to
Repl.dispatch() directly) rather than going through a real embedded
uvicorn server + WebSocket - faster, and the HTTP-server-in-a-thread style
used by test_web_integration.py/test_web_memory.py is about proving the
*server plumbing* works, which is orthogonal to what's tested here (the
dispatcher's command handling). All against the simulator; nothing here
has been checked against real hardware.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device  # noqa: E402
from aor_dv10.transport.simulator import SimulatorTransport  # noqa: E402
from aor_dv10.web import server as webserver  # noqa: E402
from aor_dv10.web.server import _dispatch_plain  # noqa: E402


def make_device(*, scope_mode: bool = False) -> DV10Device:
    transport = SimulatorTransport()
    transport.scope_mode = scope_mode
    dev = DV10Device(transport)
    dev.connect()
    return dev


# -- small typed commands (vi/vs/ve/klcolor/ifbw/delay/freetime/serial) -----


def test_web_vi_lists_vfos():
    dev = make_device()
    out = _dispatch_plain(dev, "vi")
    assert "VFO-A" in out
    assert "VFO-B" in out


def test_web_vs_starts_vfo_search():
    dev = make_device()
    assert _dispatch_plain(dev, "vs") == "VFO search started"


def test_web_ve_show_and_set():
    dev = make_device()
    out = _dispatch_plain(dev, "ve 60 15 on")
    assert "delay=60" in out
    assert "free=15" in out
    assert "autostore=True" in out
    out2 = _dispatch_plain(dev, "ve")
    assert "delay=60" in out2


def test_web_klcolor_show_and_set():
    dev = make_device()
    assert _dispatch_plain(dev, "klcolor 3") == "3 (MAGENDA)"
    assert _dispatch_plain(dev, "klcolor") == "3 (MAGENDA)"


def test_web_ifbw_show_and_set():
    dev = make_device()
    _dispatch_plain(dev, "ifbw 1")
    assert _dispatch_plain(dev, "ifbw") == "1"


def test_web_bw_show_and_set_by_hz():
    # "bw" is the mode-aware Hz-based counterpart to "ifbw"'s raw digit -
    # see DV10Device.set_if_bandwidth_hz()/get_if_bandwidth_hz(). Reply
    # text mirrors the CLI's "bw" formatting - see cli/repl.py.
    dev = make_device()
    _dispatch_plain(dev, "bw 100000")  # FM/IF1 = 100 kHz
    out = _dispatch_plain(dev, "bw")
    assert out.startswith("100000 Hz")
    # the rest of FM's choices - no 200000: confirmed absent on real
    # hardware (2026-09-01), see IF_BANDWIDTH_HZ's comment in device.py
    assert "6000" in out and "30000" in out
    assert "200000" not in out
    assert _dispatch_plain(dev, "ifbw") == "1"


def test_web_bw_rejects_value_not_offered_by_current_mode():
    dev = make_device()
    with pytest.raises(ValueError):
        _dispatch_plain(dev, "bw 3800")  # not an FM choice (default mode)


def test_web_id_shows_model_firmware_and_family():
    dev = make_device()
    out = _dispatch_plain(dev, "id")
    assert "DV10" in out
    assert "family=DV10" in out


def test_web_delay_show_and_set():
    dev = make_device()
    _dispatch_plain(dev, "delay 60")
    assert _dispatch_plain(dev, "delay") == "60"


def test_web_freetime_show_and_set():
    dev = make_device()
    _dispatch_plain(dev, "freetime 15")
    assert _dispatch_plain(dev, "freetime") == "15"


def test_web_serial_returns_value():
    dev = make_device()
    assert _dispatch_plain(dev, "serial") == "SIMULATED0001"


# -- rmem ---------------------------------------------------------------


def test_web_rmem_write_read_tune_delete_roundtrip():
    dev = make_device()
    assert _dispatch_plain(dev, "rmem write 0 1 146.520 00 test-chan") == "wrote 00-01"
    out = _dispatch_plain(dev, "rmem read 0 1")
    assert "146.52000 MHz" in out
    assert "test-chan" in out
    assert _dispatch_plain(dev, "rmem tune 0 1") == "ok"
    assert _dispatch_plain(dev, "rmem delete 0 1") == "deleted"
    out2 = _dispatch_plain(dev, "rmem read 0 1")
    assert "not registered" in out2


def test_web_rmem_readbank_and_bank_and_bankset():
    dev = make_device()
    _dispatch_plain(dev, "rmem write 0 1 146.520 00 test-chan")
    out = _dispatch_plain(dev, "rmem readbank 0")
    assert "1 registered of" in out
    info = _dispatch_plain(dev, "rmem bank 0")
    assert "bank 00:" in info
    assert _dispatch_plain(dev, "rmem bankset 0 20 0 my-bank") == "bank 00 set"


def test_web_rmem_find():
    dev = make_device()
    _dispatch_plain(dev, "rmem write 0 1 146.520 00 findme")
    out = _dispatch_plain(dev, "rmem find findme")
    assert "00-01" in out
    assert _dispatch_plain(dev, "rmem find nonexistent-tag") == "(no matches)"


def test_web_rmem_usage_with_no_args():
    dev = make_device()
    assert _dispatch_plain(dev, "rmem").startswith("usage:")


# -- search ---------------------------------------------------------------


def test_web_search_write_read_run_delete_roundtrip():
    dev = make_device()
    out = _dispatch_plain(dev, "search write 0 144.0 148.0 12500 0 00 0 search-tag")
    assert out == "search bank 00 set"
    read_out = _dispatch_plain(dev, "search read 0")
    assert "144.0000-148.0000 MHz" in read_out
    assert _dispatch_plain(dev, "search run 0") == "search started"
    assert _dispatch_plain(dev, "search delete 0") == "search bank deleted"


def test_web_search_lolimit_hilimit():
    dev = make_device()
    _dispatch_plain(dev, "search lolimit 144.0")
    assert "144.0000 MHz" in _dispatch_plain(dev, "search lolimit")
    _dispatch_plain(dev, "search hilimit 148.0")
    assert "148.0000 MHz" in _dispatch_plain(dev, "search hilimit")


# -- scan -------------------------------------------------------------------


def test_web_scan_sread_swrite_roundtrip():
    dev = make_device()
    assert _dispatch_plain(dev, "scan swrite 0 20 5 1 0 1") == "search scan group 00 set"
    out = _dispatch_plain(dev, "scan sread 0")
    assert "delay=20" in out
    assert "autostore=True" in out
    assert "[0, 1]" in out


def test_web_scan_mread_mwrite_roundtrip():
    dev = make_device()
    assert _dispatch_plain(dev, "scan mwrite 0 20 5 0 1") == "memory scan group 00 set"
    out = _dispatch_plain(dev, "scan mread 0")
    assert "delay=20" in out
    assert "[0, 1]" in out


def test_web_scan_autostore_and_banklink():
    dev = make_device()
    assert _dispatch_plain(dev, "scan autostore") == "off"
    assert _dispatch_plain(dev, "scan autostore on") is not None
    assert _dispatch_plain(dev, "scan autostore") == "on"
    _dispatch_plain(dev, "scan banklink 0 1")
    assert _dispatch_plain(dev, "scan banklink") == "[0, 1]"
    _dispatch_plain(dev, "scan banklink clear")
    assert _dispatch_plain(dev, "scan banklink") == "[]"


# -- pass ---------------------------------------------------------------


def test_web_pass_mark_list_delete_roundtrip():
    dev = make_device()
    assert _dispatch_plain(dev, "pass mark 146.0") == "marked"
    out = _dispatch_plain(dev, "pass list")
    assert "146.0000 MHz" in out
    assert _dispatch_plain(dev, "pass delete") == "deleted"
    assert "0 of" in _dispatch_plain(dev, "pass list")


# -- timer --------------------------------------------------------------


def test_web_timer_show_and_off():
    dev = make_device()
    out = _dispatch_plain(dev, "timer")
    assert "action=" in out
    assert _dispatch_plain(dev, "timer off") == "timer deactivated"


def test_web_timer_set_vfo_target():
    dev = make_device()
    out = _dispatch_plain(dev, "timer set vfo:A once 00:00 01:00 recording - 5")
    assert "action=recording" in out
    assert "start=00:00" in out
    assert "end=01:00" in out


def test_web_timer_set_unknown_target():
    dev = make_device()
    out = _dispatch_plain(dev, "timer set bogus:X once 00:00 01:00")
    assert "unknown target" in out


# -- sd -------------------------------------------------------------------


def test_web_sd_dir_info_status():
    dev = make_device()
    assert _dispatch_plain(dev, "sd dir") == "(no files)"
    assert "free=" in _dispatch_plain(dev, "sd info")
    assert "-" in _dispatch_plain(dev, "sd status")


def test_web_sd_rsq_show_and_set():
    dev = make_device()
    out = _dispatch_plain(dev, "sd rsq on")
    assert out == "squelch skip set to on"
    assert "squelch skip: on" in _dispatch_plain(dev, "sd rsq")


# -- scope ------------------------------------------------------------------


def test_web_scope_fast_and_normal():
    dev = make_device(scope_mode=True)
    fast = _dispatch_plain(dev, "scope fast")
    assert "points" in fast
    normal = _dispatch_plain(dev, "scope normal")
    assert "points" in normal


def test_web_scope_usage_on_bad_arg():
    dev = make_device()
    assert _dispatch_plain(dev, "scope sideways").startswith("usage:")


# -- select -------------------------------------------------------------


def test_web_select_add_list_remove_clear():
    dev = make_device()
    # Start clean - _select_scan_list is module-level/shared across calls.
    webserver._select_scan_list.clear()
    out = _dispatch_plain(dev, "select add 0 1")
    assert "added 00-01" in out
    assert "00-01" in _dispatch_plain(dev, "select list")
    assert _dispatch_plain(dev, "select remove 0 1") == "removed"
    assert _dispatch_plain(dev, "select list") == "(empty)"
    _dispatch_plain(dev, "select add 0 1")
    assert _dispatch_plain(dev, "select clear") == "cleared"
    assert _dispatch_plain(dev, "select list") == "(empty)"


def test_web_select_run_visits_each_entry():
    dev = make_device()
    dev.write_memory_channel(0, 1, frequency_hz=146_520_000, mode="00", tag="chA")
    dev.write_memory_channel(0, 2, frequency_hz=147_000_000, mode="00", tag="chB")
    webserver._select_scan_list.clear()
    webserver._select_scan_list.add(0, 1)
    webserver._select_scan_list.add(0, 2)
    out = _dispatch_plain(dev, "select run 1 0.01")
    assert "00-01" in out
    assert "00-02" in out
    webserver._select_scan_list.clear()


def test_web_select_list_is_shared_across_dispatch_calls():
    # The whole point of the module-level _select_scan_list (vs. the CLI's
    # per-Repl-instance one): two separate _dispatch_plain() calls - as
    # from two different browser tabs hitting the same server process -
    # must see the same list.
    dev = make_device()
    webserver._select_scan_list.clear()
    _dispatch_plain(dev, "select add 1 2")
    dev2 = make_device()
    out = _dispatch_plain(dev2, "select list")
    assert "01-02" in out
    webserver._select_scan_list.clear()
