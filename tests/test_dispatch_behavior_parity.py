
from __future__ import annotations

import os

import pytest
from rich.console import Console

pytest.importorskip("fastapi")

from aor_dv10.cli.repl import Repl  # noqa: E402
from aor_dv10.device import DV10Device  # noqa: E402
from aor_dv10.web import server as webserver  # noqa: E402

CASES = [
    ("m F0", "get_mode"),
    ("f 145.500000", "get_frequency_hz"),
    ("sq 2", "get_squelch_mode"),
    ("lq 50", "get_squelch_level"),
    ("nq 20", "get_noise_squelch_level"),
    ("agcspd 1", "get_agc_speed"),
    ("attst 1", "get_attenuator_state"),
    ("dmrcc 05", "get_dmr_color_code"),
    ("p25nac 001", "get_p25_nac"),
    ("nxdnran 05", "get_nxdn_ran"),
    ("beeplvl 3", "get_beep_level"),
    ("vollimit 10", "get_volume_limit"),
    ("contrast 30", "get_lcd_contrast"),
    ("dmrslot 2", "get_dmr_slot"),
]


def _cli():
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev, Repl(dev, Console(file=open(os.devnull, "w")))


def _web():
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


@pytest.mark.parametrize("verb,getter", CASES)
def test_cli_and_web_produce_same_device_state(verb, getter):
    cli_dev, repl = _cli()
    web_dev = _web()
    try:
        assert repl.dispatch(verb) is True
        webserver._dispatch_plain(web_dev, verb)
        assert getattr(cli_dev, getter)() == getattr(web_dev, getter)(), (
            f"CLI and web disagree on {verb!r} -> {getter}()"
        )
    finally:
        cli_dev.disconnect()
        web_dev.disconnect()


def test_cli_and_web_agree_on_status_poll():
    cli_dev, _repl = _cli()
    web_dev = _web()
    try:
        a, b = cli_dev.status(), web_dev.status()
        assert a.frequency_hz == b.frequency_hz
        assert a.mode == b.mode
        assert a.squelch == b.squelch
    finally:
        cli_dev.disconnect()
        web_dev.disconnect()
