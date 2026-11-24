"""The Python API: iterating, filtering and serializing results."""

from __future__ import annotations

import json

import ezdxf
import pytest
from conftest import first

import dxf_diff
from dxf_diff import ChangeKind, DxfDiffError, compare


@pytest.fixture
def result(base_path, rev_path):
    return compare(base_path, rev_path)


def test_iterate_and_filter(result):
    assert sorted(c.dxftype for c in result) == ["CIRCLE", "LINE", "LWPOLYLINE", "TEXT"]
    assert [c.dxftype for c in result.added] == ["LWPOLYLINE"]
    assert [c.dxftype for c in result.removed] == ["CIRCLE"]
    assert [c.dxftype for c in result.filter(kind="modified")] == ["LINE", "TEXT"]
    assert [c.dxftype for c in result.filter(kind=[ChangeKind.ADDED, "removed"])] == ["LWPOLYLINE", "CIRCLE"]
    assert [c.dxftype for c in result.filter(dxftype="line")] == ["LINE"]
    assert {c.dxftype for c in result.filter(layer="wall*")} == {"LINE", "LWPOLYLINE"}
    assert all(c.kind is ChangeKind.UNCHANGED for c in result.filter(kind="unchanged"))
    assert result.filter(kind="unchanged") == result.unchanged


def test_summary_and_json_serialization(result):
    summary = result.summary()
    assert summary["entities"] == {"added": 1, "removed": 1, "modified": 2, "unchanged": len(result.unchanged)}
    data = json.loads(result.to_json())
    assert data["format"] == "dxf-diff-report" and data["format_version"] == 1
    assert data["tool"]["version"] == dxf_diff.__version__
    assert data["summary"] == summary and data["has_changes"] is True
    assert len(data["entities"]) == 4  # unchanged entities are left out by default
    line = next(e for e in data["entities"] if e["dxftype"] == "LINE")
    assert line["changes"] == [{"name": "end", "old": [10.0, 0.0, 0.0], "new": [12.0, 0.0, 0.0]}]
    keys = "kind dxftype layer space old_handle new_handle description changes matched_by"
    assert list(line) == keys.split()
    full = result.to_dict(include_unchanged=True)
    assert len(full["entities"]) == len(result.entities)


def test_compare_accepts_loaded_drawings(base_path):
    doc = ezdxf.readfile(base_path)
    other = ezdxf.readfile(base_path)
    first(other, "CIRCLE").dxf.radius = 6
    [change] = list(compare(doc, other))
    assert change.description == "CIRCLE radius 5 -> 6"
    assert change.old_entity.dxf.radius == 5 and change.new_entity.dxf.radius == 6


def test_missing_file_and_dwg_raise_dxf_diff_error(base_path, tmp_path):
    with pytest.raises(DxfDiffError, match="no such file"):
        compare(base_path, tmp_path / "missing.dxf")
    dwg = tmp_path / "drawing.dxf"
    dwg.write_bytes(b"AC1032\x00\x00\x00\x00binary dwg data")
    with pytest.raises(DxfDiffError, match="DWG"):
        compare(base_path, dwg)


def test_damaged_file_is_recovered_with_a_warning(base_path, tmp_path, caplog):
    damaged = tmp_path / "damaged.dxf"
    damaged.write_bytes(base_path.read_bytes().replace(b"ENDSEC", b"", 1))  # broken HEADER section
    result = compare(base_path, damaged)
    assert "is damaged" in caplog.text
    assert result.summary()["entities"]["unchanged"] > 0
