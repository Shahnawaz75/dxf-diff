"""Classification of entity, layer and block changes."""

from __future__ import annotations

import ezdxf
import pytest
from conftest import build_base, first

from dxf_diff import ChangeKind, compare


def only_change(result):
    changes = list(result)
    assert len(changes) == 1, [c.description for c in changes]
    return changes[0]


def test_identical_files_have_no_differences(base_path):
    result = compare(base_path, base_path)
    assert not result.has_changes
    assert list(result) == []
    assert result.summary()["entities"]["unchanged"] == len(ezdxf.readfile(base_path).modelspace())
    assert {c.matched_by for c in result.entities} == {"handle"}


def test_moved_line_end_is_modified(base_path, revise):
    def edit(doc):
        first(doc, "LINE").dxf.end = (12, 0)

    change = only_change(compare(base_path, revise(edit)))
    assert change.kind is ChangeKind.MODIFIED
    assert (change.dxftype, change.layer, change.matched_by) == ("LINE", "WALLS", "handle")
    assert change.old_handle == change.new_handle
    assert change.description == "LINE end moved (10,0) -> (12,0)"
    assert [(p.name, p.old, p.new) for p in change.changes] == [("end", (10.0, 0.0, 0.0), (12.0, 0.0, 0.0))]


def test_changed_text(base_path, revise):
    change = only_change(compare(base_path, revise(lambda d: setattr(first(d, "TEXT").dxf, "text", "REV B"))))
    assert change.kind is ChangeKind.MODIFIED
    assert change.description == "TEXT 'REV A' -> 'REV B'"


def test_deleted_circle_is_removed(base_path, revise):
    def edit(doc):
        doc.modelspace().delete_entity(first(doc, "CIRCLE"))

    change = only_change(compare(base_path, revise(edit)))
    assert (change.kind, change.dxftype, change.layer) == (ChangeKind.REMOVED, "CIRCLE", "EQUIP")
    assert change.new_handle is None and change.old_handle
    assert change.description == "CIRCLE r=5 at (20,20)"


def test_added_polyline(base_path, revise):
    def edit(doc):
        doc.modelspace().add_lwpolyline([(0, 80), (20, 80), (20, 90)], close=True, dxfattribs={"layer": "WALLS"})

    change = only_change(compare(base_path, revise(edit)))
    assert (change.kind, change.dxftype, change.layer) == (ChangeKind.ADDED, "LWPOLYLINE", "WALLS")
    assert change.old_handle is None
    assert change.description == "LWPOLYLINE 3 vertices, closed, first (0,80)"


def test_changed_block_attribute(base_path, revise):
    def edit(doc):
        first(doc, "INSERT").get_attrib("SIZE").dxf.text = '6"'

    change = only_change(compare(base_path, revise(edit)))
    assert change.kind is ChangeKind.MODIFIED
    assert change.description == "INSERT VALVE attribute SIZE '4\"' -> '6\"'"


def test_moved_block_reference(base_path, revise):
    change = only_change(compare(base_path, revise(lambda d: first(d, "INSERT").translate(5, 0, 0))))
    assert change.description == "INSERT VALVE insert moved (60,10) -> (65,10)"


def test_dimension_measurement_and_text_override(base_path, revise):
    def edit(doc):
        dim = first(doc, "DIMENSION")
        dim.dxf.defpoint3 = (12, 0)
        dim.dxf.text = "12 (REF)"
        dim.override().render()

    change = only_change(compare(base_path, revise(edit)))
    names = [p.name for p in change.changes]
    assert names[:2] == ["measurement", "text_override"]
    assert change.description.startswith("DIMENSION measurement 10 -> 12, text_override '<>' -> '12 (REF)'")


@pytest.mark.parametrize(
    ("dxftype", "edit", "expected"),
    [
        ("HATCH", lambda e: e.set_pattern_fill("ANSI32", scale=0.5), "HATCH pattern_name 'ANSI31' -> 'ANSI32'"),
        ("ELLIPSE", lambda e: setattr(e.dxf, "ratio", 0.6), "ELLIPSE ratio 0.5 -> 0.6"),
        ("ARC", lambda e: setattr(e.dxf, "end_angle", 120), "ARC end_angle 90 -> 120"),
        ("POINT", lambda e: setattr(e.dxf, "location", (71, 70)), "POINT location moved (70,70) -> (71,70)"),
        ("SOLID", lambda e: setattr(e.dxf, "vtx1", (83, 20)), "SOLID vtx1 moved (82,20) -> (83,20)"),
        ("XLINE", lambda e: setattr(e.dxf, "start", (0, 101)), "XLINE start moved (0,100) -> (0,101)"),
        ("MTEXT", lambda e: setattr(e, "text", "NOTE 1\\PNOTE 3"), "MTEXT 'NOTE 1 / NOTE 2' -> 'NOTE 1 / NOTE 3'"),
        ("CIRCLE", lambda e: setattr(e.dxf, "color", 1), "CIRCLE color BYLAYER -> 1 (red)"),
    ],
)
def test_entity_type_changes(base_path, revise, dxftype, edit, expected):
    change = only_change(compare(base_path, revise(lambda d: edit(first(d, dxftype)))))
    assert (change.kind, change.dxftype) == (ChangeKind.MODIFIED, dxftype)
    assert change.description == expected


