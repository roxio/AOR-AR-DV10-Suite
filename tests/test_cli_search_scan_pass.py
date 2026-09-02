"""Regression tests for the CLI verbs: "search ...",
"scan ...", "pass ...". See src/aor_dv10/cli/repl.py's
_dispatch_search()/_dispatch_scan()/_dispatch_pass() and
tests/test_search_scan_pass.py for the underlying device.py API these
verbs wrap. All against the simulator - see this module's sibling for the
"nothing confirmed against real hardware yet" caveat.
"""

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device


def make_repl() -> Repl:
    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


# -- search --------------------------------------------------------------


def test_cli_search_write_read_run_delete():
    repl = make_repl()
    assert repl.dispatch("search write 1 144.0 148.0 12500 0 F0 1 2MBAND") is True
    info = repl.device.read_search_bank(1)
    assert info.lower_limit_hz == 144_000_000
    assert info.upper_limit_hz == 148_000_000
    assert info.mode == "F0"
    assert info.write_protect is True
    assert info.tag == "2MBAND"
    assert repl.dispatch("search read 1") is True
    assert repl.dispatch("search run 1") is True
    assert repl.dispatch("search delete 1") is True
    import pytest
    from aor_dv10.protocol.codec import DV10ProtocolError
    with pytest.raises(DV10ProtocolError):
        repl.device.read_search_bank(1)


def test_cli_search_lolimit_hilimit_roundtrip():
    repl = make_repl()
    assert repl.dispatch("search lolimit 144.0") is True
    assert repl.device.get_search_lower_limit() == 144_000_000
    assert repl.dispatch("search hilimit 148.0") is True
    assert repl.device.get_search_upper_limit() == 148_000_000


# -- scan ------------------------------------------------------------------


def test_cli_scan_swrite_sread_roundtrip():
    repl = make_repl()
    assert repl.dispatch("scan swrite 0 25 5 on 1 2 3") is True
    g = repl.device.read_search_scan_group(0)
    assert g.delay_ds == 25
    assert g.free_time_s == 5
    assert g.auto_store is True
    assert g.bank_link == (1, 2, 3)
    assert repl.dispatch("scan sread 0") is True


def test_cli_scan_swrite_clear_disables_bank_links():
    repl = make_repl()
    repl.dispatch("scan swrite 0 25 5 on 1 2 3")
    assert repl.dispatch("scan swrite 0 25 5 on clear") is True
    assert repl.device.read_search_scan_group(0).bank_link == ()


def test_cli_scan_mwrite_mread_has_no_autostore():
    repl = make_repl()
    assert repl.dispatch("scan mwrite 1 10 2 5") is True
    g = repl.device.read_memory_scan_group(1)
    assert g.auto_store is None
    assert g.bank_link == (5,)
    assert repl.dispatch("scan mread 1") is True


def test_cli_scan_autostore_roundtrip():
    repl = make_repl()
    assert repl.dispatch("scan autostore on") is True
    assert repl.device.get_auto_store() is True
    assert repl.dispatch("scan autostore off") is True
    assert repl.device.get_auto_store() is False


def test_cli_scan_banklink_roundtrip_and_clear():
    repl = make_repl()
    assert repl.dispatch("scan banklink 4 5 6") is True
    assert repl.device.get_bank_link() == [4, 5, 6]
    assert repl.dispatch("scan banklink clear") is True
    assert repl.device.get_bank_link() == []


# -- pass --------------------------------------------------------------------


def test_cli_pass_mark_bare_and_list():
    repl = make_repl()
    repl.device.set_frequency_hz(146_520_000)
    assert repl.dispatch("pass mark") is True
    entries = repl.device.list_pass_frequencies()
    assert entries[0].frequency_hz == 146_520_000
    assert repl.dispatch("pass list") is True


def test_cli_pass_mark_explicit_frequency():
    repl = make_repl()
    assert repl.dispatch("pass mark 146.52") is True
    entries = repl.device.list_pass_frequencies()
    assert entries[0].frequency_hz == 146_520_000


def test_cli_pass_mark_bank():
    repl = make_repl()
    repl.device.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    assert repl.dispatch("pass mark bank 3 146.94") is True
    entries = repl.device.list_pass_frequencies(bank=3)
    assert entries[0].frequency_hz == 146_940_000
    assert repl.dispatch("pass list 3") is True


def test_cli_pass_mark_allbanks():
    repl = make_repl()
    repl.device.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    repl.device.write_search_bank(2, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    assert repl.dispatch("pass mark allbanks 145.0") is True
    assert repl.device.list_pass_frequencies(bank=1)[0].frequency_hz == 145_000_000
    assert repl.device.list_pass_frequencies(bank=2)[0].frequency_hz == 145_000_000


def test_cli_pass_delete_bare_bank_and_allbanks():
    repl = make_repl()
    repl.device.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    repl.dispatch("pass mark 146.52")
    assert repl.dispatch("pass delete") is True
    assert all(e.frequency_hz is None for e in repl.device.list_pass_frequencies())

    repl.dispatch("pass mark bank 3 146.94")
    assert repl.dispatch("pass delete bank 3") is True
    assert all(e.frequency_hz is None for e in repl.device.list_pass_frequencies(bank=3))

    repl.device.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    repl.dispatch("pass mark bank 1 145.0")
    repl.dispatch("pass mark bank 3 145.0")
    assert repl.dispatch("pass delete allbanks") is True
    assert all(e.frequency_hz is None for e in repl.device.list_pass_frequencies(bank=1))
    assert all(e.frequency_hz is None for e in repl.device.list_pass_frequencies(bank=3))


def test_cli_pass_delete_bank_and_index():
    repl = make_repl()
    repl.device.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    repl.dispatch("pass mark bank 3 146.94")
    assert repl.dispatch("pass delete bank 3 0") is True
    assert repl.device.list_pass_frequencies(bank=3)[0].frequency_hz is None
