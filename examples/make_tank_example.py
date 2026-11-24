"""Generate the example drawings tank_rev_a.dxf and tank_rev_b.dxf.

A small general-arrangement (GA) style drawing of a vertical storage tank:
elevation and plan view, nozzles as blocks with TAG/SIZE/RATING attributes,
dimensions, a nozzle schedule and a title block. REV B is made by loading REV A
and editing it, exactly like a drafter would (so entity handles are preserved):

* title block "REV A" -> "REV B" and a new revision row
* nozzle N2 resized (SIZE attribute 4" -> 6")
* nozzle N3 moved up from EL 3000 to EL 3600 (its dimension follows)
* nozzle N4 deleted, nozzle N5 added (block, dimension, plan view mark)
* revision clouds on a new layer REVISION

Run:  python examples/make_tank_example.py
Then: dxf-diff examples/tank_rev_a.dxf examples/tank_rev_b.dxf --html examples/report.html
"""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

HERE = Path(__file__).resolve().parent
R, H, RISE = 4000.0, 9600.0, 670.0  # shell radius, shell height, cone roof rise (mm)
PLAN = (11800.0, 8400.0)  # centre of the plan view
# mark: (size, rating, service, elevation, orientation in plan view [deg, clockwise from north])
NOZZLES = {
    "N1": ('6"', "150#", "INLET", 600.0, 90.0),
    "N2": ('4"', "150#", "OUTLET", 1800.0, 45.0),
    "N3": ('2"', "150#", "DRAIN", 3000.0, 135.0),
    "N4": ('3"', "150#", "LEVEL GAUGE", 6000.0, 225.0),
}
N5 = ('3"', "150#", "OVERFLOW", 8400.0, 315.0)


def schedule_row(mark: str, size: str, rating: str, service: str, elevation: str) -> str:
    return f"{mark}  {size}  {rating}  {service}  EL {elevation}"


def schedule_y(row: int) -> float:
    return 2600.0 - 280.0 * row


def _setup(doc: Drawing) -> None:
    for name, color, linetype in (
        ("SHELL", 7, "Continuous"),
        ("NOZZLES", 4, "Continuous"),
        ("CENTER", 1, "CENTER"),
        ("DIMENSIONS", 2, "Continuous"),
        ("FOUNDATION", 8, "Continuous"),
        ("ANNOTATION", 7, "Continuous"),
        ("TITLE", 7, "Continuous"),
    ):
        doc.layers.add(name, color=color, linetype=linetype)
    doc.dimstyles.new(
        "GA",
        dxfattribs={"dimtxt": 150, "dimasz": 120, "dimexo": 60, "dimexe": 80, "dimgap": 40, "dimdec": 0, "dimtad": 1},
    )
    nozzle = doc.blocks.new("TANK-NOZZLE")  # drawn pointing +x, base point on the shell
    nozzle.add_line((0, 60), (200, 60))
    nozzle.add_line((0, -60), (200, -60))
    nozzle.add_lwpolyline([(200, -110), (230, -110), (230, 110), (200, 110)], close=True)
    nozzle.add_line((-80, 0), (320, 0), dxfattribs={"linetype": "CENTER"})
    nozzle.add_attdef("TAG", (280, 30), dxfattribs={"height": 120})
    nozzle.add_attdef("SIZE", (280, -150), dxfattribs={"height": 90})
    nozzle.add_attdef("RATING", (500, -150), dxfattribs={"height": 90})


def add_nozzle(doc: Drawing, mark: str, size: str, rating: str, elevation: float, slot: int) -> None:
    """Shell nozzle in the elevation view plus its elevation dimension."""
    msp = doc.modelspace()
    ref = msp.add_blockref("TANK-NOZZLE", (R, elevation), dxfattribs={"layer": "NOZZLES"})
    ref.add_auto_attribs({"TAG": mark, "SIZE": size, "RATING": rating})
    msp.add_linear_dim(
        base=(R + 1250 + 380 * slot, 0),
        p1=(R, 0),
        p2=(R + 230, elevation),
        angle=90,
        dimstyle="GA",
        dxfattribs={"layer": "DIMENSIONS"},
    ).render()


def add_plan_mark(doc: Drawing, mark: str, orientation: float) -> None:
    """Nozzle orientation line and tag in the plan view."""
    msp = doc.modelspace()
    dx, dy = math.sin(math.radians(orientation)), math.cos(math.radians(orientation))
    cx, cy = PLAN
    msp.add_line(
        (cx + dx * R, cy + dy * R), (cx + dx * (R + 450), cy + dy * (R + 450)), dxfattribs={"layer": "NOZZLES"}
    )
    msp.add_text(mark, height=180, dxfattribs={"layer": "NOZZLES"}).set_placement(
        (cx + dx * (R + 700), cy + dy * (R + 700)), align=TextEntityAlignment.MIDDLE_CENTER
    )


