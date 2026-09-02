"""Regression tests for two correctness bugs, fixed against the AR-DV1
wire-protocol spec. See device.py's get_step_adjust_hz()/set_step_adjust_hz() and
_parse_composite_fields() docstrings for the full account. All against
the simulator; nothing here has been checked against real hardware.
"""

from aor_dv10.device import DV10Device


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


# -- item 7: standalone SH is kHz-decimal, not a bare integer Hz value ----


def test_step_adjust_hz_wire_format_is_khz_decimal():
    dev = make_device()
    dev.set_step_adjust_hz(3120)  # 3.12 kHz, one of the spec's own enum values
    raw = dev.raw("SH").value
    assert raw == "003.12", f"expected kHz-decimal wire format, got {raw!r}"


def test_step_adjust_hz_getter_returns_int_hz():
    dev = make_device()
    dev.set_step_adjust_hz(500)
    value = dev.get_step_adjust_hz()
    assert value == 500
    assert isinstance(value, int)


def test_step_adjust_hz_roundtrip_spec_enum_values():
    # A sample of the AR-DV1 spec's own fixed enum (0.05, 0.25, 0.5, 1,
    # 2.5, 3.12, 3.75, 4.16, 4.5, 5.0, 6.25, 10.0, 12.5, 15.0, 25.0, 50.0,
    # 250.0 kHz) - not exhaustive, just enough to prove the kHz<->Hz
    # conversion is correct at both ends of the range and at an
    # awkward 2-decimal value (4.16).
    dev = make_device()
    for hz in (50, 1000, 4160, 6250, 250_000):
        dev.set_step_adjust_hz(hz)
        assert dev.get_step_adjust_hz() == hz


def test_step_adjust_hz_default_is_zero():
    # Spec default is "000.00" kHz = 0 Hz.
    dev = make_device()
    assert dev.get_step_adjust_hz() == 0


# -- item 8: a tag/name value containing a literal space no longer -------
# -- truncates at the first space (MX/MW/SE all share the fix, via ------
# -- _parse_composite_fields()'s new tag_field="TT" handling). -----------


def test_memory_channel_tag_with_space_roundtrips():
    dev = make_device()
    dev.write_memory_channel(0, 1, frequency_hz=146_520_000, mode="00", tag="2M BAND")
    info = dev.read_memory_channel(0, 1)
    assert info.tag == "2M BAND"


def test_memory_bank_tag_with_space_roundtrips():
    # MW's tag field is truncated to 12 chars by write_memory_bank() -
    # unrelated to this fix, just something to stay under here.
    dev = make_device()
    dev.write_memory_bank(0, tag="Local Rptrs")
    info = dev.get_memory_bank_info(0)
    assert info.tag == "Local Rptrs"


def test_search_bank_tag_with_space_roundtrips():
    dev = make_device()
    dev.write_search_bank(0, tag="2M BAND")
    info = dev.read_search_bank(0)
    assert info.tag == "2M BAND"


def test_tag_with_multiple_spaces_preserved_verbatim():
    # Not just "one space" - the whole rest of the line, verbatim (still
    # under the 12-char truncation write_memory_channel() itself applies).
    dev = make_device()
    dev.write_memory_channel(0, 2, frequency_hz=146_520_000, mode="00", tag="NOAA WX 1")
    info = dev.read_memory_channel(0, 2)
    assert info.tag == "NOAA WX 1"
