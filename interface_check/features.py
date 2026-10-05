"""Per-part features: holes, bosses, planar faces, hole patterns, mass properties.

Computed once per part definition in its own coordinates, then moved by each
instance's 4x4 — consistent across copies and N times cheaper.

A hole is a *concave* cylindrical face: its outward normal points at the axis.
STEP often splits one hole into two half-cylinders, so faces on the same axis
line with the same diameter are merged, and a merged group must close (>= ~300
degrees) to count. That last test is what keeps inside-corner fillets — also
concave cylinders — out of the hole list.

Mesh bodies. A triangulated mesh saved as STEP (an STL converted to B-rep) has
thousands of flat triangles and no analytic surfaces: no holes to find, and
contact search over its faces is quadratic for nothing. :func:`classify_body`
counts faces and triangles first; a MESH body gets mass properties and a
bounding box only, and the report says which analyses were skipped for it.
"""
from __future__ import annotations

import math

import numpy as np
from OCP.Bnd import Bnd_Box
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.gp import gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from .ingest_step import signature
from .models import Boss, Features, Hole, HolePattern, PlanarFace, canon
from .version import EXTRACTION_VERSION

#: A merged cylinder group must cover this much of a turn to be a hole/boss.
CLOSED_FRACTION = 0.83
DIA_TOL = 0.05          # mm, same-diameter test for patterns
CIRCLE_SPREAD = 0.005   # relative radius spread for a bolt circle

#: Mesh policy: at least this many faces, and this share of them triangles.
MESH_MIN_FACES = 200
MESH_TRIANGLE_RATIO = 0.6
#: ...or an all-flat body this large (quad meshes, faceted exports).
MESH_FLAT_FACES = 5000
MESH_FLAT_RATIO = 0.99


def faces(shape):
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        yield TopoDS.Face_s(exp.Current())
        exp.Next()


def _vec(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()])


def _point_normal(face) -> tuple[np.ndarray, np.ndarray]:
    """Mid-UV point and outward normal (BRepGProp_Face honours face orientation)."""
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    p, n = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal((umin + umax) / 2, (vmin + vmax) / 2, p, n)
    n = _vec(n)
    return _vec(p), n / (np.linalg.norm(n) or 1.0)


def classify_body(shape) -> tuple[str, int, int]:
    """(BREP|MESH, face count, triangle count) from one cheap pass over the faces."""
    n = tri = flat = 0
    for f in faces(shape):
        n += 1
        if BRepAdaptor_Surface(f, False).GetType() != GeomAbs_Plane:
            continue
        flat += 1
        e, exp = 0, TopExp_Explorer(f, TopAbs_EDGE)
        while exp.More() and e < 4:
            e += 1
            exp.Next()
        tri += e == 3
    mesh = (n >= MESH_MIN_FACES and tri / n >= MESH_TRIANGLE_RATIO) or (
        n >= MESH_FLAT_FACES and flat / n >= MESH_FLAT_RATIO)
    return ("MESH" if mesh else "BREP"), n, tri


def _face_box(f) -> np.ndarray:
    b = Bnd_Box()
    BRepBndLib.Add_s(f, b)
    return np.array(b.Get(), dtype=float)


def extract(shape) -> Features:
    kind, n_faces, n_tri = classify_body(shape)
    if kind == "MESH":
        feats = Features(geometry_type="MESH", face_count=n_faces, triangle_count=n_tri)
        sig = signature(shape)
        feats.volume, feats.area, feats.bbox = sig["volume"], sig["area"], tuple(sig["bbox"])
        feats.com, feats.inertia = volume_props(shape)
        return feats
    raw: list[tuple] = []
    planes: list[PlanarFace] = []
    for k, f in enumerate(faces(shape)):
        s = BRepAdaptor_Surface(f)
        kind = s.GetType()
        if kind == GeomAbs_Cylinder:
            cyl = s.Cylinder()
            o, d = _vec(cyl.Location()), _vec(cyl.Axis().Direction())
            p, n = _point_normal(f)
            radial = p - (o + d * np.dot(p - o, d))
            concave = np.dot(n, radial) < 0
            umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
            raw.append((concave, o, d, 2 * cyl.Radius(), vmin, vmax, umax - umin))
        elif kind == GeomAbs_Plane:
            p, n = _point_normal(f)
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, props)
            planes.append(PlanarFace(_vec(props.CentreOfMass()), n, props.Mass(), f, k, _face_box(f)))
    holes, bosses = _merge_cylinders(raw)
    feats = Features(holes=holes, bosses=bosses, planes=planes, face_count=n_faces, triangle_count=n_tri)
    feats.patterns = patterns(holes)
    sig = signature(shape)
    feats.volume, feats.area, feats.bbox = sig["volume"], sig["area"], tuple(sig["bbox"])
    feats.com, feats.inertia = volume_props(shape)
    return feats


