"""FeatureGraph -> exact solid, placed; and meshes from the solid.

Solids come from OrionFlow's existing FeatureGraph compiler
(`app.compilers.build123d_compiler`), so a robot link is built by the same
code path as any other part. Meshes are tessellated from the exact solid -
the solid is the truth, a mesh is only ever a view of it.
"""
from __future__ import annotations

import numpy as np
import trimesh
from build123d import Compound, Location
from OCP.gp import gp_Trsf

from app.compilers.build123d_compiler import Build123dCompiler, BuildContext
from app.domain.feature_graph import FeatureGraph

#: Tessellation for simulator meshes, mm and degrees.
LINEAR_TOL_MM = 0.05
ANGULAR_TOL_DEG = 5.0

_compiler = Build123dCompiler.__new__(Build123dCompiler)   # no output dir: geometry only


def solid(graph: FeatureGraph):
    """Compile a FeatureGraph to its exact solid (millimetres)."""
    ctx = BuildContext(graph)
    _compiler._build_geometry(ctx)
    if ctx.part is None:
        raise ValueError("FeatureGraph built nothing")
    part = ctx.part
    solids = part.solids()
    if len(solids) != 1:
        raise ValueError(f"FeatureGraph built {len(solids)} solids, expected exactly one")
    if not solids[0].is_valid:
        raise ValueError("FeatureGraph built an invalid solid")
    return solids[0]


def place(shape, T: np.ndarray):
    """The shape moved by a 4x4 transform (millimetres)."""
    tr = gp_Trsf()
    tr.SetValues(*(float(v) for v in T[0, :4]), *(float(v) for v in T[1, :4]), *(float(v) for v in T[2, :4]))
    return shape.moved(Location(tr))


def mesh_m(shape) -> trimesh.Trimesh:
    """Tessellate an exact solid into a closed mesh, in metres."""
    verts, tris = shape.tessellate(LINEAR_TOL_MM, ANGULAR_TOL_DEG)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=np.float64) * 1e-3
    m = trimesh.Trimesh(v, np.asarray(tris, dtype=np.int64), process=True)
    trimesh.repair.fix_normals(m)
    return m


def compound(shapes) -> Compound:
    return Compound(list(shapes))
