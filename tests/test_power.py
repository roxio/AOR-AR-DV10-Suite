"""Regression tests for power_on()/power_off() (ZP/QP) and the "power"
verb in both the CLI and the web panel's _dispatch_plain().

Added 2026-09-01 after fixing a code-honesty bug: both device.py methods
used to discard the Response entirely, and the web verb always returned
a hardcoded "ok" regardless of what the device actually said - see
docs/PROTOCOL.md's "power off (QP) surfaces a fake ok" entry. These
tests lock in that the real Response now comes back through, and that
bad/missing "on"/"off" arguments are rejected with a clear usage error
instead of a raw IndexError.

All against the simulator; QP's real-hardware response has never been
confirmed (see PROTOCOL.md) - the simulator's empty-ack model for QP is
an explicit unverified guess, not a confirmation, so these tests pin
down current *code* behaviour, not real device behaviour.
"""

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


# -- device.py: power_on()/power_off() return the real Response ---------


def test_power_on_returns_confirmed_message_response(dev):
    resp = dev.power_on()
    assert isinstance(resp, Response)
    assert resp.code == "ZP"
    assert resp.value == "AOR AR-DV10"


def test_power_off_returns_a_response_object(dev):
    # QP's real-hardware reply is unconfirmed (see PROTOCOL.md) - this
    # only pins down that the simulator's modelled ack now actually
    # reaches the caller instead of being discarded, whatever it is.
    resp = dev.power_off()
    assert isinstance(resp, Response)
    assert resp.code == "QP"


# -- web panel verb dispatch ---------------------------------------------


def test_web_power_on_surfaces_the_real_reply_not_a_hardcoded_ok():
    d = make_web_device()
    out = _dispatch_plain(d, "power on")
    assert out == "ZP AOR AR-DV10"


def test_web_power_off_reply_reflects_the_actual_response():
    d = make_web_device()
    out = _dispatch_plain(d, "power off")
    # Whatever QP's value is, the code echo must be present - this is
    # the "real reply, not a fake ok" contract; not a claim about what
    # QP's value should be (unconfirmed on real hardware).
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
