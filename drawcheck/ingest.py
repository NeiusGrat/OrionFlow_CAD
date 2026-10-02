"""PDF -> pages of positioned text and closed boxes.

Most drawings a supplier receives are exported from CAD, so the PDF carries
the real characters of every dimension: reading that layer is exact and free.
Two kinds of page carry no usable text and are marked for the vision reader:
  image     a scan: the page is a picture.
  outlined  the CAD system drew every character as line strokes (SHX fonts,
            "text as geometry" export). The page is vector, but there is no
            text to read. Easy to miss: it looks like a vector drawing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from .model import BBox, Line, Page, Word

#: Fewer words than this on a page that also carries an image => a scan.
MIN_VECTOR_WORDS = 8

#: Smallest box side we keep (points). Hatching and arrowheads are smaller.
MIN_RECT_SIDE = 3.0

#: A word that looks like a dimension value.
_DIMLIKE = re.compile(r"^(\d+[xX])?[ØR]?(\d+[.,]\d+|[.,]\d+|\d{1,3})°?$")


def _span_info(spans: list[tuple[BBox, str, float, tuple[float, float]]], bbox: BBox):
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    for sb, font, size, d in spans:
        if sb[0] - 0.5 <= cx <= sb[2] + 0.5 and sb[1] - 0.5 <= cy <= sb[3] + 0.5:
            return font, size, d
    return "", 0.0, (1.0, 0.0)


def _closed_quad(lines: list) -> list[tuple[float, float]] | None:
    """Four line segments that close into a 4-gon, at any rotation."""
    if len(lines) != 4:
        return None
    pts = [(round(it[1].x, 1), round(it[1].y, 1)) for it in lines]
    ends = [(round(it[2].x, 1), round(it[2].y, 1)) for it in lines]
    for i in range(4):
        a, b = ends[i], pts[(i + 1) % 4]
        if abs(a[0] - b[0]) > 0.6 or abs(a[1] - b[1]) > 0.6:
            return None
    return [(it[1].x, it[1].y) for it in lines]


def _boxes(page: pymupdf.Page) -> tuple[list[BBox], list[list[tuple[float, float]]], int]:
    rects: list[BBox] = []
    quads: list[list[tuple[float, float]]] = []
    paths = page.get_drawings()
    for path in paths:
        items = path.get("items", [])
        for it in items:
            if it[0] == "re":
                r = pymupdf.Rect(it[1]).normalize()
                if r.width >= MIN_RECT_SIDE and r.height >= MIN_RECT_SIDE:
                    rects.append((r.x0, r.y0, r.x1, r.y1))
                    quads.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)])
            elif it[0] == "qu":
                q = it[1]
                quads.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)])
        lines = [it for it in items if it[0] == "l"]
        if len(lines) == 4 and len(items) == 4:
            q = _closed_quad(lines)
            if q:
                xs, ys = [p[0] for p in q], [p[1] for p in q]
                if max(xs) - min(xs) >= MIN_RECT_SIDE and max(ys) - min(ys) >= MIN_RECT_SIDE:
                    quads.append(q)
                    if len({round(x, 1) for x in xs}) == 2 and len({round(y, 1) for y in ys}) == 2:
                        rects.append((min(xs), min(ys), max(xs), max(ys)))
    return rects, quads, len(paths)


def _shown(m: pymupdf.Matrix, b) -> BBox:
    r = pymupdf.Rect(b) * m
    return (r.x0, r.y0, r.x1, r.y1)


def read_page(page: pymupdf.Page) -> Page:
    """Everything is returned in the page as displayed: a sheet stored portrait
    with /Rotate 90 is read landscape, the way the drawing is meant to be read."""
    m = page.rotation_matrix
    rot = pymupdf.Matrix(m.a, m.b, m.c, m.d, 0, 0)

    def turn(d) -> tuple[float, float]:
        p = pymupdf.Point(d) * rot
        return (round(p.x, 6), round(p.y, 6))

    spans: list[tuple[BBox, str, float, tuple[float, float]]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                spans.append((_shown(m, s["bbox"]), s["font"], s["size"], turn(line["dir"])))

    grouped: dict[tuple[int, int], list[Word]] = {}
    for x0, y0, x1, y1, text, bno, lno, _wno in page.get_text("words"):
        bbox = _shown(m, (x0, y0, x1, y1))
        font, size, d = _span_info(spans, bbox)
        grouped.setdefault((bno, lno), []).append(Word(text, bbox, font, size, d))

    lines: list[Line] = []
    for words in grouped.values():
        bbox = (
            min(w.bbox[0] for w in words), min(w.bbox[1] for w in words),
            max(w.bbox[2] for w in words), max(w.bbox[3] for w in words),
        )
        lines.append(Line(" ".join(w.text for w in words), bbox, words, words[0].font))
    lines.sort(key=lambda ln: (round(ln.bbox[1], 0), ln.bbox[0]))

    rects, quads, n_paths = _boxes(page)
    if page.rotation:
        rects = [_shown(m, r) for r in rects]
        quads = [[tuple(pymupdf.Point(p) * m) for p in q] for q in quads]
    words = [w for ln in lines for w in ln.words]
    dimlike = sum(1 for w in words if _DIMLIKE.match(w.text))
    if len(words) < MIN_VECTOR_WORDS and page.get_images(full=False):
        layer = "image"
    elif n_paths > 300 and dimlike < max(4, n_paths // 200):
        layer = "outlined"
    else:
        layer = "text"
    r = page.rect
    return Page(
        index=page.number, width=r.width, height=r.height, lines=lines,
        rects=rects, quads=quads, layer=layer, scanned=layer != "text",
    )


def read_pdf(path: str | Path) -> list[Page]:
    with pymupdf.open(str(path)) as doc:
        return [read_page(p) for p in doc]


def render_page(path: str | Path, index: int, dpi: int = 150) -> tuple[bytes, float]:
    """PNG bytes of one page, and the image-pixels-per-point scale."""
    with pymupdf.open(str(path)) as doc:
        pix = doc[index].get_pixmap(dpi=dpi)
        return pix.tobytes("png"), dpi / 72.0
