"""Regression tests for search banks (SE/SR/SS/SX/
SL/SU), scan groups (SG/MG) and their standalone sub-commands (AS/BK), and
pass frequencies (PW/PR/PD) - see
aor_dv10.device.DV10Device's "search banks"/"scan groups"/"pass
frequencies" sections. All against the simulator; nothing here has been
checked against real hardware yet - see the docstrings on the device.py
methods under test for what's confirmed vs. inferred.
"""

import pytest

from aor_dv10.device import DV10Device, ScanGroupInfo, SearchBankInfo
from aor_dv10.protocol.codec import DV10ProtocolError


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


# -- search banks (SE/SR/SS/SX/SL/SU) ----------------------------------------


def test_write_then_read_search_bank_roundtrip(dev):
    dev.write_search_bank(
        1,
        lower_limit_hz=144_000_000,
        upper_limit_hz=148_000_000,
        step_hz=12_500,
        step_adjust_hz=0,
        mode="F0",
        write_protect=True,
        tag="2MBAND",
    )
    info = dev.read_search_bank(1)
    assert info == SearchBankInfo(
        bank=1,
        registered=True,
        lower_limit_hz=144_000_000,
        upper_limit_hz=148_000_000,
        step_hz=12_500,
        step_adjust_hz=0,
        mode="F0",
        write_protect=True,
        tag="2MBAND",
    )


def test_search_bank_mode_is_natural_order_not_reversed(dev):
    # Same "safety-critical" convention as write_memory_channel() - see
    # write_search_bank()'s docstring.
    dev.write_search_bank(2, mode="F0")
    info = dev.read_search_bank(2)
    assert info.mode == "F0"


def test_write_search_bank_omitted_fields_keep_previous_except_pt(dev):
    dev.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000, write_protect=True)
    dev.write_search_bank(3, step_hz=25_000)  # SL/SU/PT omitted
    info = dev.read_search_bank(3)
    assert info.lower_limit_hz == 144_000_000  # kept
    assert info.upper_limit_hz == 148_000_000  # kept
    assert info.step_hz == 25_000  # newly written
    assert info.write_protect is False  # PT resets to 0 when omitted


def test_read_search_bank_not_registered_raises(dev):
    with pytest.raises(DV10ProtocolError):
        dev.read_search_bank(9)


def test_execute_search(dev):
    dev.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.execute_search(1)  # must not raise


def test_execute_search_unregistered_raises(dev):
    with pytest.raises(DV10ProtocolError):
        dev.execute_search(5)


def test_delete_search_bank(dev):
    dev.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.delete_search_bank(1)
    with pytest.raises(DV10ProtocolError):
        dev.read_search_bank(1)


def test_delete_search_bank_not_registered_raises(dev):
    with pytest.raises(DV10ProtocolError):
        dev.delete_search_bank(7)


def test_search_lower_upper_limit_roundtrip(dev):
    dev.set_search_lower_limit(144_000_000)
    dev.set_search_upper_limit(148_000_000)
    assert dev.get_search_lower_limit() == 144_000_000
    assert dev.get_search_upper_limit() == 148_000_000


# -- scan groups (SG search-side / MG memory-side) + AS/BK standalone -------


def test_write_then_read_search_scan_group_roundtrip(dev):
    dev.write_search_scan_group(0, delay_ds=25, free_time_s=5, auto_store=True, bank_link=[1, 2, 3])
    info = dev.read_search_scan_group(0)
    assert info == ScanGroupInfo(group=0, delay_ds=25, free_time_s=5, auto_store=True, bank_link=(1, 2, 3))


def test_write_then_read_memory_scan_group_roundtrip(dev):
    dev.write_memory_scan_group(1, delay_ds=10, free_time_s=2, bank_link=[5])
    info = dev.read_memory_scan_group(1)
    # MG has no AS sub-field at all - auto_store must stay None, not False.
    assert info == ScanGroupInfo(group=1, delay_ds=10, free_time_s=2, auto_store=None, bank_link=(5,))


def test_memory_scan_group_never_gets_an_auto_store_field(dev):
    dev.write_memory_scan_group(2, delay_ds=20, free_time_s=0)
    info = dev.read_memory_scan_group(2)
    assert info.auto_store is None


def test_bank_link_none_omits_leaving_previous_value_unchanged(dev):
    # bank_link follows the SAME omit-convention as every other field in
    # this composite write: None means "don't send BK at all", not
    # "disable it" - see write_search_scan_group()'s docstring.
    dev.write_search_scan_group(0, bank_link=[1, 2])
    assert dev.read_search_scan_group(0).bank_link == (1, 2)
    dev.write_search_scan_group(0, delay_ds=30)  # bank_link left at its default (None) -> omitted
    assert dev.read_search_scan_group(0).bank_link == (1, 2)  # unchanged


def test_bank_link_empty_list_disables_all_links(dev):
    dev.write_search_scan_group(0, bank_link=[1, 2])
    assert dev.read_search_scan_group(0).bank_link == (1, 2)
    dev.write_search_scan_group(0, bank_link=[])  # explicit empty list -> BK99
    assert dev.read_search_scan_group(0).bank_link == ()


