"""Fixture-based round-trip tests pinning the
exact wire-level field layouts this project has transcribed from the
AR-DV1 command-list spec for the composite MX/MA (memory channel) and
SE/SR (search bank) commands - so a future transcription slip (wrong
field order, wrong padding width/precision, a swapped digit count) breaks
a test immediately here, rather than only showing up as a subtle
real-hardware mismatch someone has to notice on their own.

Two directions per command family, matching the item's own description:

- PARSE: a spec-shaped fixture string (built by hand to the exact
  field order/width the spec documents - AOR's own manual has no worked
  composite examples with real numbers to transcribe verbatim, unlike
  tests/test_memory.py's real backup-CSV fixture) goes IN, and the right
  MemoryChannelInfo/SearchBankInfo fields must come OUT.
- BUILD: known Python values go into write_memory_channel()/
  write_search_bank(), and the EXACT wire string those methods send must
  come out - captured via DV10Device.set_trace_sink() rather than
  guessing at the transport layer's byte format.

See device.py's write_memory_channel()/write_search_bank()/
_parse_memory_channel_response()/_parse_search_bank_response() docstrings
for the field-layout confirmations these fixtures pin down. All against
the simulator; nothing here talks
to real hardware - that's exactly why pinning the *documented* format
here matters, so a real-hardware session has one thing fewer to
independently re-derive from scratch.
"""

from aor_dv10.device import DV10Device


def make_device() -> DV10Device:
    dev = DV10Device.open_simulator()
    dev.connect()
    return dev


def capture_tx(dev: DV10Device, action) -> str:
    """Run ``action()`` (a no-arg callable that triggers exactly one
    write) and return the single TX trace line's raw text - "the exact
    bytes sent on the wire" without having to reach into the transport
    layer directly. Fails loudly if 0 or >1 TX lines show up, since a
    fixture test that silently checked the wrong line would be worse
    than no test at all."""
    captured = []
    dev.set_trace_sink(lambda line: captured.append(line))
    try:
        action()
    finally:
        dev.set_trace_sink(None)
    tx_lines = [line for line in captured if " TX " in line]
    assert len(tx_lines) == 1, f"expected exactly 1 TX line, got {tx_lines!r}"
    return tx_lines[0]


# -- MX/MA: live memory channel -------------------------------------------


def test_mx_ma_parse_fixture_full_record():
    # Hand-built to the exact "MP/RF/ST/SH/MD/PT/TT" field order/widths
    # documented for MA's response body (see
    # _parse_memory_channel_response()'s docstring) - MP1 (pass channel
    # on), 439.3 MHz, 12.5 kHz step, 3.12 kHz step-adjust (one of SH's own
    # documented enum values), digital-off/FM mode, write-protected, and
    # a tag containing a space.
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
    # The spec's own "- - -" placeholder for an unprogrammed slot.
    dev = make_device()
    info = dev._parse_memory_channel_response(0, 2, "- - -")
    assert info.registered is False


def test_mx_build_fixture_matches_documented_field_order():
    # "MXbbcc [MPp] [RFffff.fffff] [STggg.gg] [SHhhh.hh] [MDdan] [PTa]
    # [TTttt]" - see write_memory_channel()'s docstring. Field order in
    # the built string must match the spec's, even though the simulator/
    # a real receiver would presumably accept a different order too -
    # this pins what THIS PROJECT sends, not just what's accepted.
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
    assert "MX0001 MP1 RF0439.30000 ST012.50 SH003.12 MDF0 PT1 TT2m rptr" in tx


def test_mx_build_fixture_omits_untouched_fields():
    # Only bbcc + whatever was explicitly given - no field the spec calls
    # optional should show up when left at its Python default.
    dev = make_device()
    tx = capture_tx(dev, lambda: dev.write_memory_channel(1, 5, frequency_hz=146_520_000))
    assert "MX0105 RF0146.52000" in tx
    for absent in ("MP1", "ST0", "SH0", "MD", "PT1", "TT"):
        assert absent not in tx


# -- SE/SR: search bank ----------------------------------------------------


def test_se_sr_parse_fixture_full_record():
    # "SL/SU/ST/SH/MD/PT/TT" - SL/SU use the coarser "ffff.ffff" width
    # (100Hz resolution), confirmed distinct from RF/OL's "ffff.fffff" -
    # see _format_search_freq_mhz()'s docstring.
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
    # "SEbb [SLffff.ffff] [SUffff.ffff] [STggg.gg] [SHhhh.hh] [MDdan]
    # [PTa] [TTttt]" - see write_search_bank()'s docstring.
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
    assert "PT1" not in tx  # write_protect=False must not send PT at all
