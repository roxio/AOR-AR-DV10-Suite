
from __future__ import annotations

from aor_dv10.device_types import PassFrequencyEntry, ScanGroupInfo, SearchBankInfo
from aor_dv10.record_format import format_pass_list, format_scan_group, format_search_bank


def test_format_search_bank():
    info = SearchBankInfo(
        bank=3, registered=True, lower_limit_hz=145_000_000, upper_limit_hz=146_000_000,
        step_hz=12_500, step_adjust_hz=0, mode="0F0", write_protect=False, tag="2M",
    )
    assert format_search_bank(info) == (
        "bank 03: 145.0000-146.0000 MHz  step=12500  stepadj=0  "
        "mode=0F0  protect=False  '2M'"
    )


def test_format_search_bank_unknown_limits():
    info = SearchBankInfo(
        bank=0, registered=False, lower_limit_hz=None, upper_limit_hz=None,
        step_hz=None, step_adjust_hz=None, mode=None, write_protect=True, tag="",
    )
    assert format_search_bank(info) == (
        "bank 00: ?-? MHz  step=None  stepadj=None  mode=None  protect=True  ''"
    )


def test_format_scan_group():
    info = ScanGroupInfo(group=2, delay_ds=20, free_time_s=5, auto_store=True, bank_link=(0, 3, 39))
    assert format_scan_group(info, kind="search") == (
        "search group 02: delay=20 free=5 autostore=True banks=[0, 3, 39]"
    )
    assert format_scan_group(info, kind="memory") == (
        "memory group 02: delay=20 free=5 autostore=True banks=[0, 3, 39]"
    )


def test_format_pass_list():
    entries = [
        PassFrequencyEntry(index=0, frequency_hz=145_500_000),
        PassFrequencyEntry(index=1, frequency_hz=None),
        PassFrequencyEntry(index=2, frequency_hz=433_500_000),
    ]
    assert format_pass_list(entries) == (
        "00: 145.5000 MHz\n02: 433.5000 MHz\n(2 of 3 slots used)"
    )
