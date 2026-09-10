"""Convert the repaired meshes into B-rep solids and write STEP per part.

Runs inside FreeCAD's interpreter. ``makeShapeFromMesh`` with sewing turns the
triangle soup into a shell; ``removeSplitter`` then fuses coplanar triangles
back into single planar faces, which is what takes a plate from 818 loose
triangles to 467 real faces.

Refinement is only kept when it preserves the part: on a couple of meshes
``removeSplitter`` returns a compound with essentially no volume, and silently
shipping that would put a hollow ghost into the assembly.
"""
import json
import os
import time

import FreeCAD  # noqa: F401  - initialises the module path Mesh/Part load from
import Mesh
import Part

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "work", "repaired")
OUT = os.path.join(ROOT, "work", "brep")
SEW_TOL = 0.02          # mm; float32 STL of a millimetre-scale part


def to_solid(path):
    md = Mesh.Mesh(path)
    shell = Part.Shape()
    shell.makeShapeFromMesh(md.Topology, SEW_TOL, True)
    stats = {"tris": md.CountFacets, "sewn_faces": len(shell.Faces),
             "closed": bool(shell.isClosed())}

    # A watertight mesh can still sew into a Compound of separate shells when a
    # seam falls outside the tolerance - `left_shell` closed at the mesh level
    # and still arrived as a Compound holding no solid. Re-sew those faces on
    # their own, at a looser tolerance, before giving up on the part.
    if not shell.isClosed():
        for tol in (SEW_TOL * 5, SEW_TOL * 25):
            try:
                merged = Part.Shape()
                merged.makeShapeFromMesh(md.Topology, tol, True)
                if merged.isClosed():
                    shell = merged
                    stats["resewn_tol"] = tol
                    stats["closed"] = True
                    break
            except Exception:
                break

    shape = shell
    if shell.isClosed():
        try:
            solid = Part.Solid(shell)
            if solid.Volume < 0:
                solid.reverse()
            shape = solid
        except Exception as exc:
            stats["solid_error"] = str(exc)[:80]

    base_vol = abs(shape.Volume)
    base_solids = len(shape.Solids)
    try:
        refined = shape.removeSplitter()
        # Refinement must not cost the part its solidity: merging coplanar faces
        # can hand back a Compound holding no solid at all, and `left_shell`
        # went into the assembly that way - a closed mesh that still could not
        # be measured or booleaned.
        kept = (len(refined.Faces) > 0 and refined.isValid()
                and len(refined.Solids) >= base_solids
                and (base_vol <= 0 or abs(abs(refined.Volume) - base_vol) / base_vol < 0.01))
        if kept:
            shape = refined
        stats["refined"] = bool(kept)
    except Exception as exc:
        stats["refine_error"] = str(exc)[:80]
        stats["refined"] = False

    # Closing a curved shell with a centroid fan can leave self-intersecting
    # facets, and an invalid solid is worse in an assembly than a valid shell:
    # booleans and mass properties both go wrong silently. Try OCC's shape fix,
    # and keep it only if it actually helps without moving the geometry.
    if not shape.isValid():
        try:
            fixed = shape.copy()
            fixed.fix(0.01, 0.01, 0.1)
            moved = max(abs(a - b) for a, b in zip(
                (fixed.BoundBox.XLength, fixed.BoundBox.YLength, fixed.BoundBox.ZLength),
                (shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength)))
            drift = (abs(abs(fixed.Volume) - abs(shape.Volume)) / abs(shape.Volume)
                     if shape.Volume else 0.0)
            if fixed.isValid() and moved < 0.05 and drift < 0.02:
                shape = fixed
                stats["fixed"] = True
        except Exception as exc:
            stats["fix_error"] = str(exc)[:80]

    bb = shape.BoundBox
    stats.update(faces=len(shape.Faces), volume=float(abs(shape.Volume)),
                 valid=bool(shape.isValid()), shape_type=shape.ShapeType,
                 extents=[round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)])
    return shape, stats


def main():
    os.makedirs(OUT, exist_ok=True)
    report = {}
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".stl"):
            continue
        name = fn[:-4]
        t0 = time.time()
        try:
            shape, stats = to_solid(os.path.join(SRC, fn))
        except Exception as exc:
            report[name] = {"error": str(exc)[:120]}
            continue
        shape.exportBrep(os.path.join(OUT, name + ".brep"))
        stats["seconds"] = round(time.time() - t0, 2)
        stats["brep_kb"] = round(os.path.getsize(os.path.join(OUT, name + ".brep")) / 1024, 1)
        report[name] = stats

    with open(os.path.join(ROOT, "work", "solid_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    lines = [f"{'part':40s} {'tris':>5s} {'faces':>6s} {'type':>9s} {'ref':>5s} "
             f"{'valid':>5s} {'vol_mm3':>10s} {'kB':>7s} {'s':>5s}"]
    for n, s in report.items():
        if "error" in s:
            lines.append(f"{n:40s} ERROR {s['error']}")
            continue
        lines.append(f"{n:40s} {s['tris']:5d} {s['faces']:6d} {s['shape_type']:>9s} "
                     f"{str(s.get('refined')):>5s} {str(s['valid']):>5s} {s['volume']:10.1f} "
                     f"{s['brep_kb']:7.1f} {s['seconds']:5.1f}")
    ns = sum(1 for s in report.values() if s.get("shape_type") == "Solid")
    lines.append(f"\nsolids {ns}/{len(report)}   "
                 f"total BREP {sum(s.get('brep_kb', 0) for s in report.values()) / 1024:.1f} MB")
    with open(os.path.join(ROOT, "work", "solid_report.txt"), "w") as fh:
        fh.write("\n".join(lines))


main()
