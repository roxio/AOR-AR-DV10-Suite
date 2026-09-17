
import json
import time
import urllib.request

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device  # noqa: E402


def _get_json(url: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.1)
    raise AssertionError(f"{url} never came up: {last_exc!r}")


def test_start_in_thread_shares_the_given_device():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    panel = None
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18781, mdns=False)
        assert panel.url == "http://127.0.0.1:18781/"
        assert panel.mdns_url is None

        status = _get_json(f"{panel.url}api/status")
        assert status["connected"] is True
        assert status["frequency_hz"] == 145_500_000

        dev.set_frequency_hz(146_520_000)
        status2 = _get_json(f"{panel.url}api/status")
        assert status2["frequency_hz"] == 146_520_000
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()


def test_embedded_panel_stop_shuts_down_the_background_thread():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18782, mdns=False)
        _get_json(f"{panel.url}api/status")
        assert panel.thread.is_alive()

        panel.stop(timeout=5.0)
        assert not panel.thread.is_alive()
    finally:
        dev.disconnect()


def test_websocket_replies_are_always_strings_even_for_numeric_getters():
    pytest.importorskip("websockets")
    import asyncio

    import websockets

    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    panel = None
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18783, mdns=False)
        _get_json(f"{panel.url}api/status")

        async def exchange():
            async with websockets.connect(f"ws://127.0.0.1:{panel.port}/ws") as ws:
                await ws.recv()
                await ws.send("step 12500")
                assert await ws.recv() == "12500"
                await ws.send("stepadj 500")
                assert await ws.recv() == "500"
                await ws.send("s")
                assert isinstance(await ws.recv(), str)

        asyncio.run(exchange())
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()


def test_api_status_includes_model_and_sah_sal_gating_for_dv10():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    panel = None
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18784, mdns=False)
        status = _get_json(f"{panel.url}api/status")
        assert status["device_family"] == "DV10"
        assert "DV10" in status["model"]
        assert sorted(status["analog_modes_without_distinction"]) == ["2", "3"]
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()


def test_api_status_exposes_raw_squelch_state_for_digital_detection():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    panel = None
    try:
        dev._chan.write("LM", "1003")  # noqa: SLF001 - -100dB, state 3 = detecting digital mode
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18786, mdns=False)
        status = _get_json(f"{panel.url}api/status")
        assert status["squelch_state"] == 3
        assert status["squelch_open"] is True
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()


def test_api_status_gating_is_empty_for_a_dv1():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev._transport.state["WI"] = "AOR AR-DV1"  # noqa: SLF001
    dev.connect()
    panel = None
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18785, mdns=False)
        status = _get_json(f"{panel.url}api/status")
        assert status["device_family"] == "DV1"
        assert status["analog_modes_without_distinction"] == []
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()
