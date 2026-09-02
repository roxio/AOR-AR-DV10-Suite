"""Regression tests for `dv10-cli
--export-commands FORMAT`, a machine-readable dump of the full
aor_dv10.protocol.commands.COMMANDS registry - useful for cross-checking
against a future AOR manual revision without hand-diffing PDFs again.
Deliberately makes no device connection (neither --simulator nor --port),
since this is pure static data - these tests call main()/export_commands()
directly with argv/stdout substituted, same style as other CLI tests in
this project call Repl.dispatch() directly.
"""

import csv
import io
import json

from aor_dv10.cli.__main__ import export_commands, main
from aor_dv10.protocol.commands import COMMANDS


def test_export_commands_json_covers_the_full_registry():
    out = io.StringIO()
    export_commands("json", out)
    rows = json.loads(out.getvalue())
    assert len(rows) == len(COMMANDS)
    assert {r["code"] for r in rows} == set(COMMANDS.keys())


def test_export_commands_json_row_shape():
    out = io.StringIO()
    export_commands("json", out)
    rows = {r["code"]: r for r in json.loads(out.getvalue())}
    rf = rows["RF"]
    assert rf["description"] == COMMANDS["RF"].description
    assert rf["access"] == COMMANDS["RF"].access.value
    assert rf["notes"] == COMMANDS["RF"].notes


def test_export_commands_json_sorted_by_code():
    out = io.StringIO()
    export_commands("json", out)
    rows = json.loads(out.getvalue())
    codes = [r["code"] for r in rows]
    assert codes == sorted(codes)


def test_export_commands_csv_covers_the_full_registry():
    out = io.StringIO()
    export_commands("csv", out)
    reader = csv.DictReader(io.StringIO(out.getvalue()))
    rows = list(reader)
    assert reader.fieldnames == ["code", "description", "access", "notes"]
    assert len(rows) == len(COMMANDS)
    assert {r["code"] for r in rows} == set(COMMANDS.keys())


def test_export_commands_rejects_unknown_format():
    import pytest

    with pytest.raises(ValueError):
        export_commands("xml", io.StringIO())


def test_cli_export_commands_flag_exits_zero_without_a_device(capsys, monkeypatch):
    # No --simulator, no --port: if this tried to open a real serial
    # connection it would fail loudly (no hardware in this test
    # environment) - succeeding here proves the export path really does
    # skip device connection entirely, as documented.
    rc = main(["--export-commands", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    assert len(rows) == len(COMMANDS)


def test_cli_export_commands_csv_flag_via_main(capsys):
    rc = main(["--export-commands", "csv"])
    assert rc == 0
    captured = capsys.readouterr()
    reader = csv.DictReader(io.StringIO(captured.out))
    assert len(list(reader)) == len(COMMANDS)
