
import pytest

from aor_dv10.device import DV10Device, IF_BANDWIDTH_HZ, KEY_BACKLIGHT_COLORS


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d




def test_kl_default_is_off(dev):
    assert dev.get_key_backlight_color() == "0"
    assert KEY_BACKLIGHT_COLORS["0"] == "OFF"


def test_kl_roundtrip(dev):
    dev.set_key_backlight_color(5)
    assert dev.get_key_backlight_color() == "5"
    assert KEY_BACKLIGHT_COLORS["5"] == "CYAN"


def test_kl_color_table_covers_every_documented_value():
    assert set(KEY_BACKLIGHT_COLORS) == {str(i) for i in range(8)}


def test_kl_color_3_is_the_misspelled_spec_literal():
    assert KEY_BACKLIGHT_COLORS["3"] == "MAGENDA"




def test_if_default_matches_fm_spec_default(dev):
    assert dev.get_if_bandwidth() == "3"
    assert IF_BANDWIDTH_HZ["FM"]["3"] == 15_000


def test_if_roundtrip(dev):
    dev.set_if_bandwidth(1)
    assert dev.get_if_bandwidth() == "1"


def test_if_bandwidth_table_shapes():
    assert len(IF_BANDWIDTH_HZ["FM"]) == 4
    assert len(IF_BANDWIDTH_HZ["AM"]) == 4
    for narrow_mode in ("SAH", "SAL", "USB", "LSB", "CW"):
        assert len(IF_BANDWIDTH_HZ[narrow_mode]) == 2
    assert IF_BANDWIDTH_HZ["SAH"] == IF_BANDWIDTH_HZ["SAL"]
    assert IF_BANDWIDTH_HZ["USB"] == IF_BANDWIDTH_HZ["LSB"]




def test_if_bandwidth_options_hz_matches_current_analog_mode(dev):
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["FM"]
    dev.set_mode("F1")
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["AM"]


def test_if_bandwidth_hz_decodes_current_raw_value(dev):
    assert dev.get_if_bandwidth_hz() == 15_000
    dev.set_if_bandwidth(1)
    assert dev.get_if_bandwidth_hz() == 100_000


def test_set_if_bandwidth_hz_roundtrips_through_raw_digit(dev):
    dev.set_if_bandwidth_hz(6_000)
    assert dev.get_if_bandwidth() == "4"
    assert dev.get_if_bandwidth_hz() == 6_000


def test_set_if_bandwidth_hz_follows_mode_switch(dev):
    dev.set_mode("F1")
    dev.set_if_bandwidth_hz(3_800)
    assert dev.get_if_bandwidth() == "3"
    assert dev.get_if_bandwidth_hz() == 3_800


def test_set_if_bandwidth_hz_rejects_value_not_offered_by_current_mode(dev):
    before = dev.get_if_bandwidth()
    with pytest.raises(ValueError):
        dev.set_if_bandwidth_hz(3_800)
    assert dev.get_if_bandwidth() == before




def test_if_bandwidth_options_empty_while_digital_mode_active(dev):
    dev.set_mode("00")
    assert dev.get_if_bandwidth_options_hz() == {}


def test_if_bandwidth_hz_is_none_while_digital_mode_active(dev):
    dev.set_mode("00")
    assert dev.get_if_bandwidth_hz() is None


def test_set_if_bandwidth_hz_rejects_any_value_while_digital_mode_active(dev):
    dev.set_mode("00")
    before = dev.get_if_bandwidth()
    with pytest.raises(ValueError, match="digital"):
        dev.set_if_bandwidth_hz(6_000)
    with pytest.raises(ValueError, match="digital"):
        dev.set_if_bandwidth_hz(100_000)
    assert dev.get_if_bandwidth() == before


def test_if_bandwidth_options_return_once_digital_is_switched_off(dev):
    dev.set_mode("00")
    assert dev.get_if_bandwidth_options_hz() == {}
    dev.set_mode("F0")
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["FM"]




def test_dl_default_matches_spec_default(dev):
    assert dev.get_delay_time_ds() == 20


def test_dl_roundtrip(dev):
    dev.set_delay_time_ds(50)
    assert dev.get_delay_time_ds() == 50


def test_dl_unlimited_special_value_roundtrips_literally(dev):
    dev.set_delay_time_ds(100)
    assert dev.get_delay_time_ds() == 100


def test_dl_is_independent_of_the_scan_group_dl_subfield(dev):
    dev.write_search_scan_group(0, delay_ds=77)
    dev.set_delay_time_ds(11)
    assert dev.get_delay_time_ds() == 11
    assert dev.read_search_scan_group(0).delay_ds == 77




def test_fr_default_matches_spec_default(dev):
    assert dev.get_free_time_s() == 0


def test_fr_roundtrip(dev):
    dev.set_free_time_s(45)
    assert dev.get_free_time_s() == 45


def test_fr_is_independent_of_the_scan_group_fr_subfield(dev):
    dev.write_search_scan_group(0, free_time_s=33)
    dev.set_free_time_s(7)
    assert dev.get_free_time_s() == 7
    assert dev.read_search_scan_group(0).free_time_s == 33




def test_rn_returns_a_string(dev):
    serial = dev.get_serial_number()
    assert isinstance(serial, str)
    assert serial


def test_rn_has_no_write_method():
    assert not hasattr(DV10Device, "set_serial_number")