def text(doc: Drawing, value: str, x: float, y: float, height: float, layer: str = "ANNOTATION") -> None:
    doc.modelspace().add_text(value, height=height, dxfattribs={"layer": layer, "insert": (x, y)})


def build_rev_a() -> Drawing:
    doc = ezdxf.new("R2018", setup=True, units=4)  # millimetres
    _setup(doc)
    msp = doc.modelspace()
    # elevation view
    msp.add_lwpolyline([(-R, 0), (R, 0), (R, H), (-R, H)], close=True, dxfattribs={"layer": "SHELL"})
    for y in (2400, 4800, 7200):  # horizontal shell course seams
        msp.add_line((-R, y), (R, y), dxfattribs={"layer": "SHELL"})
    msp.add_lwpolyline([(-R - 60, H), (0, H + RISE), (R + 60, H)], dxfattribs={"layer": "SHELL"})
    msp.add_lwpolyline(
        [(-R - 100, -12), (R + 100, -12), (R + 100, 0), (-R - 100, 0)], close=True, dxfattribs={"layer": "SHELL"}
    )
    ring = [(-R - 400, -600), (R + 400, -600), (R + 400, -12), (-R - 400, -12)]
    msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "FOUNDATION"})
    hatch = msp.add_hatch(dxfattribs={"layer": "FOUNDATION"})
    hatch.paths.add_polyline_path(ring, is_closed=True)
    hatch.set_pattern_fill("ANSI31", scale=40, color=8)
    msp.add_line((0, -900), (0, H + RISE + 400), dxfattribs={"layer": "CENTER"})
    msp.add_circle((-2000, 1000), 300, dxfattribs={"layer": "NOZZLES"})  # manway M1
    msp.add_circle((-2000, 1000), 380, dxfattribs={"layer": "NOZZLES"})
    text(doc, 'M1 24" MANWAY', -2380, 1500, 150, "NOZZLES")
    vent = msp.add_blockref(
        "TANK-NOZZLE", (1500, H + RISE * (1 - 1500 / R)), dxfattribs={"layer": "NOZZLES", "rotation": 90}
    )
    vent.add_auto_attribs({"TAG": "N6", "SIZE": '8"', "RATING": "150#"})
    for slot, (mark, (size, rating, _service, elevation, orientation)) in enumerate(NOZZLES.items()):
        add_nozzle(doc, mark, size, rating, elevation, slot)
        add_plan_mark(doc, mark, orientation)
    msp.add_linear_dim(
        base=(-R - 900, 0), p1=(-R, 0), p2=(-R, H), angle=90, dimstyle="GA", dxfattribs={"layer": "DIMENSIONS"}
    ).render()
    msp.add_linear_dim(
        base=(0, -1300), p1=(-R, -12), p2=(R, -12), dimstyle="GA", dxfattribs={"layer": "DIMENSIONS"}
    ).render()
    text(doc, "ELEVATION", -800, -2100, 250)
    # plan view
    cx, cy = PLAN
    msp.add_circle(PLAN, R, dxfattribs={"layer": "SHELL"})
    msp.add_line((cx - R - 400, cy), (cx + R + 400, cy), dxfattribs={"layer": "CENTER"})
    msp.add_line((cx, cy - R - 400), (cx, cy + R + 400), dxfattribs={"layer": "CENTER"})
    msp.add_circle((cx, cy + 1500), 110, dxfattribs={"layer": "NOZZLES"})  # roof vent N6 in plan
    text(doc, "N6", cx + 200, cy + 1450, 150, "NOZZLES")
    text(doc, "0°", cx + 150, cy + R + 250, 160)
    text(doc, "PLAN", cx - 350, cy - R - 1000, 250)
    # nozzle schedule
    text(doc, "NOZZLE SCHEDULE", 11000, 2950, 180)
    for row, (mark, (size, rating, service, elevation, _o)) in enumerate(NOZZLES.items()):
        text(doc, schedule_row(mark, size, rating, service, f"{elevation:.0f}"), 11000, schedule_y(row), 130)
    text(doc, schedule_row("N6", '8"', "150#", "VENT", "ROOF"), 11000, schedule_y(4), 130)
    text(doc, schedule_row("M1", '24"', "150#", "MANWAY", "1000"), 11000, schedule_y(5), 130)
    # sheet border and title block
    msp.add_lwpolyline(
        [(-6500, -2800), (17500, -2800), (17500, 13200), (-6500, 13200)], close=True, dxfattribs={"layer": "TITLE"}
    )
    msp.add_lwpolyline(
        [(10800, -2800), (17500, -2800), (17500, -400), (10800, -400)], close=True, dxfattribs={"layer": "TITLE"}
    )
    msp.add_line((10800, -1500), (17500, -1500), dxfattribs={"layer": "TITLE"})
    msp.add_line((16000, -2800), (16000, -1500), dxfattribs={"layer": "TITLE"})
    text(doc, "STORAGE TANK T-101", 11000, -800, 300, "TITLE")
    text(doc, "GENERAL ARRANGEMENT", 11000, -1250, 220, "TITLE")
    text(doc, "DWG No. TK-101-GA-001", 11000, -1950, 180, "TITLE")
    text(doc, "SCALE 1:50   UNITS mm", 11000, -2400, 150, "TITLE")
    text(doc, "REV A", 16200, -2300, 250, "TITLE")
    text(doc, "dxf-diff example drawing - not for construction", 11000, -2700, 90, "TITLE")
    text(doc, "A   2026-10-02   ISSUED FOR REVIEW", 10900, -150, 120, "TITLE")
    return doc


