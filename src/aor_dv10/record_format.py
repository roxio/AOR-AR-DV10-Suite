
from __future__ import annotations

from typing import Iterable


def format_search_bank(info) -> str:
    lo = f"{info.lower_limit_hz / 1_000_000:.4f}" if info.lower_limit_hz is not None else "?"
    hi = f"{info.upper_limit_hz / 1_000_000:.4f}" if info.upper_limit_hz is not None else "?"
    return (
        f"bank {info.bank:02d}: {lo}-{hi} MHz  step={info.step_hz}  "
        f"stepadj={info.step_adjust_hz}  mode={info.mode}  "
        f"protect={info.write_protect}  {info.tag!r}"
    )


def format_scan_group(info, *, kind: str) -> str:
    return (
        f"{kind} group {info.group:02d}: delay={info.delay_ds} free={info.free_time_s} "
        f"autostore={info.auto_store} banks={list(info.bank_link)}"
    )


def format_pass_list(entries: Iterable) -> str:
    entries = list(entries)
    used = [e for e in entries if e.frequency_hz is not None]
    lines = [f"{e.index:02d}: {e.frequency_hz / 1_000_000:.4f} MHz" for e in used]
    lines.append(f"({len(used)} of {len(entries)} slots used)")
    return "\n".join(lines)
