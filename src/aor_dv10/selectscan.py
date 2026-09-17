
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Tuple

DEFAULT_MAX_ENTRIES = 50


@dataclass
class SelectScanList:

    entries: List[Tuple[int, int]] = field(default_factory=list)
    max_entries: int = DEFAULT_MAX_ENTRIES

    def add(self, bank: int, channel: int) -> None:
        pair = (bank, channel)
        if pair in self.entries:
            return
        if len(self.entries) >= self.max_entries:
            raise ValueError(
                f"select-scan list is full ({self.max_entries} entries max)"
            )
        self.entries.append(pair)

    def remove(self, bank: int, channel: int) -> bool:
        pair = (bank, channel)
        if pair in self.entries:
            self.entries.remove(pair)
            return True
        return False

    def clear(self) -> None:
        self.entries.clear()

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


def run_select_scan(
    tune_fn: Callable[[int, int], None],
    entries: List[Tuple[int, int]],
    dwell_s: float = 2.0,
    cycles: Optional[int] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Iterator[Tuple[int, int]]:
    if not entries:
        raise ValueError("select-scan list is empty - add entries first")
    if sleep_fn is None:
        sleep_fn = _time.sleep

    completed_cycles = 0
    while cycles is None or completed_cycles < cycles:
        for bank, channel in entries:
            if should_stop is not None and should_stop():
                return
            tune_fn(bank, channel)
            yield (bank, channel)
            sleep_fn(dwell_s)
        completed_cycles += 1
