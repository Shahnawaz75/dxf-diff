"""The dxf-diff command: exit codes, terminal output, report files and textconv."""

from __future__ import annotations

import json
import re
import subprocess
import sys

from conftest import build_base, first

from dxf_diff import __version__
from dxf_diff.cli import main

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_exit_code_0_when_identical(base_path, capsys):
    assert main([str(base_path), str(base_path)]) == 0
    assert "No differences." in capsys.readouterr().out


def test_exit_code_1_and_summary_when_different(base_path, rev_path, capsys):
    assert main([str(base_path), str(rev_path)]) == 1
    out = capsys.readouterr().out
    assert "Entities: 1 added, 1 removed, 2 modified" in out
    assert "Layers:   1 modified" in out
    assert "LINE end moved (10,0) -> (12,0)" in out
    assert "TEXT 'REV A' -> 'REV B'" in out
    assert "color 3 (green) -> 5 (blue)" in out
    assert not ANSI.search(out)  # captured output is not a TTY: no colors


def test_color_always_and_brief_and_quiet(base_path, rev_path, capsys):
    assert main([str(base_path), str(rev_path), "--color", "always"]) == 1
    assert ANSI.search(capsys.readouterr().out)
    assert main([str(base_path), str(rev_path), "--brief"]) == 1
    out = capsys.readouterr().out
    assert "Entities:" in out and "LINE end moved" not in out
    assert main([str(base_path), str(rev_path), "-q"]) == 1
    assert capsys.readouterr().out == ""


def test_exit_code_2_on_errors(base_path, tmp_path, capsys):
    assert main([str(base_path), str(tmp_path / "missing.dxf")]) == 2
    assert "no such file" in capsys.readouterr().err
    bad = tmp_path / "bad.dxf"
    bad.write_text("this is not a drawing\n")
    assert main([str(base_path), str(bad)]) == 2
    assert "cannot read" in capsys.readouterr().err
    dwg = tmp_path / "drawing.dwg"
    dwg.write_bytes(b"AC1032\x00\x00\x00\x00binary dwg data")
    assert main(["--textconv", str(dwg)]) == 2
    assert "DWG" in capsys.readouterr().err
    assert main([str(base_path)]) == 2  # usage error: only one file
    assert main([str(base_path), str(base_path), "--tolerance", "-1"]) == 2


def test_ignore_options(base_path, rev_path, capsys):
    args = [str(base_path), str(rev_path), "--ignore-layer", "TEXT", "--ignore-layer", "EQUIP", "--layer", "W*"]
    assert main(args) == 1
    out = capsys.readouterr().out
    assert "LINE end moved" in out and "REV B" not in out and "CIRCLE" not in out


def test_json_and_html_report_files(base_path, rev_path, tmp_path, capsys):
    report, html = tmp_path / "report.json", tmp_path / "report.html"
    assert main([str(base_path), str(rev_path), "--json", str(report), "--html", str(html), "-q"]) == 1
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    data = json.loads(report.read_text(encoding="utf-8"))
    keys = "format format_version tool old new options has_changes summary entities layers blocks"
    assert list(data) == keys.split()
    assert data["options"]["tolerance"] == 1e-6 and data["old"]["path"] == str(base_path)
    assert data["summary"]["entities"]["modified"] == 2
    assert data["layers"][0]["changes"] == [{"name": "color", "old": 3, "new": 5}]
    assert main([str(base_path), str(rev_path), "--json", "-"]) == 1
    assert json.loads(capsys.readouterr().out)["has_changes"] is True  # stdout holds only JSON


def test_textconv_is_deterministic_and_handle_free(base_path, tmp_path, capsys):
    assert main(["--textconv", str(base_path)]) == 0
    first_run = capsys.readouterr().out
    assert main(["--textconv", str(base_path)]) == 0
    assert capsys.readouterr().out == first_run
    reexported = tmp_path / "reexported.dxf"
    build_base(skip_handles=7).saveas(reexported)  # same content, other handles and GUIDs
    assert main(["--textconv", str(reexported)]) == 0
    assert capsys.readouterr().out == first_run
    lines = first_run.splitlines()
    assert lines[0] == "# dxf-diff textconv 1"
    start = lines.index('LAYOUT "Model"') + 1
    end = next(i for i in range(start, len(lines)) if lines[i].startswith("LAYOUT"))
    model = lines[start:end]
    records = [line for line in model if not line.startswith("    ")]
    assert records == sorted(records)
    assert '  CIRCLE layer="EQUIP" center=(20,20) radius=5 thickness=0' in model


def test_textconv_shows_the_edit(base_path, revise, capsys):
    rev = revise(lambda d: setattr(first(d, "CIRCLE").dxf, "radius", 6))
    main(["--textconv", str(base_path)])
    old = set(capsys.readouterr().out.splitlines())
    main(["--textconv", str(rev)])
    new = set(capsys.readouterr().out.splitlines())
    assert old - new == {'  CIRCLE layer="EQUIP" center=(20,20) radius=5 thickness=0'}
    assert new - old == {'  CIRCLE layer="EQUIP" center=(20,20) radius=6 thickness=0'}


def test_module_entry_point(base_path, rev_path):
    cmd = [sys.executable, "-m", "dxf_diff", str(base_path), str(rev_path), "--brief"]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 1 and "Entities:" in run.stdout
    run = subprocess.run([sys.executable, "-m", "dxf_diff", "--version"], capture_output=True, text=True)
    assert run.returncode == 0 and __version__ in run.stdout
