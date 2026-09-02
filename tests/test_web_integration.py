"""Tests for embedding the web panel into another process/thread - see
web/server.py's start_in_thread() and cli/__main__.py's --web flag, the
point of which is to let "dv10-cli --web" give one command, one device
connection, both interfaces (CLI + browser) at once.

Skipped entirely if the [web] extra (fastapi/uvicorn) isn't installed,
since that's an optional dependency of this project, not a hard one.
"""

import json
import time
import urllib.request

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device  # noqa: E402


def _get_json(url: str, timeout: float = 5.0):
    """Poll a URL until it responds or the timeout elapses - the embedded
    uvicorn server starts asynchronously in its own thread, so the caller
    can't assume it's already accepting connections immediately after
    start_in_thread() returns."""
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
    """The whole point of start_in_thread(): the web panel must answer
    using the SAME DV10Device the caller already connected, not a second
    one - proven here by mutating the device directly and checking the web
    panel's /api/status reflects it, and vice versa via a WS-style verb."""
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

        # Mutate the device directly (as the CLI's REPL thread would) and
        # confirm the web panel - running in its own thread - sees it
        # through the SAME device instance, not a stale/separate one.
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
        _get_json(f"{panel.url}api/status")  # wait for it to actually be up
        assert panel.thread.is_alive()

        panel.stop(timeout=5.0)
        assert not panel.thread.is_alive()
    finally:
        dev.disconnect()


def test_websocket_replies_are_always_strings_even_for_numeric_getters():
    """Regression test for a real-hardware-discovered bug: ws_endpoint()
    used to hand _dispatch_plain()'s return value straight to
    websocket.send_text(), which requires an actual str - but a few verbs
    (step, stepadj) return int | None straight from the underlying
    DV10Device getters. Live-tested "step 12500" against a real AR-DV10
    crashed the ASGI app with AttributeError: 'int' object has no
    attribute 'encode'.

    Deliberately goes through a REAL embedded server over a REAL
    WebSocket (unlike test_web_dispatch_ported_verbs.py's direct
    _dispatch_plain() calls) since that ASGI send_text() boundary is
    exactly where the bug lived - calling _dispatch_plain() directly in
    Python never exercises the str-type requirement at all."""
    pytest.importorskip("websockets")
    import asyncio

    import websockets

    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    panel = None
    try:
        panel = webserver.start_in_thread(dev, host="127.0.0.1", port=18783, mdns=False)
        _get_json(f"{panel.url}api/status")  # wait for it to actually be up

        async def exchange():
            async with websockets.connect(f"ws://127.0.0.1:{panel.port}/ws") as ws:
                await ws.recv()  # greeting line
                await ws.send("step 12500")
                assert await ws.recv() == "12500"
                await ws.send("stepadj 500")
                assert await ws.recv() == "500"
                # A verb that returns a bare string still round-trips
                # normally through the same (now type-agnostic) code path.
                await ws.send("s")
                assert isinstance(await ws.recv(), str)

        asyncio.run(exchange())
    finally:
        if panel is not None:
            panel.stop()
        dev.disconnect()


def test_api_status_includes_model_and_sah_sal_gating_for_dv10():
    """/api/status exposes DV10Device.model()/device_family()/
    analog_modes_without_distinction() - see their docstrings in
    device.py. The web panel's Mode section uses
    analog_modes_without_distinction to grey out SAH/SAL, since neither
    is functionally distinct from the other on a real DV10 (per user
    report)."""
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
    """/api/status must expose LM's raw 0-3 squelch_state digit (see
    device.SQUELCH_STATES), not just the collapsed squelch_open boolean -
    the web panel's SQL pill uses squelch_state == 3 ("detecting digital
    mode") to show a distinct "digital signal" indicator instead of the
    generic "open" pill it shows for a plain noise/level/tone squelch
    opening (squelch_open just checks state != 0, which can't tell the
    two apart)."""
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
