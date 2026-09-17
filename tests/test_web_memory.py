
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
    p = webserver.start_in_thread(dev, host="127.0.0.1", port=18790, mdns=False)
    _get_json(f"{p.url}api/status")
    try:
        yield p, dev
    finally:
        p.stop()
        dev.disconnect()
        webserver._memory_banks = []
        webserver._memory_channels = []


def test_reconnect_endpoint(panel):
    p, dev = panel
    status, body = _post(f"{p.url}api/reconnect")
    assert status == 200
    assert body["connected"] is True
    dev.set_frequency_hz(145_500_000)
    assert dev.get_frequency_hz() == 145_500_000


def test_memory_autolabel_fills_blank_names(panel):
    p, _dev = panel
    from aor_dv10.memory import MemoryChannel
    from aor_dv10.web import server as webserver

    webserver._memory_banks = []
    webserver._memory_channels = [
        MemoryChannel(bank=0, channel=0, frequency_hz=145_500_000, mode="0F0", name=""),
        MemoryChannel(bank=0, channel=1, frequency_hz=433_500_000, mode="0F0", name="KEEP"),
    ]
    status, body = _post(f"{p.url}api/memory/autolabel")
    assert status == 200
    assert body["labeled"] == 1
    assert webserver._memory_channels[0].name.startswith("0F0")
    assert webserver._memory_channels[1].name == "KEEP"


def test_memory_autolabel_404_before_import(panel):
    p, _dev = panel
    status, _ = _post(f"{p.url}api/memory/autolabel")
    assert status == 404


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

    status, body = _post(f"{p.url}api/memory/tune/4/0")
    assert status == 400
    assert "unprogrammed" in body["detail"]

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


def test_memory_live_export_rejects_bad_bank(panel):
    p, _dev = panel
    status, _ = _get(f"{p.url}api/memory/live_export/40")
    assert status == 400
    status, _ = _get(f"{p.url}api/memory/live_export/-1")
    assert status == 400


def test_memory_live_export_reads_the_live_device(panel):
    p, dev = panel
    dev.write_memory_channel(
        3, 5, frequency_hz=146_520_000, mode="F0", tag="LIVE CH", write_protect=True
    )

    status, body = _get(f"{p.url}api/memory/live_export/3")
    assert status == 200

    from aor_dv10.memory import parse_backup_csv
    banks, channels = parse_backup_csv(body.decode("utf-8"))
    assert len(banks) == 1
    assert banks[0].index == 3
    assert len(channels) == 50

    ch5 = next(c for c in channels if c.channel == 5)
    assert ch5.frequency_mhz == 146.52
    assert ch5.name == "LIVE CH"
    assert ch5.protect is True
    assert sum(1 for c in channels if not c.is_empty) == 1


def test_memory_diff_requires_import_first(panel):
    p, _dev = panel
    status, body = _get(f"{p.url}api/memory/diff/3")
    assert status == 404
    assert "import" in json.loads(body)["detail"]


def test_memory_diff_rejects_bad_bank(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    status, _ = _get(f"{p.url}api/memory/diff/40")
    assert status == 400


def test_memory_diff_reports_only_changed_channels(panel):
    p, dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())

    status, body = _get(f"{p.url}api/memory/diff/0")
    assert status == 200
    result = json.loads(body)
    assert result["bank"] == 0
    assert result["compared"] == 50
    assert result["differences"] > 0
    assert any(d["bank_channel"] == "00-00" for d in result["channels"])

    dev.write_memory_channel(0, 0, frequency_hz=145_500_000, mode="000", tag="CH-001")
    status, body = _get(f"{p.url}api/memory/diff/0")
    result = json.loads(body)
    assert not any(d["bank_channel"] == "00-00" for d in result["channels"])




def test_memory_new_export_endpoints_404_before_import(panel):
    p, _dev = panel
    for ep in ("export_json", "export_chirp"):
        status, _ = _get(f"{p.url}api/memory/{ep}")
        assert status == 404


def test_adif_export_404_before_import(panel):
    p, _dev = panel
    status, _ = _get(f"{p.url}api/adif/export")
    assert status == 404


