
from __future__ import annotations

import pytest

from aor_dv10.protocol.codec import CommandChannel, DV10ResyncNeeded
from aor_dv10.transport.base import Transport


class _RecordingTransport(Transport):
    def __init__(self, responses=None):
        self.writes: list[bytes] = []
        self._responses = list(responses or [])
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write_line(self, data: bytes) -> None:
        self.writes.append(data)

    def read_line(self, timeout: float):
        if self._responses:
            return self._responses.pop(0)
        return None


def test_read_is_retried_once_on_timeout():
    t = _RecordingTransport()
    ch = CommandChannel(t, timeout=0.01)
    with pytest.raises(DV10ResyncNeeded):
        ch.read("RF")
    assert t.writes == [b"RF\r", b"\r", b"RF\r", b"\r"]


def test_write_is_not_resent_on_timeout():
    t = _RecordingTransport()
    ch = CommandChannel(t, timeout=0.01)
    with pytest.raises(DV10ResyncNeeded):
        ch.write("RF", "0145.50000")
    assert t.writes == [b"RF0145.50000\r", b"\r"]
    assert sum(1 for w in t.writes if w.startswith(b"RF")) == 1


def test_valueless_write_can_opt_out_of_retry():
    t = _RecordingTransport()
    ch = CommandChannel(t, timeout=0.01)
    with pytest.raises(DV10ResyncNeeded):
        ch.send("PW", retry=False)
    assert t.writes == [b"PW\r", b"\r"]


def test_read_returns_parsed_value_when_response_arrives():
    t = _RecordingTransport([b"RF0145.50000\r"])
    ch = CommandChannel(t, timeout=0.01)
    resp = ch.read("RF")
    assert resp.value == "0145.50000"
    assert t.writes == [b"RF\r"]


def test_re_prefix_on_success_is_stripped():
    t = _RecordingTransport([b"20RF0145.50000\r"])
    ch = CommandChannel(t, timeout=0.01)
    resp = ch.read("RF")
    assert resp.value == "0145.50000"
    assert resp.result_code == 20


def test_transaction_blocks_other_threads():
    import threading
    import time

    t = _RecordingTransport([b"RF0145.50000\r"])
    ch = CommandChannel(t, timeout=0.05)
    order: list[str] = []
    started = threading.Event()

    def holder():
        with ch.transaction():
            order.append("tx-start")
            started.set()
            time.sleep(0.15)
            order.append("tx-end")

    def sender():
        started.wait()
        time.sleep(0.02)
        ch.send("RF")
        order.append("send-done")

    th1 = threading.Thread(target=holder)
    th2 = threading.Thread(target=sender)
    th1.start()
    th2.start()
    th1.join()
    th2.join()
    assert order == ["tx-start", "tx-end", "send-done"]
