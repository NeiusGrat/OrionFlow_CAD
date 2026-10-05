"""Interface rules: every pass/fail here is arithmetic on measured geometry.

Rules (default tolerances in brackets):

  HOLE_MISALIGNED          hole in A meets a hole in B off-axis (0.05 .. 3 mm)
  HOLE_MISSING             hole in A opens onto B's face with no hole in B within 3 mm
  PATTERN_MISMATCH         bolt circle / rectangle spacing differs across the joint (0.1 mm)
  FASTENER_SIZE_MISMATCH   aligned holes share no metric size (clearance M4 on tapped M3)
  BEARING_SEAT             housing bore != bearing OD, or shaft != bearing bore (0.05 mm)
  MOTOR_FLANGE             plate on a motor face has no pilot bore, or one smaller than the pilot
  COMPONENT_UNCONFIRMED    named like a library part, geometry does not show its spec
  INTERFERENCE             two parts share volume (> 0.5 mm^3)
"""
from __future__ import annotations

import re

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepGProp import BRepGProp
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps

from ..components.library import Library, Match, confirm
from ..features import axis_offset, parallel
from ..interfaces import Contact, distance, near_pairs
from ..models import Features, Finding, Hole, Instance
from . import fasteners

ALIGN_TOL = 0.05
SEARCH = 3.0
PATTERN_TOL = 0.1
SEAT_TOL = 0.05
INTERFERENCE_MM3 = 0.5
NOMINAL_ONLY = "STEP carries no thread or fit class; nominal sizes compared only"
#: Boolean common is skipped above this many faces on either part (cost grows
#: superlinearly); the skip is counted and reported, never silent.
INTERFERENCE_MAX_FACES = 3000

#: How each rule's measured value is computed: the evidence trail every claim cites.
METHOD = {
    "HOLE_MISALIGNED": "axis-line offset of concave cylinders crossing a BRepExtrema-confirmed contact plane",
    "HOLE_MISSING": "hole axis/contact-plane intersection tested against the mating face (BRepExtrema point-face)",
    "PATTERN_MISMATCH": "hole-centre pattern classification (bolt circle / rectangle) compared across the joint",
    "FASTENER_SIZE_MISMATCH": "measured hole diameters against ISO 273 clearance / ISO 2306 tap-drill table",
    "BEARING_SEAT": "coaxial cylinder diameters against the SKF/ISO 15 bearing table",
    "MOTOR_FLANGE": "coaxial pilot bore diameter against the NEMA ICS 16 flange table",
    "COMPONENT_UNCONFIRMED": "library spec compared with the instance's measured hole pattern / cylinders",
    "INTERFERENCE": "BRepAlgoAPI_Common volume between the two solids",
}
HARDWARE = re.compile(r"screw|bolt|nut\b|washer|shcs|bhcs|fhcs|iso\s?4762|din\s?912|insert|rivet|pin\b|standoff",
                      re.I)


def is_hardware(name: str) -> bool:
    return bool(HARDWARE.search(name))


def _vertex(p: np.ndarray):
    return BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()


def _crossing(h: Hole, p0: np.ndarray, n: np.ndarray) -> np.ndarray | None:
    """Where the hole's axis meets the plane, if the hole reaches it."""
    if not parallel(h.axis, n):
        return None
    t = float(np.dot(p0 - h.center, n) / np.dot(h.axis, n))
    if abs(t) > h.depth / 2 + ALIGN_TOL:
        return None
    return h.center + h.axis * t


def _key(inst: Instance, h: Hole) -> tuple:
    return (inst.instance_id, *np.round(h.center, 2), round(h.diameter, 2))


