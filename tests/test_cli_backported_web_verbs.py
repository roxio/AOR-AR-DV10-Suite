"""Regression tests for the 18 CLI verbs backported from the web panel's
_dispatch_plain(): priochan/priointerval, dmrcc/dmrcm/dmrslot,
p25nac/p25pm, nxdnran/nxdnnm, dcrcode, descr, beeplvl/vollimit/digain/
mgain/contrast, movenext/moveprev, stepadj. These verbs existed in the
web panel's terminal dispatcher since the manual-sourced expansion but
were not ported into the desktop CLI until now - this
file closes that gap. All against the simulator; nothing here has been
checked against real hardware.
"""

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_cli_priochan_show_and_set():
    repl = make_repl()
    assert repl.dispatch("priochan") is True
    assert repl.dispatch("priochan 0 5") is True
    assert repl.device.get_priority_channel() == "00-05"


def test_cli_priointerval_show_and_set():
    repl = make_repl()
    assert repl.dispatch("priointerval") is True
    assert repl.dispatch("priointerval 10") is True
    assert repl.device.get_priority_interval() == "10"


def test_cli_dmrcc_show_and_set():
    repl = make_repl()
    assert repl.dispatch("dmrcc") is True
    assert repl.dispatch("dmrcc 5") is True
    assert repl.device.get_dmr_color_code() == "05"


def test_cli_dmrcm_requires_on_off():
    repl = make_repl()
    import pytest
    with pytest.raises(ValueError):
        repl.dispatch("dmrcm")
    assert repl.dispatch("dmrcm on") is True
    assert repl.device.get_dmr_mute_by_color_code() == "1"
    assert repl.dispatch("dmrcm off") is True
    assert repl.device.get_dmr_mute_by_color_code() == "0"


def test_cli_dmrslot_show_and_set():
    repl = make_repl()
    assert repl.dispatch("dmrslot") is True
    assert repl.dispatch("dmrslot 2") is True
    assert repl.device.get_dmr_slot() == "2"


def test_cli_p25nac_show_and_set():
    repl = make_repl()
    assert repl.dispatch("p25nac") is True
    assert repl.dispatch("p25nac 1AB") is True
    assert repl.device.get_p25_nac() == "1AB"


def test_cli_p25pm_requires_on_off():
    repl = make_repl()
    assert repl.dispatch("p25pm on") is True
    assert repl.device.get_p25_mute_by_nac() == "1"


def test_cli_nxdnran_show_and_set():
    repl = make_repl()
    assert repl.dispatch("nxdnran") is True
    assert repl.dispatch("nxdnran 12") is True
    assert repl.device.get_nxdn_ran() == "12"


def test_cli_nxdnnm_requires_on_off():
    repl = make_repl()
    assert repl.dispatch("nxdnnm on") is True
    assert repl.device.get_nxdn_mute_by_ran() == "1"


def test_cli_dcrcode_show_and_set():
    repl = make_repl()
    assert repl.dispatch("dcrcode") is True
    assert repl.dispatch("dcrcode 123") is True
    assert repl.device.get_dcr_descramble_code() == "00123"


def test_cli_descr_requires_on_off():
    repl = make_repl()
    assert repl.dispatch("descr on") is True
    assert repl.device.get_voice_descrambler_enabled() == "1"


def test_cli_beeplvl_show_and_set():
    repl = make_repl()
    assert repl.dispatch("beeplvl") is True
    assert repl.dispatch("beeplvl 5") is True
    assert repl.device.get_beep_level() == "5"


def test_cli_vollimit_show_and_set():
    repl = make_repl()
    assert repl.dispatch("vollimit") is True
    assert repl.dispatch("vollimit 3") is True
    assert repl.device.get_volume_limit() == "03"


def test_cli_digain_show_and_set():
    repl = make_repl()
    assert repl.dispatch("digain") is True
    assert repl.dispatch("digain 5.5") is True
    assert repl.device.get_digital_gain() == "05.50"


def test_cli_vollimit_and_digain_are_independent():
    # AV (vollimit) and DA (digain) must not be confused with each other -
    # both are "volume-ish" concepts but distinct wire commands.
    repl = make_repl()
    repl.dispatch("vollimit 7")
    repl.dispatch("digain 2.5")
    assert repl.device.get_volume_limit() == "07"
    assert repl.device.get_digital_gain() == "02.50"


def test_cli_mgain_show_and_set():
    repl = make_repl()
    assert repl.dispatch("mgain") is True
    assert repl.dispatch("mgain 50") is True
    assert repl.device.get_manual_gain() == "050"


def test_cli_contrast_show_and_set():
    repl = make_repl()
    assert repl.dispatch("contrast") is True
    assert repl.dispatch("contrast 10") is True
    assert repl.device.get_lcd_contrast() == "10"


def test_cli_movenext_and_moveprev_do_not_raise():
    repl = make_repl()
    assert repl.dispatch("movenext") is True
    assert repl.dispatch("moveprev") is True


def test_cli_stepadj_show_and_set():
    repl = make_repl()
    assert repl.dispatch("stepadj") is True
    assert repl.dispatch("stepadj 100") is True
    # get_step_adjust_hz() now returns int Hz, not the raw wire string -
    # corrected alongside SH's kHz-decimal wire format fix.
    assert repl.device.get_step_adjust_hz() == 100
