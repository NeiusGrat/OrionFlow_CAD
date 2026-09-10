"""Turn recovered slab profiles back into a B-rep solid.

Each slab becomes one extrusion: its exterior ring is a face, its interior rings
are cut from it, and any ring that fitted a circle is rebuilt as a real circle
rather than the 60-sided prism the tessellation would otherwise leave behind.
The slabs are then fused into one solid.

The result is checked against the mesh it came from - volume and bounding box -
because a reconstruction that is quietly 8% light is worse than no
reconstruction at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from build123d import (Circle, Face, Location, Plane, Polyline, Vector, Wire,
                       extrude, make_face)

from .slabs import Slab, recover

#: right-handed in-plane axes for a section normal to `axis` (u x v = +axis)
PLANE_AXES = {0: (1, 2), 1: (2, 0), 2: (0, 1)}
_UNIT = [Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1)]


def slab_plane(axis: int, offset: float) -> Plane:
    u, _v = PLANE_AXES[axis]
    return Plane(origin=_UNIT[axis] * offset, x_dir=_UNIT[u], z_dir=_UNIT[axis])


def _ring_face(kind, data) -> Face | None:
    """One recovered ring -> a planar face in the slab's local plane."""
    if kind == "circle":
        cx, cy, r = data
        if r <= 1e-6:
            return None
        return Location((cx, cy, 0)) * Circle(r).face()
    pts = np.asarray(data, dtype=float)
    if len(pts) and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    # drop points that repeat after simplification; OCC will not build on them
    keep = [pts[0]]
    for p in pts[1:]:
        if np.linalg.norm(p - keep[-1]) > 1e-6:
            keep.append(p)
    if len(keep) < 3:
        return None
    verts = [(float(x), float(y), 0.0) for x, y in keep]
    try:
        return make_face(Wire(Polyline(*verts, close=True)))
    except Exception:
        return None


def slab_solid(slab: Slab, axis: int):
    """Extrude one slab's profile into a solid.

    Each disjoint region of the section is extruded on its own and the results
    are fused. Adding two Faces together yields a ShapeList rather than a shape,
    and a plane cannot relocate a ShapeList - so a slab whose section had two
    islands used to raise inside the handler and vanish without a trace, which
    is how a 3 mm bracket came back 1 mm thick with a plausible volume.
    """
    plane = slab_plane(axis, slab.lo)
    solids = []
    for ext, interiors in slab.rings:
        face = _ring_face(*ext)
        if face is None:
            continue
        for kind, data in interiors:
            hole = _ring_face(kind, data)
            if hole is None:
                continue
            try:
                cut = face - hole
                face = cut if isinstance(cut, Face) else cut.faces()[0]
            except Exception:
                pass
        try:
            solids.append(extrude(plane * face, amount=slab.depth))
        except Exception:
            continue
    if not solids:
        return None
    out = solids[0]
    for extra in solids[1:]:
        try:
            out = out + extra
        except Exception:
            pass
    return out


#: A rebuild is accepted only inside these bounds. They are exported so the
#: verifier grades against the same numbers the gate used - when the two drifted
#: apart, a part accepted at 0.07 mm was then reported as out of spec.
VOLUME_TOL = 0.02          # fraction of the reference volume
EXTENT_TOL_FLOOR = 0.05    # mm
EXTENT_TOL_FRAC = 0.003    # of the part's largest dimension


def extent_budget(extents) -> float:
    """Allowed bounding-box error for a part of this size.

    The sampler resolves the slab axis at span/samples and takes each slab's
    profile from a single section, so the extent it can resolve scales with the
    part: 0.7 mm between samples on a 70 mm battery against 0.2 mm on a 20 mm
    bracket. A fixed absolute tolerance therefore over-constrains large parts
    and under-constrains small ones.
    """
    return max(EXTENT_TOL_FLOOR, EXTENT_TOL_FRAC * float(max(extents)))


#: Ceiling on the per-axis solids that the cross-axis intersection will accept.
INTERSECT_MAX_FACES = 400

