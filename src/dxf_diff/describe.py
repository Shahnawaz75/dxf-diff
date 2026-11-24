"""Short, human-readable descriptions of entities and of their changes."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence

from ezdxf.tools.text import plain_mtext

from .model import PropertyChange

ACI_NAMES = {
    0: "BYBLOCK",
    1: "red",
    2: "yellow",
    3: "green",
    4: "cyan",
    5: "blue",
    6: "magenta",
    7: "white",
    256: "BYLAYER",
}
DIMTYPES = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular", 6: "ordinate"}
LAYER_FLAGS = {
    "on": ("turned on", "turned off"),
    "frozen": ("frozen", "thawed"),
    "locked": ("locked", "unlocked"),
    "plot": ("plot on", "plot off"),
}
_SINGULAR = {"vertices": "vertex", "control_points": "control point", "fit_points": "fit point"}
MAX_PHRASES = 3


def fmt_num(value: float, places: int = 4) -> str:
    """Format a number compactly: ``10.0 -> '10'``, ``0.25 -> '0.25'``."""
    text = f"{float(value):.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def is_point(value: Any) -> bool:
    return isinstance(value, tuple) and len(value) in (2, 3) and all(isinstance(v, float) for v in value)


def _is_point_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(is_point(v) for v in value)


def fmt_point(p: Sequence[float], places: int = 4) -> str:
    """``(10,0)`` for 2D points, ``(10,0,5)`` when z is not zero."""
    coords = p if len(p) == 3 and p[2] != 0.0 else p[:2]
    return "(" + ",".join(fmt_num(c, places) for c in coords) + ")"


def _pair(fmt: Callable[[Any, int], str], old: Any, new: Any) -> str:
    """``old -> new``, with more decimals when 4 would make both look the same."""
    for places in (4, 6, 8, 10):
        a, b = fmt(old, places), fmt(new, places)
        if a != b:
            break
    return f"{a} -> {b}"


def fmt_color(value: int) -> str:
    """ACI color number with its name, e.g. ``1 (red)`` or ``BYLAYER``."""
    if value in (0, 256):
        return ACI_NAMES[value]
    name = ACI_NAMES.get(value)
    return f"{value} ({name})" if name else str(value)


def quote(text: Any, limit: int = 48) -> str:
    text = " / ".join(str(text).splitlines()) if text else ""
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"'{text}'"


def fmt_value(name: str, value: Any) -> str:
    if name in ("color", "true_color") and isinstance(value, int) and not isinstance(value, bool):
        return fmt_color(value) if name == "color" else f"#{value:06X}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return fmt_num(value)
    if isinstance(value, str):
        return quote(value)
    if is_point(value):
        return fmt_point(value)
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    return "none" if value is None else str(value)


def _attribs_phrase(old: Dict[str, str], new: Dict[str, str]) -> str:
    parts = []
    for tag in list(old) + [t for t in new if t not in old]:
        if tag not in new:
            parts.append(f"attribute {tag} removed")
        elif tag not in old:
            parts.append(f"attribute {tag} added {quote(new[tag])}")
        elif old[tag] != new[tag]:
            parts.append(f"attribute {tag} {quote(old[tag])} -> {quote(new[tag])}")
    return ", ".join(parts)


def _points_phrase(name: str, old: List[Any], new: List[Any], tol: float) -> str:
    if len(old) != len(new):
        return f"{name.replace('_', ' ')} {len(old)} -> {len(new)}"
    moved = [i for i, (a, b) in enumerate(zip(old, new)) if any(abs(x - y) > tol for x, y in zip(a, b))]
    if len(moved) == 1:
        i = moved[0]
        return f"{_SINGULAR.get(name, name)} {i} moved {_pair(fmt_point, old[i], new[i])}"
    return f"{len(moved)} {name.replace('_', ' ')} moved"


def phrase(change: PropertyChange, tol: float = 1e-6, dxftype: str = "") -> str:
    """Describe one property change, e.g. ``end moved (10,0) -> (12,0)``."""
    name, old, new = change.name, change.old, change.new
    if name == "text" and isinstance(old, str) and isinstance(new, str):
        if dxftype == "MTEXT":
            old, new = plain_mtext(old), plain_mtext(new)
        return f"{quote(old)} -> {quote(new)}"
    if name == "attribs" and isinstance(old, dict) and isinstance(new, dict):
        return _attribs_phrase(old, new)
    if name in LAYER_FLAGS and isinstance(new, bool):
        return LAYER_FLAGS[name][0 if new else 1]
    if is_point(old) and is_point(new):
        return f"{name} moved {_pair(fmt_point, old, new)}"
    if _is_point_list(old) and _is_point_list(new):
        return _points_phrase(name, old, new, tol)
    if isinstance(old, list) and isinstance(new, list) and len(old) != len(new):
        return f"{name.replace('_', ' ')} {len(old)} -> {len(new)}"
    if isinstance(old, list) or isinstance(new, list):
        return f"{name.replace('_', ' ')} changed"
    if old is None:
        return f"{name} set to {fmt_value(name, new)}"
    if new is None:
        return f"{name} removed (was {fmt_value(name, old)})"
    if isinstance(old, float) and isinstance(new, float):
        return f"{name} {_pair(fmt_num, old, new)}"
    return f"{name} {fmt_value(name, old)} -> {fmt_value(name, new)}"


def join_phrases(phrases: List[str]) -> str:
    text = ", ".join(phrases[:MAX_PHRASES])
    if len(phrases) > MAX_PHRASES:
        text += f" (+{len(phrases) - MAX_PHRASES} more)"
    return text


def describe_modification(dxftype: str, props: Dict[str, Any], changes: Sequence[PropertyChange], tol: float) -> str:
    """One line for a modified entity, e.g. ``TEXT 'REV A' -> 'REV B'``."""
    prefix = f"INSERT {props.get('name', '')}".rstrip() if dxftype == "INSERT" else dxftype
    return f"{prefix} {join_phrases([phrase(c, tol, dxftype) for c in changes])}"


def describe_layer(changes: Sequence[PropertyChange], tol: float) -> str:
    return join_phrases([phrase(c, tol) for c in changes])


def summarize(dxftype: str, p: Dict[str, Any]) -> str:
    """One line for an added or removed entity, e.g. ``CIRCLE r=5 at (20,20)``."""
    try:
        if dxftype == "LINE":
            return f"LINE {fmt_point(p['start'])} to {fmt_point(p['end'])}"
        if dxftype in ("CIRCLE", "ARC"):
            text = f"{dxftype} r={fmt_num(p['radius'])} at {fmt_point(p['center'])}"
            if dxftype == "ARC":
                text += f" {fmt_num(p['start_angle'])}-{fmt_num(p['end_angle'])} deg"
            return text
        if dxftype == "ELLIPSE":
            return f"ELLIPSE at {fmt_point(p['center'])} ratio {fmt_num(p['ratio'])}"
        if dxftype in ("LWPOLYLINE", "POLYLINE"):
            verts = p["vertices"]
            closed = ", closed" if p.get("closed") else ""
            return f"{dxftype} {len(verts)} vertices{closed}, first {fmt_point(verts[0])}"
        if dxftype == "SPLINE":
            return f"SPLINE degree {p['degree']}, {len(p['control_points'] or p['fit_points'])} points"
        if dxftype in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            text = str(plain_mtext(p["text"])) if dxftype == "MTEXT" else p["text"]
            return f"{dxftype} {quote(text)} at {fmt_point(p['insert'])}"
        if dxftype == "INSERT":
            attribs = " ".join(f"{k}={quote(v, 24)}" for k, v in list(p.get("attribs", {}).items())[:3])
            return f"INSERT {p['name']} at {fmt_point(p['insert'])} {attribs}".rstrip()
        if dxftype == "DIMENSION":
            m = p.get("measurement")
            value = fmt_num(m) if isinstance(m, float) else ""
            override = "" if p.get("text_override") == "<>" else f" text {quote(p.get('text_override'))}"
            return f"DIMENSION {DIMTYPES.get(p['dimtype'], '')} {value}".rstrip() + override
        if dxftype == "HATCH":
            return f"HATCH {p['pattern_name'] or 'SOLID'}, {len(p['boundaries'])} boundary path(s)"
        if dxftype == "POINT":
            return f"POINT at {fmt_point(p['location'])}"
        if "vtx0" in p:
            return f"{dxftype} at {fmt_point(p['vtx0'])}"
    except (KeyError, IndexError, TypeError):
        pass
    return dxftype
