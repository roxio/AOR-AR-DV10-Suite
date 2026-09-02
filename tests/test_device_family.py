"""Regression tests for device_family()/analog_modes_without_distinction() -
model detection (via WI/model()) used to gate model-specific UI quirks, the
first of which is SAH/SAL not being functionally distinct on the AR-DV10
(per user report against real hardware - see the
ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY comment block in device.py).
All against the simulator; nothing here has been checked against real DV1
hardware (only DV10 - see the same comment block for why DV1 is a
presumption, not a confirmed finding).
"""

import pytest

from aor_dv10.device import ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY, DV10Device


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


def test_device_family_detects_dv10_from_default_simulator_model(dev):
    # Simulator default WI value ("AR-DV10") - see transport/simulator.py.
    assert dev.model()
    assert dev.device_family() == "DV10"


def test_device_family_checks_dv10_before_dv1_substring(dev):
    # "DV1" is itself a substring of "DV10" - a real DV10's own "AOR
    # AR-DV10" response must not be misidentified as a DV1 by checking
    # the shorter substring first. See device_family()'s docstring.
    assert "DV1" in dev.model().upper()
    assert dev.device_family() == "DV10"


def test_device_family_detects_dv1_when_model_string_says_so(dev):
    dev._transport.state["WI"] = "AOR AR-DV1"  # noqa: SLF001
    assert dev.device_family() == "DV1"


def test_device_family_detects_dv3_when_model_string_says_so(dev):
    # DV3 is the family that additionally offers the 10dB attenuator
    # (web-panel ATT gating keys off device_family()=="DV3").
    dev._transport.state["WI"] = "AOR AR-DV3"  # noqa: SLF001
    assert dev.device_family() == "DV3"


def test_device_family_unrecognised_model_returns_empty_string(dev):
    dev._transport.state["WI"] = "AOR SOMETHING ELSE"  # noqa: SLF001
    assert dev.device_family() == ""


def test_model_is_cached_after_first_read(dev):
    # WI doesn't change mid-connection and this project now polls
    # model()/device_family() every 1.5s from the web panel - see
    # model()'s docstring. Mutating the simulator's backing state after
    # the first read must NOT be reflected until a reconnect.
    first = dev.model()
    dev._transport.state["WI"] = "something completely different"  # noqa: SLF001
    assert dev.model() == first


def test_device_family_cache_cleared_on_reconnect():
    dev = DV10Device.open_simulator()
    dev.connect()
    try:
        assert dev.device_family() == "DV10"
    finally:
        dev.disconnect()

    dev._transport.state["WI"] = "AOR AR-DV1"  # noqa: SLF001
    dev.connect()
    try:
        assert dev.device_family() == "DV1"
    finally:
        dev.disconnect()


def test_analog_modes_without_distinction_for_dv10(dev):
    assert dev.analog_modes_without_distinction() == {"2", "3"}


def test_analog_modes_without_distinction_empty_for_dv1(dev):
    dev._transport.state["WI"] = "AOR AR-DV1"  # noqa: SLF001
    assert dev.analog_modes_without_distinction() == set()


def test_analog_modes_without_distinction_empty_for_unknown_model(dev):
    dev._transport.state["WI"] = "AOR SOMETHING ELSE"  # noqa: SLF001
    assert dev.analog_modes_without_distinction() == set()


def test_analog_modes_without_distinction_table_only_covers_known_codes():
    for family, codes in ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY.items():
        assert family in ("DV10", "DV1")
        assert codes <= {"0", "1", "2", "3", "4", "5", "6"}