def _merge_cylinders(raw) -> tuple[list[Hole], list[Boss]]:
    groups: dict[tuple, list] = {}
    for concave, o, d, dia, v0, v1, du in raw:
        dc = canon(d)
        foot = o - dc * np.dot(o, dc)          # axis point closest to the origin
        key = (concave, round(dia, 2), *np.round(foot, 2), *np.round(dc, 3))
        a0, a1 = sorted((np.dot(o + d * v0, dc), np.dot(o + d * v1, dc)))
        g = groups.get(key)
        if g is None:
            groups[key] = [concave, foot, dc, dia, a0, a1, du]
        else:
            g[4], g[5], g[6] = min(g[4], a0), max(g[5], a1), g[6] + du
    holes, bosses = [], []
    for concave, foot, dc, dia, a0, a1, turn in groups.values():
        if turn < CLOSED_FRACTION * 2 * math.pi:
            continue                           # a fillet or a partial arc, not a hole
        centre = foot + dc * (a0 + a1) / 2
        if concave:
            holes.append(Hole(centre, dc, dia, a1 - a0))
        else:
            bosses.append(Boss(centre, dc, dia, a1 - a0))
    return _join_coaxial(holes), bosses


def _join_coaxial(holes: list[Hole]) -> list[Hole]:
    """Same axis line, same diameter, touching spans -> one hole (split by a face)."""
    out: list[Hole] = []
    for h in sorted(holes, key=lambda h: (h.diameter, *h.center)):
        for o in out:
            if (abs(o.diameter - h.diameter) < 1e-3 and abs(abs(np.dot(o.axis, h.axis)) - 1) < 1e-6
                    and axis_offset(o, h.center) < 1e-3):
                lo = min(np.dot(o.span()[0], o.axis), np.dot(h.span()[0], o.axis))
                hi = max(np.dot(o.span()[1], o.axis), np.dot(h.span()[1], o.axis))
                gap = max(np.dot(h.span()[0], o.axis) - np.dot(o.span()[1], o.axis),
                          np.dot(o.span()[0], o.axis) - np.dot(h.span()[1], o.axis))
                if gap <= 1e-3:
                    foot = o.center - o.axis * np.dot(o.center, o.axis)
                    o.center, o.depth = foot + o.axis * (lo + hi) / 2, hi - lo
                    break
        else:
            out.append(Hole(h.center.copy(), h.axis.copy(), h.diameter, h.depth))
    return out


def axis_offset(h, point: np.ndarray) -> float:
    """Distance from a point to the axis line of a hole/boss."""
    v = point - h.center
    return float(np.linalg.norm(v - h.axis * np.dot(v, h.axis)))


def parallel(a: np.ndarray, b: np.ndarray, tol: float = 1e-3) -> bool:
    return abs(abs(float(np.dot(a, b))) - 1.0) < tol


# ------------------------------------------------------------------ patterns

def patterns(holes: list[Hole]) -> list[HolePattern]:
    """Group holes by parallel axis, diameter and plane; classify each group."""
    groups: list[list[Hole]] = []
    for h in holes:
        for g in groups:
            r = g[0]
            if (parallel(r.axis, h.axis) and abs(r.diameter - h.diameter) <= DIA_TOL
                    and abs(np.dot(h.center - r.center, r.axis)) <= max(r.depth, h.depth)):
                g.append(h)
                break
        else:
            groups.append([h])
    out = []
    for g in groups:
        if len(g) < 3:
            continue
        out.extend(_classify(g))
    return out


