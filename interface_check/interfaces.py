"""Which instances touch, and on which planes.

Two instances form an interface when the minimum distance between them is
about zero. The planes they touch on are pairs of planar faces with opposite
normals, on the same plane, that actually meet (face-to-face distance ~0) —
two coplanar faces at opposite ends of the parts are not a contact.

Two phases, so exact OpenCASCADE work runs only on real candidates:

  broad   instance AABBs, sweep-and-prune on X -> instance pairs whose boxes overlap
  narrow  per pair, planar faces matched by plane offset (sorted array, binary
          search), then normal, then face-AABB overlap; only the survivors get
          an exact BRepExtrema face-to-face distance, at most MAX_FACE_PAIRS.

A pair involving a MESH body is adjacency only: its boxes overlap, so the
interface graph (change impact) keeps the edge, but no exact distance is spent
on thousands of triangles that no rule reads.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

from .models import Features, Instance, Interface, PlanarFace

TOUCH_GAP = 0.05        # mm
MAX_INSTANCES = 500
#: Exact face-to-face distance calls per touching pair; beyond it the largest
#: faces are kept and the cut is reported.
MAX_FACE_PAIRS = 400


def box(shape, gap: float = 0.0) -> Bnd_Box:
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    if gap:
        b.Enlarge(gap)
    return b


def distance(a, b) -> float:
    d = BRepExtrema_DistShapeShape(a, b)
    return d.Value() if d.IsDone() else float("inf")


def near_pairs(instances: list[Instance], gap: float) -> list[tuple[Instance, Instance]]:
    """Pairs whose boxes, grown by ``gap``, overlap (sweep and prune on X)."""
    boxes = {}
    for i in instances:
        b = box(i.shape, gap)
        if not b.IsVoid():
            boxes[i.instance_id] = b
    items = sorted(((boxes[i.instance_id].Get()[0], i) for i in instances if i.instance_id in boxes),
                   key=lambda t: t[0])
    out, active = [], []
    for x0, inst in items:
        b = boxes[inst.instance_id]
        active = [o for o in active if boxes[o.instance_id].Get()[3] >= x0]
        for o in active:
            if not boxes[o.instance_id].IsOut(b):
                out.append((o, inst))
        active.append(inst)
    return out


def touching(instances: list[Instance], gap: float = TOUCH_GAP, approximate: set[str] | None = None
             ) -> list[tuple[Instance, Instance, float | None]]:
    """Pairs within ``gap``. Pairs with an instance in ``approximate`` are box-overlap only (distance None)."""
    approximate = approximate or set()
    out = []
    for a, b in near_pairs(instances, gap):
        if a.instance_id in approximate or b.instance_id in approximate:
            out.append((a, b, None))
            continue
        d = distance(a.shape, b.shape)
        if d <= gap:
            out.append((a, b, d))
    return out


def _arrays(planes: list[PlanarFace]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = np.array([p.normal for p in planes], dtype=float).reshape(-1, 3)
    pts = np.array([p.point for p in planes], dtype=float).reshape(-1, 3)
    boxes = np.array([p.box if p.box is not None else [-np.inf] * 3 + [np.inf] * 3 for p in planes],
                     dtype=float).reshape(-1, 6)
    return n, np.einsum("ij,ij->i", n, pts), boxes


def contact_planes(fa: Features, fb: Features, ang: float = 0.999, off: float = TOUCH_GAP,
                   max_pairs: int = MAX_FACE_PAIRS, stats: dict | None = None
                   ) -> list[tuple[PlanarFace, PlanarFace]]:
    """Face pairs of A and B that face each other on one plane and actually meet."""
    if not fa.planes or not fb.planes:
        return []
    na, da, ba = _arrays(fa.planes)
    nb, db, bb = _arrays(fb.planes)
    # Same plane, opposite normals: n_b = -n_a and n_b.p = -d_a. Sort B by -d_b.
    key = -db
    order = np.argsort(key)
    skey = key[order]
    cand: list[tuple[int, int]] = []
    for i in range(len(na)):
        lo, hi = np.searchsorted(skey, da[i] - off), np.searchsorted(skey, da[i] + off, side="right")
        if lo == hi:
            continue
        js = order[lo:hi]
        js = js[(nb[js] @ na[i]) < -ang]
        if not len(js):
            continue
        # face boxes must overlap (grown by the contact gap)
        ok = np.all(ba[i, :3] - off <= bb[js, 3:], axis=1) & np.all(bb[js, :3] <= ba[i, 3:] + off, axis=1)
        cand.extend((i, int(j)) for j in js[ok])
    if stats is not None:
        stats["candidates"] = stats.get("candidates", 0) + len(cand)
    if len(cand) > max_pairs:
        cand.sort(key=lambda ij: -(fa.planes[ij[0]].area + fb.planes[ij[1]].area))
        if stats is not None:
            stats["capped"] = stats.get("capped", 0) + len(cand) - max_pairs
        cand = cand[:max_pairs]
    out = []
    for i, j in cand:
        pa, pb = fa.planes[i], fb.planes[j]
        if pa.face is not None and pb.face is not None and distance(pa.face, pb.face) > off:
            continue
        out.append((pa, pb))
    if stats is not None:
        stats["exact"] = stats.get("exact", 0) + len(cand)
    return out


@dataclass
class Contact:
    a: Instance
    b: Instance
    distance: float | None                  # None: box adjacency only (a MESH body is involved)
    faces: list[tuple[PlanarFace, PlanarFace]]

    @property
    def exact(self) -> bool:
        return self.distance is not None

    def planes(self) -> list[tuple[np.ndarray, np.ndarray]]:
        """Distinct contact planes as (point, normal of A)."""
        seen: list[tuple[np.ndarray, np.ndarray]] = []
        for pa, _ in self.faces:
            if not any(abs(np.dot(pa.point - p, n)) < 1e-3 and np.dot(pa.normal, n) > 0.999 for p, n in seen):
                seen.append((pa.point, pa.normal))
        return seen

    def to_interface(self) -> Interface:
        return Interface(self.a.path, self.b.path, self.planes(), self.distance)


def find_contacts(instances: list[Instance], feats: dict[str, Features], stats: dict | None = None
                  ) -> list[Contact]:
    mesh = {iid for iid, f in feats.items() if f.is_mesh}
    out = []
    for a, b, d in touching(instances, approximate=mesh):
        faces = [] if d is None else contact_planes(feats[a.instance_id], feats[b.instance_id], stats=stats)
        out.append(Contact(a, b, d, faces))
    return out


def graph(contacts: list[Contact]) -> dict[str, set[str]]:
    g: dict[str, set[str]] = defaultdict(set)
    for c in contacts:
        g[c.a.instance_id].add(c.b.instance_id)
        g[c.b.instance_id].add(c.a.instance_id)
    return g
