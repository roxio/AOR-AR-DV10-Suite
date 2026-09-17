
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src" / "aor_dv10" / "cli" / "repl.py"
WEB = ROOT / "src" / "aor_dv10" / "web" / "server.py"


def _verbs_in(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    verbs = set(re.findall(r'verb\s*==\s*"([^"]+)"', src))
    for group in re.findall(r"verb\s+in\s+\(([^)]*)\)", src):
        verbs.update(re.findall(r'"([^"]+)"', group))
    return verbs


def test_web_dispatch_verbs_are_a_subset_of_cli():
    cli = _verbs_in(CLI)
    web = _verbs_in(WEB)
    assert cli, "no CLI verbs parsed - regex drifted"
    assert web, "no web verbs parsed - regex drifted"
    missing = sorted(web - cli)
    assert not missing, f"web handles verbs the CLI does not: {missing}"


def test_both_dispatchers_handle_the_core_verbs():
    cli = _verbs_in(CLI)
    web = _verbs_in(WEB)
    for v in ("s", "f", "m", "sq", "raw", "vfo", "mem", "search", "scan", "pass"):
        assert v in cli, f"CLI missing core verb {v!r}"
        assert v in web, f"web missing core verb {v!r}"
