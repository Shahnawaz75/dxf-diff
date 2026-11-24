"""Shared fixtures: a base drawing built with ezdxf and helpers to make revisions of it."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import ezdxf
import pytest
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment


def build_base(skip_handles: int = 0) -> Drawing:
    """A small drawing with one entity of every supported type.

    ``skip_handles`` burns handle numbers first, which simulates a file that was
    re-exported by another program: same content, different handles.
    """
    doc = ezdxf.new("R2018", setup=True)
    for _ in range(skip_handles):
        doc.entitydb.handles.next()
    doc.layers.add("WALLS", color=7)
    doc.layers.add("TEXT", color=2)
    doc.layers.add("EQUIP", color=3)
    doc.layers.add("DIMS", color=1)
    valve = doc.blocks.new("VALVE")
    valve.add_circle((0, 0), 1)
    valve.add_line((-1, 0), (1, 0))
    valve.add_attdef("TAG", (0, 1.5), dxfattribs={"height": 0.5})
    valve.add_attdef("SIZE", (0, -2), dxfattribs={"height": 0.5})

    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALLS"})
    msp.add_line((10, 0), (10, 10), dxfattribs={"layer": "WALLS"})
    msp.add_circle((20, 20), 5, dxfattribs={"layer": "EQUIP"})
    msp.add_arc((30, 0), 3, 0, 90, dxfattribs={"layer": "WALLS"})
    msp.add_ellipse((40, 0), major_axis=(4, 0), ratio=0.5)
    msp.add_spline([(0, 30), (5, 35), (10, 30), (15, 35)])
    msp.add_text("REV A", height=2.5, dxfattribs={"layer": "TEXT"}).set_placement(
        (50, 50), align=TextEntityAlignment.MIDDLE_CENTER
    )
    msp.add_mtext("NOTE 1\\PNOTE 2", dxfattribs={"layer": "TEXT", "char_height": 1.5, "insert": (50, 40)})
    valve_ref = msp.add_blockref("VALVE", (60, 10), dxfattribs={"layer": "EQUIP"})
    valve_ref.add_auto_attribs({"TAG": "V-101", "SIZE": '4"'})
    msp.add_linear_dim(base=(0, -5), p1=(0, 0), p2=(10, 0), dxfattribs={"layer": "DIMS"}).render()
    hatch = msp.add_hatch(color=8, dxfattribs={"layer": "WALLS"})
    hatch.paths.add_polyline_path([(70, 0), (80, 0), (80, 10), (70, 10)], is_closed=True)
    hatch.set_pattern_fill("ANSI31", scale=0.5)
    msp.add_point((70, 70))
    msp.add_solid([(80, 20), (82, 20), (80, 22)])
    msp.add_3dface([(90, 0, 0), (91, 0, 0), (91, 1, 1), (90, 1, 1)])
    msp.add_lwpolyline([(0, 50), (10, 50), (10, 60)], dxfattribs={"layer": "WALLS"})
    msp.add_polyline2d([(0, 70), (5, 75), (10, 70)])
    msp.add_xline((0, 100), (1, 0))  # no dedicated extractor: generic attribute comparison
    doc.paperspace().add_text("SHEET 1", height=3, dxfattribs={"insert": (10, 10)})
    return doc


def first(doc: Drawing, dxftype: str, layout: str = "Model"):
    """The first entity of ``dxftype`` in the given layout."""
    space = doc.modelspace() if layout == "Model" else doc.layouts.get(layout)
    return next(e for e in space if e.dxftype() == dxftype)


@pytest.fixture
def base_path(tmp_path: Path) -> Path:
    path = tmp_path / "base.dxf"
    build_base().saveas(path)
    return path


@pytest.fixture
def revise(tmp_path: Path, base_path: Path) -> Callable[..., Path]:
    """Load the base drawing, apply ``edit(doc)`` and save it as a new revision."""

    def _revise(edit: Callable[[Drawing], None], name: str = "rev.dxf") -> Path:
        doc = ezdxf.readfile(base_path)
        edit(doc)
        path = tmp_path / name
        doc.saveas(path)
        return path

    return _revise


@pytest.fixture
def rev_path(revise: Callable[..., Path]) -> Path:
    """A revision with one change of each kind: 1 added, 1 removed, 2 modified, 1 layer modified."""

    def edit(doc: Drawing) -> None:
        first(doc, "LINE").dxf.end = (12, 0)
        first(doc, "TEXT").dxf.text = "REV B"
        doc.modelspace().delete_entity(first(doc, "CIRCLE"))
        doc.modelspace().add_lwpolyline([(0, 80), (20, 80)], dxfattribs={"layer": "WALLS"})
        doc.layers.get("EQUIP").color = 5

    return revise(edit)