def _find(doc: Drawing, dxftype: str, predicate) -> object:
    return next(e for e in doc.modelspace() if e.dxftype() == dxftype and predicate(e))


def _cloud(points: list) -> list:
    """Closed revision cloud around a rectangle: many small arcs (bulges) outwards."""
    (x0, y0), (x1, y1) = points
    step = 260.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    vertices = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
        n = max(1, round(math.hypot(bx - ax, by - ay) / step))
        vertices += [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n, 0, 0, 0.6) for i in range(n)]
    return vertices


def make_rev_b(rev_a: Path) -> Drawing:
    doc = ezdxf.readfile(rev_a)
    msp = doc.modelspace()

    def nozzle(mark: str):
        return _find(doc, "INSERT", lambda e: e.get_attrib_text("TAG") == mark)

    def dim_to(elevation: float):
        return _find(doc, "DIMENSION", lambda e: abs(e.dxf.defpoint3.y - elevation) < 1e-6 and e.dxf.defpoint3.x > R)

    def schedule(mark: str):
        return _find(doc, "TEXT", lambda e: e.dxf.text.startswith(mark + " "))

    _find(doc, "TEXT", lambda e: e.dxf.text == "REV A").dxf.text = "REV B"
    text(doc, "B   2026-11-20   N2 RESIZED, N3 RELOCATED, N4 DELETED, N5 ADDED", 10900, 150, 120, "TITLE")
    nozzle("N2").get_attrib("SIZE").dxf.text = '6"'
    schedule("N2").dxf.text = schedule_row("N2", '6"', "150#", "OUTLET", "1800")
    nozzle("N3").translate(0, 600, 0)  # moves the attached attributes too
    dim = dim_to(3000)
    dim.dxf.defpoint3 = (R + 230, 3600)
    dim.override().render()
    schedule("N3").dxf.text = schedule_row("N3", '2"', "150#", "DRAIN", "3600")
    msp.delete_entity(nozzle("N4"))
    msp.delete_entity(dim_to(6000))
    msp.delete_entity(schedule("N4"))
    msp.delete_entity(_find(doc, "TEXT", lambda e: e.dxf.text == "N4"))
    msp.delete_entity(
        _find(doc, "LINE", lambda e: e.dxf.layer == "NOZZLES" and e.dxf.start.x < PLAN[0] and e.dxf.start.y < PLAN[1])
    )
    size, rating, service, elevation, orientation = N5
    add_nozzle(doc, "N5", size, rating, elevation, 3)
    add_plan_mark(doc, "N5", orientation)
    text(doc, schedule_row("N5", size, rating, service, f"{elevation:.0f}"), 11000, schedule_y(6), 130)
    doc.layers.add("REVISION", color=6)
    for box in (((R - 250, 3300), (R + 1000, 3950)), ((R - 250, 8100), (R + 1000, 8750))):
        msp.add_lwpolyline(_cloud(list(box)), format="xyseb", close=True, dxfattribs={"layer": "REVISION"})
    return doc


def main() -> None:
    rev_a, rev_b = HERE / "tank_rev_a.dxf", HERE / "tank_rev_b.dxf"
    build_rev_a().saveas(rev_a)
    make_rev_b(rev_a).saveas(rev_b)
    print(f"wrote {rev_a.name} and {rev_b.name}")


if __name__ == "__main__":
    main()
