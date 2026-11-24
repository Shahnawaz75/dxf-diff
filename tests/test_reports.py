"""HTML report (self-contained, SVG overlay) and PNG image."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from dxf_diff import compare, render_html, write_html, write_png

SVG_NS = "{http://www.w3.org/2000/svg}"


def svg_of(html: str) -> ET.Element:
    return ET.fromstring(re.search(r'<svg id="view".*?</svg>', html, re.S).group(0))  # must be well-formed XML


def test_html_report_is_self_contained_with_svg_overlay(base_path, rev_path, tmp_path):
    report = tmp_path / "report.html"
    write_html(compare(base_path, rev_path), report)
    html = report.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") and "\r\n" not in html
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=", html), "no external assets"
    assert "@import" not in html and "url(" not in html
    groups = svg_of(html).findall(f".//{SVG_NS}g")
    classes = [g.get("class") for g in groups]
    assert "ent added" in classes and "ent removed" in classes
    assert "ent modified o" in classes and "ent modified n" in classes  # old dashed + new solid
    assert "u" in classes  # unchanged entities in light grey
    ids = {g.get("data-id") for g in groups if g.get("data-id")}
    rows = re.findall(r'<tr data-id="(\d+)" data-bbox="[-\d. ]+"', html)
    assert len(rows) == 4 and set(rows) == ids  # every table row can highlight and zoom to its entity
    assert "REV B" in html and "color 3 (green) -&gt; 5 (blue)" in html


def test_html_report_without_changes_and_with_paperspace(base_path, revise):
    html = render_html(compare(base_path, base_path))
    assert "No entity changes." in html and svg_of(html).findall(f"./{SVG_NS}g[@class='u']/{SVG_NS}path")
    rev = revise(lambda d: d.paperspace().add_text("<script>&", dxfattribs={"insert": (1, 1)}))
    html = render_html(compare(base_path, rev, layouts=True))
    assert "listed in the table but not drawn" in html
    assert "&lt;script&gt;&amp;" in html and "<script>&" not in html  # drawing text is escaped


def test_png_overlay(base_path, rev_path, tmp_path):
    pytest.importorskip("matplotlib")
    image = tmp_path / "overlay.png"
    write_png(compare(base_path, rev_path), image)
    assert image.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
