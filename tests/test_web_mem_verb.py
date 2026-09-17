
from pathlib import Path

import pytest

from aor_dv10.device import DV10Device
from aor_dv10.web import server as web_server
from aor_dv10.web.server import _dispatch_plain

FIXTURE = Path(__file__).parent / "fixtures" / "ARDV10_ConnectExport_sample.csv"


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


@pytest.fixture(autouse=True)
def _reset_shared_memory_state():
    web_server._memory_banks = []
    web_server._memory_channels = []
    yield
    web_server._memory_banks = []
    web_server._memory_channels = []


def test_mem_with_no_args_returns_usage():
    dev = make_device()
    out = _dispatch_plain(dev, "mem")
    assert out.startswith("usage: mem load")


def test_mem_subcommand_before_load_reports_no_database():
    dev = make_device()
    for cmd in ["mem list", "mem find CH-001", "mem goto 00-00", "mem export /tmp/x.csv"]:
        out = _dispatch_plain(dev, cmd)
        assert "no memory database loaded" in out


def test_mem_load_reports_counts_and_populates_shared_state():
    dev = make_device()
    out = _dispatch_plain(dev, f"mem load {FIXTURE}")
    assert "Loaded" in out
    assert "channel slots" in out
    assert len(web_server._memory_channels) > 0
    assert len(web_server._memory_banks) > 0


def test_mem_load_bad_path_reports_error_not_traceback():
    dev = make_device()
    out = _dispatch_plain(dev, "mem load /no/such/file/here.csv")
    assert out.startswith("error:")


def test_mem_list_and_find_known_channel():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    listed = _dispatch_plain(dev, "mem list 0")
    assert "00-00" in listed
    assert "CH-001" in listed

    found = _dispatch_plain(dev, "mem find CH-001")
    assert "00-00" in found
    assert "145.50000 MHz" in found


def test_mem_find_no_matches():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem find NO-SUCH-CHANNEL-NAME-XYZ")
    assert out == "(no matches)"


def test_mem_goto_tunes_device_via_f_m_step_writes():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem goto 00-00")
    assert "Tuned to 00-00" in out
    assert dev.get_frequency_hz() == 145_500_000


def test_mem_goto_unknown_channel_is_an_error_not_a_crash():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem goto 39-99")
    assert out.startswith("error:")
    assert "no such channel" in out


def test_mem_goto_bad_format_is_an_error_not_a_crash():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem goto notabankchannel")
    assert "expected" in out


def test_mem_export_round_trips_through_shared_state(tmp_path):
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out_path = tmp_path / "roundtrip.csv"
    out = _dispatch_plain(dev, f"mem export '{out_path}'")
    assert "Wrote" in out
    assert out_path.exists()
    from aor_dv10.memory import parse_backup_csv
    _, channels = parse_backup_csv(out_path.read_text(encoding="utf-8"))
    ch = next(c for c in channels if c.bank == 0 and c.channel == 0)
    assert ch.name == "CH-001"


def test_mem_export_without_rest_arg_is_usage_not_crash():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem export")
    assert out == "usage: mem export <path>"


def test_mem_unknown_subcommand_is_reported_not_raised():
    dev = make_device()
    _dispatch_plain(dev, f"mem load {FIXTURE}")
    out = _dispatch_plain(dev, "mem bogus")
    assert "unknown 'mem' subcommand" in out


def test_mem_shares_state_with_rest_import_endpoint():
    dev = make_device()
    from aor_dv10.memory import parse_backup_csv

    banks, channels = parse_backup_csv(FIXTURE.read_text(encoding="utf-8-sig"))
    web_server._memory_banks, web_server._memory_channels = banks, channels

    out = _dispatch_plain(dev, "mem find CH-001")
    assert "00-00" in out
