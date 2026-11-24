"""Self-contained HTML report with an interactive SVG overlay of both drawings."""

from __future__ import annotations

import math
import os
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from ._version import __version__
from .model import ChangeKind, DiffResult
from .render import Box, Scene, SceneItem, Shape, build_scene

_CHUNK = 4000  # unchanged shapes merged into one <path> element
_STATUS_CLASS = {"removed": "ent removed", "old": "ent modified o", "new": "ent modified n", "added": "ent added"}
_STATUS_ORDER = {"removed": 0, "old": 1, "new": 2, "added": 3}


def _num(value: float, nd: int) -> str:
    text = f"{value:.{nd}f}"
    if nd:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _d(cmds: Sequence[Tuple], nd: int) -> str:
    """SVG path data; y is negated because SVG's y axis points down."""
    out = []
    for c in cmds:
        if c[0] == "Z":
            out.append("Z")
            continue
        coords = c[1:]
        pairs = [f"{_num(coords[k], nd)},{_num(-coords[k + 1], nd)}" for k in range(0, len(coords), 2)]
        out.append(c[0] + " ".join(pairs) + ("h0" if c[0] == "M" and len(cmds) == 1 else ""))
    return "".join(out)


def _texts(shape: Shape, nd: int) -> List[str]:
    size = _num(shape.height * 1.4, nd + 2)
    anchor = "" if shape.anchor == "start" else f' text-anchor="{shape.anchor}"'
    out = []
    for x, y, text in shape.lines:
        if not text.strip():
            continue
        sx, sy = _num(x, nd), _num(-y, nd)
        rotate = f' transform="rotate({_num(-shape.rotation, 3)} {sx} {sy})"' if abs(shape.rotation) > 1e-9 else ""
        out.append(f'<text x="{sx}" y="{sy}" font-size="{size}"{anchor}{rotate}>{escape(text)}</text>')
    return out


def _item_svg(item: SceneItem, nd: int) -> str:
    paths, hit = [], []
    for shape in item.shapes:
        if shape.kind == "text":
            paths.extend(_texts(shape, nd))
            continue
        d = _d(shape.cmds, nd)
        cls = {"fill": ' class="f"', "dot": ' class="d"'}.get(shape.kind, "")
        paths.append(f'<path{cls} d="{d}"/>')
        hit.append(d)
    if hit:
        paths.append(f'<path class="hit" d="{"".join(hit)}"/>')
    return f'<g class="{_STATUS_CLASS[item.status]}" data-id="{item.index}">{"".join(paths)}</g>'


def _unchanged_svg(items: List[SceneItem], nd: int) -> str:
    groups: Dict[str, List[str]] = {"path": [], "fill": [], "dot": []}
    texts: List[str] = []
    for item in items:
        for shape in item.shapes:
            if shape.kind == "text":
                texts.extend(_texts(shape, nd))
            else:
                groups[shape.kind].append(_d(shape.cmds, nd))
    out = ['<g class="u">']
    for kind, ds in groups.items():
        cls = {"fill": ' class="f"', "dot": ' class="d"'}.get(kind, "")
        for start in range(0, len(ds), _CHUNK):
            out.append(f'<path{cls} d="{"".join(ds[start : start + _CHUNK])}"/>')
    out.extend(texts)
    out.append("</g>")
    return "".join(out)


def _svg(scene: Scene, nd: int, viewbox: Box) -> str:
    vb = " ".join(_num(v, nd) for v in viewbox)
    unchanged = [it for it in scene.items if it.status == "unchanged"]
    changed = sorted((it for it in scene.items if it.status != "unchanged"), key=lambda it: _STATUS_ORDER[it.status])
    body = _unchanged_svg(unchanged, nd) + "".join(_item_svg(it, nd) for it in changed)
    return f'<svg id="view" xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" preserveAspectRatio="xMidYMid meet">{body}</svg>'


def _bboxes(scene: Scene) -> Dict[int, Box]:
    boxes: Dict[int, Box] = {}
    for item in scene.items:
        box = item.bbox() if item.index >= 0 else None
        if box is None:
            continue
        if item.index in boxes:
            a = boxes[item.index]
            box = (min(a[0], box[0]), min(a[1], box[1]), max(a[2], box[2]), max(a[3], box[3]))
        boxes[item.index] = box
    return boxes


def _badge(kind: ChangeKind) -> str:
    return f'<span class="k {kind.value}">{kind.value}</span>'


