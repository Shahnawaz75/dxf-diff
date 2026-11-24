"""Turn the entities of a diff into simple 2D primitives (shared by HTML and PNG output).

Curves stay curves: ezdxf's ``make_path`` gives lines and Bezier segments, which
map 1:1 to SVG path commands and matplotlib paths. Blocks and dimensions are
expanded with ``virtual_entities()``. Text is kept as text (baseline + height).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from ezdxf import path as ezpath
from ezdxf.math import Vec3

from .model import ChangeKind, DiffResult

Box = Tuple[float, float, float, float]  # min x, min y, max x, max y
BLOCK_LIKE = {"INSERT", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION", "LEADER", "MULTILEADER", "MLINE"}
FILLED = {"SOLID", "TRACE", "HATCH", "MPOLYGON"}
MAX_DEPTH = 8


@dataclass
class Shape:
    """A path (``cmds``: M/L/Q/C/Z tuples in WCS), a filled area, a dot or text lines."""

    kind: str  # "path", "fill", "dot" or "text"
    cmds: List[Tuple[Any, ...]] = field(default_factory=list)
    lines: List[Tuple[float, float, str]] = field(default_factory=list)  # text baselines
    height: float = 0.0
    rotation: float = 0.0
    anchor: str = "start"  # SVG text-anchor: start, middle or end

    def points(self) -> Iterator[Tuple[float, float]]:
        """Points that bound the shape (curve control points included)."""
        for c in self.cmds:
            for k in range(1, len(c) - 1, 2):
                yield c[k], c[k + 1]
        if self.kind == "text":
            r = math.radians(self.rotation)
            dx, dy, ux, uy = math.cos(r), math.sin(r), -math.sin(r), math.cos(r)
            for x, y, text in self.lines:
                width = max(len(text), 1) * self.height * 0.75
                start = {"start": 0.0, "middle": -width / 2, "end": -width}[self.anchor]
                for along, up in (
                    (start, 0.0),
                    (start + width, 0.0),
                    (start, self.height),
                    (start + width, self.height),
                ):
                    yield x + dx * along + ux * up, y + dy * along + uy * up


@dataclass
class SceneItem:
    """The shapes of one entity. ``index`` points into ``DiffResult.changes`` (-1: unchanged)."""

    status: str  # "unchanged", "removed", "added", "old" or "new" (old/new: modified)
    shapes: List[Shape]
    index: int = -1

    def bbox(self) -> Optional[Box]:
        return bounding_box(p for s in self.shapes for p in s.points())


@dataclass
class Scene:
    items: List[SceneItem]
    extents: Box
    skipped: int = 0  # unchanged entities left out to keep the output light


def bounding_box(points: Iterable[Tuple[float, float]]) -> Optional[Box]:
    xs, ys = [], []
    for x, y in points:
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _path_commands(path: Any) -> List[Tuple[Any, ...]]:
    cmds: List[Tuple[Any, ...]] = []
    for sub in path.sub_paths():
        cmds.append(("M", sub.start.x, sub.start.y))
        for c in sub.commands():
            if c.type == ezpath.Command.LINE_TO:
                cmds.append(("L", c.end.x, c.end.y))
            elif c.type == ezpath.Command.CURVE3_TO:
                cmds.append(("Q", c.ctrl.x, c.ctrl.y, c.end.x, c.end.y))
            elif c.type == ezpath.Command.CURVE4_TO:
                cmds.append(("C", c.ctrl1.x, c.ctrl1.y, c.ctrl2.x, c.ctrl2.y, c.end.x, c.end.y))
            else:
                cmds.append(("M", c.end.x, c.end.y))
        if len(sub) and sub.is_closed:
            cmds.append(("Z",))
    return cmds


def _text_shape(
    origin: Vec3, rotation: float, height: float, lines: List[str], anchor: str, first: float, spacing: float
) -> Shape:
    """``first``: distance from ``origin`` down to the first baseline, in text direction."""
    r = math.radians(rotation)
    down_x, down_y = math.sin(r), -math.cos(r)
    baselines = []
    for i, text in enumerate(lines):
        offset = first + i * spacing
        baselines.append((origin.x + down_x * offset, origin.y + down_y * offset, text))
    return Shape("text", lines=baselines, height=height, rotation=rotation, anchor=anchor)


def _text(e: Any) -> Shape:
    align, p1, _p2 = e.get_placement()
    name = align.name  # LEFT, CENTER, RIGHT, ALIGNED, MIDDLE, FIT, TOP_LEFT ... BOTTOM_RIGHT
    height = float(e.dxf.get("height", 2.5)) or 2.5
    anchor = "end" if "RIGHT" in name else "middle" if ("CENTER" in name or name == "MIDDLE") else "start"
    first = {"TOP": height, "MIDDLE": height / 2, "BOTTOM": -0.2 * height}.get(name.split("_")[0], 0.0)
    text = e.plain_text() if hasattr(e, "plain_text") else str(e.dxf.get("text", ""))
    origin = e.ocs().to_wcs(p1)
    return _text_shape(origin, float(e.dxf.get("rotation", 0.0)), height, [text], anchor, first, 0.0)


def _mtext(e: Any) -> Shape:
    lines = e.plain_text(split=True) or [""]
    row, col = divmod(int(e.dxf.get("attachment_point", 1)) - 1, 3)
    height = float(e.dxf.get("char_height", 2.5)) or 2.5
    spacing = height * 5 / 3 * float(e.dxf.get("line_spacing_factor", 1.0))
    total = height + (len(lines) - 1) * spacing
    first = (height, height - total / 2, -(len(lines) - 1) * spacing)[min(row, 2)]
    anchor = ("start", "middle", "end")[min(col, 2)]
    return _text_shape(Vec3(e.dxf.insert), float(e.get_rotation()), height, lines, anchor, first, spacing)


def _emit(e: Any, out: List[Shape], depth: int) -> None:
    dxftype = e.dxftype()
    try:
        if dxftype == "TEXT" or (dxftype in ("ATTRIB", "ATTDEF") and not int(e.dxf.get("flags", 0)) & 1):
            out.append(_text(e))  # invisible attributes (flag 1) are skipped
        elif dxftype == "MTEXT":
            out.append(_mtext(e))
        elif dxftype == "POINT":
            if str(e.dxf.get("layer", "0")).upper() != "DEFPOINTS":  # dimension definition points
                p = Vec3(e.dxf.location)
                out.append(Shape("dot", [("M", p.x, p.y)]))
        elif dxftype in BLOCK_LIKE:
            if depth >= MAX_DEPTH:
                return
            refs = list(e.multi_insert()) if dxftype == "INSERT" and e.mcount > 1 else [e]
            for ref in refs:
                for child in ref.virtual_entities():
                    _emit(child, out, depth + 1)
                for attrib in getattr(ref, "attribs", ()) if dxftype == "INSERT" else ():
                    _emit(attrib, out, depth + 1)
        else:
            out.append(Shape("fill" if dxftype in FILLED else "path", _path_commands(ezpath.make_path(e))))
    except Exception:  # unsupported (e.g. XLINE, IMAGE) or invalid entity: not drawn
        return


def entity_shapes(entity: Any) -> List[Shape]:
    """All primitives needed to draw ``entity``."""
    out: List[Shape] = []
    if entity is not None:
        _emit(entity, out, 0)
    return out


def build_scene(result: DiffResult, space: str = "Model", max_unchanged: int = 60000) -> Scene:
    """Collect the shapes of one space; changed entities first, then unchanged ones.

    Unchanged entities are only context, so once ``max_unchanged`` shapes are drawn
    the rest are skipped (counted in ``Scene.skipped``).
    """
    items: List[SceneItem] = []
    for index, change in enumerate(result.changes):
        if change.space != space:
            continue
        if change.kind is ChangeKind.REMOVED:
            items.append(SceneItem("removed", entity_shapes(change.old_entity), index))
        elif change.kind is ChangeKind.ADDED:
            items.append(SceneItem("added", entity_shapes(change.new_entity), index))
        else:
            items.append(SceneItem("old", entity_shapes(change.old_entity), index))
            items.append(SceneItem("new", entity_shapes(change.new_entity), index))
    budget, skipped = max_unchanged, 0
    for change in result.entities:
        if change.kind is not ChangeKind.UNCHANGED or change.space != space:
            continue
        if budget <= 0:
            skipped += 1
            continue
        shapes = entity_shapes(change.new_entity)
        budget -= len(shapes)
        items.append(SceneItem("unchanged", shapes))
    extents = bounding_box(p for item in items for s in item.shapes for p in s.points()) or (0.0, 0.0, 1.0, 1.0)
    return Scene(items, extents, skipped)
