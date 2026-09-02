"""Regression tests for frequency scope - FD (fast)
and GL (normal). See src/aor_dv10/device.py's "Frequency scope" section for
the significant caveat this whole area carries: no AR-DV10/AR-DV1
reference document - including the full operating manual - describes any
way to enter "scope mode", which both commands document as a precondition
for success. Because there is no real scope-mode state machine to model,
the simulator exposes a test-only ``scope_mode`` toggle (mirroring task
13's ``sd_error_injection`` precedent) rather than any documented
protocol-level trigger. All against the simulator; nothing here has been
checked against real hardware, and in particular whether "scope mode" is
reachable at all on a real receiver remains unconfirmed.
"""

import pytest

from aor_dv10.device import DV10Device, ScopeLine
from aor_dv10.protocol.codec import DV10ProtocolError


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d


# -- FD (fast-speed scan) -----------------------------------------------


def test_fd_raises_when_not_in_scope_mode(dev):
    with pytest.raises(DV10ProtocolError):
        dev.read_scope_data_fast()


def test_fd_returns_dbm_values_in_scope_mode(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    values = dev.read_scope_data_fast()
    assert len(values) == 40
    assert all(isinstance(v, int) for v in values)
    # decoded as dbm = -int(chunk), so every value must be <= 0.
    assert all(v <= 0 for v in values)


def test_fd_is_deterministic(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    first = dev.read_scope_data_fast()
    second = dev.read_scope_data_fast()
    assert first == second


# -- GL (normal-speed scan) -----------------------------------------------


def test_gl_raises_when_not_in_scope_mode(dev):
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.read_scope_data_normal()
    # read_scope_data_normal() forces RE on for the read (same pattern as
    # sd_dir()), so - unlike FD's unforced read - the numeric result code
    # is reliably surfaced here.
    assert exc_info.value.code == "30"


def test_gl_returns_scope_lines_in_scope_mode(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    lines = dev.read_scope_data_normal()
    assert len(lines) == 10
    assert all(isinstance(line, ScopeLine) for line in lines)


def test_gl_frequencies_are_ascending_and_118mhz_range(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    lines = dev.read_scope_data_normal()
    freqs = [line.frequency_hz for line in lines]
    assert freqs == sorted(freqs)
    assert freqs[0] == 118_000_000
    assert all(118_000_000 <= f <= 119_000_000 for f in freqs)


def test_gl_level_raw_is_two_digits(dev):
    # Per the AR-DV1 spec's own literal GL syntax ("Fffff.fffffLkkc") - see
    # ScopeLine's docstring for why this is narrower than LM/FD's 3-digit
    # convention, and unconfirmed against real hardware.
    dev._transport.scope_mode = True  # noqa: SLF001
    lines = dev.read_scope_data_normal()
    assert all(len(line.level_raw) == 2 for line in lines)
    assert all(line.level_raw.isdigit() for line in lines)


def test_gl_squelch_open_property(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    lines = dev.read_scope_data_normal()
    for line in lines:
        assert line.squelch_open == (line.squelch_state != 0)


def test_gl_restores_re_state_after_read(dev):
    # read_scope_data_normal() temporarily forces RE on for the duration of
    # the read (same defensive pattern as sd_dir()) - it must restore
    # whatever RE was before, even though the simulator's default RE state
    # is off ("0"), same as every other RE-forcing method in this project.
    dev._transport.scope_mode = True  # noqa: SLF001
    assert (dev._chan.read("RE").value or "0").strip() == "0"  # noqa: SLF001
    dev.read_scope_data_normal()
    assert (dev._chan.read("RE").value or "0").strip() == "0"  # noqa: SLF001
