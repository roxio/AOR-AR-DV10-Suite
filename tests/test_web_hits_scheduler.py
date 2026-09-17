
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
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.1)
    raise AssertionError(f"{url} never came up: {last!r}")


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post_bytes(url: str, data: bytes, content_type: str = "application/json"):
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


def _delete(url: str):
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def panel():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    p = webserver.start_in_thread(dev, host="127.0.0.1", port=18795, mdns=False)
    _get_json(f"{p.url}api/status")
    try:
        yield p, dev
    finally:
        p.stop()
        dev.disconnect()
        webserver._hits.clear()
        webserver._scheduled_jobs.clear()


def test_hits_add_list_clear(panel):
    p, _dev = panel
    status, body = _post_bytes(
        f"{p.url}api/hits",
        json.dumps({"time": "t1", "mhz": 145.5, "dbm": -50, "digital": False, "mode": "0F0", "tone": "88.5"}).encode(),
    )
    assert status == 200
    assert body["count"] == 1

    status, body = _get(f"{p.url}api/hits")
    hits = json.loads(body)["hits"]
    assert hits[-1]["mhz"] == 145.5
    assert hits[-1]["tone"] == "88.5"

    status, body = _delete(f"{p.url}api/hits")
    assert body["count"] == 0
    status, body = _get(f"{p.url}api/hits")
    assert json.loads(body)["hits"] == []


def test_scheduler_rejects_bad_job(panel):
    p, _dev = panel
    status, _ = _post_bytes(
        f"{p.url}api/scheduler/jobs",
        json.dumps({"id": "x", "action": "nope", "interval_s": 10}).encode(),
    )
    assert status == 400
    status, _ = _post_bytes(
        f"{p.url}api/scheduler/jobs",
        json.dumps({"id": "x", "action": "backup", "interval_s": 0}).encode(),
    )
    assert status == 400


def test_scheduler_crud_and_manual_run(panel, tmp_path, monkeypatch):
    p, _dev = panel
    from aor_dv10.web import server as webserver

    monkeypatch.setattr(webserver, "_backup_dir", tmp_path)

    status, body = _post_bytes(
        f"{p.url}api/scheduler/jobs",
        json.dumps({"id": "b1", "action": "backup", "interval_s": 60}).encode(),
    )
    assert status == 200
    assert body["job"]["id"] == "b1"

    status, body = _get(f"{p.url}api/scheduler/jobs")
    assert [j["id"] for j in json.loads(body)["jobs"]] == ["b1"]

    status, body = _post(f"{p.url}api/scheduler/jobs/b1/run")
    assert status == 200
    assert "no memory database" in body["result"]

    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    status, body = _post(f"{p.url}api/scheduler/jobs/b1/run")
    assert status == 200
    assert "backup" in body["result"]
    assert any(tmp_path.glob("*.json"))

    status, body = _delete(f"{p.url}api/scheduler/jobs/b1")
    assert body["deleted"] == "b1"
    status, _ = _post(f"{p.url}api/scheduler/jobs/b1/run")
    assert status == 404


def test_scheduler_scan_job_runs_search(panel):
    p, dev = panel
    dev.write_search_bank(0, lower_limit_hz=145_000_000, upper_limit_hz=146_000_000, step_hz=12_500)
    status, body = _post_bytes(
        f"{p.url}api/scheduler/jobs",
        json.dumps({"id": "s1", "action": "scan", "interval_s": 300, "bank": 0}).encode(),
    )
    assert status == 200
    status, body = _post(f"{p.url}api/scheduler/jobs/s1/run")
    assert status == 200
    assert "search bank 00" in body["result"]


def test_import_url_rejects_non_http(panel):
    p, _dev = panel
    status, _ = _post_bytes(
        f"{p.url}api/import/url", json.dumps({"url": "ftp://example/x.csv"}).encode()
    )
    assert status == 400


def test_import_url_handles_fetch_failure(panel):
    p, _dev = panel
    status, body = _post_bytes(
        f"{p.url}api/import/url",
        json.dumps({"url": "http://127.0.0.1:1/none.csv"}).encode(),
    )
    assert status == 502
    assert "could not fetch" in body["detail"]