def _entity_rows(result: DiffResult, boxes: Dict[int, Box], nd: int) -> str:
    rows = []
    for index, c in enumerate(result.changes):
        attrs = f' data-id="{index}"'
        box = boxes.get(index)
        if box:  # x y w h in SVG coordinates (y flipped)
            values = (box[0], -box[3], box[2] - box[0], box[3] - box[1])
            attrs += f' data-bbox="{" ".join(_num(v, nd) for v in values)}"'
        handle = escape(c.handle)
        if c.old_handle and c.new_handle and c.old_handle != c.new_handle:  # matched by geometry or similarity
            handle = f"{escape(c.old_handle)} &rarr; {escape(c.new_handle)}"
        space = "" if c.space == "Model" else f' <span class="sp">({escape(c.space)})</span>'
        rows.append(
            f"<tr{attrs}><td>{index + 1}</td><td>{_badge(c.kind)}</td><td>{escape(c.dxftype)}</td>"
            f'<td>{escape(c.layer)}{space}</td><td class="h">{handle}</td><td>{escape(c.description)}</td></tr>'
        )
    return "".join(rows) or '<tr><td colspan="6" class="none">No entity changes.</td></tr>'


def _table_section(title: str, changes: Sequence) -> str:
    if not changes:
        return ""
    rows = []
    for c in changes:
        details = "".join(f"<li>{escape(d)}</li>" for d in getattr(c, "details", []))
        details = f"<ul>{details}</ul>" if details else ""
        rows.append(
            f"<tr><td>{_badge(c.kind)}</td><td>{escape(c.name)}</td><td>{escape(c.description)}{details}</td></tr>"
        )
    return (
        f"<h2>{title} ({len(changes)})</h2><table><thead><tr><th>Change</th><th>Name</th>"
        f"<th>Description</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _card(cls: str, count: int, label: str) -> str:
    return f'<div class="card {cls}"><b>{count}</b>{label}</div>'


def render_html(result: DiffResult, title: Optional[str] = None, max_unchanged: int = 60000) -> str:
    """Return the complete HTML report as a string."""
    scene = build_scene(result, max_unchanged=max_unchanged)
    minx, miny, maxx, maxy = scene.extents
    size = max(maxx - minx, maxy - miny, 1e-9)
    nd = max(0, min(8, 5 - math.floor(math.log10(size))))
    pad = size * 0.03
    viewbox = (minx - pad, -(maxy + pad), maxx - minx + 2 * pad, maxy - miny + 2 * pad)
    counts = result.summary()["entities"]
    old_name, new_name = os.path.basename(result.old_path), os.path.basename(result.new_path)
    notes = []
    if scene.skipped:
        notes.append(f"{scene.skipped} unchanged entities are not drawn, to keep this report responsive.")
    if any(c.space != "Model" for c in result.changes):
        notes.append("Changes in paperspace layouts are listed in the table but not drawn.")
    cards = "".join(_card(k, counts[k], k) for k in ("added", "removed", "modified", "unchanged"))
    cards += _card("table", len(result.layers), "layer changes") + _card("table", len(result.blocks), "block changes")
    replacements = {
        "%%TITLE%%": escape(title or f"dxf-diff: {old_name} vs {new_name}"),
        "%%OLD%%": escape(result.old_path),
        "%%NEW%%": escape(result.new_path),
        "%%CARDS%%": cards,
        "%%SVG%%": _svg(scene, nd, viewbox),
        "%%NOTES%%": "".join(f'<p class="note">{escape(n)}</p>' for n in notes),
        "%%COUNT%%": str(len(result.changes)),
        "%%ROWS%%": _entity_rows(result, _bboxes(scene), nd),
        "%%LAYERS%%": _table_section("Layer changes", result.layers),
        "%%BLOCKS%%": _table_section("Block definition changes", result.blocks),
        "%%TOLERANCE%%": escape(str(result.options.get("tolerance", ""))),
        "%%VERSION%%": __version__,
    }
    html = TEMPLATE
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


def write_html(result: DiffResult, path: Union[str, Path], title: Optional[str] = None) -> None:
    """Write the HTML report to ``path`` (UTF-8, LF line endings, no external assets)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(render_html(result, title=title))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="dxf-diff %%VERSION%%">
<title>%%TITLE%%</title>
<style>
:root{--add:#1a7f37;--rem:#cf222e;--mod:#e8590c;--modold:#f59f00;--unch:#c3c9d1;--ink:#1f2328;--mute:#59636e;--line:#d1d9e0;--bg:#f6f8fa}
*{box-sizing:border-box}
body{margin:0;font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{padding:14px 20px 10px;background:#fff;border-bottom:1px solid var(--line)}
h1{font-size:19px;margin:0 0 6px}h1 small{font-weight:400;color:var(--mute);font-size:13px;margin-left:6px}
h2{font-size:15px;margin:22px 0 8px}
.files{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font:12.5px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;word-break:break-all}
.files b{font-family:system-ui,sans-serif;font-size:11px;letter-spacing:.04em;align-self:center}
.files .o{color:var(--rem)}.files .n{color:var(--add)}
main{padding:12px 20px 24px}
.cards{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 12px}
.card{background:#fff;border:1px solid var(--line);border-left-width:4px;border-radius:6px;padding:5px 14px 6px;min-width:104px;color:var(--mute);font-size:12.5px}
.card b{display:block;font-size:21px;line-height:1.2;color:var(--ink)}
.card.added{border-left-color:var(--add)}.card.removed{border-left-color:var(--rem)}.card.modified{border-left-color:var(--mod)}.card.unchanged{border-left-color:var(--unch)}.card.table{border-left-color:#8250df}
.viewer{background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.bar{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;padding:7px 12px;border-bottom:1px solid var(--line);font-size:13px}
.bar label{display:inline-flex;align-items:center;gap:4px;cursor:pointer}
.sw{display:inline-block;width:22px;border-top:3px solid;vertical-align:middle;margin-right:5px}
.sw.dash{border-top-style:dashed}
.legend span{white-space:nowrap;margin-right:12px}
.bar button{font:inherit;padding:2px 12px;border:1px solid var(--line);border-radius:6px;background:#f6f8fa;cursor:pointer}
.hint{color:var(--mute);font-size:12px;margin-left:auto}
#view{display:block;width:100%;height:62vh;min-height:320px;background:#fff;cursor:grab;user-select:none;touch-action:none}
#view path{fill:none;stroke:currentColor;stroke-width:1.1px;vector-effect:non-scaling-stroke;stroke-linecap:round;stroke-linejoin:round}
#view text{fill:currentColor;font-family:Arial,Helvetica,sans-serif;white-space:pre}
#view path.f{fill:currentColor;fill-opacity:.14}
#view path.d{stroke-width:5px}
#view .u{color:var(--unch);pointer-events:none}
#view .removed{color:var(--rem)}#view .added{color:var(--add)}#view .modified.n{color:var(--mod)}
#view .modified.o{color:var(--modold)}#view .modified.o path{stroke-dasharray:6 4}#view .modified.o text{opacity:.75}
#view path.hit{stroke:transparent;stroke-width:12px;stroke-dasharray:none;fill:none}
#view .ent{cursor:pointer}
#view .ent.hov path:not(.hit),#view .ent.sel path:not(.hit){stroke-width:3.2px}
#view .ent.hov text,#view .ent.sel text{font-weight:700}
#view .ent.sel{animation:blink .9s ease-in-out 2}
@keyframes blink{50%{opacity:.2}}
#view.hide-u .u,#view.hide-old .removed,#view.hide-old .o,#view.hide-new .added,#view.hide-new .n{display:none}
.tools{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap}
input[type=search]{font:inherit;padding:4px 9px;border:1px solid var(--line);border-radius:6px;min-width:240px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);font-size:13px}
th,td{padding:5px 9px;border-bottom:1px solid #eaeef2;text-align:left;vertical-align:top}
th{background:#f3f5f7;font-weight:600}
td ul{margin:4px 0 0;padding-left:18px;color:var(--mute)}
tr[data-id]{cursor:pointer}tr[data-id]:hover,tr.hov{background:#fff8c5}tr.sel{background:#ffe9a8}
td.h{font-family:ui-monospace,Consolas,monospace;color:var(--mute);white-space:nowrap}
td.none{color:var(--mute);text-align:center;padding:14px}
.k{display:inline-block;min-width:68px;text-align:center;padding:0 7px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
.k.added{background:var(--add)}.k.removed{background:var(--rem)}.k.modified{background:var(--mod)}
.sp,.note{color:var(--mute);font-size:12.5px}
footer{color:var(--mute);font-size:12px;padding:0 20px 22px}footer a{color:inherit}
@media (max-width:700px){main{padding:10px}header{padding:12px 10px}#view{height:52vh}.hint{display:none}}
</style>
</head>
<body>
<header>
<h1>dxf-diff report<small>%%COUNT%% entity changes</small></h1>
<div class="files"><b class="o">OLD</b><span>%%OLD%%</span><b class="n">NEW</b><span>%%NEW%%</span></div>
</header>
<main>
<div class="cards">%%CARDS%%</div>
<div class="viewer">
<div class="bar">
<span class="legend"><span><i class="sw" style="color:var(--rem)"></i>removed</span><span><i class="sw" style="color:var(--add)"></i>added</span><span><i class="sw dash" style="color:var(--modold)"></i>modified (old)</span><span><i class="sw" style="color:var(--mod)"></i>modified (new)</span><span><i class="sw" style="color:var(--unch)"></i>unchanged</span></span>
<label><input type="checkbox" data-toggle="u" checked>unchanged</label>
<label><input type="checkbox" data-toggle="old" checked>old</label>
<label><input type="checkbox" data-toggle="new" checked>new</label>
<button type="button" id="fit">Fit</button>
<span class="hint">Wheel: zoom &middot; drag: pan &middot; click: select</span>
</div>
%%SVG%%
</div>
%%NOTES%%
<div class="tools"><h2>Entity changes (%%COUNT%%)</h2><input id="filter" type="search" placeholder="Filter changes..." aria-label="Filter changes"></div>
<table id="changes"><thead><tr><th>#</th><th>Change</th><th>Type</th><th>Layer</th><th>Handle</th><th>Description</th></tr></thead>
<tbody>%%ROWS%%</tbody></table>
%%LAYERS%%
%%BLOCKS%%
</main>
<footer>Generated by dxf-diff %%VERSION%% (tolerance %%TOLERANCE%%) &middot; <a href="https://github.com/Shahnawaz75/dxf-diff">github.com/Shahnawaz75/dxf-diff</a></footer>
<script>
(function () {
  var svg = document.getElementById('view');
  var home = svg.getAttribute('viewBox').split(' ').map(Number), vb = home.slice();
  var drag = null, moved = false, current = null;
  function setVB(b) { vb = b; svg.setAttribute('viewBox', b.join(' ')); }
  function toSvg(x, y) { return new DOMPoint(x, y).matrixTransform(svg.getScreenCTM().inverse()); }
  function unitsPerPixel() { var r = svg.getBoundingClientRect(); return Math.max(vb[2] / r.width, vb[3] / r.height); }
  svg.addEventListener('wheel', function (e) {
    e.preventDefault();
    var p = toSvg(e.clientX, e.clientY);
    var k = Math.pow(1.0015, Math.max(-300, Math.min(300, e.deltaY * (e.deltaMode === 1 ? 33 : 1))));
    setVB([p.x - (p.x - vb[0]) * k, p.y - (p.y - vb[1]) * k, vb[2] * k, vb[3] * k]);
  }, { passive: false });
  svg.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, vb: vb.slice(), s: unitsPerPixel() }; moved = false;
    svg.style.cursor = 'grabbing';
  });
  window.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    if (moved) setVB([drag.vb[0] - dx * drag.s, drag.vb[1] - dy * drag.s, drag.vb[2], drag.vb[3]]);
  });
  window.addEventListener('pointerup', function () { drag = null; svg.style.cursor = ''; });
  function mark(id, cls, on) {
    var nodes = document.querySelectorAll('[data-id="' + id + '"]');
    for (var i = 0; i < nodes.length; i++) nodes[i].classList.toggle(cls, on);
  }
  function zoomTo(b) {
    var m = Math.max(b[2], b[3], home[2] * 0.03, home[3] * 0.03) * 0.8;
    setVB([b[0] - m, b[1] - m, b[2] + 2 * m, b[3] + 2 * m]);
  }
  function select(id, fromDrawing) {
    if (current !== null) mark(current, 'sel', false);
    current = id; mark(id, 'sel', true);
    var row = document.querySelector('tr[data-id="' + id + '"]');
    if (!row) return;
    if (fromDrawing) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    else if (row.getAttribute('data-bbox')) zoomTo(row.getAttribute('data-bbox').split(' ').map(Number));
  }
  svg.addEventListener('click', function (e) {
    if (moved) return;
    var g = e.target.closest ? e.target.closest('.ent') : null;
    if (g) select(g.getAttribute('data-id'), true);
  });
  var rows = document.querySelectorAll('tr[data-id]');
  Array.prototype.forEach.call(rows, function (row) {
    var id = row.getAttribute('data-id');
    row.addEventListener('click', function () { select(id, false); });
    row.addEventListener('mouseenter', function () { mark(id, 'hov', true); });
    row.addEventListener('mouseleave', function () { mark(id, 'hov', false); });
  });
  Array.prototype.forEach.call(document.querySelectorAll('input[data-toggle]'), function (box) {
    box.addEventListener('change', function () { svg.classList.toggle('hide-' + box.getAttribute('data-toggle'), !box.checked); });
  });
  document.getElementById('fit').addEventListener('click', function () { setVB(home.slice()); });
  var filter = document.getElementById('filter');
  filter.addEventListener('input', function () {
    var q = filter.value.toLowerCase();
    Array.prototype.forEach.call(rows, function (row) {
      row.style.display = row.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
    });
  });
})();
</script>
</body>
</html>
"""
