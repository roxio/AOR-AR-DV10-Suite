
import pytest

from aor_dv10.device import DV10Device, VfoSearchSettings


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d




def test_bare_enter_vfo_mode_matches_original_real_hardware_confirmed_form(dev):
    dev._transport.vfo_mode = False  # noqa: SLF001
    dev.enter_vfo_mode("A")
    assert dev._transport.vfo_mode is True  # noqa: SLF001
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
    dev.enter_vfo_mode("B", step_hz=25_000)
    info = {v.vfo: v for v in dev.read_vfo_info()}
    assert info["B"].frequency_hz == 446_006_250
    assert info["B"].mode == "F0"
    assert info["B"].step_hz == 25_000


def test_enter_vfo_mode_only_touches_the_selected_vfo(dev):
    dev.enter_vfo_mode("A", frequency_hz=145_500_000)
    dev.enter_vfo_mode("B", frequency_hz=446_006_250)
    info = {v.vfo: v for v in dev.read_vfo_info()}
    assert info["A"].frequency_hz == 145_500_000
    assert info["B"].frequency_hz == 446_006_250
    assert info["Z"].frequency_hz == 145_500_000




def test_read_vfo_info_always_returns_three_entries(dev):
    entries = dev.read_vfo_info()
    assert {e.vfo for e in entries} == {"A", "B", "Z"}


def test_read_vfo_info_multiline_response_with_re_on(dev):
    dev.set_result_code_prefixing(True)
    dev.enter_vfo_mode("A", frequency_hz=145_500_000)
    dev.enter_vfo_mode("B", frequency_hz=446_006_250)
    entries = {e.vfo: e for e in dev.read_vfo_info()}
    assert len(entries) == 3
    assert entries["A"].frequency_hz == 145_500_000
    assert entries["B"].frequency_hz == 446_006_250




def test_vfo_search_settings_roundtrip(dev):
    dev.write_vfo_search_settings(delay_ds=30, free_time_s=5, auto_store=True)
    assert dev.read_vfo_search_settings() == VfoSearchSettings(
        delay_ds=30, free_time_s=5, auto_store=True
    )


def test_vfo_search_settings_default(dev):
    assert dev.read_vfo_search_settings() == VfoSearchSettings(
        delay_ds=20, free_time_s=0, auto_store=False
    )


def test_vfo_search_settings_omitted_fields_keep_previous(dev):
    dev.write_vfo_search_settings(delay_ds=30, free_time_s=5, auto_store=True)
    dev.write_vfo_search_settings(free_time_s=10)
    s = dev.read_vfo_search_settings()
    assert s.delay_ds == 30
    assert s.auto_store is True
    assert s.free_time_s == 10


def test_execute_vfo_search_does_not_raise(dev):
    dev.execute_vfo_search()
