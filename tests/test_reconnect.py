
from __future__ import annotations

from aor_dv10.device import DV10Device


def test_reconnect_preserves_simulator_state_and_reports_connected():
    dev = DV10Device.open_simulator()
    dev.connect()
    try:
        dev.set_frequency_hz(145_500_000)
        dev.reconnect()
        assert dev.connected
        assert dev.get_frequency_hz() == 145_500_000
    finally:
        dev.disconnect()


def test_reconnect_is_safe_from_a_never_connected_device():
    dev = DV10Device.open_simulator()
    dev.reconnect()
    assert dev.connected
    dev.disconnect()
