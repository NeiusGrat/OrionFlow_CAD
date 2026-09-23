"""Rebuild a round part as a revolved solid.

The slab sampler cannot see a tire: every section normal to its axis is an
annulus whose outer ring is the tessellation's 60-gon, and every section along
it is a different chord. What a round part actually has is one meridian
profile swept through 360 degrees, so this recovers that profile and revolves
it. The result has true circular edges and cylindrical/conical/toroidal
faces where the source mesh had a polygon fan.

The profile comes from a half-plane section through the axis. One section can
land on a local feature (a notch, a spoke), so several angles are tried and
the one whose revolved volume is closest to the reference wins. It is then
graded by the same volume and extent gate the slab rebuild uses - a part that
is not actually round fails it and stays faceted.
"""
from __future__ import annotations

import numpy as np
from build123d import Axis, Face, Location, Plane, Polyline, Vector, make_face, revolve
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .rebuild import Rebuild, _assess, extent_budget

#: Profile simplification tolerance (mm). Below the source's own float32 noise
#: floor for millimetre parts, well above the triangle size of a coarse mesh.
SIMPLIFY_MM = 0.02

#: Points this close to the axis are put on it, so the revolve does not leave
#: a hair-thin bore down the middle of a solid disc.
ON_AXIS_MM = 0.05

_E = np.eye(3)


def _frame(axis: int):
    """Right-handed (u, v, axis) unit vectors for a revolve about `axis`."""
    u, v = {0: (1, 2), 1: (2, 0), 2: (0, 1)}[axis]
    return _E[u], _E[v], _E[axis]


def _profile(mesh, centre, u, v, w, theta) -> Polygon | None:
    """Meridian profile in (r, h) from the half-plane at angle `theta`."""
    radial = np.cos(theta) * u + np.sin(theta) * v
    normal = np.cross(w, radial)
    sec = mesh.section(plane_origin=centre, plane_normal=normal)
    if sec is None:
        return None
    polys = []
    for ring in sec.discrete:
        pts = np.asarray(ring)
        if len(pts) < 3:
            continue
        rel = pts - centre
        s = rel @ radial
        h = rel @ w
        p = Polygon(np.column_stack([s, h]))
        if not p.is_valid:
            p = p.buffer(0)
        if p.area > 1e-6:
            polys.append(p)
    if not polys:
        return None
    # Section rings nest (outer boundary, bores); even-odd fill recovers the
    # material, then only the half with positive radius is the meridian.
    polys.sort(key=lambda p: -p.area)
    region = None
    for p in polys:
        region = p if region is None else region.symmetric_difference(p)
    big = float(np.max(mesh.extents)) * 4
    half = region.intersection(box(0.0, -big, big, big))
    half = unary_union(half).simplify(SIMPLIFY_MM, preserve_topology=True)
    if half.is_empty:
        return None
    if half.geom_type == "MultiPolygon":
        half = max(half.geoms, key=lambda g: g.area)
    return half if half.geom_type == "Polygon" and half.area > 1e-6 else None


def _ring(coords) -> list[tuple[float, float, float]]:
    pts = [(0.0 if r < ON_AXIS_MM else float(r), 0.0, float(h)) for r, h in coords]
    out = []
    for p in pts:
        if not out or np.hypot(p[0] - out[-1][0], p[2] - out[-1][2]) > 1e-6:
            out.append(p)
    if np.allclose(out[0], out[-1]):
        out = out[:-1]
    return out


def _solid(poly: Polygon, origin, u, w):
    """Revolve `poly` (r along local X, h along local Z) and place it."""
    outer = make_face(Polyline(*_ring(poly.exterior.coords), close=True))
    for hole in poly.interiors:
        outer = outer - make_face(Polyline(*_ring(hole.coords), close=True))
    if isinstance(outer, list) or not isinstance(outer, Face):
        faces = outer.faces() if hasattr(outer, "faces") else outer
        outer = max(faces, key=lambda f: f.area)
    local = revolve(outer, Axis.Z, 360)
    place = Location(Plane(origin=Vector(*origin), x_dir=Vector(*u), z_dir=Vector(*w)))
    return place * local


def surface_extents(mesh, samples: int = 200_000) -> np.ndarray:
    """Extents of the area the surface actually covers.

    `mesh.extents` is set by vertices, and a sliver triangle with no area can
    carry a vertex half a millimetre past the part: the tire's bounding box is
    7.91 mm wide while its surface is 7.75 mm wide all the way round. Grading
    a rebuild against a spike is grading it against the defect it removes.
    """
    pts, _ = __import__("trimesh").sample.sample_surface(mesh, samples, seed=0)
    return pts.max(axis=0) - pts.min(axis=0)


def rebuild_revolved(mesh, name: str = "", axis: int | None = None,
                     reference_volume: float | None = None, angles: int = 24) -> Rebuild:
    """Best revolve of `mesh` about an axis through its bounding-box centre.

    Every angle's profile is revolved and graded; among those that pass, the
    one whose axial width is most common round the part wins. A mesh damaged
    along one arc (the tire narrows by 0.4 mm over 110 degrees) should not
    donate its damaged section to the whole part.
    """
    ref = reference_volume if reference_volume else float(abs(mesh.volume))
    target = surface_extents(mesh)
    centre = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
    cands: list[Rebuild] = []
    for ax in ([axis] if axis is not None else [0, 1, 2]):
        u, v, w = _frame(ax)
        for theta in np.linspace(0, 2 * np.pi, angles, endpoint=False):
            try:
                prof = _profile(mesh, centre, u, v, w, theta)
                if prof is None:
                    continue
                solid = _solid(prof, centre, u, w)
            except Exception:
                continue
            cand = _assess(name, ax, solid, mesh, 1, 0, ref)
            if cand is None:
                continue
            bb = solid.bounding_box()
            ext = np.array([bb.size.X, bb.size.Y, bb.size.Z])
            cand.extent_error = float(np.max(np.abs(ext - target)))
            cand.extent_tol = extent_budget(target)
            cand.circles = len(prof.exterior.coords) - 1 + sum(len(i.coords) - 1 for i in prof.interiors)
            cand.width = float(ext[ax])
            cands.append(cand)
    if not cands:
        return Rebuild(name, -1, None, 0.0, ref, 0, 0, 0, 1e9, extent_budget(target))
    passing = [c for c in cands if c.ok]
    if passing:
        widths = np.array([c.width for c in passing])
        mode = np.median(widths)
        return min(passing, key=lambda c: (abs(c.width - mode), c.volume_error))
    return min(cands, key=lambda c: (c.volume_error + c.extent_error))