def _plane_coords(g: list[Hole]) -> tuple[np.ndarray, np.ndarray]:
    ax = g[0].axis
    ref = np.array([1.0, 0, 0]) if abs(ax[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(ax, ref)
    u /= np.linalg.norm(u)
    v = np.cross(ax, u)
    pts = np.array([[np.dot(h.center, u), np.dot(h.center, v)] for h in g])
    return pts, np.array([u, v])


def _classify(g: list[Hole]) -> list[HolePattern]:
    pts, _ = _plane_coords(g)
    centre2 = pts.mean(axis=0)
    centroid = np.mean([h.center for h in g], axis=0)
    dia = float(np.mean([h.diameter for h in g]))
    r = np.linalg.norm(pts - centre2, axis=1)
    if len(g) == 4:
        dists = sorted(np.linalg.norm(pts[i] - pts[j]) for i in range(4) for j in range(i + 1, 4))
        a, b, diag = dists[0], dists[2], dists[5]
        is_rect = (abs(dists[0] - dists[1]) < 0.05 and abs(dists[2] - dists[3]) < 0.05
                   and abs(dists[4] - dists[5]) < 0.05 and abs(math.hypot(a, b) - diag) < 0.05)
        if is_rect:
            # A square is also a 4-hole bolt circle; keep its PCD so either reading compares.
            pcd = float(diag) if abs(a - b) < 0.05 else None
            return [HolePattern("rect", g, g[0].axis, centroid, dia, pcd=pcd, a=float(a), b=float(b))]
    if r.mean() > 1e-6 and (r.max() - r.min()) / r.mean() < CIRCLE_SPREAD:
        return [HolePattern("circle", g, g[0].axis, centroid, dia, pcd=float(2 * r.mean()))]
    return [HolePattern("group", g, g[0].axis, centroid, dia)]


# ------------------------------------------------------------------ mass

def volume_props(shape) -> tuple[np.ndarray, np.ndarray]:
    """Centre of mass (mm) and inertia about it, density 1 (mm^5)."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    com = _vec(props.CentreOfMass())
    M = props.MatrixOfInertia()
    inertia = np.array([[M.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
    return com, inertia


def mass_props(f: Features, density_kg_m3: float) -> tuple[float, np.ndarray, np.ndarray]:
    """kg, COM in mm, inertia about COM in kg*m^2."""
    return f.volume * 1e-9 * density_kg_m3, f.com, f.inertia * density_kg_m3 * 1e-15


# ------------------------------------------------------------------ cache form

def to_record(f: Features) -> dict:
    """Plain JSON form for the part cache. Faces are stored by index, not by value."""
    arr = lambda a: None if a is None else np.asarray(a, dtype=float).tolist()  # noqa: E731
    return {
        "extraction_version": EXTRACTION_VERSION, "geometry_type": f.geometry_type,
        "face_count": f.face_count, "triangle_count": f.triangle_count,
        "holes": [[arr(h.center), arr(h.axis), h.diameter, h.depth] for h in f.holes],
        "bosses": [[arr(b.center), arr(b.axis), b.diameter, b.length] for b in f.bosses],
        "planes": [[arr(p.point), arr(p.normal), p.area, p.index, arr(p.box)] for p in f.planes],
        "volume": f.volume, "area": f.area, "com": arr(f.com), "inertia": arr(f.inertia), "bbox": list(f.bbox),
    }


def from_record(r: dict, shape) -> Features:
    """Rebuild features from the cache; planar faces are re-attached from the live shape by index."""
    a = lambda v: None if v is None else np.array(v, dtype=float)  # noqa: E731
    holes = [Hole(a(c), a(x), d, depth) for c, x, d, depth in r["holes"]]
    bosses = [Boss(a(c), a(x), d, ln) for c, x, d, ln in r["bosses"]]
    planes = [PlanarFace(a(p), a(n), area, None, idx, a(box)) for p, n, area, idx, box in r["planes"]]
    if planes:
        flist = list(faces(shape))
        for pf in planes:
            pf.face = flist[pf.index]
    f = Features(holes=holes, bosses=bosses, planes=planes, volume=r["volume"], area=r["area"],
                 com=a(r["com"]), inertia=a(r["inertia"]), bbox=tuple(r["bbox"]),
                 geometry_type=r["geometry_type"], face_count=r["face_count"],
                 triangle_count=r["triangle_count"], cached=True)
    f.patterns = patterns(holes)
    return f
