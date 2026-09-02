"""Tests for the web panel's "mem" REST endpoints (/api/memory/*) - the
web-GUI counterpart of the CLI's "mem" verb family, both built on
aor_dv10.memory. Same style as test_web_integration.py: a real embedded
uvicorn server in a background thread, polled/hit with urllib.request so
this doesn't need extra test dependencies (no requests, no TestClient/
httpx - the project's [web] extra doesn't include either).

Skipped entirely if the [web] extra (fastapi/uvicorn) isn't installed.
"""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from aor_dv10.device import DV10Device  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ARDV10_ConnectExport_sample.csv"


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


def _post_bytes(url: str, data: bytes, content_type: str = "text/csv"):
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(url: str):
    req = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture
def panel():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    p = webserver.start_in_thread(dev, host="127.0.0.1", port=18790, mdns=False)
    _get_json(f"{p.url}api/status")  # wait for it to actually be up
    try:
        yield p, dev
    finally:
        p.stop()
        dev.disconnect()
        webserver._memory_banks = []
        webserver._memory_channels = []


def test_memory_endpoints_404_before_import(panel):
    p, _dev = panel
    status, _ = _get(f"{p.url}api/memory")
    assert status == 404
    status, _ = _get(f"{p.url}api/memory/banks")
    assert status == 404
    status, _ = _post(f"{p.url}api/memory/tune/0/0")
    assert status == 404
    status, _ = _get(f"{p.url}api/memory/export")
    assert status == 404


def test_memory_import_and_search_real_export(panel):
    p, _dev = panel
    status, body = _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    assert status == 200
    assert body == {"banks": 40, "channels": 2000, "programmed": 469}

    status, body = _get(f"{p.url}api/memory?q=CH-00")
    assert status == 200
    result = json.loads(body)
    assert result["total"] == 9
    assert result["channels"][0]["name"] == "CH-001"
    assert result["channels"][0]["frequency_mhz"] == 145.5

    status, body = _get(f"{p.url}api/memory/banks")
    banks = json.loads(body)["banks"]
    assert len(banks) == 40
    assert banks[0] == {"index": 0, "protect": False, "title": "---"}


def test_memory_import_rejects_garbage(panel):
    p, _dev = panel
    status, body = _post_bytes(f"{p.url}api/memory/import", b"not,a,valid,header\r\n")
    assert status == 400
    assert "AR-DV10 Connect" in body["detail"]


def test_memory_tune_moves_the_shared_device(panel):
    p, dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())

    status, body = _post(f"{p.url}api/memory/tune/0/0")
    assert status == 200
    assert body["tuned"] == "00-00"
    assert dev.get_frequency_hz() == 145_500_000
    assert dev.get_mode() == "000"

    # bank 04 channel 00 is a confirmed-empty slot in the real export
    status, body = _post(f"{p.url}api/memory/tune/4/0")
    assert status == 400
    assert "unprogrammed" in body["detail"]

    # in-range bank/channel that's simply not in the fixture's programmed
    # set still resolves to a 400 (unprogrammed), never a 404 (unknown)
    status, body = _post(f"{p.url}api/memory/tune/39/49")
    assert status in (200, 400)


def test_memory_export_roundtrips(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())

    status, body = _get(f"{p.url}api/memory/export")
    assert status == 200

    from aor_dv10.memory import parse_backup_csv
    banks, channels = parse_backup_csv(body.decode("utf-8"))
    assert len(banks) == 40
    assert len(channels) == 2000
    assert sum(1 for c in channels if not c.is_empty) == 469
