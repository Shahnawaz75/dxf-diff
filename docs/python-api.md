---
title: dxf-diff Python API
description: Compare DXF drawings from Python with dxf-diff - compare(), DiffResult, EntityChange, filtering, JSON serialization, HTML and PNG reports and textconv.
---

# Python API

```python
from dxf_diff import compare

result = compare("old.dxf", "new.dxf", tolerance=1e-6)
print(result.summary())
for change in result:
    print(change.kind, change.dxftype, change.layer, change.handle, change.description)
```

Everything below is importable from the `dxf_diff` package.

## `compare(old, new, tolerance=1e-6, *, layers=None, ignore_layers=None, ignore_props=None, layouts=False, match="auto", options=None)`

Compares two drawings and returns a `DiffResult`.

| Argument | Meaning |
| --- | --- |
| `old`, `new` | path of a DXF file (`str` or `pathlib.Path`) or an already loaded `ezdxf` drawing |
| `tolerance` | coordinates, lengths and angles (in degrees) that differ by less are equal |
| `layers` | only compare entities on layers matching these wildcard patterns (case-insensitive) |
| `ignore_layers` | skip entities on layers matching these patterns |
| `ignore_props` | property names to ignore, e.g. `["color", "linetype"]` or `"color,lineweight"`; `color` also covers `true_color`, `linetype` also covers `ltscale` |
| `layouts` | also compare paperspace layouts (default: modelspace only) |
| `match` | `"auto"`, `"handle"` (always trust handles) or `"geometry"` (ignore handles) |
| `options` | a `CompareOptions` object with the same fields; overrides the keyword arguments |

Raises `DxfDiffError` when a file does not exist, is a DWG file or cannot be read. Damaged DXF files are repaired with ezdxf's recover mode and a warning is logged.

## `DiffResult`

| Member | |
| --- | --- |
| `iter(result)` | the entity changes: added, removed and modified entities |
| `entities` | all `EntityChange` records, unchanged entities included |
| `changes`, `added`, `removed`, `modified`, `unchanged` | lists of `EntityChange` |
| `layers` | list of `LayerChange` (only changed layers) |
| `blocks` | list of `BlockChange` (only changed block definitions) |
| `has_changes` | `True` if any entity, layer or block differs |
| `filter(kind=None, dxftype=None, layer=None, space=None)` | `kind` and `dxftype` take one value or a list, `layer` is a wildcard pattern |
| `summary()` | counts, e.g. `{"entities": {"added": 1, "removed": 0, "modified": 2, "unchanged": 40}, "layers": {...}, "blocks": {...}}` |
| `to_dict(include_unchanged=False)` | JSON-ready dict (see below) |
| `to_json(path=None, indent=2, include_unchanged=False)` | JSON string, also written to `path` when given |
| `old_doc`, `new_doc` | the loaded ezdxf drawings |

```python
result.filter(kind="modified", dxftype=["TEXT", "MTEXT"])
result.filter(kind=["added", "removed"], layer="NOZ*")
[c for c in result if c.matched_by == "similarity"]
```

## `EntityChange`

| Field | |
| --- | --- |
| `kind` | `ChangeKind.ADDED`, `REMOVED`, `MODIFIED` or `UNCHANGED` (a `str` enum: `kind == "added"` works) |
| `dxftype`, `layer`, `space` | entity type, layer (NEW side if it exists) and layout name (`"Model"` for modelspace) |
| `old_handle`, `new_handle`, `handle` | handles in OLD / NEW; `handle` is the NEW one if present |
| `description` | one line, e.g. `INSERT TANK-NOZZLE attribute SIZE '4"' -> '6"'` |
| `changes` | list of `PropertyChange(name, old, new)` for modified entities |
| `matched_by` | `"handle"`, `"geometry"` or `"similarity"` for paired entities, `None` otherwise |
| `old_entity`, `new_entity` | the ezdxf entities (or `None`) |

Property values are plain Python values: points are `(x, y, z)` tuples, vertex lists are lists of points, block attributes are a `{tag: text}` dict.

## `LayerChange` and `BlockChange`

Both have `kind`, `name`, `description` and `changes` (a list of `PropertyChange`). `BlockChange.details` lists the changed entities inside the block definition, for example `"modified: CIRCLE radius 1 -> 1.5"`.

## Reports and textconv

```python
from dxf_diff import compare, render_html, textconv, write_html, write_png

result = compare("old.dxf", "new.dxf")
write_html(result, "report.html")  # self-contained HTML with SVG overlay
html = render_html(result)  # the same as a string
write_png(result, "overlay.png")  # needs matplotlib: pip install "dxf-diff[png]"
print(textconv("drawing.dxf"))  # normalized text dump used by git
```

## JSON format

`dxf-diff --json report.json` and `result.to_json()` write:

```json
{
  "format": "dxf-diff-report",
  "format_version": 1,
  "tool": {"name": "dxf-diff", "version": "0.1.0"},
  "old": {"path": "examples/tank_rev_a.dxf", "dxfversion": "AC1032"},
  "new": {"path": "examples/tank_rev_b.dxf", "dxfversion": "AC1032"},
  "options": {"tolerance": 1e-06, "layers": [], "ignore_layers": [], "ignore_props": [], "layouts": false, "match": "auto"},
  "has_changes": true,
  "summary": {
    "entities": {"added": 8, "removed": 5, "modified": 6, "unchanged": 46},
    "layers": {"added": 1, "removed": 0, "modified": 0},
    "blocks": {"added": 0, "removed": 0, "modified": 0}
  },
  "entities": [
    {
      "kind": "modified",
      "dxftype": "INSERT",
      "layer": "NOZZLES",
      "space": "Model",
      "old_handle": "C3",
      "new_handle": "C3",
      "description": "INSERT TANK-NOZZLE attribute SIZE '4\"' -> '6\"'",
      "changes": [
        {"name": "attribs", "old": {"TAG": "N2", "SIZE": "4\"", "RATING": "150#"}, "new": {"TAG": "N2", "SIZE": "6\"", "RATING": "150#"}}
      ],
      "matched_by": "handle"
    }
  ],
  "layers": [
    {"kind": "added", "name": "REVISION", "description": "layer added (color 6 (magenta), linetype Continuous)", "changes": []}
  ],
  "blocks": []
}
```

Unchanged entities are left out unless `include_unchanged=True`. Points are written as `[x, y, z]` lists.
