
from aor_dv10.device import DV10Device
from aor_dv10.web.server import _dispatch_plain


def _make_simulator_model(model: str):
    dev = DV10Device.open_simulator()
    dev.connect()
    if model:
        dev._transport.state["WI"] = model  # noqa: SLF001
    return dev


def test_sd_rec_stop_refused_on_dv10_default_simulator():
    dev = DV10Device.open_simulator()
    with dev:
        assert dev.device_family() == "DV10"
        try:
            _dispatch_plain(dev, "sd rec stop")
            raise AssertionError("sd rec stop should have been refused on DV10")
        except ValueError as exc:
            assert "front-panel" in str(exc) or "not supported" in str(exc)


def test_sd_rec_start_still_allowed_on_dv10():
    dev = DV10Device.open_simulator()
    with dev:
        assert dev.device_family() == "DV10"
        assert _dispatch_plain(dev, "sd rec start") == "recording started"


def test_sd_rec_stop_allowed_on_non_dv10():
    dev = _make_simulator_model("AOR AR-DV1")
    with dev:
        assert dev.device_family() == "DV1"
        result = _dispatch_plain(dev, "sd rec stop")
        assert "stopped" in result


def test_sd_backup_refused_on_dv10():
    dev = DV10Device.open_simulator()
    with dev:
        assert dev.device_family() == "DV10"
        try:
            _dispatch_plain(dev, "sd backup SRCHBK")
            raise AssertionError("sd backup should be refused on DV10")
        except ValueError as exc:
            assert "not supported on the AR-DV10" in str(exc)


def test_sd_restore_refused_on_dv10():
    dev = DV10Device.open_simulator()
    with dev:
        try:
            _dispatch_plain(dev, "sd restore X.DAT")
            raise AssertionError("sd restore should be refused on DV10")
        except ValueError as exc:
            assert "not supported on the AR-DV10" in str(exc)


def test_sd_backup_allowed_on_non_dv10():
    dev = _make_simulator_model("AOR AR-DV1")
    with dev:
        assert dev.device_family() == "DV1"
        result = _dispatch_plain(dev, "sd backup SRCHBK")
        assert "backed up" in result
