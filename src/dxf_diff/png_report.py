"""Static PNG image of the overlay (optional, needs ``pip install "dxf-diff[png]"``)."""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .model import DiffResult, DxfDiffError
from .render import Shape, build_scene

#: status -> (color, line style, line width, z-order)
STYLES: Dict[str, Tuple[str, Any, float, int]] = {
    "unchanged": ("#c3c9d1", "-", 0.6, 1),
    "removed": ("#cf222e", "-", 1.3, 2),
    "old": ("#f59f00", (0, (4, 3)), 1.1, 3),
    "new": ("#e8590c", "-", 1.4, 4),
    "added": ("#1a7f37", "-", 1.3, 5),
}
LABELS = {
    "removed": "removed",
    "added": "added",
    "old": "modified (old)",
    "new": "modified (new)",
    "unchanged": "unchanged",
}


def _mpl_path(cmds: Sequence[Tuple[Any, ...]]) -> Any:
    from matplotlib.path import Path as MplPath

    verts: List[Tuple[float, float]] = []
    codes: List[Any] = []
    start = (0.0, 0.0)
    for c in cmds:
        op = c[0]
        if op == "M":
            start = (c[1], c[2])
            verts.append(start)
            codes.append(MplPath.MOVETO)
        elif op == "L":
            verts.append((c[1], c[2]))
            codes.append(MplPath.LINETO)
        elif op == "Q":
            verts += [(c[1], c[2]), (c[3], c[4])]
            codes += [MplPath.CURVE3] * 2
        elif op == "C":
            verts += [(c[1], c[2]), (c[3], c[4]), (c[5], c[6])]
            codes += [MplPath.CURVE4] * 3
        elif op == "Z":
            verts.append(start)
            codes.append(MplPath.CLOSEPOLY)
    return MplPath(verts, codes) if len(verts) > 1 else None


def _text_paths(shape: Shape) -> List[Any]:
    from matplotlib.textpath import TextPath
    from matplotlib.transforms import Affine2D

    paths = []
    for x, y, text in shape.lines:
        if not text.strip():
            continue
        glyphs = TextPath((0, 0), text, size=shape.height * 1.4)
        width = glyphs.get_extents().width
        shift = {"start": 0.0, "middle": -width / 2, "end": -width}[shape.anchor]
        transform = Affine2D().translate(shift, 0).rotate_deg(shape.rotation).translate(x, y)
        paths.append(glyphs.transformed(transform))
    return paths


def write_png(
    result: DiffResult,
    path: Union[str, Path],
    width: int = 1600,
    height: int = 1000,
    dpi: int = 100,
    title: Optional[str] = None,
) -> None:
    """Render the overlay of OLD and NEW into a PNG file with matplotlib."""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.lines import Line2D
        from matplotlib.patches import PathPatch
        from matplotlib.path import Path as MplPath
    except ImportError as exc:
        raise DxfDiffError('PNG output needs matplotlib: pip install "dxf-diff[png]"') from exc

    scene = build_scene(result)
    fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.01, 0.01, 0.98, 0.88))
    ax.set_aspect("equal")
    ax.axis("off")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # missing glyphs etc.
        for status, (color, style, lw, z) in STYLES.items():
            strokes: List[Any] = []
            fills: List[Any] = []
            glyphs: List[Any] = []
            dots: List[Any] = []
            for item in (it for it in scene.items if it.status == status):
                for shape in item.shapes:
                    if shape.kind == "text":
                        glyphs += _text_paths(shape)
                    elif shape.kind == "dot":
                        dots.append(shape.cmds[0][1:3])
                    else:
                        p = _mpl_path(shape.cmds)
                        if p is not None:
                            (fills if shape.kind == "fill" else strokes).append(p)
            if strokes:
                ax.add_patch(
                    PathPatch(
                        MplPath.make_compound_path(*strokes),
                        fill=False,
                        edgecolor=color,
                        linewidth=lw,
                        linestyle=style,
                        zorder=z,
                        capstyle="round",
                    )
                )
            if fills:
                ax.add_patch(
                    PathPatch(
                        MplPath.make_compound_path(*fills),
                        facecolor=color,
                        alpha=0.15,
                        edgecolor=color,
                        linewidth=lw * 0.6,
                        zorder=z,
                    )
                )
            if glyphs:
                ax.add_patch(
                    PathPatch(MplPath.make_compound_path(*glyphs), facecolor=color, edgecolor="none", zorder=z)
                )
            if dots:
                ax.plot([d[0] for d in dots], [d[1] for d in dots], "o", ms=3, color=color, zorder=z)
    minx, miny, maxx, maxy = scene.extents
    pad = max(maxx - minx, maxy - miny, 1e-9) * 0.03
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    counts = result.summary()["entities"]
    name = title or f"{os.path.basename(result.old_path)}  ->  {os.path.basename(result.new_path)}"
    fig.text(0.012, 0.955, name, fontsize=15, weight="bold", color="#1f2328")
    fig.text(
        0.012,
        0.915,
        f"{counts['added']} added, {counts['removed']} removed, {counts['modified']} modified, "
        f"{counts['unchanged']} unchanged  |  dxf-diff",
        fontsize=11,
        color="#59636e",
    )
    handles = [
        Line2D([], [], color=STYLES[s][0], linestyle=STYLES[s][1], lw=2.2, label=LABELS[s])
        for s in ("removed", "added", "old", "new", "unchanged")
    ]
    fig.legend(handles=handles, loc="upper right", ncol=5, frameon=False, fontsize=10, bbox_to_anchor=(0.99, 0.985))
    fig.savefig(os.fspath(path), dpi=dpi, facecolor="white")
