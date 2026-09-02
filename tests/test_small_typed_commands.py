"""Regression tests for the smaller typed commands -
KL (key backlight color), IF (per-mode IF bandwidth), DL/FR (standalone
delay/free-time, distinct from the same-named sub-fields inside the SG/MG
scan-group composites), and RN (AR-DV1 serial number, with an
access correction from R/W to R-only). Notably: the "MAGENDA"
(sic) KL color-3 typo (confirmed via both the rendered PDF image and
pdftotext's raw text layer, same as the "SYSYEM" backup-kind typo); IF's
"IFn, IFnn" documented response shape; and why "SN" ("Output serial
number") was deliberately left raw-only rather than getting a typed
method of its own. All against the simulator; nothing here has been
checked against real hardware.
"""

import pytest

from aor_dv10.device import DV10Device, IF_BANDWIDTH_HZ, KEY_BACKLIGHT_COLORS


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


# -- KL (key backlight color) ------------------------------------------


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
    # Confirmed as a genuine AR-DV1 spec typo (not an OCR/pdftotext
    # artifact) via both the rendered PDF image and the raw text layer.
    assert KEY_BACKLIGHT_COLORS["3"] == "MAGENDA"


# -- IF (IF bandwidth) ---------------------------------------------------


def test_if_default_matches_fm_spec_default(dev):
    # AR-DV1 spec: "FM: n = ... 3->15KHz ... (default: 3 FM)".
    assert dev.get_if_bandwidth() == "3"
    assert IF_BANDWIDTH_HZ["FM"]["3"] == 15_000


def test_if_roundtrip(dev):
    dev.set_if_bandwidth(1)
    assert dev.get_if_bandwidth() == "1"


def test_if_bandwidth_table_shapes():
    # FM has 4 values (1-4; digit "0"/200 kHz was in the AR-DV10 manual's
    # own table but confirmed absent on real hardware, see IF_BANDWIDTH_HZ's
    # comment - FM only actually runs 6-100 kHz), AM/SAH/SAL/USB/LSB/CW all
    # narrower still - per the spec's own per-mode lists, not a uniform
    # digit range.
    assert len(IF_BANDWIDTH_HZ["FM"]) == 4
    assert len(IF_BANDWIDTH_HZ["AM"]) == 4
    for narrow_mode in ("SAH", "SAL", "USB", "LSB", "CW"):
        assert len(IF_BANDWIDTH_HZ[narrow_mode]) == 2
    # SAH/SAL share one set of values, as do USB/LSB - per the spec text.
    assert IF_BANDWIDTH_HZ["SAH"] == IF_BANDWIDTH_HZ["SAL"]
    assert IF_BANDWIDTH_HZ["USB"] == IF_BANDWIDTH_HZ["LSB"]


# -- mode-aware IF bandwidth helpers (get/set by Hz, not raw digit) -----
#
# get_if_bandwidth_options_hz()/get_if_bandwidth_hz()/set_if_bandwidth_hz()
# exist so a caller/UI (the web panel's Mode section, the "bw" CLI verb)
# can work in Hz instead of needing to already know which raw IF digit
# means what for whichever analog mode happens to be selected right now -
# see their docstrings and the device.py IF (IF bandwidth) decode table.


def test_if_bandwidth_options_hz_matches_current_analog_mode(dev):
    # Default mode is "0F0" (FM, digital off) - see the simulator's "MD"
    # default.
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["FM"]
    dev.set_mode("F1")  # digital off, analog AM
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["AM"]


def test_if_bandwidth_hz_decodes_current_raw_value(dev):
    # Spec default raw IF value is "3", which means 15 kHz under FM (see
    # test_if_default_matches_fm_spec_default above).
    assert dev.get_if_bandwidth_hz() == 15_000
    dev.set_if_bandwidth(1)  # FM/IF1 = 100 kHz
    assert dev.get_if_bandwidth_hz() == 100_000


def test_set_if_bandwidth_hz_roundtrips_through_raw_digit(dev):
    dev.set_if_bandwidth_hz(6_000)  # FM's narrowest option, raw digit "4"
    assert dev.get_if_bandwidth() == "4"
    assert dev.get_if_bandwidth_hz() == 6_000


def test_set_if_bandwidth_hz_follows_mode_switch(dev):
    dev.set_mode("F1")  # digital off, analog AM
    dev.set_if_bandwidth_hz(3_800)  # AM's narrowest option, raw digit "3"
    assert dev.get_if_bandwidth() == "3"
    assert dev.get_if_bandwidth_hz() == 3_800


