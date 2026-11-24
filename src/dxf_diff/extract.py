"""Turn ezdxf entities into plain, comparable property dicts.

Conventions: points are tuples of three floats, sequences are lists, block
attributes are a ``{tag: text}`` dict. Everything else is a str, int, float or bool.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

from ezdxf import path as ezpath

Props = Dict[str, Any]
Point = Tuple[float, float, float]

COMMON_DEFAULTS: Props = {"color": 256, "linetype": "BYLAYER", "lineweight": -1, "ltscale": 1.0}
OPTIONAL_COMMON = ("true_color", "transparency")
#: String properties compared case-insensitively (DXF table names are case-insensitive).
CASE_INSENSITIVE = frozenset({"layer", "linetype", "style", "dimstyle", "name", "pattern_name"})
#: ``--ignore-props`` names that cover more than one property.
PROP_ALIASES = {"color": ("color", "true_color"), "linetype": ("linetype", "ltscale")}
_SKIP_GENERIC = frozenset({"handle", "owner", "layer", "paperspace", *COMMON_DEFAULTS, *OPTIONAL_COMMON})
_DIGITS = 10  # rounding applied to every float to suppress floating point noise


def num(value: Any) -> float:
    """Return ``value`` as a plain, slightly rounded float (never ``-0.0``)."""
    result = round(float(value), _DIGITS)
    return 0.0 if result == 0 else result


def point(value: Any) -> Point:
    """Return a 3D point tuple from a Vec2, Vec3, numpy array or sequence."""
    v = tuple(value)
    return (num(v[0]), num(v[1]), num(v[2]) if len(v) > 2 else 0.0)


def angle(degrees: Any) -> float:
    """Normalize an angle in degrees to [0, 360)."""
    a = float(degrees) % 360.0
    return 0.0 if abs(a - 360.0) < 1e-6 or abs(a) < 1e-12 else num(a)


def _get(entity: Any, name: str, default: Any) -> Any:
    value = entity.dxf.get(name, default)
    return default if value is None else value


def _line(e: Any) -> Props:
    return {"start": point(e.dxf.start), "end": point(e.dxf.end), "thickness": num(_get(e, "thickness", 0.0))}


def _circle(e: Any) -> Props:
    return {"center": point(e.dxf.center), "radius": num(e.dxf.radius), "thickness": num(_get(e, "thickness", 0.0))}


def _arc(e: Any) -> Props:
    props = _circle(e)
    props["start_angle"] = angle(e.dxf.start_angle)
    props["end_angle"] = angle(e.dxf.end_angle)
    return props


def _ellipse(e: Any) -> Props:
    tau = 2.0 * math.pi

    def param(value: float) -> float:
        p = float(value) % tau
        return 0.0 if abs(p - tau) < 1e-9 else num(p)

    start, end = param(_get(e, "start_param", 0.0)), param(_get(e, "end_param", tau))
    if abs(end - start) < 1e-9:  # full ellipse
        start, end = 0.0, num(tau)
    return {
        "center": point(e.dxf.center),
        "major_axis": point(e.dxf.major_axis),
        "ratio": num(e.dxf.ratio),
        "start_param": start,
        "end_param": end,
    }


def _lwpolyline(e: Any) -> Props:
    pts = list(e.get_points("xyb"))
    props: Props = {
        "vertices": [point(p[:2]) for p in pts],
        "closed": bool(e.closed),
        "const_width": num(_get(e, "const_width", 0.0)),
        "elevation": num(_get(e, "elevation", 0.0)),
    }
    bulges = [num(p[2]) for p in pts]
    if any(bulges):
        props["bulges"] = bulges
    return props


def _polyline(e: Any) -> Props:
    verts = list(e.vertices)
    props: Props = {
        "mode": e.get_mode(),
        "closed": bool(e.is_closed),
        "vertices": [point(v.dxf.location) for v in verts if not v.is_face_record],
    }
    bulges = [num(_get(v, "bulge", 0.0)) for v in verts]
    if any(bulges):
        props["bulges"] = bulges
    faces = [[int(_get(v, f"vtx{i}", 0)) for i in range(4)] for v in verts if v.is_face_record]
    if faces:
        props["faces"] = faces
    return props


def _spline(e: Any) -> Props:
    return {
        "degree": int(_get(e, "degree", 3)),
        "closed": bool(e.closed),
        "control_points": [point(p) for p in e.control_points],
        "fit_points": [point(p) for p in e.fit_points],
        "knots": [num(k) for k in e.knots],
        "weights": [num(w) for w in e.weights],
    }


def _text(e: Any) -> Props:
    props: Props = {
        "text": str(_get(e, "text", "")),
        "insert": point(e.dxf.insert),
        "height": num(_get(e, "height", 2.5)),
        "rotation": angle(_get(e, "rotation", 0.0)),
        "style": str(_get(e, "style", "Standard")),
        "width": num(_get(e, "width", 1.0)),
        "oblique": angle(_get(e, "oblique", 0.0)),
        "halign": int(_get(e, "halign", 0)),
        "valign": int(_get(e, "valign", 0)),
    }
    if props["halign"] or props["valign"]:
        props["align_point"] = point(_get(e, "align_point", e.dxf.insert))
    if e.dxftype() in ("ATTRIB", "ATTDEF"):
        props = {"tag": str(_get(e, "tag", "")), **props}
    return props


def _mtext(e: Any) -> Props:
    return {
        "text": str(e.text),
        "insert": point(e.dxf.insert),
        "char_height": num(_get(e, "char_height", 2.5)),
        "width": num(_get(e, "width", 0.0)),
        "rotation": angle(e.get_rotation()),
        "attachment_point": int(_get(e, "attachment_point", 1)),
        "style": str(_get(e, "style", "Standard")),
    }


def _insert(e: Any) -> Props:
    attribs: Dict[str, str] = {}
    for attrib in e.attribs:
        tag = str(_get(attrib, "tag", ""))
        key, n = tag, 2
        while key in attribs:  # duplicate tags are legal in DXF
            key, n = f"{tag}#{n}", n + 1
        attribs[key] = str(_get(attrib, "text", ""))
    props: Props = {
        "name": str(e.dxf.name),
        "insert": point(e.dxf.insert),
        "xscale": num(_get(e, "xscale", 1.0)),
        "yscale": num(_get(e, "yscale", 1.0)),
        "zscale": num(_get(e, "zscale", 1.0)),
        "rotation": angle(_get(e, "rotation", 0.0)),
    }
    if attribs:
        props["attribs"] = attribs
    if e.mcount > 1:  # MINSERT grid
        for name, default in (("column_count", 1), ("row_count", 1), ("column_spacing", 0.0), ("row_spacing", 0.0)):
            props[name] = num(_get(e, name, default))
    return props


def _dimension(e: Any) -> Props:
    try:
        measured = e.get_measurement()
    except Exception:  # incomplete definition points
        measured = None
    if isinstance(measured, (int, float)):
        measurement: Any = num(measured)
    else:
        measurement = point(measured) if measured is not None else None
    props: Props = {
        "measurement": measurement,
        "text_override": str(_get(e, "text", "")) or "<>",
        "dimtype": int(e.dimtype),
    }
    for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4", "defpoint5"):
        if e.dxf.hasattr(name):
            props[name] = point(e.dxf.get(name))
    props["dimstyle"] = str(_get(e, "dimstyle", "Standard"))
    return props


def _hatch(e: Any) -> Props:
    try:
        boundaries = [[point(v) for v in p.control_vertices()] for p in ezpath.from_hatch(e)]
    except Exception:  # broken boundary data: compare the remaining attributes
        boundaries = []
    return {
        "pattern_name": str(_get(e, "pattern_name", "")),
        "solid_fill": int(_get(e, "solid_fill", 0)),
        "pattern_scale": num(_get(e, "pattern_scale", 1.0)),
        "pattern_angle": angle(_get(e, "pattern_angle", 0.0)),
        "boundaries": boundaries,
    }


def _point(e: Any) -> Props:
    return {"location": point(e.dxf.location)}


def _quad(e: Any) -> Props:
    props: Props = {f"vtx{i}": point(_get(e, f"vtx{i}", (0.0, 0.0, 0.0))) for i in range(4)}
    if e.dxftype() == "3DFACE":
        props["invisible_edges"] = int(_get(e, "invisible_edges", 0))
    return props


def _plain(value: Any) -> Any:
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return num(value)
    try:
        return point(value)
    except (TypeError, ValueError, IndexError):
        return str(value)


def _generic(e: Any) -> Props:
    """Fallback for all other entity types: their raw DXF attributes."""
    attribs = e.dxf.all_existing_dxf_attribs()
    return {k: _plain(v) for k, v in sorted(attribs.items()) if k not in _SKIP_GENERIC}


# fmt: off
EXTRACTORS: Dict[str, Callable[[Any], Props]] = {
    "LINE": _line, "CIRCLE": _circle, "ARC": _arc, "ELLIPSE": _ellipse, "SPLINE": _spline,
    "LWPOLYLINE": _lwpolyline, "POLYLINE": _polyline, "HATCH": _hatch, "POINT": _point,
    "TEXT": _text, "ATTRIB": _text, "ATTDEF": _text, "MTEXT": _mtext, "INSERT": _insert,
    "DIMENSION": _dimension, "SOLID": _quad, "TRACE": _quad, "3DFACE": _quad,
}
# fmt: on


def geometry_props(entity: Any) -> Props:
    """Type specific properties (geometry, text, block name, attributes ...)."""
    extractor = EXTRACTORS.get(entity.dxftype(), _generic)
    try:
        return extractor(entity)
    except Exception:  # malformed entity: fall back to its raw attributes
        return _generic(entity)


def common_props(entity: Any) -> Props:
    """Display properties shared by all entities (color, linetype, lineweight ...)."""
    props: Props = {
        "color": int(_get(entity, "color", 256)),
        "linetype": str(_get(entity, "linetype", "BYLAYER")),
        "lineweight": int(_get(entity, "lineweight", -1)),
        "ltscale": num(_get(entity, "ltscale", 1.0)),
    }
    for name in OPTIONAL_COMMON:
        value = entity.dxf.get(name)
        if value is not None:
            props[name] = int(value)
    return props


def layer_props(layer: Any) -> Props:
    """Comparable properties of a LAYER table entry."""
    props: Props = {
        "color": int(layer.color),
        "on": not layer.is_off(),
        "frozen": bool(layer.is_frozen()),
        "locked": bool(layer.is_locked()),
        "linetype": str(_get(layer, "linetype", "Continuous")),
        "lineweight": int(_get(layer, "lineweight", -3)),
        "plot": bool(_get(layer, "plot", 1)),
    }
    true_color = layer.dxf.get("true_color")
    if true_color is not None:
        props["true_color"] = int(true_color)
    return props


def named_blocks(doc: Any) -> List[Any]:
    """Block definitions worth comparing: no anonymous (``*D1`` ...), layout or XREF blocks."""
    return [b for b in doc.blocks if not b.name.startswith("*") and not (b.block is not None and b.block.is_xref)]


def base_point(block_layout: Any) -> Point:
    block = block_layout.block
    return point(block.dxf.base_point) if block is not None else (0.0, 0.0, 0.0)


def freeze(value: Any, ndigits: int) -> Hashable:
    """A hashable, rounded copy of a property value, used as a matching key."""
    if isinstance(value, float):
        r = round(value, ndigits)
        return 0.0 if r == 0 else r
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v, ndigits) for v in value)
    if isinstance(value, dict):
        return tuple(
            (k, freeze(v.upper() if k in CASE_INSENSITIVE and isinstance(v, str) else v, ndigits))
            for k, v in sorted(value.items())
        )
    return value


def values_differ(a: Any, b: Any, tol: float, ignore_case: bool = False) -> bool:
    """Compare two property values; numbers (also inside points/lists) use ``tol``."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a != b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) > tol
    if isinstance(a, str) and isinstance(b, str):
        return a.upper() != b.upper() if ignore_case else a != b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) != len(b) or any(values_differ(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() != b.keys() or any(values_differ(a[k], b[k], tol) for k in a)
    return a != b


def _ends(name: str) -> Callable[[Props], List[Any]]:
    def keys(p: Props) -> List[Any]:
        seq = p.get(name) or []
        return [seq[0], seq[-1]] if seq else []

    return keys


def _insert_keys(p: Props) -> List[Any]:
    name = str(p.get("name", "")).upper()
    return [(name, p.get("insert")), (name, p["attribs"]) if p.get("attribs") else None]


def _keys(*names: str) -> Callable[[Props], List[Any]]:
    return lambda p: [p.get(name) for name in names]


# fmt: off
#: Looser keys used to pair leftover entities as "modified" (each key must be unique).
SIMILARITY: Dict[str, Callable[[Props], List[Any]]] = {
    "LINE": _keys("start", "end"), "CIRCLE": _keys("center"), "ARC": _keys("center"), "ELLIPSE": _keys("center"),
    "LWPOLYLINE": _ends("vertices"), "POLYLINE": _ends("vertices"),
    "SPLINE": lambda p: _ends("control_points")(p) or _ends("fit_points")(p),
    "TEXT": _keys("insert", "text"), "MTEXT": _keys("insert", "text"), "ATTDEF": _keys("tag"),
    "INSERT": _insert_keys,
    "DIMENSION": lambda p: [(p.get("dimtype"), p.get("defpoint2")), (p.get("dimtype"), p.get("defpoint3"))],
    "SOLID": _keys("vtx0"), "TRACE": _keys("vtx0"), "3DFACE": _keys("vtx0"),
}
# fmt: on


def similarity_keys(dxftype: str, props: Props, ndigits: int) -> List[Optional[Hashable]]:
    """Frozen similarity keys for an entity, ``None`` where a key is unavailable."""
    try:
        raw = SIMILARITY[dxftype](props) if dxftype in SIMILARITY else []
    except (KeyError, IndexError, TypeError):
        return []
    missing = [k is None or (isinstance(k, tuple) and any(part is None for part in k)) for k in raw]
    return [None if gap else freeze(key, ndigits) for key, gap in zip(raw, missing)]
