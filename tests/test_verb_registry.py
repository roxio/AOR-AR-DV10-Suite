
from __future__ import annotations

from aor_dv10.cli.repl import _VERBS
from aor_dv10.verb_registry import VERBS, render_web_help, verb_names


def test_verb_names_match_registry_order():
    assert verb_names() == [v for v, _ in VERBS]


def test_cli_verbs_are_derived_from_registry():
    assert _VERBS == verb_names()
    for required in ("s", "f", "m", "sp", "sn", "rmem", "search", "timer"):
        assert required in _VERBS


def test_render_web_help_mentions_core_verbs():
    text = render_web_help()
    assert text.startswith("commands: ")
    assert "f [MHZ]" in text
    assert "sp" in text and "sn" in text


def test_no_duplicate_verbs():
    names = verb_names()
    assert len(names) == len(set(names))
