"""Cross-checks, all arithmetic: drawing vs CAD, drawing vs BOM/PO, and the
drawing against itself (drawcheck's rules: missing tolerances, reversed limits,
undefined datums...).

Severity is a property of the consequence, and is shown in the UI by shape:

    critical   the part cannot be accepted as documented: the model is outside
               the drawing's limits, the PO revision is not the drawing's, a
               callout cannot be inspected as written
    major      someone has to decide: a feature count differs, a material
               differs, a size has no tolerance
    minor      worth recording: a model value inside limits but off nominal, a
               dimension the model could not locate
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

from .characteristics import Characteristic, _fmt
from .measure import Measurement

SEVERITIES = ("critical", "major", "minor")
DRAWCHECK_SEVERITY = {"error": "critical", "warning": "major", "info": "minor"}


@dataclass
class Finding:
    id: str
    severity: str
    kind: str                       # cad | bom | drawing | tolerance
    title: str
    message: str
    char_no: int | None = None
    drawing_value: str = ""
    cad_value: str = ""
    rule: str = ""
    page: int | None = None
    bbox: list = field(default_factory=list)
    evidence: str = ""
    cad_nodes: list[str] = field(default_factory=list)
    query: str = ""                 # the question to send the customer, when there is one
    decision: str = ""              # "" | accepted | rejected | ignored
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _fid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


# ------------------------------------------------------------------ drawing vs CAD

#: a candidate this far from nominal is "the same feature, different size";
#: further than this it is a different feature and the dimension is unlocated.
def _near(nominal: float) -> float:
    return max(1.0, 0.08 * nominal)


def _within(c: Characteristic, v: float) -> bool | None:
    if c.lower is None and c.upper is None:
        return None
    eps = 1e-6
    return (c.lower is None or v >= c.lower - eps) and (c.upper is None or v <= c.upper + eps)


def _metric_tap_sizes(size: float, pitch: float | None) -> list[float]:
    p = pitch or {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0, 20: 2.5}.get(int(size), 0)
    return [size, round(size - p, 3), round(size - 1.0825 * p, 3)] if p else [size]


class _Scaled:
    """A characteristic seen in millimetres (the model's unit), whatever the drawing uses."""

    def __init__(self, c: Characteristic):
        self.c = c
        self.k = 25.4 if c.unit == "in" else 1.0
        sc = lambda v: None if v is None else v * self.k  # noqa: E731
        self.nominal, self.lower, self.upper = sc(c.nominal), sc(c.lower), sc(c.upper)
        self.depth = sc(c.depth)

    def show(self, mm: float | None) -> str:
        """A model value in the drawing's unit, the way the drawing would print it."""
        if mm is None:
            return ""
        return _fmt(round(mm / self.k, 4 if self.k != 1 else 4))

    def back(self, mm: float) -> float:
        return round(mm / self.k, 5)


def cad_check(chars: list[Characteristic], m: Measurement) -> list[Finding]:
    """Every comparison in millimetres (the model's unit); every value shown in the drawing's."""
    out: list[Finding] = []
    holes = [c for c in m.cylinders if c.kind in ("hole", "boss")]
    arcs = [c for c in m.cylinders if c.kind == "arc"]
    # threads last: a tapped hole's minor diameter is often within a few hundredths
    # of a clearance hole's, so threads may only take holes no other balloon claimed
    ordered = [c for c in chars if c.type != "Thread"] + [c for c in chars if c.type == "Thread"]
    claimed: set[str] = set()
    for c in ordered:
        s = _Scaled(c)
        if c.type == "Thread":
            _thread(s, [h for h in holes if h.id not in claimed], out)
            claimed.update(c.cad_nodes)
            continue
        if c.kind in ("gdt", "surface", "note"):
            c.cad_status, c.cad_note = "not_measurable", "a nominal model carries no form, finish or process"
            continue
        if c.type in ("Angle", "Reference"):
            c.cad_status, c.cad_note = "not_measurable", "not located in the model"
            continue
        if c.nominal is None:
            continue
        if c.type == "Diameter":
            _diameter(s, holes, out)
            claimed.update(c.cad_nodes)
        elif c.type == "Radius":
            _radius(s, arcs + holes, out)
        else:
            _linear(s, m, out)
    _counts(chars, out)
    return out


def _counts(chars: list[Characteristic], out: list[Finding]) -> None:
    """One hole size is often called out more than once (1X here, 2X there, a view
    later). Compare the *sum* of callouts per model hole group with the model."""
    groups: dict[tuple, list[Characteristic]] = {}
    for c in chars:
        if c.type == "Diameter" and c.cad_status in ("agrees", "deviates") and c.cad_nodes:
            groups.setdefault(tuple(sorted(c.cad_nodes)), []).append(c)
    for nodes, cs in groups.items():
        called = sum(c.count or 1 for c in cs)
        model = len(nodes)
        if called == model:
            continue
        first = cs[0]
        balloons = ", ".join(f"#{c.no}" for c in cs)
        if called > model:
            for c in cs:
                c.cad_status = "count" if c.cad_status == "agrees" else c.cad_status
            out.append(Finding(_fid("cad-count", first.designator, balloons), "major", "cad", "Feature count differs",
                               f"Balloon(s) {balloons} call for {called} x Ø{_fmt(first.nominal)} in total; the model "
                               f"has {model}.", first.no, f"{called}X", f"{model}X", "CAD-COUNT", first.page,
                               list(first.bbox), first.designator, list(nodes)))
        else:
            out.append(Finding(_fid("cad-count-under", first.designator, balloons), "minor", "cad",
                               "More holes in the model than called out",
                               f"The model has {model} x Ø{_fmt(first.nominal)}; balloon(s) {balloons} account for "
                               f"{called}. Check the rest are dimensioned (or covered by a note).", first.no,
                               f"{called}X", f"{model}X", "CAD-COUNT", first.page, list(first.bbox),
                               first.designator, list(nodes)))


def _within_mm(s: "_Scaled", v: float) -> bool | None:
    if s.lower is None and s.upper is None:
        return None
    eps = 1e-6 * max(1.0, s.k)
    return (s.lower is None or v >= s.lower - eps) and (s.upper is None or v <= s.upper + eps)


def _diameter(s: "_Scaled", holes, out: list[Finding]) -> None:
    c = s.c
    if not holes:
        c.cad_status, c.cad_note = "not_found", "the model has no cylindrical holes or bosses"
        return
    best = min(holes, key=lambda h: abs(h.diameter - s.nominal))
    if abs(best.diameter - s.nominal) > _near(s.nominal):
        c.cad_status = "not_found"
        c.cad_note = f"no hole or boss near Ø{_fmt(c.nominal)} (closest Ø{s.show(best.diameter)})"
        out.append(Finding(_fid("cad-nf", c.designator, c.no), "major", "cad", "Feature not in the model",
                           f"Ø{_fmt(c.nominal)} {c.unit} (balloon {c.no}) has no matching hole or boss in the model; "
                           f"the closest is Ø{s.show(best.diameter)} {c.unit}.", c.no, c.designator,
                           f"Ø{s.show(best.diameter)}", "CAD-DIA", c.page, list(c.bbox), c.designator))
        return
    same = [h for h in holes if abs(h.diameter - best.diameter) < 1e-3]
    c.cad_value, c.cad_count, c.cad_nodes = s.back(best.diameter), len(same), [h.id for h in same]
    if _within_mm(s, best.diameter) is False:
        c.cad_status = "deviates"
        c.cad_note = f"model Ø{s.show(best.diameter)} is outside {_fmt(c.lower)} – {_fmt(c.upper)} {c.unit}"
        out.append(Finding(_fid("cad-dev", c.designator, c.no), "critical", "cad", "Drawing and model disagree",
                           f"Balloon {c.no}: the drawing requires Ø{_fmt(c.lower)} – {_fmt(c.upper)} {c.unit}, the model "
                           f"measures Ø{s.show(best.diameter)} ({(best.diameter - s.nominal) / s.k:+.4f} from nominal). "
                           "One of them is wrong; a part made to the model fails this characteristic.",
                           c.no, c.designator, f"Ø{s.show(best.diameter)}", "CAD-DIA", c.page, list(c.bbox),
                           c.designator, c.cad_nodes,
                           query=f"The drawing gives Ø{_fmt(c.nominal)} and the 3D model Ø{s.show(best.diameter)}. "
                                 "Which governs?"))
    else:
        c.cad_status = "agrees"
        if abs(best.diameter - s.nominal) > 1e-3:
            c.cad_note = f"model at Ø{s.show(best.diameter)}, inside the limits but off nominal"


def _radius(s: "_Scaled", cyls, out: list[Finding]) -> None:
    c = s.c
    if not cyls:
        c.cad_status, c.cad_note = "not_found", "no radius in the model"
        return
    best = min(cyls, key=lambda h: abs(h.diameter / 2 - s.nominal))
    r = best.diameter / 2
    if abs(r - s.nominal) > _near(s.nominal):
        c.cad_status, c.cad_note = "not_found", f"no radius near R{_fmt(c.nominal)}"
        return
    c.cad_value, c.cad_nodes = s.back(r), [best.id]
    if _within_mm(s, r) is False:
        c.cad_status = "deviates"
        out.append(Finding(_fid("cad-dev", c.designator, c.no), "critical", "cad", "Drawing and model disagree",
                           f"Balloon {c.no}: R{_fmt(c.lower)} – {_fmt(c.upper)} {c.unit} on the drawing, "
                           f"R{s.show(r)} in the model.", c.no, c.designator, f"R{s.show(r)}", "CAD-RAD", c.page,
                           list(c.bbox), c.designator, c.cad_nodes))
    else:
        c.cad_status = "agrees"


def _linear(s: "_Scaled", m: Measurement, out: list[Finding]) -> None:
    c = s.c
    if not m.candidates:
        c.cad_status = "not_found"
        return
    best = min(m.candidates, key=lambda k: (abs(k.value - s.nominal), k.how != "extent"))
    if abs(best.value - s.nominal) > _near(s.nominal):
        c.cad_status, c.cad_note = "not_found", f"no model distance near {_fmt(c.nominal)} {c.unit}"
        out.append(Finding(_fid("cad-nl", c.designator, c.no), "minor", "cad", "Dimension not located in the model",
                           f"Balloon {c.no} ({c.designator}) matches no distance in the model "
                           f"(closest {s.show(best.value)} {c.unit}). Check it by hand.",
                           c.no, c.designator, f"closest {s.show(best.value)}", "CAD-LIN", c.page, list(c.bbox),
                           c.designator))
        return
    c.cad_value, c.cad_nodes = s.back(best.value), list(best.nodes)
    c.cad_note = {"plane_distance": "between parallel faces", "hole_spacing": "between hole axes",
                  "hole_to_face": "hole axis to face", "extent": "overall size"}[best.how]
    if c.type == "Basic":
        ok = abs(best.value - s.nominal) <= 1e-3 * s.k
    elif c.lower is None and c.upper is None:
        ok = None
    else:
        ok = _within_mm(s, best.value)
    if ok is False:
        c.cad_status = "deviates"
        lim = "exactly (basic)" if c.type == "Basic" else f"{_fmt(c.lower)} – {_fmt(c.upper)} {c.unit}"
        out.append(Finding(_fid("cad-dev", c.designator, c.no), "critical", "cad", "Drawing and model disagree",
                           f"Balloon {c.no}: the drawing requires {_fmt(c.nominal)} {lim}; the nearest model "
                           f"distance ({c.cad_note}) is {s.show(best.value)}.", c.no, c.designator,
                           s.show(best.value), "CAD-LIN", c.page, list(c.bbox), c.designator, c.cad_nodes))
    else:
        c.cad_status = "agrees"


def _thread(s: "_Scaled", holes, out: list[Finding]) -> None:
    c = s.c
    if c.nominal is None or not holes or c.unit == "in":
        c.cad_status, c.cad_note = "not_measurable", "only metric threads are matched to model holes"
        return
    sizes = _metric_tap_sizes(s.nominal, c.pitch)
    best, which, best_score = None, None, None
    for h in holes:
        for i, size in enumerate(sizes):
            d = abs(h.diameter - size)
            if d > 0.15:
                continue
            score = d + (0.5 * abs(h.length - s.depth) / s.depth if s.depth else 0.0)
            if best_score is None or score < best_score:
                best, which, best_score = h, i, score
    if best is None:
        c.cad_status, c.cad_note = "not_found", f"no hole at M{_fmt(c.nominal)} major, minor or tap-drill size"
        out.append(Finding(_fid("cad-thr", c.designator, c.no), "major", "cad", "Thread not in the model",
                           f"Balloon {c.no} ({c.designator}): no hole in the model at the thread's major, minor or "
                           "tap-drill diameter.", c.no, c.designator, "", "CAD-THR", c.page, list(c.bbox), c.designator))
        return
    c.cad_value, c.cad_nodes, c.cad_status = s.back(best.diameter), [best.id], "agrees"
    c.cad_note = (f"modelled as Ø{s.show(best.diameter)} "
                  + ("(major diameter)" if which == 0 else "(tap drill)" if which == 1 else "(minor diameter)")
                  + f", {s.show(best.length)} deep")


# ------------------------------------------------------------------ drawing vs BOM / PO

def _n(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def bom_check(title: dict, rows) -> tuple[list[Finding], dict | None]:
    """Find the drawing's line in the BOM / PO and compare revision, material, name."""
    dwg = title.get("drawing_number") or title.get("part_number") or ""
    name = title.get("title") or ""
    row = next((r for r in rows if dwg and _n(r.part_number) == _n(dwg)), None)
    if row is None and name:
        row = next((r for r in rows if _n(r.name) == _n(name)), None)
    out: list[Finding] = []
    if row is None:
        out.append(Finding(_fid("bom-missing", dwg, name), "major", "bom", "Part not on the BOM / PO",
                           f"No line in the BOM / PO has part number {dwg or '—'} or name {name or '—'}.",
                           drawing_value=dwg or name, rule="BOM-LINE"))
        return out, None
    rev_d, rev_b = (title.get("revision") or "").strip(), (row.revision or "").strip()
    if rev_d and rev_b and _n(rev_d) != _n(rev_b):
        out.append(Finding(_fid("bom-rev", dwg, rev_d, rev_b), "critical", "bom", "Revision differs from the PO",
                           f"The drawing is revision {rev_d}; the BOM / PO line for {row.part_number} orders revision "
                           f"{rev_b}. Inspecting to the wrong revision voids the FAI.", drawing_value=f"Rev {rev_d}",
                           cad_value=f"Rev {rev_b}", rule="BOM-REV",
                           query=f"The PO orders revision {rev_b} but the drawing supplied is revision {rev_d}. "
                                 "Which revision is to be supplied?"))
    elif not rev_b and rev_d:
        out.append(Finding(_fid("bom-norev", dwg), "minor", "bom", "PO line has no revision",
                           f"The BOM / PO line for {row.part_number} states no revision; the drawing is {rev_d}.",
                           drawing_value=f"Rev {rev_d}", rule="BOM-REV"))
    mat_d, mat_b = title.get("material") or "", row.material or ""
    if mat_d and mat_b and _n(mat_b) not in _n(mat_d) and _n(mat_d) not in _n(mat_b):
        out.append(Finding(_fid("bom-mat", dwg, mat_d, mat_b), "major", "bom", "Material differs from the PO",
                           f"Drawing material {mat_d}; BOM / PO material {mat_b}.", drawing_value=mat_d,
                           cad_value=mat_b, rule="BOM-MAT"))
    elif mat_d and mat_b and _n(mat_d) != _n(mat_b):
        out.append(Finding(_fid("bom-mat-short", dwg, mat_d, mat_b), "minor", "bom",
                           "Material written differently on the PO",
                           f"Drawing says {mat_d}, the PO says {mat_b}. Same grade, but the certificate must match "
                           "the drawing's designation.", drawing_value=mat_d, cad_value=mat_b, rule="BOM-MAT"))
    return out, row.to_dict()


# ------------------------------------------------------------------ drawing against itself

def drawing_findings(report, chars: list[Characteristic]) -> list[Finding]:
    out = []
    for f in report.findings:
        hit = next((c.no for c in chars if f.bbox and c.page == f.page and _overlap(c.bbox, f.bbox)), None)
        out.append(Finding("d" + f.id, DRAWCHECK_SEVERITY[f.severity], "drawing", f.title, f.message, hit,
                           f.evidence, "", f.rule, f.page, list(f.bbox) if f.bbox else [], f.evidence, query=f.query))
    for c in chars:
        if c.inspect and c.kind == "dimension" and c.tol_source == "none" and c.lower is None and c.upper is None:
            if any(x.char_no == c.no and x.rule.startswith("DM") for x in out):
                continue
            out.append(Finding(_fid("tol-none", c.designator, c.no), "major", "tolerance", "No tolerance to inspect against",
                               f"Balloon {c.no} ({c.designator}) has no tolerance of its own, and "
                               + (c.tol_note or "no general tolerance applies") + ".",
                               c.no, c.designator, "", "FAI-TOL", c.page, list(c.bbox), c.designator,
                               query=f"Please state the tolerance for {c.designator}."))
    return out


def _overlap(a, b, pad: float = 4.0) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])
