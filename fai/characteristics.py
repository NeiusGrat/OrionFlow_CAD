"""Drawing annotations -> numbered, toleranced characteristics (the Form 3 rows).

Every characteristic says where its limits came from:

    drawing            the callout carries its own tolerance or limits
    iso286             an ISO 286 fit class on the callout, looked up
    general_note       untoleranced; the drawing's general-tolerance note applies
    selected_class     untoleranced; the class chosen at upload applies (no note on the drawing)
    gdt                a geometric tolerance: zone 0 .. tolerance
    none               no tolerance could be established -> it must be queried

Balloon numbers follow reading order per sheet (top band to bottom, left to
right), so the same drawing always balloons the same way.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from drawcheck.model import Annotation, Drawing

from .tolerances import fit_limits, general_angle, general_linear, general_radius

GDT_WORD = {
    "flatness": "Flatness", "straightness": "Straightness", "circularity": "Circularity",
    "cylindricity": "Cylindricity", "profile_line": "Profile of a line", "profile_surface": "Profile of a surface",
    "perpendicularity": "Perpendicularity", "parallelism": "Parallelism", "angularity": "Angularity",
    "position": "Position", "concentricity": "Concentricity", "symmetry": "Symmetry",
    "circular_runout": "Circular runout", "total_runout": "Total runout",
}


@dataclass
class Characteristic:
    no: int
    page: int
    zone: str
    kind: str                       # dimension | thread | gdt | surface | note
    type: str                       # Linear | Diameter | Radius | Angle | Basic | Reference | Thread | <GD&T> | Ra | Note
    designator: str                 # the callout as printed
    requirement: str                # the requirement in words, as it goes on Form 3
    nominal: float | None = None
    tol_minus: float | None = None
    tol_plus: float | None = None
    lower: float | None = None
    upper: float | None = None
    unit: str = "mm"
    count: int = 1
    pitch: float | None = None      # threads: pitch in mm when the callout states it
    depth: float | None = None      # threads / holes: depth in mm when stated
    tol_source: str = "none"
    tol_note: str = ""             # why no tolerance could be established
    confidence: str = "vector"      # vector | vision | confirmed (from the reader)
    bbox: tuple = ()
    balloon: tuple = ()             # (x, y) balloon centre in page points
    inspect: bool = True            # False for reference / basic dimensions
    method: str = ""                # suggested inspection method
    # filled by the cross-check
    cad_value: float | None = None
    cad_count: int | None = None
    cad_nodes: list[str] = field(default_factory=list)
    cad_status: str = ""            # agrees | deviates | count | not_found | not_measurable | no_model
    cad_note: str = ""
    # filled by the reviewer
    result: str = ""                # measured value(s) as written by the inspector
    status: str = "open"            # open | pass | fail | accepted | waived
    nc_number: str = ""
    tooling: str = ""
    reviewer_note: str = ""
    edited: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        d["balloon"] = list(self.balloon)
        return d


def _fmt(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


# ------------------------------------------------------------------ zones

_ZONE_NUM = re.compile(r"^\d{1,2}$")
_ZONE_LET = re.compile(r"^[A-HJ-NP-Z]$")


def zone_grid(page) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    """Zone labels printed along the border: columns (x, '1'..), rows (y, 'A'..)."""
    cols, rows = [], []
    edge_x, edge_y = page.width * 0.04, page.height * 0.04
    for ln in page.lines:
        t = ln.text.strip()
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if _ZONE_NUM.match(t) and (cy < edge_y or cy > page.height - edge_y):
            cols.append((cx, t))
        elif _ZONE_LET.match(t) and (cx < edge_x or cx > page.width - edge_x):
            rows.append((cy, t))
    dedupe = lambda xs: sorted({lab: v for v, lab in xs}.items(), key=lambda kv: kv[1])  # noqa: E731
    cols = [(v, k) for k, v in dedupe(cols)]
    rows = [(v, k) for k, v in dedupe(rows)]
    return (cols, rows) if len(cols) >= 2 and len(rows) >= 2 else ([], [])


def _nearest(v: float, marks: list[tuple[float, str]]) -> str:
    return min(marks, key=lambda m: abs(m[0] - v))[1]


def zone_of(bbox, grid) -> str:
    cols, rows = grid
    if not cols:
        return ""
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return f"{_nearest(cy, rows)}{_nearest(cx, cols)}"


# ------------------------------------------------------------------ general tolerance

def general_tolerance(d: Drawing) -> dict | None:
    for a in d.of("note"):
        g = a.data.get("general_tolerance")
        if g and g.get("linear_class"):
            return {**g, "text": a.text}
    return None


def drawing_units(d: Drawing) -> str:
    """'in' when a note or the title block says inches, else 'mm' (the default of ISO drawings)."""
    from drawcheck.parse import parse_units

    for a in d.of("note"):
        if a.data.get("units") == "inch":
            return "in"
    t = d.title.get("units")
    if t is not None and parse_units(t.text) == "inch":
        return "in"
    if units_stated(d):
        return "mm"
    # Not stated. Inch drawings print decimals without the leading zero (".250"); metric
    # drawings never do. Inferred, and reported as inferred by the pipeline.
    raws = [a.data.get("raw_nominal") or "" for a in d.of("dimension")]
    dotted = sum(1 for r in raws if r.startswith("."))
    return "in" if raws and dotted >= max(2, 0.5 * len(raws)) else "mm"


def units_stated(d: Drawing) -> bool:
    from drawcheck.parse import parse_units

    t = d.title.get("units")
    return any(a.data.get("units") for a in d.of("note")) or (t is not None and parse_units(t.text) is not None)


def general_profile(d: Drawing) -> str | None:
    """A note like "<profile frame> APPLIES TO ALL UNTOLERANCED SURFACES": the tolerance
    for every size the drawing leaves untoleranced. Returns the note text."""
    for a in d.of("note"):
        g = a.data.get("general_tolerance") or {}
        if g.get("standard") in ("untoleranced_note", "model_basic") and "UNTOLERANCED" in a.text.upper():
            return a.text
    return None


# ------------------------------------------------------------------ building rows

def _dimension(a: Annotation, gt_class: str | None, gt_source: str, units: str = "mm",
               profile_note: str | None = None) -> dict:
    x = a.data
    nom = x.get("nominal")
    prefix = x.get("prefix") or ""
    count = x.get("count") or 1
    if x.get("angle"):
        typ = "Angle"
    elif x.get("basic"):
        typ = "Basic"
    elif x.get("reference"):
        typ = "Reference"
    elif prefix in ("Ø", "⌀"):
        typ = "Diameter"
    elif prefix.upper().startswith("R") or prefix.upper() == "SR":
        typ = "Radius"
    else:
        typ = "Linear"
    row: dict[str, Any] = dict(kind="dimension", type=typ, nominal=nom, count=count,
                               unit="deg" if typ == "Angle" else units)
    tt = x.get("tol_type")
    if typ in ("Basic", "Reference"):
        row.update(inspect=False, tol_source="drawing",
                   requirement=f"{_fmt(nom)} {'BASIC' if typ == 'Basic' else 'REF'}",
                   method="verified through its feature control frame" if typ == "Basic" else "not inspected")
        return row
    lo = hi = None
    if tt in ("symmetric", "bilateral", "limits") and x.get("upper") is not None and x.get("lower") is not None:
        a1, a2 = float(x["upper"]), float(x["lower"])
        lo, hi = min(a1, a2), max(a1, a2)
        row["tol_source"] = "drawing"
    elif tt == "fit" and x.get("fit") and nom is not None:
        fit = x["fit"]
        parts = fit.split("/")
        lim = fit_limits(nom, parts[0]) if len(parts) == 1 else None
        if lim:
            lo, hi = lim
            row["tol_source"] = "iso286"
            row["fit"] = fit
        else:
            row["tol_note"] = (f"fit {fit} is a pair, not one feature's class" if len(parts) > 1
                               else f"fit class {fit} is outside the ISO 286 table used")
    elif tt in ("max", "min") and nom is not None:
        row["tol_source"] = "drawing"
        row["one_sided"] = tt
    elif tt == "none" and nom is not None and profile_note and typ != "Angle":
        # Controlled by the general profile tolerance, not by +/- limits on the size.
        row["tol_source"] = "general_profile"
        row["tol_note"] = "controlled by the general profile note: " + re.sub(r"^\d+\.\s*", "", profile_note)[:90]
    elif tt == "none" and nom is not None and gt_class and units == "mm":
        # ISO 2768 is a metric table: never applied to an inch drawing.
        t = (general_angle(gt_class) if typ == "Angle" else
             general_radius(nom, gt_class) if typ == "Radius" else general_linear(nom, gt_class))
        if t is not None:
            lo, hi = -t, t
            row["tol_source"] = gt_source
    elif tt == "none" and nom is not None and gt_class and units == "in":
        row["tol_note"] = "ISO 2768 is metric and does not apply to an inch drawing"
    if lo is not None and nom is not None:
        row.update(tol_minus=round(lo, 6), tol_plus=round(hi, 6),
                   lower=round(nom + lo, 6), upper=round(nom + hi, 6))
    elif row.get("one_sided") == "max":
        row.update(upper=nom)
    elif row.get("one_sided") == "min":
        row.update(lower=nom)
    lim = (f"{_fmt(row.get('lower'))} – {_fmt(row.get('upper'))}" if row.get("lower") is not None
           and row.get("upper") is not None else "")
    unit = "°" if typ == "Angle" else f" {units}"
    what = {"Diameter": "Diameter", "Radius": "Radius", "Angle": "Angle", "Linear": "Length"}[typ]
    tail = (f", limits {lim}{unit}" if lim else ", per the general profile tolerance"
            if row.get("tol_source") == "general_profile" else ", no tolerance established")
    row["requirement"] = f"{f'{count}X ' if count > 1 else ''}{what} {_fmt(nom)}{unit}" + tail
    row["method"] = {"Diameter": "bore gauge / CMM", "Radius": "radius gauge / CMM",
                     "Angle": "protractor / CMM"}.get(typ, "caliper / height gauge / CMM")
    return row


def _thread(a: Annotation) -> dict:
    x = a.data
    depth = f", depth {_fmt(x['depth'])} mm" if x.get("depth") else (", through" if x.get("thru") else "")
    callout = re.split(r"\s*[↧▽]|\s+DEPTH|\s+DP|\s+THRU", a.text, maxsplit=1, flags=re.I)[0].strip()
    cls = f" class {x['class']}" if x.get("class") and x["class"] not in callout else ""
    return dict(kind="thread", type="Thread", count=x.get("count") or 1, inspect=True, tol_source="drawing",
                nominal=x.get("size") if isinstance(x.get("size"), (int, float)) else None, pitch=x.get("pitch"), depth=x.get("depth"),
                requirement=f"Thread {callout}{cls}{depth}", method="thread plug / ring gauge GO/NO-GO")


def _gdt(a: Annotation) -> dict:
    x = a.data
    name = GDT_WORD.get(x.get("characteristic") or "", (x.get("characteristic") or "Geometric").replace("_", " ").title())
    tol = x.get("tolerance")
    datums = "-".join(x.get("datums") or [])
    zone = f"{'Ø' if x.get('diameter_zone') else ''}{_fmt(tol)}"
    req = f"{name} within {zone} mm" + (f" to datums {datums}" if datums else "")
    if x.get("material"):
        req += f" at {'MMC' if x['material'] == 'M' else 'LMC' if x['material'] == 'L' else x['material']}"
    return dict(kind="gdt", type=name, nominal=0.0 if tol is not None else None, lower=0.0 if tol is not None else None,
                upper=tol, tol_minus=0.0 if tol is not None else None, tol_plus=tol,
                tol_source="gdt" if tol is not None else "none", requirement=req, method="CMM")


def _surface(a: Annotation) -> dict:
    x = a.data
    v = x.get("value")
    return dict(kind="surface", type=x.get("param") or "Ra", nominal=None, upper=v, tol_source="drawing",
                requirement=f"Surface roughness {x.get('param') or 'Ra'} ≤ {_fmt(v)} µm", unit="µm",
                method="profilometer")


#: notes that state an inspectable requirement
_NOTE_KEYS = ("edge_note", "heat_treatment", "hardness", "general_finish", "plating", "marking")


def _note(a: Annotation) -> dict | None:
    if a.data.get("in_title_block") or not any(a.data.get(k) for k in _NOTE_KEYS):
        return None
    text = re.sub(r"^\d+\.\s*", "", a.text)
    # the reader can glue a following projection statement onto the last note
    text = re.sub(r"\s*(FIRST|THIRD)\s+ANGLE\s+PROJECTION\s*$", "", text, flags=re.I)
    return dict(kind="note", type="Note", requirement=text, tol_source="drawing", method="visual / certificate")


def build(d: Drawing, selected_class: str | None = None) -> tuple[list[Characteristic], dict]:
    """Characteristics in balloon order, and how the general tolerance was resolved."""
    gt = general_tolerance(d)
    if gt:
        cls, src = gt["linear_class"], "general_note"
    elif selected_class:
        cls, src = selected_class, "selected_class"
    else:
        cls, src = None, "none"
    units = drawing_units(d)
    profile_note = general_profile(d)
    grids = {p.index: zone_grid(p) for p in d.pages}
    rows: list[tuple[Annotation, dict]] = []
    for a in d.annotations:
        r = (_dimension(a, cls, src, units, profile_note) if a.kind == "dimension" and a.data.get("nominal") is not None else
             _thread(a) if a.kind == "thread" else
             _gdt(a) if a.kind == "gdt_frame" else
             _surface(a) if a.kind == "surface_finish" else
             _note(a) if a.kind == "note" else None)
        if r:
            rows.append((a, r))
    # reading order: 40-point bands top to bottom, left to right inside a band
    rows.sort(key=lambda ar: (ar[0].page, round(ar[0].bbox[1] / 40), ar[0].bbox[0]))
    out: list[Characteristic] = []
    seen: set = set()
    for a, r in rows:
        key = (a.page, a.text, tuple(round(v) for v in a.bbox))
        if key in seen:                       # the same callout read twice (text + vision)
            continue
        seen.add(key)
        extra = {k: r.pop(k) for k in ("fit", "tol_note", "one_sided") if k in r}
        c = Characteristic(no=len(out) + 1, page=a.page, zone=zone_of(a.bbox, grids.get(a.page, ([], []))),
                           designator=a.text, confidence=a.source, bbox=tuple(round(v, 2) for v in a.bbox),
                           balloon=(round(a.bbox[0] - 11, 2), round(a.bbox[1] + min((a.bbox[3] - a.bbox[1]) / 2, 6.0), 2)), **r)
        c.tol_note = extra.get("tol_note", "")
        out.append(c)
    _spread_balloons(out)
    for c in out:
        if c.kind == "gdt":
            c.unit = units
            c.requirement = c.requirement.replace(" mm", f" {units}")
    info = {"general_tolerance": gt, "applied_class": cls if units == "mm" else None,
            "applied_source": src if units == "mm" else ("general_profile" if profile_note else "none"),
            "units": units, "units_stated": units_stated(d), "general_profile": profile_note}
    return out, info


BALLOON_GAP = 19.0      # points between balloon centres (balloons are ~15 pt across)


def _spread_balloons(chars: list[Characteristic]) -> None:
    """Move a balloon left until it clears every balloon already placed on its
    sheet. Callouts on adjacent lines (a notes block) otherwise stack exactly."""
    placed: dict[int, list[tuple[float, float]]] = {}
    for c in chars:
        x, y = c.balloon
        mine = placed.setdefault(c.page, [])
        for _ in range(12):
            if all((x - px) ** 2 + (y - py) ** 2 >= BALLOON_GAP ** 2 for px, py in mine):
                break
            x -= BALLOON_GAP
        c.balloon = (round(max(x, 8.0), 2), y)
        mine.append(c.balloon)
