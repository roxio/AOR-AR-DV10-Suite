"""Regression tests for atomic VFO control (VF),
VFO search activation (VS), VFO-search settings (VE), and VFO information
(VI) - see aor_dv10.device.DV10Device's enter_vfo_mode()/execute_vfo_search()/
read_vfo_search_settings()/write_vfo_search_settings()/read_vfo_info().
All against the simulator; nothing here has been checked against real
hardware past the original bare "VF A" confirmation - see the docstrings
on the device.py methods under test for what's confirmed vs. inferred.
"""

import pytest

from aor_dv10.device import DV10Device, VfoSearchSettings


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


# -- VF (atomic VFO write) ---------------------------------------------------


def test_bare_enter_vfo_mode_matches_original_real_hardware_confirmed_form(dev):
    """The original, real-hardware-confirmed "VF A" (bare, no other
    fields) behaviour must be unchanged by the task-12 extension - see
    enter_vfo_mode()'s docstring."""
    dev._transport.vfo_mode = False  # noqa: SLF001
    dev.enter_vfo_mode("A")
    assert dev._transport.vfo_mode is True  # noqa: SLF001
    # a tuning write that needs VFO mode should now go through
    dev.set_frequency_hz(146_520_000)
    assert dev.get_frequency_hz() == 146_520_000


def test_enter_vfo_mode_rejects_invalid_letter(dev):
    with pytest.raises(ValueError):
        dev.enter_vfo_mode("Q")


def test_enter_vfo_mode_atomic_write_sets_all_fields(dev):
    dev.enter_vfo_mode(
        "B", frequency_hz=446_006_250, step_hz=12_500, step_adjust_hz=0, mode="F0"
    )
    assert dev.get_frequency_hz() == 446_006_250
    assert dev.get_mode() == "F0"


def test_enter_vfo_mode_omitted_fields_keep_previous_value(dev):
    dev.enter_vfo_mode("B", frequency_hz=446_006_250, mode="F0")
    dev.enter_vfo_mode("B", step_hz=25_000)  # RF/MD omitted
    info = {v.vfo: v for v in dev.read_vfo_info()}
    assert info["B"].frequency_hz == 446_006_250  # kept
    assert info["B"].mode == "F0"  # kept
    assert info["B"].step_hz == 25_000  # newly written


def test_enter_vfo_mode_only_touches_the_selected_vfo(dev):
    dev.enter_vfo_mode("A", frequency_hz=145_500_000)
    dev.enter_vfo_mode("B", frequency_hz=446_006_250)
    info = {v.vfo: v for v in dev.read_vfo_info()}
    assert info["A"].frequency_hz == 145_500_000
    assert info["B"].frequency_hz == 446_006_250
    assert info["Z"].frequency_hz == 145_500_000  # untouched default


# -- VI (read all three VFOs) -------------------------------------------------


def test_read_vfo_info_always_returns_three_entries(dev):
    entries = dev.read_vfo_info()
    assert {e.vfo for e in entries} == {"A", "B", "Z"}


def test_read_vfo_info_multiline_response_with_re_on(dev):
    # Same RE-forcing reliability concern as read_memory_bank()/
    # list_pass_frequencies() - force RE on beforehand and confirm all 3
    # VFO lines still come back (not just the first).
    dev.set_result_code_prefixing(True)
    dev.enter_vfo_mode("A", frequency_hz=145_500_000)
    dev.enter_vfo_mode("B", frequency_hz=446_006_250)
    entries = {e.vfo: e for e in dev.read_vfo_info()}
    assert len(entries) == 3
    assert entries["A"].frequency_hz == 145_500_000
    assert entries["B"].frequency_hz == 446_006_250


# -- VE (VFO-search settings) + VS (activate) --------------------------------


def test_vfo_search_settings_roundtrip(dev):
    dev.write_vfo_search_settings(delay_ds=30, free_time_s=5, auto_store=True)
    assert dev.read_vfo_search_settings() == VfoSearchSettings(
        delay_ds=30, free_time_s=5, auto_store=True
    )


def test_vfo_search_settings_default(dev):
    # Simulator defaults mirror the AR-DV1 spec's own documented defaults
    # (DL=20, FR=00, AS=0/OFF) - see VfoSearchSettings.
    assert dev.read_vfo_search_settings() == VfoSearchSettings(
        delay_ds=20, free_time_s=0, auto_store=False
    )


def test_vfo_search_settings_omitted_fields_keep_previous(dev):
    dev.write_vfo_search_settings(delay_ds=30, free_time_s=5, auto_store=True)
    dev.write_vfo_search_settings(free_time_s=10)  # delay_ds/auto_store omitted
    s = dev.read_vfo_search_settings()
    assert s.delay_ds == 30  # kept
    assert s.auto_store is True  # kept
    assert s.free_time_s == 10  # newly written


def test_execute_vfo_search_does_not_raise(dev):
    dev.execute_vfo_search()  # must not raise
