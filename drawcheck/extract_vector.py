"""Pages of positioned text -> annotations, from the PDF text layer only.

Order matters: title block and notes are claimed first, then feature control
frames, then datum symbols, threads, finishes and finally dimensions, so a
number in the title block is never read as a dimension and a datum letter in
a frame is never read as a datum feature symbol.

Text on drawings is often rotated (aligned dimensions, 3D/PMI views), so
grouping happens in each word's own writing frame: u along the text, v across.
"""
from __future__ import annotations

import math
import re

from . import parse
from .model import Annotation, BBox, Drawing, Line, Page, Word

#: Text closer than this to the page edge is border zoning (A-H, 1-8), not a callout.
EDGE_MARGIN = 22.0
#: A datum feature symbol or basic-dimension box is at most this big (points).
MAX_SYMBOL_BOX = 40.0


# ------------------------------------------------------------------ geometry

def _union(boxes: list[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _contains(outer: BBox, inner: BBox, pad: float = 1.0) -> bool:
    return (outer[0] - pad <= inner[0] and outer[1] - pad <= inner[1]
            and outer[2] + pad >= inner[2] and outer[3] + pad >= inner[3])


def _center(b: BBox) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _height(b: BBox) -> float:
    return max(b[3] - b[1], 1.0)


def _same_row(a: BBox, b: BBox) -> bool:
    return abs(_center(a)[1] - _center(b)[1]) < 0.5 * max(_height(a), _height(b))


def _overlap_x(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2]


def _angle(w: Word) -> int:
    """Writing direction in whole degrees, folded so 180 == 0."""
    return round(math.degrees(math.atan2(w.dir[1], w.dir[0]))) % 180


class _Frame:
    """A word's position in its own writing frame."""
    __slots__ = ("w", "u0", "u1", "v", "h")

    def __init__(self, w: Word):
        self.w = w
        c, s = w.dir
        cx, cy = _center(w.bbox)
        u = cx * c + cy * s
        self.v = -cx * s + cy * c
        if abs(s) < 0.02:                         # horizontal: the bbox is exact
            self.u0, self.u1, self.h = w.bbox[0], w.bbox[2], _height(w.bbox)
        else:                                     # rotated: estimate length from the font size
            size = w.size or 8.0
            half = 0.27 * size * max(len(w.text), 1)
            self.u0, self.u1, self.h = u - half, u + half, size


def _point_in_quad(p: tuple[float, float], q: list[tuple[float, float]]) -> bool:
    sign = 0
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if abs(cross) < 1e-9:
            continue
        s = 1 if cross > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _quad_side(q: list[tuple[float, float]]) -> float:
    return max(math.dist(q[i], q[(i + 1) % 4]) for i in range(4))


# ------------------------------------------------------------------ preparation

def _translate_gdt_fonts(page: Page) -> None:
    for ln in page.lines:
        changed = False
        for w in ln.words:
            if "gdt" in w.font.lower():
                w.text = parse.translate_gdt_font(w.text)
                changed = True
        if changed:
            ln.text = " ".join(w.text for w in ln.words)


_DEV = re.compile(rf"[+-]\s*{parse.NUM}|0")


def _merge_stacks(page: Page) -> None:
    """A stacked tolerance is two small texts, upper deviation over lower,
    starting at the same place along the text. Merge them into one word
    '+0.021/0', top first, so row grouping cannot reorder them."""
    cands = [_Frame(w) for ln in page.lines for w in ln.words if _DEV.fullmatch(w.text)]
    gone: set[int] = set()
    for top in sorted(cands, key=lambda f: f.v):
        if id(top.w) in gone:
            continue
        for bot in cands:
            if bot is top or id(bot.w) in gone or _angle(bot.w) != _angle(top.w):
                continue
            # Rotated words have estimated starts and "-" is narrower than "+": NIST's rotated
            # stacks sit 6.4-7.0 pt apart at 12 pt, just outside the old 0.5 h.
            if (abs(bot.u0 - top.u0) < max(3.0, 0.65 * top.h) and 0 < bot.v - top.v <= 1.6 * top.h
                    and (top.w.text.startswith(("+", "-")) or bot.w.text.startswith(("+", "-")))):
                top.w.text = f"{top.w.text}/{bot.w.text}"
                top.w.bbox = _union([top.w.bbox, bot.w.bbox])
                gone.add(id(bot.w))
                break
    if gone:
        for ln in page.lines:
            ln.words = [w for w in ln.words if id(w) not in gone]
            ln.text = " ".join(w.text for w in ln.words)
        page.lines = [ln for ln in page.lines if ln.words]


def _segments(words: list[Word]) -> list[list[Word]]:
    """Words on one visual row (in their own writing direction), split where
    the gap is wider than a word space. PDFs often write each cell of a frame
    or each part of a dimension as its own text object, so the PDF's own
    lines are not enough."""
    by_angle: dict[int, list[_Frame]] = {}
    for w in words:
        by_angle.setdefault(_angle(w), []).append(_Frame(w))
    segs: list[list[Word]] = []
    for frames in by_angle.values():
        rows: list[list[_Frame]] = []
        for f in sorted(frames, key=lambda f: (f.v, f.u0)):
            for row in rows:
                if abs(row[0].v - f.v) < 0.5 * max(row[0].h, f.h):
                    row.append(f)
                    break
            else:
                rows.append([f])
        for row in rows:
            row.sort(key=lambda f: f.u0)
            cur = [row[0]]
            for f in row[1:]:
                if f.u0 - cur[-1].u1 > max(14.0, 1.6 * f.h):
                    segs.append([x.w for x in cur])
                    cur = [f]
                else:
                    cur.append(f)
            segs.append([x.w for x in cur])
    return segs


def _split_at_borders(page: Page, seg: list[Word]) -> list[list[Word]]:
    """Split horizontal text where a drawn cell border runs between two words,
    so the values of neighbouring title-block cells stay apart."""
    if len(seg) < 2 or abs(seg[0].dir[1]) > 0.02:
        return [seg]
    parts, cur = [], [seg[0]]
    for a, b in zip(seg, seg[1:]):
        cy = _center(a.bbox)[1]
        lo, hi = a.bbox[2] - 0.5, b.bbox[0] + 0.5
        # Only cells much taller than the text (title block); a frame cell hugs its text.
        tall = 2.2 * _height(a.bbox)
        border = any(r[1] <= cy <= r[3] and r[3] - r[1] > tall and (lo <= r[0] <= hi or lo <= r[2] <= hi)
                     for r in page.rects)
        if border:
            parts.append(cur)
            cur = [b]
        else:
            cur.append(b)
    parts.append(cur)
    return parts


def _visual_lines(page: Page) -> list[Line]:
    """Lines rebuilt from word positions. A PDF's own line grouping follows the
    order the CAD system wrote text objects in, which can join a drawing
    title to a note on the other side of the page."""
    out = []
    for seg in _segments([w for ln in page.lines for w in ln.words]):
        for part in _split_at_borders(page, seg):
            out.append(Line(_seg_text(part), _seg_bbox(part), part, part[0].font))
    out.sort(key=lambda ln: (round(ln.bbox[1], 0), ln.bbox[0]))
    return out


def _seg_text(seg: list[Word]) -> str:
    return " ".join(w.text for w in seg)


def _seg_bbox(seg: list[Word]) -> BBox:
    return _union([w.bbox for w in seg])


# ------------------------------------------------------------------ title block

def _smallest_rect(rects: list[BBox], inner: BBox) -> BBox | None:
    best = None
    for r in rects:
        if _contains(r, inner) and (r[2] - r[0]) < 400 and (r[3] - r[1]) < 120:
            if best is None or (r[2] - r[0]) * (r[3] - r[1]) < (best[2] - best[0]) * (best[3] - best[1]):
                best = r
    return best


def _title_block(page: Page, drawing: Drawing, used: set[int]) -> list[BBox]:
    """Find labelled fields. Returns the boxes the title block occupies."""
    label_lines: list[tuple[Line, str, str]] = []
    for ln in page.lines:
        if len(ln.text) > 60:
            continue
        hit = parse.match_label(ln.text)
        if hit:
            label_lines.append((ln, hit[0], hit[1]))
    # A title block has several labels; a single "DATE" in a note is not one.
    if len(label_lines) < 3:
        return []
    label_ids = {id(ln) for ln, _, _ in label_lines}
    region: list[BBox] = []
    for ln, field, rest in label_lines:
        value, vbox = rest, ln.bbox
        used.update(id(w) for w in ln.words)
        if not value:
            cell = _smallest_rect(page.rects, ln.bbox)
            cands: list[Line] = []
            if cell:
                cands = [o for o in page.lines if o is not ln and id(o) not in label_ids
                         and _contains(cell, o.bbox)]
            if not cands:
                right = [o for o in page.lines if o is not ln and id(o) not in label_ids
                         and _same_row(o.bbox, ln.bbox) and 0 <= o.bbox[0] - ln.bbox[2] < 120]
                below = [o for o in page.lines if o is not ln and id(o) not in label_ids
                         and _overlap_x(o.bbox, ln.bbox) and 0 <= o.bbox[1] - ln.bbox[3] < 1.6 * _height(ln.bbox)]
                cands = sorted(right, key=lambda o: o.bbox[0])[:1] or sorted(below, key=lambda o: o.bbox[1])[:1]
            if cands:
                value = " ".join(o.text for o in cands)
                vbox = _union([o.bbox for o in cands])
                for o in cands:
                    used.update(id(w) for w in o.words)
            region.append(cell or ln.bbox)
        region.extend([ln.bbox, vbox])
        if field not in drawing.title or not drawing.title[field].text:
            ann = Annotation("title_field", value, page.index, vbox, "vector",
                             {"field": field, "label_bbox": ln.bbox})
            drawing.title[field] = ann
            drawing.annotations.append(ann)
    return region


# ------------------------------------------------------------------ notes and statements

_NOTE_HEAD = re.compile(r"^\s*(GENERAL\s+)?NOTES?\b[^.]{0,40}:?\s*$", re.I)
_NOTE_ITEM = re.compile(r"^\s*(\d{1,2})[.)]\s*\S")


def statement_data(text: str) -> dict:
    """Facts a note states about the whole drawing."""
    data: dict = {}
    gt = parse.parse_general_tolerance(text)
    if gt:
        data["general_tolerance"] = gt
    stds = parse.find_standards(text)
    if stds:
        data["standards"] = stds
    units = parse.parse_units(text)
    if units:
        data["units"] = units
    t = text.upper()
    if re.search(r"\b(DEBURR|BREAK\s+(ALL\s+)?(SHARP\s+)?EDGES|REMOVE\s+(ALL\s+)?BURRS|EDGES?\s+.*CHAMFER)", t):
        data["edge_note"] = True
    if re.search(r"\b(HARDEN|HARDENED|CASE\s+HARDEN|CARBURI[SZ]E|NITRIDE|INDUCTION|QUENCH|TEMPER|HEAT\s+TREAT)", t):
        data["heat_treatment"] = True
        data["hardness"] = bool(re.search(r"\b\d{2,3}\s*-?\s*\d{0,3}\s*(HRC|HRB|HB|HBW|HV)\b|\b(HRC|HB|HV)\s*\d", t))
    if re.search(r"\b(SURFACE\s+FINISH|ROUGHNESS|ALL\s+OVER)\b", t):
        sf = parse.parse_surface(text, finish_context=True)
        if sf:
            data["general_finish"] = sf
    return data


def _note_items(lines: list[Line]) -> list[list[Line]]:
    """Join wrapped note lines: a new item starts at '1.', '2)' ...; other lines continue it."""
    # Pieces of one printed row (split by a symbol drawn as geometry) are one row.
    rows: list[list[Line]] = []
    for ln in sorted(lines, key=lambda ln: _center(ln.bbox)[1]):
        if rows and _same_row(rows[-1][0].bbox, ln.bbox):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    items: list[list[Line]] = []
    for row in rows:
        row.sort(key=lambda ln: ln.bbox[0])
        if _NOTE_ITEM.match(" ".join(ln.text for ln in row)) or not items:
            items.append(list(row))
        else:
            items[-1].extend(row)
    return items


def _notes(page: Page, drawing: Drawing, used: set[int], title_region: list[BBox]) -> list[BBox]:
    region: list[BBox] = []
    in_title = lambda b: any(_contains(r, b, pad=2) for r in title_region)  # noqa: E731
    head = next((ln for ln in page.lines if len(ln.text) < 50 and _NOTE_HEAD.match(ln.text)), None)
    items: list[list[Line]] = []
    if head:
        used.update(id(w) for w in head.words)
        region.append(head.bbox)
        # A heading like "NOTES (UNLESS OTHERWISE SPECIFIED):" carries no tolerance by itself.
        block: list[Line] = []
        last = head
        for ln in sorted(page.lines, key=lambda ln: ln.bbox[1]):
            if ln.bbox[1] <= head.bbox[1] or id(ln.words[0]) in used or _near_edge(page, ln.bbox):
                continue
            if abs(ln.bbox[0] - head.bbox[0]) > 60:
                continue
            if ln.bbox[1] - last.bbox[3] > 2.5 * _height(last.bbox):
                break
            block.append(ln)
            last = ln
        items.extend(_note_items(block))
    claimed = {id(ln) for it in items for ln in it}
    # Statements anywhere (title block cells, side notes) count too.
    for ln in page.lines:
        if id(ln) in claimed or (head is not None and ln is head):
            continue
        if statement_data(ln.text) or parse.parse_projection(ln.text):
            items.append([ln])
    for item in items:
        text = " ".join(ln.text for ln in item)
        bbox = _union([ln.bbox for ln in item])
        data = statement_data(text)
        proj = parse.parse_projection(text)
        if proj:
            drawing.annotations.append(Annotation("projection", text, page.index, bbox, "vector", {"method": proj}))
        m = _NOTE_ITEM.match(text)
        if m:
            data["number"] = int(m.group(1))
        data["in_title_block"] = in_title(bbox)
        if data.get("general_finish") is None:
            sf = parse.parse_surface(text, finish_context=True)
            if sf:
                drawing.annotations.append(Annotation("surface_finish", text, page.index, bbox,
                                                      "vector", {**sf, "general": True}))
        th = parse.parse_thread(text)
        if th:
            drawing.annotations.append(Annotation("thread", text, page.index, bbox, "vector", th))
        drawing.annotations.append(Annotation("note", text, page.index, bbox, "vector", data))
        for ln in item:
            used.update(id(w) for w in ln.words)
        region.append(bbox)
    return region


# ------------------------------------------------------------------ frames, datums, callouts

def _frames(page: Page, drawing: Drawing, segs: list[list[Word]], used: set[int]) -> None:
    headless = 0
    for seg in segs:
        seg = [w for w in seg if id(w) not in used]
        for i, w in enumerate(seg):
            if not any(c in parse.GDT_SYMBOLS for c in w.text[:1]):
                continue
            # "2X" written just before the frame belongs to it
            start = i - 1 if i > 0 and re.fullmatch(r"\d+[xX]", seg[i - 1].text) else i
            part = seg[start:]
            text = _seg_text(part)
            fcf = parse.parse_fcf(text)
            # Trailing words that are not part of a frame (e.g. a neighbouring note) - trim.
            while fcf is None and len(part) > 2:
                part = part[:-1]
                text = _seg_text(part)
                fcf = parse.parse_fcf(text)
            bbox = _seg_bbox(part)
            if fcf:
                drawing.annotations.append(Annotation("gdt_frame", text, page.index, bbox, "vector", fcf))
            else:
                drawing.warnings.append(f"page {page.index + 1}: unreadable feature control frame '{text}'")
                drawing.annotations.append(Annotation("gdt_frame", text, page.index, bbox, "vector",
                                                      {"unparsed": True}))
            used.update(id(x) for x in part)
            break
        else:
            if not seg:
                continue
            # No symbol in the text layer: the CAD system drew it as geometry.
            # Tolerance + datum letters is still a frame; read what is there.
            text = _seg_text(seg)
            fcf = parse.parse_headless_fcf(text)
            if fcf:
                drawing.annotations.append(Annotation("gdt_frame", text, page.index, _seg_bbox(seg), "vector", fcf))
                used.update(id(x) for x in seg)
                headless += 1
    if headless:
        drawing.warnings.append(
            f"page {page.index + 1}: {headless} feature control frame(s) have their symbol drawn as geometry; "
            f"datum references were checked, characteristic rules need the vision reader")


def _boxed(page: Page, w: Word) -> BBox | None:
    c = _center(w.bbox)
    for r in page.rects:
        if (r[2] - r[0]) <= MAX_SYMBOL_BOX and (r[3] - r[1]) <= MAX_SYMBOL_BOX and _contains(r, w.bbox, pad=0.5):
            return r
    for q in page.quads:
        if _quad_side(q) <= MAX_SYMBOL_BOX and _point_in_quad(c, q):
            return _union([(p[0], p[1], p[0], p[1]) for p in q])
    return None


def _datums_and_basics(page: Page, drawing: Drawing, used: set[int]) -> None:
    for ln in page.lines:
        for w in ln.words:
            if id(w) in used:
                continue
            box = _boxed(page, w)
            if box is None:
                continue
            if re.fullmatch(r"[A-Z]", w.text):
                drawing.annotations.append(Annotation("datum_feature", w.text, page.index, box, "vector",
                                                      {"letter": w.text}))
                used.add(id(w))
            elif re.fullmatch(parse.NUM + "°?", w.text) or re.fullmatch("Ø" + parse.NUM, w.text):
                d = parse.parse_dimension(w.text)
                if d:
                    d["basic"] = True
                    drawing.annotations.append(Annotation("dimension", w.text, page.index, box, "vector", d))
                    used.add(id(w))
        m = re.match(r"^DATUM\s+([A-Z])\b", ln.text.upper())
        if m and id(ln.words[0]) not in used:
            drawing.annotations.append(Annotation("datum_feature", m.group(1), page.index, ln.bbox, "vector",
                                                  {"letter": m.group(1)}))
            used.update(id(w) for w in ln.words)


def _near_edge(page: Page, b: BBox) -> bool:
    return (b[0] < EDGE_MARGIN or b[1] < EDGE_MARGIN
            or b[2] > page.width - EDGE_MARGIN or b[3] > page.height - EDGE_MARGIN)


def _callouts(page: Page, drawing: Drawing, segs: list[list[Word]], used: set[int],
              excluded: list[BBox]) -> None:
    for seg in segs:
        seg = [w for w in seg if id(w) not in used]
        if not seg:
            continue
        box = _seg_bbox(seg)
        if _near_edge(page, box) or any(_contains(r, box, pad=2) for r in excluded):
            continue
        text = _seg_text(seg)
        th = parse.parse_thread(text)
        if th:
            drawing.annotations.append(Annotation("thread", text, page.index, box, "vector", th))
            used.update(id(w) for w in seg)
            continue
        sf = parse.parse_surface(text)
        if sf:
            drawing.annotations.append(Annotation("surface_finish", text, page.index, box, "vector", sf))
            used.update(id(w) for w in seg)
            continue
        d = parse.parse_dimension(text)
        if d is None:
            continue
        # A bare 4-digit year is not a dimension we can judge.
        if d["tol_type"] == "none" and re.fullmatch(r"(19|20)\d\d", d["raw_nominal"]):
            continue
        drawing.annotations.append(Annotation("dimension", text, page.index, box, "vector", d))
        used.update(id(w) for w in seg)


# ------------------------------------------------------------------ entry

def extract(drawing: Drawing) -> Drawing:
    for page in drawing.pages:
        # An outlined page still has some real text (often the notes); read it.
        # Its callouts are geometry, so the page stays marked for the vision reader.
        if page.layer == "image":
            continue
        _translate_gdt_fonts(page)
        _merge_stacks(page)
        page.lines = _visual_lines(page)
        used: set[int] = set()
        title_region = _title_block(page, drawing, used)
        if title_region:
            tb = _union(title_region)
            # The whole block (logos, revision table, unlabelled cells), when it is compact.
            if (tb[2] - tb[0]) * (tb[3] - tb[1]) < 0.35 * page.width * page.height:
                title_region = [tb]
        notes_region = _notes(page, drawing, used, title_region)
        # Frames before datum symbols: a datum letter in a frame cell is boxed too.
        segs = _segments([w for ln in page.lines for w in ln.words if id(w) not in used])
        _frames(page, drawing, segs, used)
        _datums_and_basics(page, drawing, used)
        segs = _segments([w for ln in page.lines for w in ln.words if id(w) not in used])
        _callouts(page, drawing, segs, used, title_region + notes_region)
    drawing.extractors.append("vector")
    return drawing
