"""A stable, sorted, normalized text dump of a drawing, made for ``git diff``.

Handles, timestamps and GUIDs are left out and every section is sorted, so two
saves of the same drawing produce the same text, and a real edit shows up as a
small, readable change in ``git diff`` (see docs/git-integration.md).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .engine import Source, load_drawing
from .extract import COMMON_DEFAULTS, base_point, common_props, geometry_props, layer_props, named_blocks

HEADER_LINE = "# dxf-diff textconv 1"


class _Formatter:
    def __init__(self, precision: int) -> None:
        self.precision = precision

    def num(self, value: float) -> str:
        text = f"{value:.{self.precision}f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text

    def value(self, v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, float):
            return self.num(v)
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, tuple):
            coords = v[:2] if len(v) == 3 and v[2] == 0 else v
            return "(" + ",".join(self.value(c) for c in coords) + ")"
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k}={self.value(x)}" for k, x in sorted(v.items())) + "}"
        if isinstance(v, list):
            return "[" + ", ".join(self.value(x) for x in v) + "]"
        return "none" if v is None else json.dumps(str(v))

    def inline(self, props: Dict[str, Any]) -> str:
        return " ".join(f"{k}={self.value(v)}" for k, v in props.items())

    def sequence(self, name: str, items: List[Any]) -> List[str]:
        lines: List[str] = []
        for i, item in enumerate(items):
            if isinstance(item, list) and item and isinstance(item[0], tuple):  # e.g. hatch boundaries
                lines.extend(f"{name}[{i}][{j}]={self.value(sub)}" for j, sub in enumerate(item))
            else:
                lines.append(f"{name}[{i}]={self.value(item)}")
        return lines


def _records(entities: Iterable[Any], fmt: _Formatter) -> List[str]:
    records: List[List[str]] = []
    for entity in entities:
        props: Dict[str, Any] = {"layer": str(entity.dxf.get("layer", "0"))}
        for key, value in common_props(entity).items():  # only non-default display properties
            if str(value).upper() != str(COMMON_DEFAULTS.get(key, "")).upper():
                props[key] = value
        geometry = geometry_props(entity)
        # point lists (vertices, control points, boundaries) get one line per item, so a moved vertex is a 1-line diff
        multiline = {k for k, v in geometry.items() if isinstance(v, list) and v and isinstance(v[0], (tuple, list))}
        inline = {k: v for k, v in geometry.items() if k not in multiline}
        record = [f"{entity.dxftype()} {fmt.inline({**props, **inline})}"]
        for key in (k for k in geometry if k in multiline):  # keep the property order (sets are unordered)
            record.extend("  " + line for line in fmt.sequence(key, geometry[key]))
        records.append(record)
    records.sort()
    return [line for record in records for line in record]


def textconv(source: Source, precision: int = 6) -> str:
    """Return the normalized text dump of a DXF file (what ``dxf-diff --textconv`` prints)."""
    doc, _name = load_drawing(source)
    fmt = _Formatter(precision)
    lines = [HEADER_LINE, f"HEADER $ACADVER={doc.dxfversion} $INSUNITS={doc.header.get('$INSUNITS', 0)}"]
    for layer in sorted(doc.layers, key=lambda layer: layer.dxf.name.upper()):
        lines.append(f"LAYER {fmt.value(layer.dxf.name)} {fmt.inline(layer_props(layer))}")
    for block in sorted(named_blocks(doc), key=lambda b: b.name.upper()):
        lines.append(f"BLOCK {fmt.value(block.name)} base_point={fmt.value(base_point(block))}")
        lines.extend("  " + line for line in _records(block, fmt))
    for name in doc.layouts.names_in_taborder():
        lines.append(f"LAYOUT {fmt.value(name)}")
        lines.extend("  " + line for line in _records(doc.layouts.get(name), fmt))
    return "\n".join(lines) + "\n"
