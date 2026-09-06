"""Tests for the web panel's live-memory bank-editor REST endpoints
(/api/memory/live_bank/*) - the browser-facing table editor for the
receiver's OWN memory banks (MA/MX/MQ), distinct from the CSV-backup
/api/memory/* endpoints (aor_dv10.memory) tested in test_web_memory.py.

Same style as test_web_memory.py: a real embedded uvicorn server in a
background thread, hit with urllib.request (no requests/httpx dependency).
Skipped entirely if the [web] extra (fastapi/uvicorn) isn't installed.
"""

import itertools
import json
import time
import urllib.error
import urllib.request

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device  # noqa: E402


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _wait_until_up(url: str, timeout: float = 5.0):
    """start_in_thread() returns as soon as the background thread is
    spawned, not once uvicorn has actually bound the port - a single-shot
    request right after it can race the real startup. Poll instead, same
    as test_web_memory.py's _get_json()."""
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0):
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.1)
    raise AssertionError(f"{url} never came up: {last_exc!r}")


def _post_json(url: str, data: dict):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _delete(url: str):
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


_next_port = itertools.count(18800)


@pytest.fixture
def panel():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    # A fresh port per test (rather than one fixed port reused across this
    # file's dozen tests, the way test_web_memory.py's 3-test file does)
    # avoids a real flake seen while writing this file: back-to-back
    # bind/stop cycles on the exact same port can hit "address already in
    # use" before the OS fully releases the previous test's socket.
    port = next(_next_port)
    p = webserver.start_in_thread(dev, host="127.0.0.1", port=port, mdns=False)
    _wait_until_up(f"{p.url}api/status")
    try:
        yield p, dev
    finally:
        p.stop()
        dev.disconnect()


def test_live_bank_rejects_out_of_range_bank(panel):
    p, _dev = panel
    status, _ = _get(f"{p.url}api/memory/live_bank/40")
    assert status == 400
    status, _ = _get(f"{p.url}api/memory/live_bank/-1")
    assert status in (400, 404, 422)  # FastAPI path-int coercion may 404/422 on "-1"


def test_live_bank_read_all_slots_unprogrammed(panel):
    p, _dev = panel
    status, body = _get(f"{p.url}api/memory/live_bank/7")
    assert status == 200
    assert body["bank"] == 7
    assert len(body["channels"]) == 50
    assert all(c["registered"] is False for c in body["channels"])
    assert body["channels"][0]["bank_channel"] == "07-00"


def test_live_bank_reflects_a_channel_written_directly_on_the_device(panel):
    p, dev = panel
    dev.write_memory_channel(
        7, 12, frequency_hz=146_520_000, step_hz=25_000, step_adjust_hz=5_000,
        mode="F0", pass_channel=True, write_protect=False, tag="DIRECT",
    )
    status, body = _get(f"{p.url}api/memory/live_bank/7")
    assert status == 200
    ch = body["channels"][12]
    assert ch["registered"] is True
    assert ch["frequency_mhz"] == pytest.approx(146.52)
    assert ch["step_hz"] == 25_000
    assert ch["step_adjust_hz"] == 5_000
    assert ch["mode"] == "F0"
    assert ch["pass_channel"] is True
    assert ch["write_protect"] is False
    assert ch["tag"] == "DIRECT"


def test_live_channel_write_round_trips_every_field(panel):
    p, _dev = panel
    status, body = _post_json(f"{p.url}api/memory/live_bank/2/9", {
        "frequency_mhz": 445.0,
        "step_hz": 12500,
        "step_adjust_hz": 2500,
        "mode": "00",
        "pass_channel": True,
        "write_protect": False,
        "tag": "REST-WR",
    })
    assert status == 200
    assert body["registered"] is True
    assert body["frequency_mhz"] == pytest.approx(445.0)
    assert body["step_hz"] == 12500
    assert body["step_adjust_hz"] == 2500
    assert body["mode"] == "00"
    assert body["pass_channel"] is True
    assert body["tag"] == "REST-WR"

    # Re-fetching the whole bank should agree with the single-write response.
    status, bank_body = _get(f"{p.url}api/memory/live_bank/2")
    assert status == 200
    assert bank_body["channels"][9] == body


