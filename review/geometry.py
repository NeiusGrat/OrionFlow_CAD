"""Features and contacts for the Model Graph (M2).

Built on interface_check's extraction (cylindrical faces merged into holes and
bosses, holes grouped into patterns, planar faces) and its contact search
(sweep-and-prune, then exact BRepExtrema distances). This module adds what
the review needs on top:

* **Through vs blind** for every hole, by classifying a point just past each
  end of the hole against the solid: open at both ends is through.
* **Typed contacts.** A touching pair is ``cylindrical`` when a boss of one
  sits coaxially in a hole of the other (a shaft in a bore, a bolt in a
  hole — the radial clearance is recorded), ``coaxial-hole`` when holes of
  both line up, ``planar`` when faces meet face to face, and ``point``
  otherwise (curved or edge contact). A pair can be several at once; the
  most specific becomes its ``type``.
* **A marker point** per contact (assembly frame), so the viewer can draw it
  and a finding can point at it.

Every number here is measured from B-rep geometry. Nothing is inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: coaxial = axes parallel within this angle and offset within this distance
COAX_ANGLE = 0.9995          # cos(~1.8 deg)
COAX_OFFSET = 0.15           # mm
#: largest radial clearance still read as "this boss is in that hole"
FIT_MAX_CLEARANCE = 1.0      # mm on diameter
HOLE_MATCH_DIA = 1.0         # mm: coaxial holes of mating parts within this of each other


@dataclass
class PartFeatures:
    features: list[dict] = field(default_factory=list)
    plane_count: int = 0


def _r(v, nd=4):
    return [round(float(x), nd) for x in np.asarray(v).ravel()]


def _through(shape, center, axis, depth, diameter) -> bool | None:
    """Open across its whole end, at both ends -> through. None when the classifier cannot say.

    Just past each end, the axis point and a ring at 80 % of the radius must
    all be outside the solid. The ring is what tells a stepped bore (a 22 mm
    seat ending on a shoulder with a 16 mm hole below it) from a through
    hole: on the axis both look open, at the ring only the through hole is.
    """
    try:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_OUT

        c, a = np.asarray(center, float), np.asarray(axis, float)
        ref = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        u = np.cross(a, ref)
        u /= np.linalg.norm(u)
        v = np.cross(a, u)
        r = 0.4 * diameter
        offsets = [np.zeros(3)] + [r * (np.cos(t) * u + np.sin(t) * v) for t in np.linspace(0, 2 * np.pi, 6, endpoint=False)]
        for s in (-1, 1):
            end = c + a * s * (depth / 2 + 0.05)
            for off in offsets:
                cls = BRepClass3d_SolidClassifier(shape, gp_Pnt(*map(float, end + off)), 1e-4)
                if cls.State() != TopAbs_OUT:
                    return False
        return True
    except Exception:  # noqa: BLE001
        return None


def part_features(part_id: str, shape, feats) -> PartFeatures:
    """interface_check Features (part frame) -> graph feature records."""
    out = PartFeatures(plane_count=len(feats.planes))
    if feats.is_mesh:
        return out
    hole_ids: dict[int, str] = {}
    for k, h in enumerate(feats.holes):
        fid = f"{part_id}.h{k + 1}"
        hole_ids[id(h)] = fid
        out.features.append({
            "id": fid, "part_id": part_id, "kind": "hole",
            "center": _r(h.center), "axis": _r(h.axis, 6), "diameter": round(float(h.diameter), 4),
            "depth": round(float(h.depth), 4), "through": _through(shape, h.center, h.axis, h.depth, h.diameter),
        })
    for k, b in enumerate(feats.bosses):
        out.features.append({
            "id": f"{part_id}.c{k + 1}", "part_id": part_id, "kind": "cylinder",
            "center": _r(b.center), "axis": _r(b.axis, 6), "diameter": round(float(b.diameter), 4),
            "length": round(float(b.length), 4),
        })
    for k, p in enumerate(feats.patterns):
        out.features.append({
            "id": f"{part_id}.p{k + 1}", "part_id": part_id, "kind": "pattern", "pattern": p.kind,
            "count": len(p.holes), "diameter": round(float(p.diameter), 4),
            "pcd": None if p.pcd is None else round(float(p.pcd), 4),
            "a": None if p.a is None else round(float(p.a), 4), "b": None if p.b is None else round(float(p.b), 4),
            "axis": _r(p.axis, 6), "centroid": _r(p.centroid),
            "holes": [hole_ids[id(h)] for h in p.holes if id(h) in hole_ids], "description": p.describe(),
        })
    return out


# --------------------------------------------------------------- contacts --

def _coaxial(c1, a1, c2, a2) -> bool:
    a1, a2 = np.asarray(a1, float), np.asarray(a2, float)
    if abs(float(np.dot(a1, a2))) < COAX_ANGLE:
        return False
    d = np.asarray(c2, float) - np.asarray(c1, float)
    off = d - a1 * np.dot(d, a1)
    return float(np.linalg.norm(off)) <= COAX_OFFSET


def _spans_overlap(c1, a1, len1, c2, len2) -> bool:
    a1 = np.asarray(a1, float)
    t = float(np.dot(np.asarray(c2, float) - np.asarray(c1, float), a1))
    return abs(t) <= (len1 + len2) / 2 + 0.05


def _fits(fa, fb) -> list[dict]:
    """Boss of A in hole of B (and the other way round), placed features in the assembly frame."""
    out = []
    for bosses, holes, flip in ((fa.bosses, fb.holes, False), (fb.bosses, fa.holes, True)):
        for b in bosses:
            for h in holes:
                if h.diameter + 1e-6 < b.diameter - 0.02:      # boss larger than the hole: not seated in it
                    continue
                clearance = h.diameter - b.diameter
                if clearance > FIT_MAX_CLEARANCE:
                    continue
                if not (_coaxial(h.center, h.axis, b.center, b.axis) and _spans_overlap(h.center, h.axis, h.depth, b.center, b.length)):
                    continue
                out.append({"shaft_on": "b" if flip else "a", "hole_diameter": round(float(h.diameter), 4),
                            "shaft_diameter": round(float(b.diameter), 4), "clearance": round(float(clearance), 4),
                            "axis": _r(h.axis, 6), "point": _r(h.center)})
    return out


def _coaxial_holes(fa, fb) -> list[dict]:
    out = []
    for ha in fa.holes:
        for hb in fb.holes:
            if abs(ha.diameter - hb.diameter) > HOLE_MATCH_DIA and not (min(ha.diameter, hb.diameter) / max(ha.diameter, hb.diameter) > 0.7):
                continue
            if _coaxial(ha.center, ha.axis, hb.center, hb.axis) and _spans_overlap(ha.center, ha.axis, ha.depth, hb.center, hb.depth + 1.0):
                out.append({"diameter_a": round(float(ha.diameter), 4), "diameter_b": round(float(hb.diameter), 4),
                            "axis": _r(ha.axis, 6), "point": _r((ha.center + hb.center) / 2)})
    return out


def _face_boxes(shape, gap: float) -> tuple[list, np.ndarray]:
    """Placed faces of a shape and their AABBs grown by ``gap`` (assembly frame)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    faces, boxes = [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        b = Bnd_Box()
        BRepBndLib.Add_s(f, b, True)
        if not b.IsVoid():
            b.Enlarge(gap)
            faces.append(f)
            boxes.append(b.Get())
        ex.Next()
    return faces, np.array(boxes, dtype=float).reshape(-1, 6)


def _compound(faces):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    c, bld = TopoDS_Compound(), BRep_Builder()
    bld.MakeCompound(c)
    for f in faces:
        bld.Add(c, f)
    return c


def _min_face_distance(fa, ba, fb, bb, gap: float):
    """Exact minimum distance between the faces of A and B that could be within ``gap``.

    Only faces whose grown boxes overlap a face of the other shape take part;
    they are gathered into one compound per side and measured with a single
    minimum-only, multi-threaded BRepExtrema call (one call over the
    candidates is ~10x faster than face by face on gear-tooth geometry, same
    value). Returns (distance, midpoint), or (None, None) when no face boxes
    overlap — which proves the shapes are farther apart than ``gap`` without a
    single exact computation.
    """
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.Extrema import Extrema_ExtFlag_MIN

    hit = np.all(ba[:, None, :3] <= bb[None, :, 3:], axis=2) & np.all(bb[None, :, :3] <= ba[:, None, 3:], axis=2)
    ia, ib = np.where(hit.any(axis=1))[0], np.where(hit.any(axis=0))[0]
    if not len(ia):
        return None, None
    d = BRepExtrema_DistShapeShape()
    d.SetFlag(Extrema_ExtFlag_MIN)
    d.SetMultiThread(True)
    d.LoadS1(_compound([fa[i] for i in ia]))
    d.LoadS2(_compound([fb[j] for j in ib]))
    d.Perform()
    if not d.IsDone() or d.NbSolution() == 0:
        return None, None
    p1, p2 = d.PointOnShape1(1), d.PointOnShape2(1)
    return d.Value(), [(p1.X() + p2.X()) / 2, (p1.Y() + p2.Y()) / 2, (p1.Z() + p2.Z()) / 2]


def touching_pairs(ic_instances, placed: dict, gap: float = 0.05) -> list[tuple]:
    """(a, b, distance | None, point | None) for every pair within ``gap``.

    Broad phase: instance AABBs (sweep and prune). Narrow phase: face AABBs,
    then exact BRepExtrema face-to-face distances, nearest candidates first,
    stopping at the first touching face pair. A MESH body is box adjacency
    only (distance None), as in interface_check.
    """
    from interface_check.interfaces import near_pairs

    cache: dict[str, tuple] = {}

    def faces_of(inst):
        if inst.instance_id not in cache:
            cache[inst.instance_id] = _face_boxes(inst.shape, gap / 2)
        return cache[inst.instance_id]

    out = []
    for a, b in near_pairs(ic_instances, gap):
        if placed[a.instance_id].is_mesh or placed[b.instance_id].is_mesh:
            out.append((a, b, None, None))
            continue
        fa, ba = faces_of(a)
        fb, bb = faces_of(b)
        d, pt = _min_face_distance(fa, ba, fb, bb, gap)
        if d is not None and d <= gap:
            out.append((a, b, d, pt))
    return out


def contacts(ic_instances, placed: dict, iid_of: dict[str, str], stats: dict | None = None) -> list[dict]:
    """Typed contact records for every touching pair (min distance <= 0.05 mm)."""
    from interface_check.interfaces import contact_planes

    out: list[dict] = []
    for n, (a, b, dist, mid) in enumerate(touching_pairs(ic_instances, placed), start=1):
        exact = dist is not None
        fa, fb = placed[a.instance_id], placed[b.instance_id]
        fits = _fits(fa, fb) if exact else []
        coax = _coaxial_holes(fa, fb) if exact else []
        faces = contact_planes(fa, fb, stats=stats) if exact else []
        seen: list[tuple[np.ndarray, np.ndarray]] = []
        for pa, _ in faces:
            if not any(abs(np.dot(pa.point - p, nrm)) < 1e-3 and np.dot(pa.normal, nrm) > 0.999 for p, nrm in seen):
                seen.append((pa.point, pa.normal))
        planes = [{"point": _r(p), "normal": _r(nrm, 6)} for p, nrm in seen]
        kinds = (["cylindrical"] if fits else []) + (["coaxial-hole"] if coax else []) + (["planar"] if planes else [])
        if not kinds:
            kinds = ["point"] if exact else ["adjacent"]
        point = (fits[0]["point"] if fits else coax[0]["point"] if coax else planes[0]["point"] if planes else
                 (_r(mid) if mid is not None else None))
        out.append({
            "id": f"c{n:04d}", "a": iid_of[a.instance_id], "b": iid_of[b.instance_id], "type": kinds[0], "kinds": kinds,
            "min_distance": None if dist is None else round(float(dist), 5), "exact": exact,
            "point": point, "planes": planes, "fits": fits, "coaxial_holes": coax,
            "method": "exact BRepExtrema face-to-face distance <= 0.05 mm; planar faces matched by plane offset "
                      "and normal; fits = coaxial boss/hole within 1 mm diametral clearance",
        })
    return out
