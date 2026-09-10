"""Measure a repaired mesh: cross-sections and planar levels.

Everything here answers one question: what numbers was the original part drawn
from? `section` returns a profile in the part's own coordinates, which is what
the slab reconstruction extrudes; `planar_levels` reports the coordinates where
the part has real planar faces, which is how you read the steps of a bracket off
it. `describe` is the command-line view of both:

    python measure.py xl330 trunk_base

Ring fitting lives in recon.slabs, next to the code that consumes it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
REPAIRED = ROOT / "work" / "repaired"


def load(name: str) -> trimesh.Trimesh:
    return trimesh.load(REPAIRED / f"{name}.stl", process=True)


def planar_levels(mesh: trimesh.Trimesh, axis: int, min_area: float = 2.0):
    """Coordinates along `axis` carrying real planar faces, with their area.

    These are the levels a prismatic part was modelled at: plate faces, boss
    tops, counterbore floors.
    """
    n = np.zeros(3)
    n[axis] = 1.0
    flat = np.abs(np.abs(mesh.face_normals @ n) - 1.0) < 1e-3
    if not flat.any():
        return []
    centres = mesh.triangles_center[flat][:, axis]
    areas = mesh.area_faces[flat]
    order = np.argsort(centres)
    centres, areas = centres[order], areas[order]
    groups, cur = [], [0]
    for i in range(1, len(centres)):
        if centres[i] - centres[cur[-1]] < 1e-3:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    out = [(round(float(np.mean(centres[g])), 4), round(float(areas[g].sum()), 2))
           for g in groups if areas[g].sum() >= min_area]
    return sorted(out, key=lambda t: -t[1])


#: For a section normal to `axis`, the two global axes the 2D result is
#: expressed in, ordered right-handed so that u x v = +axis. Using (X, Z) for a
#: Y-section instead of (Z, X) would silently mirror every recovered profile.
PLANE_AXES = {0: (1, 2), 1: (2, 0), 2: (0, 1)}


def section(mesh: trimesh.Trimesh, axis: int, at: float):
    """Cross-section at `at` along `axis`, in the part's own coordinates.

    ``Path3D.to_2D`` picks an arbitrary in-plane frame, so the raw polygons come
    back rotated and offset with respect to the part. Every profile we recover
    is going to be extruded back into the assembly, so the section is mapped
    through the inverse transform and re-expressed in the two global axes the
    plane spans - a mirrored bracket is not a detail you want to find later.
    """
    n = np.zeros(3)
    n[axis] = 1.0
    o = np.zeros(3)
    o[axis] = at
    s = mesh.section(plane_origin=o, plane_normal=n)
    if s is None:
        return None
    # trimesh hands back the matrix that moves the planar path *back* into 3D
    p2, to_3D = s.to_2D()
    polys = list(p2.polygons_full)
    if not polys:
        return None
    u, v = PLANE_AXES[axis]

    def back(coords):
        c = np.asarray(coords)
        pts = np.column_stack([c[:, 0], c[:, 1], np.zeros(len(c)), np.ones(len(c))])
        xyz = (to_3D @ pts.T).T[:, :3]
        return np.column_stack([xyz[:, u], xyz[:, v]])

    mapped = []
    for g in polys:
        mapped.append(Polygon(back(g.exterior.coords),
                              [back(r.coords) for r in g.interiors]))
    out = unary_union(mapped)
    return out if not out.is_empty else None


def describe(name: str) -> None:
    m = load(name)
    print(f"=== {name} ===")
    print(f"  bbox {np.round(m.extents, 3)}  min {np.round(m.bounds[0], 3)}  "
          f"max {np.round(m.bounds[1], 3)}")
    print(f"  watertight={m.is_watertight} volume={m.volume:.1f} faces={len(m.faces)} "
          f"bodies={m.body_count}")
    for ax, letter in ((0, "X"), (1, "Y"), (2, "Z")):
        lv = planar_levels(m, ax)[:8]
        if lv:
            print(f"  planar {letter}: " + "  ".join(f"{c:.3f}({a:.0f})" for c, a in lv))


if __name__ == "__main__":
    import sys
    for n in sys.argv[1:]:
        describe(n)
        print()
