"""Tests for protocol tracing - CommandChannel's always-on
TX/RX ring buffer (aor_dv10.protocol.codec) and its CLI ("debug ...") /
web ("debug ..." WS verb, /api/debug/trace) front ends. The point of this
feature is letting a real-hardware session be reproduced precisely later,
so what's tested here is specifically: tracing happens unconditionally
(not just while a sink is attached), a sink gets live lines, and every
front end can pull/save the recorded history.
"""

from pathlib import Path

import pytest

from aor_dv10.device import DV10Device


def test_trace_is_always_recorded_even_without_a_sink():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(145_500_000)
        dev.get_mode()
        # snapshot before __exit__ disconnects (which sends its own EX
        # command and would add two more trace lines, not part of what
        # this test is pinning)
        lines = dev.trace_lines()
    assert len(lines) == 4  # TX/RX for the write, TX/RX for the read
    assert "TX b'RF0145.50000\\r'" in lines[0]
    assert "RX" in lines[1]
    assert "TX b'MD\\r'" in lines[2]
    assert "RX b'MD0F0\\r'" in lines[3]


def test_trace_lines_respects_n_and_order():
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(145_500_000)
        dev.get_mode()
        dev.get_squelch_mode()
    all_lines = dev.trace_lines()
    last_2 = dev.trace_lines(2)
    assert last_2 == all_lines[-2:]


def test_set_trace_sink_gets_live_lines_and_can_be_unregistered():
    dev = DV10Device.open_simulator()
    with dev:
        seen = []
        dev.set_trace_sink(seen.append)
        dev.set_frequency_hz(145_500_000)
        assert len(seen) == 2  # one TX, one RX

        dev.set_trace_sink(None)
        dev.get_mode()
        assert len(seen) == 2  # nothing more delivered to the old sink...
        assert len(dev.trace_lines()) == 4  # ...but still recorded overall


def test_a_broken_sink_does_not_break_the_protocol_layer():
    dev = DV10Device.open_simulator()
    with dev:
        def boom(_line):
            raise RuntimeError("sink is broken")

        dev.set_trace_sink(boom)
        # must not raise, and must still work/record normally
        dev.set_frequency_hz(145_500_000)
        assert dev.get_frequency_hz() == 145_500_000
        assert len(dev.trace_lines()) > 0


def test_save_trace_writes_a_file(tmp_path):
    dev = DV10Device.open_simulator()
    with dev:
        dev.set_frequency_hz(145_500_000)
        out = tmp_path / "trace.log"
        count = dev.save_trace(str(out))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == count == 2


# -- CLI front end -----------------------------------------------------------

def _make_repl():
    from rich.console import Console
    from aor_dv10.cli.repl import Repl

    dev = DV10Device.open_simulator()
    dev.connect()
    console = Console(file=open("/dev/null", "w"))
    return Repl(dev, console)


def test_cli_debug_requires_a_subcommand():
    repl = _make_repl()
    with pytest.raises(ValueError, match="usage: debug"):
        repl.dispatch("debug")


def test_cli_debug_last_works_without_debug_on():
    """"debug last" pulls recorded history even if "debug on" was never
    used - tracing isn't gated on that, only live console echo is."""
    repl = _make_repl()
    repl.dispatch("f 145.500000")
    assert repl.dispatch("debug last 5") is True  # must not raise


def test_cli_debug_on_off_toggles_the_device_sink():
    repl = _make_repl()
    repl.dispatch("debug on")
    assert repl.device._chan._trace_sink is not None
    repl.dispatch("debug off")
    assert repl.device._chan._trace_sink is None


def test_cli_debug_on_with_logfile_writes_to_disk(tmp_path):
    log_path = tmp_path / "cli_trace.log"
    repl = _make_repl()
    repl.dispatch(f"debug on {log_path}")
    repl.dispatch("f 145.500000")
    repl.dispatch("debug off")
    content = log_path.read_text(encoding="utf-8")
    assert "trace session started" in content
    assert "RF0145.50000" in content


def test_cli_debug_save(tmp_path):
    out_path = tmp_path / "saved.log"
    repl = _make_repl()
    repl.dispatch("f 145.500000")
    repl.dispatch(f"debug save {out_path}")
    assert out_path.exists()
    assert "RF0145.50000" in out_path.read_text(encoding="utf-8")


def test_cli_disable_debug_is_safe_when_never_enabled():
    repl = _make_repl()
    repl.disable_debug()  # must not raise


# -- web front end -------------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


@pytest.fixture
def panel():
    from aor_dv10.web import server as webserver

    dev = DV10Device.open_simulator()
    dev.connect()
    p = webserver.start_in_thread(dev, host="127.0.0.1", port=18791, mdns=False)
    import json
    import time
    import urllib.request

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{p.url}api/status", timeout=1.0) as resp:
                json.loads(resp.read())
                break
        except Exception:
            time.sleep(0.1)
    try:
        yield p, dev
    finally:
        p.stop()
        dev.disconnect()


def test_web_debug_trace_rest_endpoint(panel):
    import json
    import urllib.request

    p, dev = panel
    dev.set_frequency_hz(145_500_000)

    with urllib.request.urlopen(f"{p.url}api/debug/trace?n=2", timeout=5.0) as resp:
        body = json.loads(resp.read())
    assert len(body["lines"]) == 2
    assert "RF0145.50000" in body["lines"][0]


def test_web_debug_ws_verb_last_and_save(panel, tmp_path):
    from aor_dv10.web.server import _dispatch_plain

    p, dev = panel
    dev.set_frequency_hz(145_500_000)

    reply = _dispatch_plain(dev, "debug last 2")
    assert "RF0145.50000" in reply

    out_path = tmp_path / "web_saved.log"
    reply = _dispatch_plain(dev, f"debug save {out_path}")
    assert "Wrote" in reply
    assert out_path.exists()
