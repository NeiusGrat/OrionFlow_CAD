"""A sample FAI project with known answers: the OF-1001 mounting bracket.

    rev A drawing    120 ±0.2, Ø30 H7 written as a fit class, no M8 thread depth
    rev B drawing    drawcheck's clean sheet: 120 ±0.1, Ø30 +0.021/0, M8x1.25-6H ↧12
    rev B STEP       the bracket as modelled — with the bore at Ø30.40 (outside
                     +0.021/0) and the tapped hole modelled at its Ø6.8 tap drill
    rev B BOM        the PO line still says revision A, and the material as EN8

So the cross-check must find: the bore disagreeing with the drawing, the BOM
revision mismatch, and the thread recognised from its tap drill; and the
revision compare must find 120 and Ø30 changed and the thread depth added.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from drawcheck.samples import A3, Sheet, _views, symbol_font

BOM_CSV = (
    "Part Number,Description,Rev,Material,Qty\n"
    "OF-1001,MOUNTING BRACKET,A,EN8,1\n"
    "ISO4762-M6x20,SOCKET HEAD CAP SCREW,,8.8 STEEL,4\n"
)


def _sheet(s: Sheet, rev: str) -> None:
    s.border()
    _views(s)
    s.text(300, 447, "200 ±0.1")
    s.text(530, 305, "120 ±0.2" if rev == "A" else "120 ±0.1")
    s.text(650, 445, "30")
    if rev == "A":
        s.text(180, 345, "Ø30 H7")
    else:
        s.text(180, 345, "Ø30")
        s.text(206, 338, "+0.021", size=6)
        s.text(206, 347, "0", size=6)
    s.text(140, 200, "4X Ø6.6 THRU")
    s.text(380, 300, "M8x1.25-6H" if rev == "A" else "M8x1.25-6H ↧12", size=9, sym=True)
    s.text(560, 240, "Ra 1.6", size=8)
    s.frame(140, 470, ["⌖", "Ø0.2", "Ⓜ", "A", "B", "C"])
    s.frame(400, 160, ["▱", "0.05"])
    s.frame(710, 300, ["⟂", "0.05", "A"])
    s.datum(560, 425, "A")
    s.datum(90, 250, "B")
    s.datum(300, 150, "C")
    s.basic(250, 230, "160")
    s.basic(330, 230, "80")
    s.text(40, 560, "NOTES:", size=9)
    notes = ["1. ALL DIMENSIONS IN MM", "2. GENERAL TOLERANCES ISO 2768-mK",
             "3. GEOMETRICAL TOLERANCING PER ISO 1101", "4. BREAK ALL SHARP EDGES 0.3 x 45°",
             "5. SURFACE ROUGHNESS Ra 3.2 ALL OVER UNLESS STATED"]
    for i, n in enumerate(notes):
        s.text(40, 575 + i * 13, n, size=8)
    s.text(40, 660, "FIRST ANGLE PROJECTION", size=8)
    s.title_block({
        "TITLE": "MOUNTING BRACKET", "DWG NO": "OF-1001", "REV": rev, "SCALE": "1:2",
        "MATERIAL": "EN8 (080M40)", "UNITS": "MM", "DRAWN": "S.M.", "CHECKED": "R.K.",
        "APPROVED": "A.P.", "DATE": "2026-09-12" if rev == "A" else "2026-10-01", "SHEET": "1 OF 1",
        "FINISH": "ZINC PLATED",
    })


def drawing(rev: str, out: str | Path) -> Path:
    font = symbol_font()
    if font is None:
        raise RuntimeError("no font with GD&T glyphs found; set DRAWCHECK_SYMBOL_FONT")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=A3[0], height=A3[1])
    _sheet(Sheet(page, font), rev)
    doc.save(str(out))
    doc.close()
    return out


def step(out: str | Path, bore: float = 30.4) -> Path:
    """The rev B bracket as modelled. Drawing frame: x right, y down from the top
    edge; model frame: x right, y up, plate on z = 0..30."""
    from build123d import Box, Cylinder, Pos, export_step

    plate = Pos(100, 60, 15) * Box(200, 120, 30)
    plate -= Pos(50, 60, 15) * Cylinder(bore / 2, 30)
    for x, y in ((20, 20), (180, 20), (20, 100), (180, 100)):
        plate -= Pos(x, y, 15) * Cylinder(6.6 / 2, 30)
    plate -= Pos(130, 60, 30 - 6) * Cylinder(6.8 / 2, 12)        # M8 tap drill, 12 deep from the top
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    export_step(plate, str(out).replace("\\", "/"))
    return out


def bom(out: str | Path) -> Path:
    out = Path(out)
    out.write_text(BOM_CSV, encoding="utf-8")
    return out
