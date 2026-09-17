
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device
from aor_dv10.protocol.codec import Response
from aor_dv10.transport.simulator import SimulatorTransport
from aor_dv10.web.server import _dispatch_plain


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


def make_web_device() -> DV10Device:
    transport = SimulatorTransport()
    d = DV10Device(transport)
    d.connect()
    return d




def test_power_on_returns_confirmed_message_response(dev):
    resp = dev.power_on()
    assert isinstance(resp, Response)
    assert resp.code == "ZP"
    assert resp.value == "AOR AR-DV10"


def test_power_off_returns_a_response_object(dev):
    resp = dev.power_off()
    assert isinstance(resp, Response)
    assert resp.code == "QP"




def test_web_power_on_surfaces_the_real_reply_not_a_hardcoded_ok():
    d = make_web_device()
    out = _dispatch_plain(d, "power on")
    assert out == "ZP AOR AR-DV10"


def test_web_power_off_reply_reflects_the_actual_response():
    d = make_web_device()
    out = _dispatch_plain(d, "power off")
    assert out.startswith("QP")
    assert out != "ok"


def test_web_power_with_no_args_is_a_clean_usage_error_not_an_indexerror():
    d = make_web_device()
    with pytest.raises(ValueError, match="usage: power"):
        _dispatch_plain(d, "power")


def test_web_power_with_bad_arg_is_a_usage_error():
    d = make_web_device()
    with pytest.raises(ValueError, match="usage: power"):
        _dispatch_plain(d, "power sideways")
