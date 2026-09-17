
import pytest

from aor_dv10.device import DV10Device, ScopeLine
from aor_dv10.protocol.codec import DV10ProtocolError


@pytest.fixture
def dev():
    d = DV10Device.open_simulator()
    with d:
        yield d




def test_fd_raises_when_not_in_scope_mode(dev):
    with pytest.raises(DV10ProtocolError):
        dev.read_scope_data_fast()


def test_fd_returns_dbm_values_in_scope_mode(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    values = dev.read_scope_data_fast()
    assert len(values) == 40
    assert all(isinstance(v, int) for v in values)
    assert all(v <= 0 for v in values)


def test_fd_is_deterministic(dev):
    dev._transport.scope_mode = True  # noqa: SLF001
    first = dev.read_scope_data_fast()
    second = dev.read_scope_data_fast()
    assert first == second




def test_gl_raises_when_not_in_scope_mode(dev):
    with pytest.raises(DV10ProtocolError) as exc_info:
        dev.read_scope_data_normal()
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
    dev._transport.scope_mode = True  # noqa: SLF001
    assert (dev._chan.read("RE").value or "0").strip() == "0"  # noqa: SLF001
    dev.read_scope_data_normal()
    assert (dev._chan.read("RE").value or "0").strip() == "0"  # noqa: SLF001