def test_standalone_auto_store_roundtrip(dev):
    dev.set_auto_store(True)
    assert dev.get_auto_store() is True
    dev.set_auto_store(False)
    assert dev.get_auto_store() is False


def test_standalone_bank_link_roundtrip(dev):
    dev.set_bank_link([4, 5, 6])
    assert dev.get_bank_link() == [4, 5, 6]
    dev.set_bank_link(None)
    assert dev.get_bank_link() == []
    dev.set_bank_link([])
    assert dev.get_bank_link() == []


# -- pass frequencies (PW mark / PR list / PD delete) ------------------------


def test_mark_bare_pw_uses_current_rf_for_vfo_search(dev):
    dev.set_frequency_hz(146_520_000)
    dev.mark_pass_frequency()
    entries = dev.list_pass_frequencies()
    assert entries[0].frequency_hz == 146_520_000
    assert entries[0].bank is None


def test_mark_explicit_frequency_for_vfo_search(dev):
    dev.mark_pass_frequency(frequency_hz=146_520_000)
    entries = dev.list_pass_frequencies()
    assert entries[0].frequency_hz == 146_520_000


def test_mark_frequency_for_a_specific_bank(dev):
    dev.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.mark_pass_frequency(frequency_hz=146_940_000, bank=3)
    entries = dev.list_pass_frequencies(bank=3)
    assert entries[0].frequency_hz == 146_940_000
    assert entries[0].bank == 3
    # a separate, VFO-search list is untouched
    assert all(e.frequency_hz is None for e in dev.list_pass_frequencies())


def test_mark_all_banks_wildcard(dev):
    dev.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.write_search_bank(2, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.mark_pass_frequency(frequency_hz=145_000_000, all_banks=True)
    assert dev.list_pass_frequencies(bank=1)[0].frequency_hz == 145_000_000
    assert dev.list_pass_frequencies(bank=2)[0].frequency_hz == 145_000_000


def test_mark_pass_frequency_bank_and_all_banks_conflict_raises(dev):
    with pytest.raises(ValueError):
        dev.mark_pass_frequency(bank=1, all_banks=True)


def test_list_pass_frequencies_always_returns_fifty_slots(dev):
    entries = dev.list_pass_frequencies()
    assert len(entries) == 50
    assert all(e.frequency_hz is None for e in entries)


def test_list_pass_frequencies_multiline_response_with_re_on(dev):
    # Same RE-forcing reliability concern as read_memory_bank() - force RE
    # on beforehand and confirm the full 50-slot list still comes back
    # (not just the first line).
    dev.set_result_code_prefixing(True)
    for i in range(5):
        dev.mark_pass_frequency(frequency_hz=146_000_000 + i * 25_000)
    entries = dev.list_pass_frequencies()
    assert len(entries) == 50
    assert sum(1 for e in entries if e.frequency_hz is not None) == 5


def test_delete_all_vfo_search_pass_frequencies(dev):
    dev.mark_pass_frequency(frequency_hz=146_520_000)
    dev.delete_pass_frequencies()
    assert all(e.frequency_hz is None for e in dev.list_pass_frequencies())


def test_delete_pass_frequencies_for_one_bank(dev):
    dev.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.mark_pass_frequency(frequency_hz=146_940_000, bank=3)
    dev.delete_pass_frequencies(bank=3)
    assert all(e.frequency_hz is None for e in dev.list_pass_frequencies(bank=3))


def test_delete_pass_frequencies_all_banks_wildcard(dev):
    dev.write_search_bank(1, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.write_search_bank(2, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.mark_pass_frequency(frequency_hz=145_000_000, bank=1)
    dev.mark_pass_frequency(frequency_hz=145_000_000, bank=2)
    dev.delete_pass_frequencies(all_banks=True)
    assert all(e.frequency_hz is None for e in dev.list_pass_frequencies(bank=1))
    assert all(e.frequency_hz is None for e in dev.list_pass_frequencies(bank=2))


def test_delete_one_pass_frequency_by_index(dev):
    dev.write_search_bank(3, lower_limit_hz=144_000_000, upper_limit_hz=148_000_000)
    dev.mark_pass_frequency(frequency_hz=146_940_000, bank=3)
    dev.delete_pass_frequencies(bank=3, index=0)
    assert dev.list_pass_frequencies(bank=3)[0].frequency_hz is None


def test_delete_pass_frequencies_index_without_bank_raises(dev):
    with pytest.raises(ValueError):
        dev.delete_pass_frequencies(index=1)


def test_delete_pass_frequencies_index_with_all_banks_raises(dev):
    with pytest.raises(ValueError):
        dev.delete_pass_frequencies(all_banks=True, index=1)


def test_delete_pass_frequencies_bank_and_all_banks_conflict_raises(dev):
    with pytest.raises(ValueError):
        dev.delete_pass_frequencies(bank=1, all_banks=True)
