"""Synthetic drawings with known content, for tests and demos.

Each sample is a real vector PDF laid out the way CAD exports are: every
callout its own text object, frames and datum symbols drawn as boxes with
the text inside, a gridded title block with small labels above values.
`EXPECTED` says which rules each sample must and must not trigger; the tests
hold the checker to it.

    python -m drawcheck sample out_dir/
"""
from __future__ import annotations

import os
from pathlib import Path

import pymupdf

A3 = (1191.0, 842.0)
SYMBOL_FONTS = [
    "C:/Windows/Fonts/seguisym.ttf",
    # Symbola has every GD&T glyph (⌖ Ⓜ ⟂ ↧); DejaVu lacks ⌖ and Ⓜ, so a frame drawn
    # with it loses its symbol and its datum cells read as datum feature symbols.
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
    "/usr/share/fonts/truetype/symbola/Symbola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def symbol_font() -> str | None:
    env = os.environ.get("DRAWCHECK_SYMBOL_FONT")
    for p in ([env] if env else []) + SYMBOL_FONTS:
        if p and Path(p).exists():
            return p
    return None


class Sheet:
    def __init__(self, page: pymupdf.Page, font: str | None):
        self.page = page
        self.sym = "sym" if font else "helv"
        if font:
            page.insert_font(fontname="sym", fontfile=font)

    def text(self, x: float, y: float, s: str, size: float = 9, sym: bool = False) -> None:
        self.page.insert_text((x, y), s, fontsize=size, fontname=self.sym if sym else "helv")

    def width(self, s: str, size: float = 9, sym: bool = False) -> float:
        return pymupdf.get_text_length(s, fontname="helv", fontsize=size) if not sym else size * 0.62 * len(s)

    def box(self, x0: float, y0: float, x1: float, y1: float, width: float = 0.6) -> None:
        self.page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=width)

    def line(self, a: tuple[float, float], b: tuple[float, float], width: float = 0.4) -> None:
        self.page.draw_line(a, b, color=(0, 0, 0), width=width)

    def frame(self, x: float, y: float, cells: list[str]) -> None:
        """Feature control frame: one boxed cell per element, symbol cell first."""
        h = 14.0
        for i, c in enumerate(cells):
            w = 18.0 if i == 0 else max(16.0, self.width(c, 8, sym=True) + 8)
            self.box(x, y, x + w, y + h)
            self.text(x + 4, y + 10.5, c, size=8, sym=True)
            x += w

    def datum(self, x: float, y: float, letter: str) -> None:
        self.box(x, y, x + 14, y + 14)
        self.text(x + 3.5, y + 10.5, letter, size=9)
        self.line((x + 7, y + 14), (x + 7, y + 26))
        self.page.draw_polyline([(x + 2, y + 32), (x + 12, y + 32), (x + 7, y + 26), (x + 2, y + 32)],
                                color=(0, 0, 0), fill=(0, 0, 0))

    def basic(self, x: float, y: float, s: str) -> None:
        w = self.width(s) + 8
        self.box(x, y, x + w, y + 14)
        self.text(x + 4, y + 10.5, s)

    def border(self) -> None:
        W, H = self.page.rect.width, self.page.rect.height
        self.box(20, 20, W - 20, H - 20, width=1.2)
        for i in range(8):                         # zone numbers, top edge
            self.text(20 + (i + 0.5) * (W - 40) / 8, 15, str(i + 1), size=7)
        for i, ch in enumerate("ABCDEF"):           # zone letters, left edge
            self.text(9, 20 + (i + 0.5) * (H - 40) / 6, ch, size=7)

    def title_block(self, fields: dict[str, str]) -> None:
        W, H = self.page.rect.width, self.page.rect.height
        x0, y0 = W - 20 - 400, H - 20 - 120
        cw, ch = 100.0, 30.0
        items = list(fields.items())
        for i, (label, value) in enumerate(items):
            col, row = i % 4, i // 4
            x, y = x0 + col * cw, y0 + row * ch
            self.box(x, y, x + cw, y + ch)
            self.text(x + 3, y + 8, label, size=5.5)
            if value:
                self.text(x + 5, y + 22, value, size=9)