def test_spline_fit_point_moved(base_path, revise):
    def edit(doc):
        spline = first(doc, "SPLINE")
        points = list(spline.fit_points)
        points[2] = (11, 30, 0)
        spline.fit_points = points

    change = only_change(compare(base_path, revise(edit)))
    assert change.description == "SPLINE fit point 2 moved (10,30) -> (11,30)"


def test_layer_table_changes(base_path, revise):
    def edit(doc):
        doc.layers.get("EQUIP").color = 5
        doc.layers.get("TEXT").freeze()
        doc.layers.add("NOTES", color=6)

    result = compare(base_path, revise(edit))
    assert list(result) == []  # the entities themselves did not change
    assert result.has_changes
    layers = {c.name: c for c in result.layers}
    assert layers["NOTES"].kind is ChangeKind.ADDED
    assert layers["EQUIP"].description == "color 3 (green) -> 5 (blue)"
    assert layers["TEXT"].description == "frozen"


def test_block_definition_change(base_path, revise):
    def edit(doc):
        next(e for e in doc.blocks.get("VALVE") if e.dxftype() == "CIRCLE").dxf.radius = 1.5

    result = compare(base_path, revise(edit))
    assert list(result) == []  # the INSERT itself is unchanged
    [block] = result.blocks
    assert (block.kind, block.name) == (ChangeKind.MODIFIED, "VALVE")
    assert block.description == "content changed: 1 modified"
    assert block.details == ["modified: CIRCLE radius 1 -> 1.5"]


def test_reexported_file_with_new_handles_matches_by_geometry(base_path, tmp_path):
    path = tmp_path / "reexported.dxf"
    build_base(skip_handles=7).saveas(path)
    old_handles = {e.dxf.handle for e in ezdxf.readfile(base_path).modelspace()}
    new_handles = {e.dxf.handle for e in ezdxf.readfile(path).modelspace()}
    assert old_handles != new_handles
    result = compare(base_path, path)
    assert not result.has_changes
    assert {c.matched_by for c in result.entities} == {"geometry"}


def test_reexported_file_with_edited_text_matches_by_similarity(base_path, tmp_path):
    doc = build_base(skip_handles=7)
    first(doc, "TEXT").dxf.text = "REV B"
    path = tmp_path / "reexported.dxf"
    doc.saveas(path)
    change = only_change(compare(base_path, path))
    assert (change.kind, change.matched_by) == (ChangeKind.MODIFIED, "similarity")
    assert change.old_handle != change.new_handle
    assert change.description == "TEXT 'REV A' -> 'REV B'"


def test_match_modes(base_path, revise):
    path = revise(lambda d: setattr(first(d, "LINE").dxf, "end", (12, 0)))
    assert only_change(compare(base_path, path, match="handle")).matched_by == "handle"
    assert only_change(compare(base_path, path, match="geometry")).matched_by == "similarity"
    with pytest.raises(ValueError):
        compare(base_path, path, match="magic")


def test_tolerance(base_path, revise):
    path = revise(lambda d: setattr(first(d, "CIRCLE").dxf, "radius", 5 + 1e-8))
    assert not compare(base_path, path).has_changes
    assert only_change(compare(base_path, path, tolerance=1e-10)).description == "CIRCLE radius 5 -> 5.00000001"


def test_arc_angle_360_equals_0(base_path, revise):
    assert not compare(base_path, revise(lambda d: setattr(first(d, "ARC").dxf, "start_angle", 360))).has_changes


def test_ignore_layers_and_layer_filter(base_path, revise):
    def edit(doc):
        first(doc, "TEXT").dxf.text = "REV B"  # layer TEXT
        first(doc, "LINE").dxf.end = (12, 0)  # layer WALLS

    path = revise(edit)
    assert [c.dxftype for c in compare(base_path, path, ignore_layers=["TEXT"])] == ["LINE"]
    assert [c.dxftype for c in compare(base_path, path, layers=["WAL*"])] == ["LINE"]
    assert [c.dxftype for c in compare(base_path, path, layers=["text"])] == ["TEXT"]


def test_ignore_props(base_path, revise):
    path = revise(lambda d: setattr(first(d, "CIRCLE").dxf, "color", 1))
    assert only_change(compare(base_path, path)).changes[0].name == "color"
    assert not compare(base_path, path, ignore_props=["color"]).has_changes
    assert not compare(base_path, path, ignore_props="linetype,color").has_changes


def test_paperspace_only_with_layouts_flag(base_path, revise):
    path = revise(lambda d: setattr(first(d, "TEXT", "Layout1").dxf, "text", "SHEET 2"))
    assert not compare(base_path, path).has_changes
    change = only_change(compare(base_path, path, layouts=True))
    assert (change.space, change.description) == ("Layout1", "TEXT 'SHEET 1' -> 'SHEET 2'")
