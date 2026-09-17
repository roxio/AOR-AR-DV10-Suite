
from aor_dv10.device import DV10Device


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


def capture_tx(dev: DV10Device, action) -> str:
    captured = []
    dev.set_trace_sink(lambda line: captured.append(line))
    try:
        action()
    finally:
        dev.set_trace_sink(None)
    tx_lines = [line for line in captured if " TX " in line]
    assert len(tx_lines) == 1, f"expected exactly 1 TX line, got {tx_lines!r}"
    return tx_lines[0]




def test_mx_ma_parse_fixture_full_record():
    dev = make_device()
    text = "MP1 RF0439.30000 ST012.50 SH003.12 MD0F0 PT1 TT2m rptr"
    info = dev._parse_memory_channel_response(0, 1, text)
    assert info.registered is True
    assert info.pass_channel is True
    assert info.frequency_hz == 439_300_000
    assert info.step_hz == 12_500
    assert info.step_adjust_hz == 3_120
    assert info.mode == "0F0"
    assert info.write_protect is True
    assert info.tag == "2m rptr"


def test_mx_ma_parse_fixture_unregistered_placeholder():
    dev = make_device()
    info = dev._parse_memory_channel_response(0, 2, "- - -")
    assert info.registered is False


def test_mx_build_fixture_matches_documented_field_order():
    dev = make_device()
    tx = capture_tx(
        dev,
        lambda: dev.write_memory_channel(
            0,
            1,
            pass_channel=True,
            frequency_hz=439_300_000,
            step_hz=12_500,
            step_adjust_hz=3_120,
            mode="F0",
            write_protect=True,
            tag="2m rptr",
        ),
    )
    assert "MX0001 MP1 RF0439.30000 ST012.50 SH003.12 MD0F0 PT1 TT2m rptr" in tx


def test_mx_build_fixture_omits_untouched_value_fields_but_always_sends_mp_pt():
    dev = make_device()
    tx = capture_tx(dev, lambda: dev.write_memory_channel(1, 5, frequency_hz=146_520_000))
    assert "MX0105 MP0 RF0146.52000 PT0" in tx
    for absent in ("MP1", "ST0", "SH0", "MD", "PT1", "TT"):
        assert absent not in tx




def test_se_sr_parse_fixture_full_record():
    dev = make_device()
    text = "SL0144.0000 SU0148.0000 ST012.50 SH000.05 MDF0 PT0 TT2m band"
    info = dev._parse_search_bank_response(0, text)
    assert info.registered is True
    assert info.lower_limit_hz == 144_000_000
    assert info.upper_limit_hz == 148_000_000
    assert info.step_hz == 12_500
    assert info.step_adjust_hz == 50
    assert info.mode == "F0"
    assert info.write_protect is False
    assert info.tag == "2m band"


def test_se_build_fixture_matches_documented_field_order():
    dev = make_device()
    tx = capture_tx(
        dev,
        lambda: dev.write_search_bank(
            0,
            lower_limit_hz=144_000_000,
            upper_limit_hz=148_000_000,
            step_hz=12_500,
            step_adjust_hz=50,
            mode="F0",
            write_protect=False,
            tag="2m band",
        ),
    )
    assert "SE00 SL0144.0000 SU0148.0000 ST012.50 SH000.05 MDF0 TT2m band" in tx
    assert "PT1" not in tx
