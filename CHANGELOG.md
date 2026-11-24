# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-24

First public release.

### Added

- `dxf-diff OLD NEW` command: compares the modelspace (and with `--layouts` the
  paperspace layouts) of two DXF files and classifies every entity as added,
  removed, modified or unchanged.
- Entity matching by handle, then by geometric fingerprint, then (for files with
  unrelated handles) by similarity; `--match auto|handle|geometry`.
- Dedicated comparison of LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, ELLIPSE,
  SPLINE, TEXT, MTEXT, ATTRIB/ATTDEF, INSERT (including attribute values and
  MINSERT grids), DIMENSION (measurement and text override), HATCH, POINT,
  SOLID, TRACE and 3DFACE; generic attribute comparison for all other types.
- Layer table changes (color, linetype, lineweight, on/off, frozen, locked, plot)
  and block definition changes.
- Options `--tolerance`, `--layer`, `--ignore-layer`, `--ignore-props`.
- Outputs: colored terminal summary (only on a TTY), `--json`, `--html`
  (self-contained report with an interactive SVG overlay), `--png` (with the
  optional `png` extra) and `--open`.
- `diff`-style exit status: 0 = no differences, 1 = differences, 2 = error.
- `dxf-diff --textconv FILE` for readable `git diff` output on `.dxf` files.
- Python API: `compare()`, `DiffResult`, `EntityChange`, `LayerChange`,
  `BlockChange`, `textconv()`, `write_html()`, `write_png()`.
- Example drawings of a storage tank (REV A / REV B) and a generated report.

[0.1.0]: https://github.com/Shahnawaz75/dxf-diff/releases/tag/v0.1.0
