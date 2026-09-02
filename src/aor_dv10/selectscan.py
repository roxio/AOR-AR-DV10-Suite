"""Select scan: an AR8200-inspired,
purely client-side feature - a user-curated list of channels spanning
arbitrary banks, scanned by looping tune_memory_channel() over the list
with a configurable per-channel dwell.

Unlike the AR8200's own GA/GD/GM/GR select-scan wire commands, nothing in
the AR-DV1 spec documents an equivalent protocol-level feature on the
AR-DV10 - so this is implemented entirely client-side on top
of the already-confirmed MR write
(aor_dv10.device.DV10Device.tune_memory_channel()). Nothing here is itself a
wire command; SelectScanList is in-memory-only client state (not saved to
the receiver or to disk by this module), and run_select_scan() is a
generator loop around repeated MR calls.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Tuple

# Arbitrary client-side cap on list size - NOT a protocol limit (there is
# no wire-level select-scan list to size against). Chosen to comfortably
# cover a "handful of channels of interest across banks" use case without
# being unbounded; raise it via SelectScanList(max_entries=...) if needed.
DEFAULT_MAX_ENTRIES = 50


@dataclass
class SelectScanList:
    """An ordered, de-duplicated list of (bank, channel) entries to scan.
    Purely client-side state - nothing is written to the receiver until
    run_select_scan() actually tunes to an entry via MR."""

    entries: List[Tuple[int, int]] = field(default_factory=list)
    max_entries: int = DEFAULT_MAX_ENTRIES

    def add(self, bank: int, channel: int) -> None:
        """Appends (bank, channel) - silently de-duplicates (adding an
        already-present entry is a no-op, not an error) but raises
        ValueError if the list is already at max_entries."""
        pair = (bank, channel)
        if pair in self.entries:
            return
        if len(self.entries) >= self.max_entries:
            raise ValueError(
                f"select-scan list is full ({self.max_entries} entries max)"
            )
        self.entries.append(pair)

    def remove(self, bank: int, channel: int) -> bool:
        """Removes (bank, channel) if present. Returns whether it was
        present - callers that want a hard error on a missing entry can
        check the return value themselves."""
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
    """Runs a select-scan loop over ``entries``, calling
    ``tune_fn(bank, channel)`` (normally DV10Device.tune_memory_channel)
    for each entry in turn and yielding the (bank, channel) pair just
    tuned - lets a caller (e.g. the CLI) print progress or check for a
    keypress between entries without this function needing to know
    anything about ttys/consoles/real time itself.

    ``sleep_fn``/``should_stop`` are injectable purely for testability - a
    test passes a fake clock (e.g. a list-appending stub) and a
    call-counting stop predicate instead of actually sleeping on real time
    or blocking on real keyboard input; production callers can leave both
    at their defaults (``sleep_fn`` falls back to time.sleep, and with no
    ``should_stop`` the loop only ends via ``cycles`` or the caller simply
    not asking the generator for more items).

    ``cycles=None`` (the default) loops forever, until either
    ``should_stop()`` returns True or the caller stops iterating (e.g.
    breaks out of a ``for`` loop over this generator) - ``cycles=N`` stops
    on its own after N full passes over ``entries``.

    Raises ValueError immediately if ``entries`` is empty - nothing to
    scan, and looping forever over an empty list would otherwise be a
    silent no-op that never yields and never returns."""
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