#: Above this many slabs the part is not prismatic along that axis - the
#: sampler is just tracing a staircase up a curved surface. Building those
#: extrusions is slow and the result is rejected anyway, so bail out first.
MAX_SLABS = 40


@dataclass
class Rebuild:
    name: str
    axis: int
    solid: object | None
    volume: float
    mesh_volume: float
    slabs: int
    faces: int
    circles: int
    extent_error: float
    extent_tol: float = EXTENT_TOL_FLOOR

    @property
    def volume_error(self) -> float:
        if not self.mesh_volume:
            return float("inf")
        return abs(self.volume - self.mesh_volume) / self.mesh_volume

    @property
    def ok(self) -> bool:
        return (self.solid is not None and self.volume > 0
                and self.volume_error < VOLUME_TOL
                and self.extent_error < self.extent_tol)


def _assess(name, axis, solid, mesh, slabs, ncirc, ref):
    try:
        vol = float(solid.volume)
        bb = solid.bounding_box()
        ext = np.array([bb.size.X, bb.size.Y, bb.size.Z])
        nfaces = len(solid.faces())
    except Exception:
        return None
    return Rebuild(name=name, axis=axis, solid=solid, volume=vol,
                   mesh_volume=ref, slabs=slabs, faces=nfaces, circles=ncirc,
                   extent_error=float(np.max(np.abs(ext - mesh.extents))),
                   extent_tol=extent_budget(mesh.extents))


def rebuild(mesh, name: str = "", axis: int | None = None,
            max_slabs: int = MAX_SLABS, reference_volume: float | None = None) -> Rebuild:
    """Rebuild `mesh` as slab extrusions.

    Four candidates are tried: one reconstruction per axis, plus the
    intersection of all of them. A single axis cannot cut a hole that runs
    across it - extruding `leg` along X leaves its transverse bores filled and
    the part comes back 59% heavy - whereas the intersection of the three
    sweeps carries every feature that any one view can see.

    `reference_volume` overrides the mesh's own volume as the fidelity
    yardstick. Seventeen of the source meshes do not close even after repair,
    and trimesh's volume for an open mesh is not a number you can grade
    against; the sewn B-rep volume from FreeCAD is.
    """
    ref = reference_volume if reference_volume else float(abs(mesh.volume))
    axes = [axis] if axis is not None else [0, 1, 2]
    candidates: list[Rebuild] = []
    per_axis: list[object] = []

    for ax in axes:
        try:
            a, slabs = recover(mesh, axis=ax)
        except Exception:
            continue
        if not slabs or len(slabs) > max_slabs:
            continue
        parts = [s for s in (slab_solid(sl, a) for sl in slabs) if s is not None]
        if not parts:
            continue
        solid = parts[0]
        for extra in parts[1:]:
            try:
                solid = solid + extra
            except Exception:
                pass
        ncirc = sum(1 for s in slabs for e, ins in s.rings
                    for k, _ in [e] + ins if k == "circle")
        cand = _assess(name, a, solid, mesh, len(slabs), ncirc, ref)
        if cand is not None:
            candidates.append(cand)
            per_axis.append(solid)

    # The intersection is what recovers a hole that runs across the extrusion
    # axis, and those parts are small brackets. On a big reconstruction it is
    # not worth it: three 2 000-face solids took over seven minutes to intersect
    # and still lost, so the sweep would sit on one part indefinitely.
    if len(per_axis) > 1 and all(len(s.faces()) <= INTERSECT_MAX_FACES
                                 for s in per_axis):
        inter = per_axis[0]
        try:
            for extra in per_axis[1:]:
                inter = inter & extra
            cand = _assess(name, -2, inter, mesh,
                           sum(c.slabs for c in candidates),
                           sum(c.circles for c in candidates), ref)
            if cand is not None:
                candidates.append(cand)
        except Exception:
            pass

    if not candidates:
        return Rebuild(name, -1, None, 0.0, ref, 0, 0, 0, 1e9,
                       extent_budget(mesh.extents))
    return min(candidates, key=lambda c: (not c.ok, c.volume_error, c.extent_error))
