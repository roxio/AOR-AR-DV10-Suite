
from __future__ import annotations

import re

__all__ = ["parse_composite_fields", "parse_known_fields"]


def parse_composite_fields(text: str, *, tag_field: str | None = None) -> dict:
    fields: dict = {}
    for match in re.finditer(r"\S+", text):
        token = match.group()
        if len(token) > 2 and token[:2].isalpha():
            code = token[:2].upper()
            if tag_field and code == tag_field.upper():
                fields[code] = text[match.start() + 2 :].strip()
                break
            fields[code] = token[2:]
    return fields


def parse_known_fields(text: str, codes) -> dict:
    fields: dict = {}
    for token in text.split():
        for code in codes:
            if token.upper().startswith(code):
                fields[code] = token[len(code):]
                break
    return fields
