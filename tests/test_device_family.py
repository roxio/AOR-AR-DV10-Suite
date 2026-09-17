
import pytest

from aor_dv10.device import ANALOG_MODES_WITHOUT_DISTINCTION_BY_FAMILY, DV10Device


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


def test_device_family_detects_dv10_from_default_simulator_model(dev):
    assert dev.model()
    assert dev.device_family() == "DV10"


def test_device_family_checks_dv10_before_dv1_substring(dev):
    assert "DV1" in dev.model().upper()
    assert dev.device_family() == "DV10"


def test_device_family_detects_dv1_when_model_string_says_so(dev):
    dev._transport.state["WI"] = "AOR AR-DV1"  # noqa: SLF001
    assert dev.device_family() == "DV1"


def test_device_family_detects_dv3_when_model_string_says_so(dev):
    dev._transport.state["WI"] = "AOR AR-DV3"  # noqa: SLF001
    assert dev.device_family() == "DV3"


def test_device_family_unrecognised_model_returns_empty_string(dev):
    dev._transport.state["WI"] = "AOR SOMETHING ELSE"  # noqa: SLF001
    assert dev.device_family() == ""


def test_model_is_cached_after_first_read(dev):
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
