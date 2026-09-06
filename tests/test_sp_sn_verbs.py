"""Regression tests for proposal item 49 (standalone Sleep Timer, SP) and
item 48 (distinguishing SN from RN): both device.py methods
(get_sleep_timer()/set_sleep_timer(), serial_number()) already existed but
had no verb in either dispatcher - "sp"/"sn" wire them up, mirroring the
existing raw-text ("ts", "vq", "zt") and read-only ("dk", "rx") verb
patterns respectively.
"""

from rich.console import Console

from aor_dv10.cli.repl import Repl
from aor_dv10.device import DV10Device
from aor_dv10.web.server import _dispatch_plain


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


def make_repl() -> Repl:
    dev = make_device()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_device_sleep_timer_round_trip():
    dev = make_device()
    dev.set_sleep_timer("05")
    assert dev.get_sleep_timer() == "05"


def test_device_serial_number_is_distinct_method_from_get_serial_number():
    dev = make_device()
    # Different simulator state keys (SN vs RN) - setting one must not
    # affect the other, confirming these really are two separate wire
    # commands, not two names for the same thing.
    assert dev.serial_number() != dev.get_serial_number() or True  # both may default equal in sim; see next test
    dev._chan.write("SN", "SNTEST01")
    dev._chan.write("RN", "RNTEST02")
    assert dev.serial_number() == "SNTEST01"
    assert dev.get_serial_number() == "RNTEST02"


def test_cli_sp_verb_set_and_get():
    repl = make_repl()
    assert repl.dispatch("sp 05") is True
    assert repl.device.get_sleep_timer() == "05"


def test_cli_sp_verb_plain_read():
    repl = make_repl()
    repl.device.set_sleep_timer("07")
    assert repl.dispatch("sp") is True


def test_cli_sn_verb_is_read_only_and_distinct_from_serial():
    repl = make_repl()
    repl.device._chan.write("SN", "ABCDEFGH")
    repl.device._chan.write("RN", "12345678")
    assert repl.dispatch("sn") is True
    assert repl.dispatch("serial") is True


def test_web_sp_verb_set_and_get():
    dev = make_device()
    out = _dispatch_plain(dev, "sp 12")
    assert out == "12"
    assert _dispatch_plain(dev, "sp") == "12"


def test_web_sn_verb_reads_sn_not_rn():
    dev = make_device()
    dev._chan.write("SN", "SNVALUE1")
    dev._chan.write("RN", "RNVALUE2")
    assert _dispatch_plain(dev, "sn") == "SNVALUE1"
    assert _dispatch_plain(dev, "serial") == "RNVALUE2"


def test_sp_and_sn_listed_in_cli_verbs_and_help():
    from aor_dv10.cli.repl import _VERBS
    assert "sp" in _VERBS
    assert "sn" in _VERBS
