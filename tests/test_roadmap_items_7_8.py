
from aor_dv10.device import DV10Device


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev




def test_step_adjust_hz_wire_format_is_khz_decimal():
    dev = make_device()
    dev.set_step_adjust_hz(3120)
    raw = dev.raw("SH").value
    assert raw == "003.12", f"expected kHz-decimal wire format, got {raw!r}"


def test_step_adjust_hz_getter_returns_int_hz():
    dev = make_device()
    dev.set_step_adjust_hz(500)
    value = dev.get_step_adjust_hz()
    assert value == 500
    assert isinstance(value, int)


def test_step_adjust_hz_roundtrip_spec_enum_values():
    dev = make_device()
    for hz in (50, 1000, 4160, 6250, 250_000):
        dev.set_step_adjust_hz(hz)
        assert dev.get_step_adjust_hz() == hz


def test_step_adjust_hz_default_is_zero():
    dev = make_device()
    assert dev.get_step_adjust_hz() == 0




def test_memory_channel_tag_with_space_roundtrips():
    dev = make_device()
    dev.write_memory_channel(0, 1, frequency_hz=146_520_000, mode="00", tag="2M BAND")
    info = dev.read_memory_channel(0, 1)
    assert info.tag == "2M BAND"


def test_memory_bank_tag_with_space_roundtrips():
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
    dev = make_device()
    dev.write_memory_channel(0, 2, frequency_hz=146_520_000, mode="00", tag="NOAA WX 1")
    info = dev.read_memory_channel(0, 2)
    assert info.tag == "NOAA WX 1"