def test_adif_export_and_import_roundtrip(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    status, body = _get(f"{p.url}api/adif/export")
    assert status == 200
    text = body.decode("utf-8")
    assert "<EOH>" in text and "<FREQ:" in text

    status, resp = _post_bytes(f"{p.url}api/adif/import", body, "text/plain")
    assert status == 200
    assert resp["programmed"] == 469


def test_adif_import_rejects_garbage(panel):
    p, _dev = panel
    status, _ = _post_bytes(f"{p.url}api/adif/import", b"<EOH>nonsense<EOR>", "text/plain")
    assert status == 400


def test_memory_backups_lifecycle(panel, tmp_path, monkeypatch):
    p, _dev = panel
    from aor_dv10.web import server as webserver

    monkeypatch.setattr(webserver, "_backup_dir", tmp_path)
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())

    status, body = _post(f"{p.url}api/memory/backups")
    assert status == 200
    name = body["name"]
    assert (tmp_path / name).exists()

    status, body = _get(f"{p.url}api/memory/backups")
    assert name in [b["name"] for b in json.loads(body)["backups"]]

    webserver._memory_banks, webserver._memory_channels = [], []
    status, body = _post(f"{p.url}api/memory/backups/{name}/restore")
    assert status == 200
    assert body["programmed"] == 469

    status, body = _delete(f"{p.url}api/memory/backups/{name}")
    assert status == 200
    assert not (tmp_path / name).exists()


def test_memory_backups_reject_path_traversal(panel, tmp_path, monkeypatch):
    p, _dev = panel
    from aor_dv10.web import server as webserver

    monkeypatch.setattr(webserver, "_backup_dir", tmp_path)
    status, _ = _post(f"{p.url}api/memory/backups/..%2Fevil.json/restore")
    assert status in (400, 404)
    status, _ = _delete(f"{p.url}api/memory/backups/..%2Fevil.json")
    assert status in (400, 404)


def test_memory_backups_create_404_before_import(panel, tmp_path, monkeypatch):
    p, _dev = panel
    from aor_dv10.web import server as webserver

    monkeypatch.setattr(webserver, "_backup_dir", tmp_path)
    status, _ = _post(f"{p.url}api/memory/backups")
    assert status == 404


def test_memory_export_json_roundtrips(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    status, body = _get(f"{p.url}api/memory/export_json")
    assert status == 200

    from aor_dv10.memory import backup_from_json
    banks, channels = backup_from_json(body.decode("utf-8"))
    assert len(banks) == 40
    assert len(channels) == 2000
    assert sum(1 for c in channels if not c.is_empty) == 469


def test_memory_import_json_restores_snapshot(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    _, snapshot = _get(f"{p.url}api/memory/export_json")

    from aor_dv10.web import server as webserver
    webserver._memory_banks, webserver._memory_channels = [], []

    status, body = _post_bytes(f"{p.url}api/memory/import_json", snapshot, "application/json")
    assert status == 200
    assert body == {"banks": 40, "channels": 2000, "programmed": 469}


def test_memory_import_json_rejects_foreign_body(panel):
    p, _dev = panel
    status, body = _post_bytes(f"{p.url}api/memory/import_json", b"{}", "application/json")
    assert status == 400


def test_memory_export_chirp_roundtrips(panel):
    p, _dev = panel
    _post_bytes(f"{p.url}api/memory/import", FIXTURE.read_bytes())
    status, body = _get(f"{p.url}api/memory/export_chirp")
    assert status == 200
    text = body.decode("utf-8")
    assert text.splitlines()[0].startswith("Location,Name,Frequency")

    from aor_dv10.memory import parse_chirp_csv
    _banks, channels = parse_chirp_csv(text)
    assert sum(1 for c in channels if not c.is_empty) == 469


def test_memory_import_freqs_endpoint(panel):
    p, _dev = panel
    body = b"Frequency,Name,Mode,Step\n145.500000,CALL,FM,12.5\n7.030000,CW QRP,CW,5\n"
    status, resp = _post_bytes(f"{p.url}api/memory/import_freqs", body, "text/csv")
    assert status == 200
    assert resp["programmed"] == 2

    status, body = _get(f"{p.url}api/memory?q=CALL")
    result = json.loads(body)
    assert result["channels"][0]["name"] == "CALL"
    assert result["channels"][0]["frequency_mhz"] == 145.5
