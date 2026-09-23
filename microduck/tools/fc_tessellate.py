"""Tessellate each part's chosen solid for the web viewer.

Runs inside FreeCAD's interpreter, and takes its geometry from the same
``load_shapes`` the STEP/FCStd assembly uses, so the viewer can never show a
different part than the CAD file does.

The previous GLB was the repaired STL meshes with normals averaged over every
vertex. That is what made the demo look broken: five of those meshes are open
(both bearings among them, although their hand-modelled solids are clean), and
averaging a normal across a hard edge turns a bracket into a blob and a coarse
cylinder into a dented one. Here every face is tessellated on its own and each
vertex takes the normal of the true surface at that point - smooth across a
cylinder, sharp at every edge.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fc_assembly import ROOT, load_shapes  # noqa: E402  (initialises FreeCAD)

import MeshPart  # noqa: E402  - only importable once FreeCAD is loaded

OUT = os.path.join(ROOT, "work", "viewer")

#: Linear deflection (mm) and angular deflection (rad) for curved faces. A
#: 20-degree step keeps a 1 mm bore visibly round without putting 90 000
#: triangles into each of the fourteen bearings.
DEFLECTION = 0.05
ANGULAR = 0.35


def tessellate(shape):
    pos, nrm, idx = [], [], []
    for face in shape.Faces:
        planar = face.Surface.__class__.__name__ == "Plane"
        try:
            if planar:
                pts, tris = face.tessellate(DEFLECTION)
            else:
                # `Face.tessellate` ignores its tolerance on curved faces (252
                # triangles per bearing race at 0.02, 0.05 and 0.2 mm alike);
                # MeshPart honours both deflections.
                m = MeshPart.meshFromShape(Shape=face, LinearDeflection=DEFLECTION,
                                           AngularDeflection=ANGULAR, Relative=False)
                pts, tris = m.Topology
        except Exception:
            continue
        if not tris:
            continue
        base = len(pos)
        fixed = None
        if planar:
            u0, u1, v0, v1 = face.ParameterRange
            fixed = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        for p in pts:
            if fixed is not None:
                n = fixed
            else:
                try:
                    u, v = face.Surface.parameter(p)
                    n = face.normalAt(u, v)
                except Exception:
                    n = None
            pos.append((p.x, p.y, p.z))
            nrm.append((n.x, n.y, n.z) if n is not None else (0.0, 0.0, 0.0))
        for a, b, c in tris:
            idx.append((base + a, base + b, base + c))

    pos = np.asarray(pos, dtype=np.float64)
    nrm = np.asarray(nrm, dtype=np.float64)
    idx = np.asarray(idx, dtype=np.int64).reshape(-1, 3)
    if not len(idx):
        return pos, nrm, idx

    # Where a surface normal could not be evaluated, use the triangle's own.
    tri_n = np.cross(pos[idx[:, 1]] - pos[idx[:, 0]], pos[idx[:, 2]] - pos[idx[:, 0]])
    missing = np.linalg.norm(nrm, axis=1) < 1e-9
    if missing.any():
        acc = np.zeros_like(pos)
        for k in range(3):
            np.add.at(acc, idx[:, k], tri_n)
        nrm[missing] = acc[missing]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)

    # Winding follows the surface normal, so back-face culling in the viewer
    # never hides a face that the solid actually has.
    avg = nrm[idx].sum(axis=1)
    flip = np.einsum("ij,ij->i", tri_n, avg) < 0
    idx[flip] = idx[flip][:, [0, 2, 1]]
    return pos, nrm, idx


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {}
    for name, (shape, source) in sorted(load_shapes().items()):
        pos, nrm, idx = tessellate(shape)
        np.savez_compressed(os.path.join(OUT, name + ".npz"),
                            positions=pos.astype(np.float32),
                            normals=nrm.astype(np.float32),
                            indices=idx.astype(np.uint32))
        bb = shape.BoundBox
        meta[name] = {
            "source": source,
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "shape_type": shape.ShapeType,
            "valid": bool(shape.isValid()),
            "solids": len(shape.Solids),
            "closed": bool(shape.Solids) or bool(getattr(shape, "isClosed", lambda: False)()),
            "volume_mm3": round(abs(shape.Volume), 2),
            "area_mm2": round(shape.Area, 2),
            "bbox_mm": [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)],
            "triangles": int(len(idx)),
            "cylindrical_faces": sum(1 for f in shape.Faces
                                     if f.Surface.__class__.__name__ in ("Cylinder", "Cone", "Toroid")),
        }
        print(f"{name:40s} {source:9s} faces={meta[name]['faces']:5d} tris={len(idx):6d}"
              f" valid={meta[name]['valid']} solids={meta[name]['solids']}")
    with open(os.path.join(OUT, "parts_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)


main()