def test_set_if_bandwidth_hz_rejects_value_not_offered_by_current_mode(dev):
    # 3800 Hz is a valid AM choice but not an FM one (FM's narrowest is
    # 6000 Hz) - must be rejected up front, with no wire write at all,
    # rather than silently accepted the way a bare set_if_bandwidth(n)
    # raw-digit write would be.
    before = dev.get_if_bandwidth()
    with pytest.raises(ValueError):
        dev.set_if_bandwidth_hz(3_800)
    assert dev.get_if_bandwidth() == before


# -- digital modes: IF is not user-settable at all (confirmed live) -----
#
# Per user report against real DV10 hardware: "bw 100000" and "bw 6000"
# BOTH failed with result code 30 while a digital mode (Auto) was active,
# even though 6000 is itself one of FM's own valid IF_BANDWIDTH_HZ values
# - the receiver auto-selects the filter itself while digital reception
# is selected, full stop, not "restricted to some digital-specific
# subset". See get_if_bandwidth_options_hz()'s docstring for why this
# returns {} rather than a guessed digital table.


def test_if_bandwidth_options_empty_while_digital_mode_active(dev):
    dev.set_mode("00")  # digital=Auto, analog=FM
    assert dev.get_if_bandwidth_options_hz() == {}


def test_if_bandwidth_hz_is_none_while_digital_mode_active(dev):
    dev.set_mode("00")  # digital=Auto, analog=FM
    assert dev.get_if_bandwidth_hz() is None


def test_set_if_bandwidth_hz_rejects_any_value_while_digital_mode_active(dev):
    dev.set_mode("00")  # digital=Auto, analog=FM
    before = dev.get_if_bandwidth()
    # Neither an FM-valid value (6000) nor an arbitrary one (100000) is
    # accepted - matches the live repro, where both failed identically.
    with pytest.raises(ValueError, match="digital"):
        dev.set_if_bandwidth_hz(6_000)
    with pytest.raises(ValueError, match="digital"):
        dev.set_if_bandwidth_hz(100_000)
    assert dev.get_if_bandwidth() == before


def test_if_bandwidth_options_return_once_digital_is_switched_off(dev):
    dev.set_mode("00")  # digital=Auto, analog=FM
    assert dev.get_if_bandwidth_options_hz() == {}
    dev.set_mode("F0")  # digital off, analog=FM
    assert dev.get_if_bandwidth_options_hz() == IF_BANDWIDTH_HZ["FM"]


# -- DL (standalone delay time) -------------------------------------------


def test_dl_default_matches_spec_default(dev):
    # AR-DV1 spec: "Default: 020" (deciseconds).
    assert dev.get_delay_time_ds() == 20


def test_dl_roundtrip(dev):
    dev.set_delay_time_ds(50)
    assert dev.get_delay_time_ds() == 50


def test_dl_unlimited_special_value_roundtrips_literally(dev):
    # AR-DV1 spec: "If nnn=100, the delay time is set as unlimited."
    dev.set_delay_time_ds(100)
    assert dev.get_delay_time_ds() == 100


def test_dl_is_independent_of_the_scan_group_dl_subfield(dev):
    # The standalone DL command must not be confused with (or share
    # storage with) the DL sub-field inside SG/MG scan-group composites
    # (task 11) - writing one must not affect the other.
    dev.write_search_scan_group(0, delay_ds=77)
    dev.set_delay_time_ds(11)
    assert dev.get_delay_time_ds() == 11
    assert dev.read_search_scan_group(0).delay_ds == 77


# -- FR (standalone free time) --------------------------------------------


def test_fr_default_matches_spec_default(dev):
    # AR-DV1 spec: "Default: 00" (seconds; 0 = OFF).
    assert dev.get_free_time_s() == 0


def test_fr_roundtrip(dev):
    dev.set_free_time_s(45)
    assert dev.get_free_time_s() == 45


def test_fr_is_independent_of_the_scan_group_fr_subfield(dev):
    dev.write_search_scan_group(0, free_time_s=33)
    dev.set_free_time_s(7)
    assert dev.get_free_time_s() == 7
    assert dev.read_search_scan_group(0).free_time_s == 33


# -- RN (serial number) ----------------------------------------------------


def test_rn_returns_a_string(dev):
    serial = dev.get_serial_number()
    assert isinstance(serial, str)
    assert serial


def test_rn_has_no_write_method():
    # CORRECTED: the summary table lists RN as R/W, but its own
    # detailed section documents only a read. Implemented read-only:
    # no set_serial_number() exists.
    assert not hasattr(DV10Device, "set_serial_number")