def _views(s: Sheet) -> None:
    """Front and side view of a bracket: outlines only, they carry no text."""
    s.box(120, 180, 520, 420, width=1.0)
    s.page.draw_circle((220, 300), 30, color=(0, 0, 0), width=1.0)
    for cx, cy in ((160, 220), (480, 220), (160, 380), (480, 380)):
        s.page.draw_circle((cx, cy), 6.6, color=(0, 0, 0), width=0.8)
    s.box(640, 180, 700, 420, width=1.0)
    s.line((120, 450), (520, 450))
    s.line((120, 440), (120, 460))
    s.line((520, 440), (520, 460))


def _clean(s: Sheet) -> None:
    s.border()
    _views(s)
    s.text(300, 447, "200 ±0.1")
    s.text(530, 305, "120 ±0.1")
    s.text(650, 445, "30")
    s.text(180, 345, "Ø30")
    s.text(206, 338, "+0.021", size=6)
    s.text(206, 347, "0", size=6)
    s.text(140, 200, "4X Ø6.6 THRU")
    s.text(380, 300, "M8x1.25-6H ↧12", size=9, sym=True)
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
    for i, n in enumerate([
        "1. ALL DIMENSIONS IN MM",
        "2. GENERAL TOLERANCES ISO 2768-mK",
        "3. GEOMETRICAL TOLERANCING PER ISO 1101",
        "4. BREAK ALL SHARP EDGES 0.3 x 45°",
        "5. SURFACE ROUGHNESS Ra 3.2 ALL OVER UNLESS STATED",
    ]):
        s.text(40, 575 + i * 13, n, size=8)
    s.text(40, 660, "FIRST ANGLE PROJECTION", size=8)
    s.title_block({
        "TITLE": "MOUNTING BRACKET", "DWG NO": "OF-1001", "REV": "B", "SCALE": "1:2",
        "MATERIAL": "EN8 (080M40)", "UNITS": "MM", "DRAWN": "S.M.", "CHECKED": "R.K.",
        "APPROVED": "A.P.", "DATE": "2026-10-01", "SHEET": "1 OF 1", "FINISH": "ZINC PLATED",
    })


def _defective(s: Sheet) -> None:
    s.border()
    _views(s)
    s.text(300, 447, "200 ±0.1")
    s.text(530, 305, "120")
    s.text(650, 445, ".5")
    s.text(180, 345, "Ø20 g6/H7")
    s.text(140, 200, "4X Ø6.6 THRU")
    s.text(380, 300, "1/4-20 UNC", size=9)
    s.text(380, 330, "M6", size=9)
    s.text(250, 480, "10 -0.1/+0.05")
    s.text(560, 240, "Ra 2.5", size=8)
    s.frame(140, 500, ["⌖", "Ø0.2", "A", "C"])        # C is never defined       -> GD-001
    s.frame(400, 160, ["▱", "0.05", "A"])              # form with datum         -> GD-002
    s.frame(710, 300, ["⟂", "0.05"])                   # orientation, no datum   -> GD-003
    s.frame(710, 340, ["↗", "0.03", "Ⓜ", "A"])          # runout with MMC         -> GD-006
    s.frame(710, 380, ["⌖", "Ø0", "A", "O"])            # zero tol, no MMC        -> GD-009
    s.datum(560, 425, "A")
    s.datum(90, 250, "O")                              # letter O                -> GD-008
    s.text(40, 560, "NOTES:", size=9)
    for i, n in enumerate([
        "1. ALL DIMENSIONS IN MM",
        "2. CASE HARDEN",
    ]):
        s.text(40, 575 + i * 13, n, size=8)
    s.title_block({
        "TITLE": "MOUNTING BRACKET", "DWG NO": "OF-1002", "REV": "", "SCALE": "1:2",
        "MATERIAL": "", "UNITS": "MM", "DRAWN": "S.M.", "CHECKED": "",
        "APPROVED": "", "DATE": "2026-10-01", "SHEET": "1 OF 1", "FINISH": "",
    })