class Checker:
    def __init__(self, instances: list[Instance], feats: dict[str, Features], contacts: list[Contact],
                 part_names: dict[str, str], library: Library | None = None):
        self.instances = instances
        self.by_id = {i.instance_id: i for i in instances}
        self.feats = feats
        self.contacts = contacts
        self.part_names = part_names        # instance_id -> part name
        self.library = library or Library()
        self.findings: list[Finding] = []
        self.matches: dict[str, Match] = {}
        self._reported: set = set()
        self.skipped: dict[str, int] = {}       # what was not computed, and how often

    def _skip(self, what: str) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + 1

    # -------------------------------------------------------------- helpers
    def _add(self, rule, severity, insts: list[Instance], message, **kw) -> None:
        kw.setdefault("parts", [self.part_names[i.instance_id] for i in insts])
        kw.setdefault("method", METHOD.get(rule, ""))
        self.findings.append(Finding(rule, severity, [i.path for i in insts], message, **kw))

    def _on_faces(self, p: np.ndarray, faces, tol: float = ALIGN_TOL) -> bool:
        v = _vertex(p)
        return any(f is not None and distance(v, f) <= tol for f in faces)

    # -------------------------------------------------------------- entry
    def run(self) -> list[Finding]:
        self.match_components()
        for c in self.contacts:
            self.check_joint(c)
        self.check_bearings()
        self.check_motors()
        self.check_interference()
        return self.findings

    # -------------------------------------------------------------- components
    def match_components(self) -> None:
        for inst in self.instances:
            name = self.part_names[inst.instance_id]
            comp = self.library.by_name(name) or self.library.by_name(inst.name)
            if comp is None:
                continue
            if self.feats[inst.instance_id].is_mesh:
                self._skip("component confirmation on mesh bodies")
                continue
            m = confirm(comp, self.feats[inst.instance_id])
            if m.confirmed:
                self.matches[inst.instance_id] = m
                continue
            # A bare number that happens to be a bearing designation ("PN 6204")
            # is not a claim worth a finding; a part *called* a bearing is.
            if comp.type == "bearing" and "bearing" not in name.lower() and not re.search(
                    r"\d(-?2?z{1,2}|-?2?rs)", name.lower()):
                continue
            self._add("COMPONENT_UNCONFIRMED", "medium", [inst],
                      f"{inst.name} is named like {comp.name} but its geometry does not show it: "
                      f"{m.reason}. Its interfaces are not checked against the {comp.name} spec.",
                      measured=m.measured, expected=_spec(comp),
                      location=list(self.feats[inst.instance_id].com))

    # -------------------------------------------------------------- bolted joints
    def check_joint(self, c: Contact) -> None:
        for p0, n in c.planes():
            suppressed = self._patterns(c.a, c.b, p0, n)
            self._holes(c.a, c.b, p0, n, c, suppressed, a_side=True)
            self._holes(c.b, c.a, p0, n, c, suppressed, a_side=False)

    def _patterns(self, A: Instance, B: Instance, p0, n) -> set:
        fa, fb = self.feats[A.instance_id], self.feats[B.instance_id]
        pa = [p for p in fa.patterns if p.kind != "group" and _crossing(p.holes[0], p0, n) is not None]
        pb = [p for p in fb.patterns if p.kind != "group" and _crossing(p.holes[0], p0, n) is not None]
        suppressed = set()
        for x in pa:
            for y in pb:
                if x.kind != y.kind or len(x.holes) != len(y.holes):
                    continue
                d = x.centroid - y.centroid
                lateral = np.linalg.norm(d - n * np.dot(d, n))
                size = x.pcd if x.kind == "circle" else np.hypot(x.a, x.b)
                if lateral > size / 4:
                    continue
                # Concentric patterns of different sizes (a motor square inside
                # a corner square) are two joints, not one mismatched joint:
                # pair only when every hole has a partner across the plane.
                near = [min(axis_offset(hy, hx.center) for hy in y.holes) for hx in x.holes]
                if max(near) > SEARCH:
                    continue
                if x.kind == "circle":
                    diff = abs(x.pcd - y.pcd)
                    meas, exp = {"pcd_mm": round(x.pcd, 3)}, {"pcd_mm": round(y.pcd, 3)}
                else:
                    diff = abs(x.a - y.a) + abs(x.b - y.b)
                    meas = {"spacing_mm": [round(x.a, 3), round(x.b, 3)]}
                    exp = {"spacing_mm": [round(y.a, 3), round(y.b, 3)]}
                if diff <= PATTERN_TOL and lateral <= PATTERN_TOL:
                    continue
                key = ("PATTERN", A.instance_id, B.instance_id, *np.round(x.centroid, 1))
                if key in self._reported:
                    continue
                self._reported.add(key)
                for h in x.holes:
                    suppressed.add(_key(A, h))
                for h in y.holes:
                    suppressed.add(_key(B, h))
                if x.pcd and y.pcd:
                    what = f"bolt circle {x.pcd:.2f} vs {y.pcd:.2f} mm"
                    meas.setdefault("pcd_mm", round(x.pcd, 3))
                    exp.setdefault("pcd_mm", round(y.pcd, 3))
                else:
                    what = f"spacing {x.a:.2f} x {x.b:.2f} vs {y.a:.2f} x {y.b:.2f} mm"
                if lateral > PATTERN_TOL:
                    what += f", centres offset {lateral:.2f} mm"
                    meas["centre_offset_mm"] = round(float(lateral), 3)
                self._add("PATTERN_MISMATCH", "high", [A, B],
                          f"Hole pattern on {A.name} ({x.describe()}) does not match {B.name} "
                          f"({y.describe()}): {what}.",
                          measured=meas, expected=exp, location=list(x.centroid))
        return suppressed

    def _holes(self, A: Instance, B: Instance, p0, n, c: Contact, suppressed: set, a_side: bool) -> None:
        fa, fb = self.feats[A.instance_id], self.feats[B.instance_id]
        b_faces = [pb.face if a_side else pa.face for pa, pb in c.faces
                   if abs(np.dot(pa.point - p0, n)) < 1e-3]
        for h in fa.holes:
            if not fasteners.is_fastener_hole(h.diameter) or _key(A, h) in suppressed:
                continue
            P = _crossing(h, p0, n)
            if P is None:
                continue
            best, off = None, 1e9
            for hb in fb.holes:
                if not fasteners.is_fastener_hole(hb.diameter) or _crossing(hb, p0, n) is None:
                    continue
                o = axis_offset(hb, P)
                if o < off:
                    best, off = hb, o
            if best is not None and off <= SEARCH:
                pair = frozenset([_key(A, h), _key(B, best)])
                if pair in self._reported or _key(B, best) in suppressed:
                    continue
                self._reported.add(pair)
                if off > ALIGN_TOL:
                    self._add("HOLE_MISALIGNED", "high", [A, B],
                              f"Hole Ø{h.diameter:.2f} in {A.name} is {off:.2f} mm off the matching "
                              f"Ø{best.diameter:.2f} hole in {B.name}.",
                              measured={"offset_mm": round(off, 3)}, expected={"offset_mm_max": ALIGN_TOL},
                              location=list(P))
                ok = fasteners.compatible(h.diameter, best.diameter)
                if ok is False:
                    self._add("FASTENER_SIZE_MISMATCH", "high", [A, B],
                              f"Mating holes take different screws: {A.name} {fasteners.describe(h.diameter)}, "
                              f"{B.name} {fasteners.describe(best.diameter)}.",
                              measured={"diameter_mm": [round(h.diameter, 3), round(best.diameter, 3)],
                                        "sizes": [sorted(fasteners.sizes(h.diameter)),
                                                  sorted(fasteners.sizes(best.diameter))]},
                              expected={"rule": "both holes accept one metric size"},
                              location=list(P), assumptions=[NOMINAL_ONLY])
                continue
            # No hole across the joint. Only a defect if B's material is there.
            if self._on_faces(P, b_faces):
                key = ("MISSING", _key(A, h))
                if key in self._reported:
                    continue
                self._reported.add(key)
                self._add("HOLE_MISSING", "high", [A, B],
                          f"Hole Ø{h.diameter:.2f} in {A.name} opens onto solid material of {B.name}: "
                          f"no hole in {B.name} within {SEARCH:.0f} mm, the fastener cannot pass.",
                          measured={"nearest_hole_mm": None if best is None else round(off, 3)},
                          expected={"hole_within_mm": SEARCH}, location=list(P))

    # -------------------------------------------------------------- bearings
    def check_bearings(self) -> None:
        bearings = {iid: m for iid, m in self.matches.items() if m.component.type == "bearing"}
        if not bearings:
            return
        near = near_pairs(self.instances, 1.0)
        for iid, m in bearings.items():
            brg = self.by_id[iid]
            c, ax = m.centre, m.axis
            comp = m.component
            neighbours = [b if a.instance_id == iid else a for a, b in near if iid in (a.instance_id, b.instance_id)]
            for other in neighbours:
                fo = self.feats[other.instance_id]
                for h in fo.holes:
                    if self._coaxial_overlap(h, c, ax, comp.width_mm, h.depth) and abs(h.diameter - comp.od_mm) <= 3:
                        self._seat(brg, other, "housing bore", h.diameter, comp.od_mm, h.center)
                for b in fo.bosses:
                    if self._coaxial_overlap(b, c, ax, comp.width_mm, b.length) and abs(b.diameter - comp.bore_mm) <= 3:
                        self._seat(brg, other, "shaft", b.diameter, comp.bore_mm, b.center)

    @staticmethod
    def _coaxial_overlap(f, c, ax, width, length) -> bool:
        if not parallel(f.axis, ax) or axis_offset(f, c) > 0.5:
            return False
        s = float(np.dot(f.center - c, ax))
        overlap = min(width / 2, s + length / 2) - max(-width / 2, s - length / 2)
        return overlap > 0.5

    def _seat(self, brg, other, what, measured, nominal, at) -> None:
        diff = measured - nominal
        if abs(diff) <= SEAT_TOL:
            return
        key = ("SEAT", brg.instance_id, other.instance_id, what)
        if key in self._reported:
            return
        self._reported.add(key)
        comp = self.matches[brg.instance_id].component
        fit = "loose" if (diff > 0) == (what == "housing bore") else "interference"
        self._add("BEARING_SEAT", "high", [brg, other],
                  f"{what.capitalize()} Ø{measured:.3f} in {other.name} does not match the {comp.name} "
                  f"{'OD' if what == 'housing bore' else 'bore'} Ø{nominal:.3f} ({diff:+.3f} mm, {fit}).",
                  measured={f"{what.replace(' ', '_')}_mm": round(measured, 4)},
                  expected={f"{what.replace(' ', '_')}_mm": nominal, "tol_mm": SEAT_TOL},
                  location=list(at), assumptions=[NOMINAL_ONLY])

    # -------------------------------------------------------------- motors
    def check_motors(self) -> None:
        for iid, m in self.matches.items():
            comp = m.component
            if comp.type != "motor" or not comp.pilot_dia_mm:
                continue
            motor = self.by_id[iid]
            fm = self.feats[iid]
            pilot = min((b for b in fm.bosses if parallel(b.axis, m.axis) and axis_offset(b, m.centre) < 0.5),
                        key=lambda b: abs(b.diameter - comp.pilot_dia_mm), default=None)
            if pilot is None:
                continue
            ends = [pilot.center + pilot.axis * pilot.length / 2, pilot.center - pilot.axis * pilot.length / 2]
            tip = max(ends, key=lambda e: np.linalg.norm(e - fm.com))
            for c in self.contacts:
                if iid not in (c.a.instance_id, c.b.instance_id):
                    continue
                plate = c.b if c.a.instance_id == iid else c.a
                if is_hardware(self.part_names[plate.instance_id]):
                    continue
                if distance(plate.shape, _vertex(tip)) > pilot.diameter / 2 + pilot.length + 1.0:
                    continue
                fp = self.feats[plate.instance_id]
                bores = [h for h in fp.holes if parallel(h.axis, pilot.axis) and axis_offset(h, pilot.center) < 0.5
                         and h.diameter > (comp.shaft_dia_mm or 0) + 0.5]
                bore = max(bores, key=lambda h: h.diameter, default=None)
                if bore is not None and bore.diameter >= comp.pilot_dia_mm - SEAT_TOL:
                    continue
                got = "no pilot bore" if bore is None else f"pilot bore Ø{bore.diameter:.2f}"
                self._add("MOTOR_FLANGE", "high", [motor, plate],
                          f"{plate.name} mounts on the {comp.name} face with {got}; the Ø{comp.pilot_dia_mm} "
                          "pilot needs a bore at least that size.",
                          measured={"pilot_bore_mm": None if bore is None else round(bore.diameter, 3)},
                          expected={"pilot_bore_min_mm": comp.pilot_dia_mm}, location=list(pilot.center))

    # -------------------------------------------------------------- interference
    def check_interference(self) -> None:
        for c in self.contacts:
            na, nb = self.part_names[c.a.instance_id], self.part_names[c.b.instance_id]
            if is_hardware(na) or is_hardware(nb) or not c.exact or c.distance > 1e-6:
                continue
            fa, fb = self.feats[c.a.instance_id], self.feats[c.b.instance_id]
            if fa.is_mesh or fb.is_mesh or max(fa.face_count, fb.face_count) > INTERFERENCE_MAX_FACES:
                self._skip("interference volume on heavy or mesh pairs")
                continue
            common = BRepAlgoAPI_Common(c.a.shape, c.b.shape)
            if not common.IsDone():
                continue
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(common.Shape(), props)
            vol = abs(props.Mass())
            if vol <= INTERFERENCE_MM3:
                continue
            at = props.CentreOfMass()
            self._add("INTERFERENCE", "medium", [c.a, c.b],
                      f"{c.a.name} and {c.b.name} overlap by {vol:.1f} mm³ at rest.",
                      measured={"overlap_mm3": round(vol, 2)}, expected={"overlap_mm3_max": INTERFERENCE_MM3},
                      location=[at.X(), at.Y(), at.Z()])


def _spec(c) -> dict:
    if c.type == "bearing":
        return {"bore_mm": c.bore_mm, "od_mm": c.od_mm, "width_mm": c.width_mm}
    return {"mount": c.mount, "pilot_dia_mm": c.pilot_dia_mm}
