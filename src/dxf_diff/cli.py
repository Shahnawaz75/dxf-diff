"""Command line interface: ``dxf-diff OLD NEW`` and ``dxf-diff --textconv FILE``.

Exit status follows ``diff``: 0 = no differences, 1 = differences found, 2 = error.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ._version import __version__
from .engine import MATCH_MODES, CompareOptions, compare
from .html_report import write_html
from .model import ChangeKind, DiffResult, DxfDiffError
from .png_report import write_png
from .textconv import textconv

EXIT_SAME, EXIT_DIFFERENT, EXIT_ERROR = 0, 1, 2
_COLORS = {"added": "32", "removed": "31", "modified": "33", "dim": "2", "bold": "1"}
_SYMBOLS = {ChangeKind.ADDED: "+", ChangeKind.REMOVED: "-", ChangeKind.MODIFIED: "~"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dxf-diff",
        description="Compare two DXF drawings and show what changed (entities, layers, blocks).",
        epilog="Exit status: 0 = no differences, 1 = differences found, 2 = error. "
        "Docs: https://github.com/Shahnawaz75/dxf-diff",
    )
    parser.add_argument("old", nargs="?", help="old / original DXF file")
    parser.add_argument("new", nargs="?", help="new / revised DXF file")
    parser.add_argument("--textconv", metavar="FILE", help="print a normalized text dump of FILE (for git diff)")
    cmp = parser.add_argument_group("comparison")
    cmp.add_argument("-t", "--tolerance", type=float, default=1e-6, help="values closer than this are equal (1e-6)")
    many: Dict[str, Any] = {"action": "append", "default": [], "metavar": "PATTERN"}
    cmp.add_argument("--layer", dest="layers", help="compare only layers matching PATTERN (wildcards)", **many)
    cmp.add_argument("--ignore-layer", dest="ignore_layers", help="ignore layers matching PATTERN (wildcards)", **many)
    cmp.add_argument("--ignore-props", help="properties to ignore, e.g. color,linetype", **{**many, "metavar": "NAMES"})
    cmp.add_argument("--layouts", action="store_true", help="also compare paperspace layouts (default: model only)")
    cmp.add_argument("--match", choices=MATCH_MODES, default="auto", help="entity matching strategy (default: auto)")
    out = parser.add_argument_group("output")
    out.add_argument("--json", metavar="PATH", help="write a JSON report ('-' for stdout)")
    out.add_argument("--html", metavar="PATH", help="write a self-contained HTML report with an SVG overlay")
    out.add_argument("--png", metavar="PATH", help='write a PNG overlay image (needs "dxf-diff[png]")')
    out.add_argument("--open", action="store_true", help="open the HTML report in a web browser")
    out.add_argument("--brief", action="store_true", help="print only the summary counts")
    out.add_argument("-q", "--quiet", action="store_true", help="print nothing, only set the exit status")
    out.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="colored output")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _paint(text: str, style: str, color: bool) -> str:
    return f"\033[{_COLORS[style]}m{text}\033[0m" if color else text


def _counts(counts: dict, kinds: Sequence[str]) -> str:
    parts = [f"{counts[k]} {k}" for k in kinds if counts.get(k)]
    return ", ".join(parts) if parts else "no changes"


def format_report(result: DiffResult, color: bool = False, brief: bool = False) -> str:
    """The terminal summary printed by ``dxf-diff OLD NEW``."""
    summary = result.summary()
    kinds = ("added", "removed", "modified")
    lines = [
        f"{_paint('OLD:', 'removed', color)} {result.old_path}",
        f"{_paint('NEW:', 'added', color)} {result.new_path}",
        f"Entities: {_counts(summary['entities'], kinds + ('unchanged',))}",
        f"Layers:   {_counts(summary['layers'], kinds)}",
        f"Blocks:   {_counts(summary['blocks'], kinds)}",
    ]
    if not result.has_changes:
        lines.append(_paint("No differences.", "bold", color))
        return "\n".join(lines)
    if brief:
        return "\n".join(lines)
    changes = result.changes
    if changes:
        type_w = min(12, max(len(c.dxftype) for c in changes))
        layer_w = min(20, max(len(c.layer) for c in changes))
        handle_w = min(12, max(len(c.handle) for c in changes))
        lines += ["", _paint("Entity changes:", "bold", color)]
        for c in changes:
            label = _paint(f"{_SYMBOLS[c.kind]} {c.kind.value:<8}", c.kind.value, color)
            handle = _paint(f"{c.handle:<{handle_w}}", "dim", color)
            space = "" if c.space == "Model" else f" [{c.space}]"
            row = f"  {label}  {c.dxftype:<{type_w}}  {c.layer:<{layer_w}}  {handle}  {c.description}{space}"
            lines.append(row.rstrip())
    for title, items in (("Layer changes:", result.layers), ("Block changes:", result.blocks)):
        if not items:
            continue
        name_w = min(24, max(len(item.name) for item in items))
        lines += ["", _paint(title, "bold", color)]
        for item in items:
            label = _paint(f"{_SYMBOLS[item.kind]} {item.kind.value:<8}", item.kind.value, color)
            lines.append(f"  {label}  {item.name:<{name_w}}  {item.description}")
            lines.extend(f"      {detail}" for detail in getattr(item, "details", [])[:10])
    return "\n".join(lines)


def _use_color(mode: str) -> bool:
    if mode != "auto":
        return mode == "always"
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":  # enable ANSI escape sequences in the Windows console
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-11)
            mode_value = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode_value)):
                kernel32.SetConsoleMode(handle, mode_value.value | 0x0004)
        except Exception:
            return False
    return True


def _configure_stdout(textconv: bool) -> None:
    """Never crash on unprintable text; for textconv UTF-8 with LF only, so git sees the same bytes on every OS."""
    try:
        options = {"encoding": "utf-8", "newline": "\n"} if textconv else {}
        sys.stdout.reconfigure(errors="replace", **options)  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass


def _run(argv: Optional[List[str]]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.getLogger("ezdxf").setLevel(logging.ERROR)
    _configure_stdout(textconv=bool(args.textconv))
    if args.textconv:
        if args.old or args.new:
            parser.error("--textconv takes exactly one file")
        sys.stdout.write(textconv(args.textconv))
        return EXIT_SAME
    if not (args.old and args.new):
        parser.error("two DXF files are required: dxf-diff OLD NEW")
    opts = CompareOptions(args.tolerance, args.layers, args.ignore_layers, args.ignore_props, args.layouts, args.match)
    result = compare(args.old, args.new, options=opts)
    if args.json == "-":
        sys.stdout.write(result.to_json() + "\n")
    elif args.json:
        result.to_json(args.json)
    html_path = args.html
    if args.open and not html_path:
        fd, html_path = tempfile.mkstemp(prefix="dxf-diff-", suffix=".html")
        os.close(fd)
    if html_path:
        write_html(result, html_path)
        if args.open:
            webbrowser.open(Path(html_path).resolve().as_uri())
    if args.png:
        write_png(result, args.png)
    if not args.quiet and args.json != "-":
        print(format_report(result, color=_use_color(args.color), brief=args.brief))
    return EXIT_DIFFERENT if result.has_changes else EXIT_SAME


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point of the ``dxf-diff`` command; returns the exit status."""
    try:
        return _run(argv)
    except SystemExit as exc:  # argparse: --help, --version, usage errors (status 2)
        return exc.code if isinstance(exc.code, int) else (EXIT_SAME if exc.code is None else EXIT_ERROR)
    except (DxfDiffError, ValueError) as exc:  # ValueError: invalid option values
        print(f"dxf-diff: error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("dxf-diff: interrupted", file=sys.stderr)
    except Exception as exc:  # unexpected failure: still exit with 2, like diff
        print(f"dxf-diff: error: {type(exc).__name__}: {exc}", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
