
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "src" / "aor_dv10" / "web" / "static" / "index.html"

_BS = chr(92)
_Q1, _Q2, _Q3 = chr(39), chr(34), chr(96)


def _read() -> str:
    return INDEX.read_text(encoding="utf-8")


_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")
_REGEX_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}


def _regex_allowed(prev_char: str, prev_word: str) -> bool:
    if prev_char == "":
        return True
    if prev_char in "([{,;:=!&|?+-*%~^<>":
        return True
    if prev_char in ")]}":
        return False
    if prev_char in _IDENT_CHARS:
        return prev_word in _REGEX_KEYWORDS
    return True


def _strip_strings_and_comments(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    stack: list[list] = [["code"]]
    prev_char, word = "", ""
    while i < n:
        frame = stack[-1]
        kind = frame[0]
        c = s[i]
        if kind == "str":
            q = frame[1]
            if c == _BS:
                out.append("  ")
                i += 2
                continue
            if c == q:
                stack.pop()
            out.append(" ")
            i += 1
            continue
        if kind == "tpl":
            if c == _BS:
                out.append("  ")
                i += 2
                continue
            if c == _Q3:
                stack.pop()
                out.append(" ")
                i += 1
                continue
            if c == "$" and i + 1 < n and s[i + 1] == "{":
                out.append("  ")
                i += 2
                stack.append(["interp", 0])
                continue
            out.append(" ")
            i += 1
            continue
        in_interp = kind == "interp"
        if c in " \t\r\n":
            out.append(" " if in_interp else c)
            i += 1
            continue
        nxt = s[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = s.find("\n", i)
            if j == -1:
                out.append(" " * (n - i))
                i = n
            else:
                out.append(" " * (j - i))
                i = j
            continue
        if c == "/" and nxt == "*":
            j = s.find("*/", i + 2)
            if j == -1:
                out.append(" " * (n - i))
                i = n
            else:
                out.append(" " * (j + 2 - i))
                i = j + 2
            continue
        if c == "/" and _regex_allowed(prev_char, word):
            i2, in_class = i + 1, False
            while i2 < n:
                ch = s[i2]
                if ch == _BS:
                    i2 += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    i2 += 1
                    break
                elif ch == "\n":
                    break
                i2 += 1
            while i2 < n and s[i2] in _IDENT_CHARS:
                i2 += 1
            out.append(" " * (i2 - i))
            i = i2
            prev_char, word = "/", ""
            continue
        if c == _Q1:
            stack.append(["str", _Q1])
            out.append(" ")
            i += 1
            prev_char, word = c, ""
            continue
        if c == _Q2:
            stack.append(["str", _Q2])
            out.append(" ")
            i += 1
            prev_char, word = c, ""
            continue
        if c == _Q3:
            stack.append(["tpl"])
            out.append(" ")
            i += 1
            prev_char, word = c, ""
            continue
        if c == "{":
            if in_interp:
                frame[1] += 1
                out.append(" ")
            else:
                out.append("{")
            i += 1
            prev_char, word = c, ""
            continue
        if c == "}":
            if in_interp:
                if frame[1] == 0:
                    stack.pop()
                else:
                    frame[1] -= 1
                out.append(" ")
            else:
                out.append("}")
            i += 1
            prev_char, word = c, ""
            continue
        if c in _IDENT_CHARS:
            word += c
        else:
            word = ""
        out.append(" " if in_interp else c)
        prev_char = c
        i += 1
    return "".join(out)



def _balance_error(s: str) -> str | None:
    pairs = {"{": "}", "(": ")", "[": "]"}
    stack = []
    for i, c in enumerate(s):
        if c in pairs:
            stack.append(c)
        elif c in pairs.values():
            if not stack or pairs[stack[-1]] != c:
                return f"unexpected {c!r} at char {i}"
            stack.pop()
    if stack:
        return f"unclosed {stack}"
    return None


def test_style_and_script_are_balanced():
    src = _read()
    style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
    script = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
    assert _balance_error(_strip_strings_and_comments(style)) is None, "CSS is unbalanced"
    assert _balance_error(_strip_strings_and_comments(script)) is None, "JS is unbalanced"


def _dict_blocks(src: str):
    en = re.search(r"\n  en: \{(.*?)\n  \},", src, re.S).group(1)
    pl = re.search(r"\n  pl: \{(.*?)\n  \},", src, re.S).group(1)
    return en, pl


def test_i18n_tables_have_no_duplicate_keys():
    en, pl = _dict_blocks(_read())
    for label, block in (("en", en), ("pl", pl)):
        counts = Counter(re.findall(r"^    ([A-Za-z_][A-Za-z0-9_]*):", block, re.M))
        dups = {k: n for k, n in counts.items() if n > 1}
        assert not dups, f"duplicate {label} i18n keys: {dups}"


def test_i18n_en_pl_key_parity():
    en, pl = _dict_blocks(_read())
    en_keys = set(re.findall(r"^    ([A-Za-z_][A-Za-z0-9_]*):", en, re.M))
    pl_keys = set(re.findall(r"^    ([A-Za-z_][A-Za-z0-9_]*):", pl, re.M))
    assert en_keys == pl_keys, f"missing in PL: {en_keys - pl_keys}; missing in EN: {pl_keys - en_keys}"


def test_every_data_i18n_attribute_resolves():
    src = _read()
    en, pl = _dict_blocks(src)
    known = set(re.findall(r"^    ([A-Za-z_][A-Za-z0-9_]*):", en, re.M))
    attrs = set(re.findall(r'data-i18n(?:-ph|-title)?="([^"]+)"', src))
    missing = sorted(a for a in attrs if a not in known)
    assert not missing, f"data-i18n keys with no entry: {missing}"


def test_inline_onclick_handlers_are_defined():
    src = _read()
    script = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
    declared = set(re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", script, re.M))
    declared |= set(re.findall(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", script, re.M))
    handlers = set(re.findall(r'on(?:click|change|input|submit)="([A-Za-z_$][\w$]*)\s*\(', src))
    builtins = {"send", "confirmDestructive", "alert", "this"}
    missing = sorted(h for h in handlers if h not in declared and h not in builtins)
    assert not missing, f"inline handlers with no declared function: {missing}"


def test_accessibility_skip_link_and_live_region():
    src = _read()
    assert 'class="skip-link"' in src and 'href="#main"' in src
    assert 'id="main"' in src
    assert 'id="ariaLive"' in src and 'aria-live="polite"' in src
    assert 'MutationObserver' in src and 'lastFocusedBeforeOverlay' in src


def test_hidden_elements_with_a_display_rule_have_a_hidden_override():
    src = _read()
    style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
    hidden_classes = set()
    for tag in re.findall(r"<[a-zA-Z][^>]*>", src):
        if not re.search(r"(?<![\w-])hidden(?![\w-])", tag):
            continue
        m = re.search(r'class="([^"]+)"', tag)
        if m:
            hidden_classes.update(m.group(1).split())
    for cls in sorted(hidden_classes):
        base = re.search(r"\.(?<!\w)" + re.escape(cls) + r"\s*\{([^}]*)\}", style)
        if not base:
            continue
        body = base.group(1)
        if "display" in body and "none" not in body:
            override = re.search(
                r"\." + re.escape(cls) + r"\[hidden\]\s*\{[^}]*display\s*:\s*none", style
            )
            assert override, (
                f".{cls} sets a display value but has no .{cls}[hidden] "
                f"display:none override - toggling .hidden won't hide it"
            )


def test_no_duplicate_top_level_let_const_class_declarations():
    src = _read()
    script = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
    decl = re.compile(r"^(let|const|class)\s+([A-Za-z_$][\w$]*)", re.M)
    counts = Counter(m.group(2) for m in decl.finditer(script))
    dups = {k: n for k, n in counts.items() if n > 1}
    assert not dups, f"duplicate top-level let/const/class declarations: {dups}"


def test_no_top_level_calls_to_undeclared_functions():
    src = _read()
    script = re.search(r"<script>(.*?)</script>", src, re.S).group(1)
    declared = set(re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", script, re.M))
    declared |= set(re.findall(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", script, re.M))
    keywords = {
        "for", "if", "while", "switch", "catch", "return", "function", "do",
        "else", "typeof", "delete", "void", "new", "in", "of", "case", "throw",
        "await", "yield", "with",
    }
    builtins = {
        "setInterval", "setTimeout", "clearInterval", "clearTimeout",
        "requestAnimationFrame", "fetch", "parseInt", "parseFloat", "isNaN",
        "alert", "confirm", "prompt", "require", "import",
    }
    calls = set(re.findall(r"^([A-Za-z_$][\w$]*)\s*\(", script, re.M))
    missing = sorted(c for c in calls if c not in declared and c not in keywords and c not in builtins)
    assert not missing, f"top-level calls to undeclared functions: {missing}"


def _chassis_span(src: str) -> tuple[int, int]:
    html = src[: src.index("<script>")]
    html = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html, flags=re.S)
    m = re.search(r'<div\b[^>]*class="[^"]*\bchassis\b[^"]*"', html)
    assert m, "no .chassis element found"
    start = m.start()
    depth = 0
    for tm in re.finditer(r"<div\b|</div>", html[start:]):
        depth += 1 if tm.group(0) == "<div" else -1
        if depth == 0:
            return start, start + tm.end()
    raise AssertionError(".chassis element never closes")


def test_chassis_shell_wraps_console_queue_and_footer():
    src = _read()
    start, end = _chassis_span(src)
    inner = src[start:end]
    for needle in ('class="service"', 'id="cmdQueuePanel"', "<footer"):
        assert needle in inner, f"{needle} fell outside the .chassis shell"