def test_live_channel_write_rejects_out_of_range(panel):
    p, _dev = panel
    status, _ = _post_json(f"{p.url}api/memory/live_bank/40/0", {"frequency_mhz": 145.0})
    assert status == 400
    status, _ = _post_json(f"{p.url}api/memory/live_bank/0/50", {"frequency_mhz": 145.0})
    assert status == 400


def test_write_protect_guard_refuses_without_force_then_succeeds_with_force(panel):
    p, dev = panel
    dev.write_memory_channel(5, 3, frequency_hz=146_000_000, mode="00", write_protect=True, tag="LOCKED")

    status, body = _post_json(f"{p.url}api/memory/live_bank/5/3", {"frequency_mhz": 147.0})
    assert status == 409
    assert "write-protected" in body["detail"]
    # the refused write must not have gone through
    assert dev.read_memory_channel(5, 3).frequency_hz == 146_000_000

    status, body = _post_json(f"{p.url}api/memory/live_bank/5/3", {"frequency_mhz": 147.0, "force": True})
    assert status == 200
    assert body["frequency_mhz"] == pytest.approx(147.0)


def test_write_protect_guard_does_not_apply_to_unregistered_slot(panel):
    """An unprogrammed slot has write_protect=False by construction (see
    MemoryChannelInfo's docstring: every field but bank/channel/registered
    is meaningless when unregistered) - writing to one for the first time
    must never be refused as "protected"."""
    p, _dev = panel
    status, body = _post_json(f"{p.url}api/memory/live_bank/9/0", {"frequency_mhz": 100.0})
    assert status == 200
    assert body["registered"] is True


def test_batch_write_reports_per_channel_results(panel):
    p, _dev = panel
    status, body = _post_json(f"{p.url}api/memory/live_bank/11/batch", {
        "channels": [
            {"channel": 0, "frequency_mhz": 145.0, "mode": "00", "tag": "A"},
            {"channel": 1, "frequency_mhz": 146.0, "mode": "00", "tag": "B"},
            {"channel": 99, "frequency_mhz": 147.0},  # out of range
        ],
    })
    assert status == 200
    results = {r["channel"]: r for r in body["results"]}
    assert results[0]["ok"] is True
    assert results[1]["ok"] is True
    assert results[99]["ok"] is False

    status, bank_body = _get(f"{p.url}api/memory/live_bank/11")
    assert bank_body["channels"][0]["tag"] == "A"
    assert bank_body["channels"][1]["tag"] == "B"


def test_batch_write_skips_protected_channel_without_force_but_writes_others(panel):
    p, dev = panel
    dev.write_memory_channel(13, 4, frequency_hz=145_000_000, mode="00", write_protect=True, tag="LOCK")

    status, body = _post_json(f"{p.url}api/memory/live_bank/13/batch", {
        "channels": [
            {"channel": 4, "frequency_mhz": 200.0},  # protected, no force
            {"channel": 6, "frequency_mhz": 200.0},  # unprotected, should go through
        ],
    })
    assert status == 200
    results = {r["channel"]: r for r in body["results"]}
    assert results[4]["ok"] is False
    assert "protect" in results[4]["error"]
    assert results[6]["ok"] is True
    # protected channel's frequency must be unchanged
    assert dev.read_memory_channel(13, 4).frequency_hz == 145_000_000


def test_batch_write_per_item_force_overrides_protect(panel):
    p, dev = panel
    dev.write_memory_channel(15, 2, frequency_hz=145_000_000, mode="00", write_protect=True, tag="LOCK")

    status, body = _post_json(f"{p.url}api/memory/live_bank/15/batch", {
        "channels": [{"channel": 2, "frequency_mhz": 250.0, "force": True}],
    })
    assert status == 200
    assert body["results"][0]["ok"] is True
    assert dev.read_memory_channel(15, 2).frequency_hz == 250_000_000


def test_live_channel_delete(panel):
    p, dev = panel
    dev.write_memory_channel(20, 8, frequency_hz=145_000_000, mode="00", tag="TOGO")
    assert dev.read_memory_channel(20, 8).registered is True

    status, body = _delete(f"{p.url}api/memory/live_bank/20/8")
    assert status == 200
    assert body["deleted"] == "20-08"
    assert dev.read_memory_channel(20, 8).registered is False


def test_live_channel_delete_rejects_out_of_range(panel):
    p, _dev = panel
    status, _ = _delete(f"{p.url}api/memory/live_bank/40/0")
    assert status == 400
