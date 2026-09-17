
import os

import pytest

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
    console = Console(file=open(os.devnull, "w"))
    return Repl(dev, console)



def test_device_boolean_passthroughs_round_trip():
    dev = make_device()
    pairs = [
        (dev.set_earphone_antenna, dev.get_earphone_antenna),
        (dev.set_freq_data_output, dev.get_freq_data_output),
        (dev.set_smeter_data_output, dev.get_smeter_data_output),
        (dev.set_monitor_offset, dev.get_monitor_offset),
        (dev.set_power_save, dev.get_power_save),
        (dev.set_receiver_status_output, dev.get_receiver_status_output),
    ]
    for setter, getter in pairs:
        setter(True)
        assert getter() == "1"
        setter(False)
        assert getter() == "0"


def test_device_raw_text_passthroughs_round_trip():
    dev = make_device()
    pairs = [
        (dev.set_function_code, dev.get_function_code),
        (dev.set_ttc_slot_number, dev.get_ttc_slot_number),
        (dev.set_voice_squelch, dev.get_voice_squelch),
        (dev.set_power_save_silent_time, dev.get_power_save_silent_time),
        (dev.set_comm_speed, dev.get_comm_speed),
    ]
    for setter, getter in pairs:
        setter("5")
        assert getter() == "5"


def test_device_digital_data_output_is_write_only_and_unrelated_to_acquire():
    dev = make_device()
    dev.set_digital_data_output("HELLO")
    assert dev.acquire_digital_data() == ""


def test_device_receiver_status_is_read_only():
    dev = make_device()
    assert dev.get_receiver_status() == "1"
    assert not hasattr(dev, "set_receiver_status")



@pytest.mark.parametrize(
    "verb,getter_name",
    [
        ("an", "get_earphone_antenna"),
        ("lc", "get_freq_data_output"),
        ("lt", "get_smeter_data_output"),
        ("ox", "get_monitor_offset"),
        ("zs", "get_power_save"),
        ("rt", "get_receiver_status_output"),
    ],
)
def test_cli_boolean_verbs_show_and_set(verb, getter_name):
    repl = make_repl()
    assert repl.dispatch(verb) is True
    assert repl.dispatch(f"{verb} on") is True
    assert getattr(repl.device, getter_name)() == "1"
    assert repl.dispatch(f"{verb} off") is True
    assert getattr(repl.device, getter_name)() == "0"


@pytest.mark.parametrize(
    "verb,getter_name",
    [
        ("ct", "get_function_code"),
        ("ts", "get_ttc_slot_number"),
        ("vq", "get_voice_squelch"),
        ("zt", "get_power_save_silent_time"),
        ("sb", "get_comm_speed"),
    ],
)
def test_cli_raw_text_verbs_show_and_set(verb, getter_name):
    repl = make_repl()
    assert repl.dispatch(verb) is True
    assert repl.dispatch(f"{verb} 7") is True
    assert getattr(repl.device, getter_name)() == "7"


def test_cli_dj_is_write_only():
    repl = make_repl()
    with pytest.raises(ValueError):
        repl.dispatch("dj")
    assert repl.dispatch("dj PAYLOAD") is True


def test_cli_dk_and_rx_are_read_only():
    repl = make_repl()
    assert repl.dispatch("dk") is True
    assert repl.dispatch("rx") is True



@pytest.mark.parametrize(
    "verb,getter_name",
    [
        ("an", "get_earphone_antenna"),
        ("lc", "get_freq_data_output"),
        ("lt", "get_smeter_data_output"),
        ("ox", "get_monitor_offset"),
        ("zs", "get_power_save"),
        ("rt", "get_receiver_status_output"),
    ],
)
def test_web_boolean_verbs_show_and_set(verb, getter_name):
    dev = make_device()
    assert _dispatch_plain(dev, verb) == "0"
    assert _dispatch_plain(dev, f"{verb} on") == "1"
    assert getattr(dev, getter_name)() == "1"
    assert _dispatch_plain(dev, f"{verb} off") == "0"


@pytest.mark.parametrize(
    "verb,getter_name",
    [
        ("ct", "get_function_code"),
        ("ts", "get_ttc_slot_number"),
        ("vq", "get_voice_squelch"),
        ("zt", "get_power_save_silent_time"),
        ("sb", "get_comm_speed"),
    ],
)
def test_web_raw_text_verbs_show_and_set(verb, getter_name):
    dev = make_device()
    assert _dispatch_plain(dev, f"{verb} 9") == "9"
    assert getattr(dev, getter_name)() == "9"
    assert _dispatch_plain(dev, verb) == "9"


def test_web_dj_is_write_only():
    dev = make_device()
    with pytest.raises(ValueError):
        _dispatch_plain(dev, "dj")
    assert _dispatch_plain(dev, "dj PAYLOAD") == "sent"


def test_web_dk_and_rx_are_read_only():
    dev = make_device()
    assert _dispatch_plain(dev, "dk") == ""
    assert _dispatch_plain(dev, "rx") == "1"
