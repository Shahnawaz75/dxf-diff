"""dxf-diff: compare two DXF files and see what changed.

Example::

    from dxf_diff import compare

    result = compare("old.dxf", "new.dxf", tolerance=1e-6)
    for change in result:
        print(change.kind, change.dxftype, change.layer, change.handle, change.description)
"""

from ._version import __version__
from .engine import CompareOptions, compare, load_drawing
from .html_report import render_html, write_html
from .model import BlockChange, ChangeKind, DiffResult, DxfDiffError, EntityChange, LayerChange, PropertyChange
from .png_report import write_png
from .textconv import textconv

__all__ = [
    "BlockChange",
    "ChangeKind",
    "CompareOptions",
    "DiffResult",
    "DxfDiffError",
    "EntityChange",
    "LayerChange",
    "PropertyChange",
    "__version__",
    "compare",
    "load_drawing",
    "render_html",
    "textconv",
    "write_html",
    "write_png",
]
