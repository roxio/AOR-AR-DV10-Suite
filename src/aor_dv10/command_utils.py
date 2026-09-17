
from __future__ import annotations

import shlex

__all__ = [
    "on_off",
    "split_command",
    "parse_clock_digits",
    "parse_bank_link_tokens",
    "WEEKDAY_BITS",
]


def on_off(token: str) -> bool:
    token = token.strip().lower()
    if token in ("on", "1", "true"):
        return True
    if token in ("off", "0", "false"):
        return False
    raise ValueError(f"expected on/off, got {token!r}")


def split_command(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)


def parse_clock_digits(token: str) -> tuple[int, int, int, int, int]:
    digits = "".join(ch for ch in token if ch.isdigit())
    if len(digits) != 10:
        raise ValueError(
            f'clock value must be 10 digits, "YYMMDDHHmm" (e.g. "2601301500" '
            f'or "26-01-30 15:00") - got {token!r}'
        )
    return (
        int(digits[0:2]), int(digits[2:4]), int(digits[4:6]),
        int(digits[6:8]), int(digits[8:10]),
    )


def parse_bank_link_tokens(tokens: list[str]):
    if tokens == ["clear"]:
        return []
    return [int(t) for t in tokens]


WEEKDAY_BITS = {"sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64}
