"""Rebuild a prismatic part as true B-rep by slicing it into slabs.

Most of the MicroDuck's printed structure is prismatic along one axis but is not
a single extrusion: a bracket is a stack of steps, bosses and pockets. So rather
than ask "is this one extrude?", we walk the part along an axis, find the runs
over which the cross-section does not change, and treat each run as a slab to
extrude back.

Slab breaks were first taken from the part's planar face levels, which is the
obvious signal but an incomplete one: a level that the export decimated away, or
one whose faces fall under the area threshold, silently merges two slabs and the
reconstruction comes back tens of percent light. Sampling the section densely
and cutting where the profile actually changes needs no such threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh
from shapely.geometry import Polygon

@dataclass
class Slab:
    lo: float
    hi: float
    polygon: Polygon | None
    rings: list = field(default_factory=list)

    @property
    def depth(self) -> float:
        return self.hi - self.lo


def prismatic_axis(mesh: trimesh.Trimesh) -> tuple[int, float]:
    """The axis whose normal direction carries the most planar face area."""
    best = (0, -1.0)
    for ax in range(3):
        n = np.zeros(3)
        n[ax] = 1.0
        flat = np.abs(np.abs(mesh.face_normals @ n) - 1.0) < 1e-3
        area = float(mesh.area_faces[flat].sum())
        if area > best[1]:
            best = (ax, area)
    return best[0], best[1] / float(mesh.area)


def _section(mesh, axis, at):
    from measure import section as _sec
    try:
        return _sec(mesh, axis, at)
    except Exception:
        return None


def _differs(a, b, tol: float) -> bool:
    """True when two cross-sections are not the same profile."""
    if (a is None) != (b is None):
        return True
    if a is None:
        return False
    union = a.union(b).area
    if union <= 1e-9:
        return False
    return a.symmetric_difference(b).area / union > tol


def slab_breaks(mesh, axis: int, samples: int = 96, tol: float = 0.02):
    """Positions along `axis` where the cross-section changes.

    Returns [(lo, hi, representative_polygon)] for every run of constant profile.
    """
    lo, hi = float(mesh.bounds[0][axis]), float(mesh.bounds[1][axis])
    span = hi - lo
    if span <= 1e-6:
        return []
    # sample strictly inside so the two end faces are never sampled edge-on
    ts = np.linspace(lo + span * 0.002, hi - span * 0.002, samples)
    polys = [_section(mesh, axis, float(t)) for t in ts]

    runs, start = [], 0
    for i in range(1, len(ts)):
        if _differs(polys[start], polys[i], tol):
            runs.append((start, i - 1))
            start = i
    runs.append((start, len(ts) - 1))

    out = []
    for a, b in runs:
        # the middle sample is the representative, but a section can fail on a
        # tangency or a sliver; scan outward rather than drop the run, because
        # dropping it silently forfeits its span and the part rebuilds short
        rep = None
        mid = (a + b) // 2
        for k in sorted(range(a, b + 1), key=lambda i: abs(i - mid)):
            if polys[k] is not None:
                rep = polys[k]
                break
        # snap the run's ends to the midpoints between neighbouring samples,
        # and to the part's own extremes at the two ends
        z0 = lo if a == 0 else 0.5 * (ts[a - 1] + ts[a])
        z1 = hi if b == len(ts) - 1 else 0.5 * (ts[b] + ts[b + 1])
        out.append((float(z0), float(z1), rep))

    # a run with no usable section at all still owns its span: give it to a
    # neighbour instead of leaving a hole in the part
    merged = []
    for z0, z1, rep in out:
        if rep is None:
            if merged:
                merged[-1] = (merged[-1][0], z1, merged[-1][2])
            continue
        if merged and merged[-1][2] is None:
            merged[-1] = (merged[-1][0], z1, rep)
        else:
            merged.append((z0, z1, rep))
    return [(a, b, r) for a, b, r in merged if r is not None]


def _fit_circle(pts: np.ndarray):
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    sol, *_ = np.linalg.lstsq(A, x ** 2 + y ** 2, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    r = float(np.sqrt(max(sol[2] + cx ** 2 + cy ** 2, 0.0)))
    res = float(np.abs(np.hypot(x - cx, y - cy) - r).max()) if r > 0 else 1e9
    return float(cx), float(cy), r, res


def _regularise(ring: np.ndarray, tol: float, circle_tol: float):
    """Snap a section ring to the primitive behind it.

    Recovering the circle is the whole point: it is the difference between a
    bore you can edit and a 60-sided prism you cannot.
    """
    pts = ring[:-1] if np.allclose(ring[0], ring[-1]) else ring
    if len(pts) >= 8:
        cx, cy, r, res = _fit_circle(pts)
        if r > 0.2 and res < circle_tol:
            return ("circle", (cx, cy, r))
    return ("poly", np.asarray(Polygon(ring).simplify(tol).exterior.coords))


def _merge_thin(runs, min_slab: float):
    """Fold runs thinner than `min_slab` into a neighbour instead of dropping them.

    The sampler works at a fixed number of samples, so on a 3 mm-thick bracket
    one sample is 0.03 mm and a genuine one-sample step falls under any sensible
    absolute threshold. Dropping it also drops its span, and the rebuilt part
    comes out 2 mm short in that direction while its volume still looks right.
    """
    runs = list(runs)
    while len(runs) > 1:
        i = min(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0])
        z0, z1, poly = runs[i]
        if z1 - z0 >= min_slab:
            break
        prev = runs[i - 1] if i > 0 else None
        nxt = runs[i + 1] if i + 1 < len(runs) else None
        # hand the span to the thicker neighbour, whose profile dominates it
        if prev is None or (nxt is not None and (nxt[1] - nxt[0]) > (prev[1] - prev[0])):
            runs[i + 1] = (z0, nxt[1], nxt[2])
        else:
            runs[i - 1] = (prev[0], z1, prev[2])
        runs.pop(i)
    return runs


def recover(mesh: trimesh.Trimesh, axis: int | None = None,
            simplify: float = 0.02, circle_tol: float = 0.05,
            min_slab: float = 0.05, samples: int = 96) -> tuple[int, list[Slab]]:
    """Slice `mesh` into slabs along `axis` and recover each slab's profile."""
    if axis is None:
        axis, _ = prismatic_axis(mesh)
    slabs: list[Slab] = []
    for z0, z1, poly in _merge_thin(slab_breaks(mesh, axis, samples=samples), min_slab):
        geoms = [poly] if isinstance(poly, Polygon) else list(poly.geoms)
        rings = []
        for g in geoms:
            ext = _regularise(np.asarray(g.exterior.coords), simplify, circle_tol)
            ins = [_regularise(np.asarray(r.coords), simplify, circle_tol)
                   for r in g.interiors]
            rings.append((ext, ins))
        slabs.append(Slab(lo=z0, hi=z1, polygon=poly, rings=rings))
    return axis, slabs