def _mixed(s: Sheet) -> None:
    s.border()
    _views(s)
    s.text(300, 447, "200")
    s.text(530, 305, "120")
    s.frame(710, 300, ["⟂", "0.05", "A"])
    s.datum(560, 425, "A")
    s.text(40, 560, "NOTES:", size=9)
    for i, n in enumerate([
        "1. DIMENSIONS IN MM",
        "2. TOLERANCES PER ISO 2768",
        "3. INTERPRET PER ASME Y14.5-2018",
        "4. DEBURR ALL EDGES",
        "5. SURFACE ROUGHNESS Ra 3.2 ALL OVER",
    ]):
        s.text(40, 575 + i * 13, n, size=8)
    s.text(40, 660, "THIRD ANGLE PROJECTION", size=8)
    s.text(40, 672, "FIRST ANGLE PROJECTION", size=8)
    s.title_block({
        "TITLE": "PLATE", "DWG NO": "OF-1003", "REV": "A", "SCALE": "1:1",
        "MATERIAL": "IS 2062 E250", "UNITS": "MM", "DRAWN": "S.M.", "CHECKED": "R.K.",
        "APPROVED": "A.P.", "DATE": "2026-10-01", "SHEET": "1 OF 1", "FINISH": "",
    })


BUILDERS = {"clean": _clean, "defective": _defective, "mixed": _mixed}

#: rule -> must fire (True) / must not fire (False). Rules not listed are not asserted.
EXPECTED: dict[str, dict[str, bool]] = {
    "clean": {r: False for r in (
        "TB-001", "TB-002", "TB-003", "TB-004", "TB-006", "TB-007", "GT-001", "GT-002", "GT-003", "GT-004",
        "PR-001", "PR-002", "UN-001", "UN-002", "DM-001", "DM-002", "DM-003", "TH-001", "TH-003", "TH-004",
        "SF-001", "SF-002", "GD-001", "GD-002", "GD-003", "GD-004", "GD-005", "GD-006", "GD-007", "GD-008",
        "GD-009", "GD-010", "GD-011", "NT-001", "RD-001")},
    "defective": {
        "TB-003": True, "TB-004": True, "TB-006": True, "TB-007": True, "GT-001": True, "PR-001": True,
        "UN-002": True, "DM-001": True, "DM-002": True, "TH-001": True, "TH-002": True, "TH-003": True,
        "SF-002": True, "GD-001": True, "GD-002": True, "GD-003": True, "GD-006": True, "GD-008": True,
        "GD-009": True, "NT-001": True, "TB-001": False, "TB-002": False, "UN-001": False, "GD-010": False,
    },
    "mixed": {
        "GT-002": True, "GT-004": True, "PR-002": True, "GT-001": False, "GT-003": False,
        "PR-001": False, "TB-004": False, "NT-001": False,
    },
    "scanned": {"RD-001": True},
}


def make(name: str, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if name == "scanned":
        src = make("clean", out.with_name(out.stem + "_src.pdf"))
        with pymupdf.open(str(src)) as d:
            pix = d[0].get_pixmap(dpi=100)
        doc = pymupdf.open()
        page = doc.new_page(width=A3[0], height=A3[1])
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        doc.save(str(out))
        doc.close()
        src.unlink()
        return out
    font = symbol_font()
    if font is None:
        raise RuntimeError("no font with GD&T glyphs found; set DRAWCHECK_SYMBOL_FONT to a TTF that has them")
    doc = pymupdf.open()
    page = doc.new_page(width=A3[0], height=A3[1])
    BUILDERS[name](Sheet(page, font))
    doc.save(str(out))
    doc.close()
    return out


def make_all(out_dir: str | Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    return {n: make(n, out_dir / f"{n}.pdf") for n in list(BUILDERS) + ["scanned"]}
