"""Assemble the MicroDuck from its part solids and write STEP / FCStd.

Runs inside FreeCAD's interpreter. Reads ``work/placements_<pose>.json`` for the
kinematic placement of all 71 part instances and ``work/brep`` (plus
``work/parametric``, which wins where it exists) for the geometry.

Each MJCF body becomes an ``App::Part`` container so the STEP comes out as a
real product tree - trunk_base / yaw2roll / hip_l / ... - rather than 71 loose
solids in one bag.
"""
import json
import os
import sys

import FreeCAD as App
import Part

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Geometry sources, each a folder of BREP named by part.
#:   faceted  - every mesh sewn into a B-rep with coplanar triangles merged
#:   slab     - profiles recovered along an axis and extruded back
#:   modelled - written by hand from measurements, for parts the others cannot
#: They were briefly one folder, which meant an accepted slab rebuild silently
#: overwrote the 19-face hand-modelled bearing with a worse one.
SOURCES = (("faceted", os.path.join(ROOT, "work", "brep")),
           ("slab", os.path.join(ROOT, "work", "slab")),
           ("modelled", os.path.join(ROOT, "work", "modelled")))
OUT = os.path.join(ROOT, "out")

#: Poses exported as STEP. The others differ only by joint angle.
STEP_BUILDS = ("zero", "rollers")

#: How much larger a recovered part may be than the faceted conversion and
#: still win. Face count is the wrong thing to minimise on its own: a recovered
#: face is a plane or a cylinder that a CAD system can select, dimension and
#: edit, while a faceted face is one triangle of a tessellation. Recovering the
#: XL330 costs 328 extra faces per servo and buys real geometry on all fifteen.
RECOVERED_FACE_BUDGET = 2.0


def load_shapes():
    """part name -> (shape, source), choosing the better solid for each part.

    Both sources are already verified against the same mesh, so correctness does
    not decide this - compactness does. A parametric rebuild is usually far
    smaller (a bearing goes from 5 201 faces to 19), but not always: `ankle_left`
    reconstructs to 0.011% volume error and still carries 1 772 faces against
    717 for the faceted conversion, because 29 slabs leave a boundary face at
    every step. Preferring parametric unconditionally would make that part -
    and the assembly - bigger for nothing.

    Validity and enclosing a volume come first - an invalid solid must never
    beat a valid shell, because booleans and mass properties both go quietly
    wrong on one, and two parts did come back invalid after their shells were
    closed. The volume test asks whether the shape carries solids rather than
    what its own type is called: fusing disjoint slab regions leaves a Compound,
    and ranking on the type name would drop the 157-face `trunk_base` in favour
    of the 467-face faceted one for no reason.

    Among usable candidates the recovered geometry wins unless it is more than
    RECOVERED_FACE_BUDGET times the size of the faceted conversion.
    """
    pools = {}
    for src, folder in SOURCES:
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".brep"):
                continue
            sh = Part.Shape()
            sh.read(os.path.join(folder, fn))
            if sh.ShapeType == "Compound" and len(sh.Solids) == 1:
                sh = sh.Solids[0]          # unwrap; it is a solid in a bag
            pools.setdefault(fn[:-5], []).append((sh, src))

    return {name: _choose(options) for name, options in pools.items()}


def _choose(options):
    """Pick the geometry for one part from the sources that offer it."""
    usable = [o for o in options if o[0].isValid() and o[0].Solids] or options
    faceted = next((o for o in usable if o[1] == "faceted"), None)
    recovered = [o for o in usable if o[1] != "faceted"]
    if recovered:
        best = min(recovered, key=lambda o: len(o[0].Faces))
        budget = RECOVERED_FACE_BUDGET * len(faceted[0].Faces) if faceted else float("inf")
        if len(best[0].Faces) <= budget:
            return best
    return min(usable, key=lambda o: (not o[0].isValid(), not o[0].Solids,
                                      len(o[0].Faces)))


def export_parts(shapes):
    """One STEP per distinct part, taken from whichever source won."""
    out = os.path.join(OUT, "parts")
    os.makedirs(out, exist_ok=True)
    written = {}
    for name, (shape, source) in shapes.items():
        path = os.path.join(out, name + ".step")
        shape.exportStep(path)
        written[name] = {"source": source, "faces": len(shape.Faces),
                         "kb": round(os.path.getsize(path) / 1024, 1)}
    return written


def build(pose_label, parts_report=None):
    with open(os.path.join(ROOT, "work", f"placements_{pose_label}.json")) as fh:
        data = json.load(fh)
    shapes = load_shapes()

    doc = App.newDocument("microduck_" + pose_label)
    containers = {}
    for b in data["bodies"]:
        part = doc.addObject("App::Part", "body_" + b["name"])
        part.Label = b["name"]
        containers[b["name"]] = part

    # nest each body under its parent so the STEP carries the kinematic tree
    for b in data["bodies"]:
        if b["parent"]:
            containers[b["parent"]].addObject(containers[b["name"]])

    missing, placed, by_source = [], 0, {}
    for inst in data["instances"]:
        entry = shapes.get(inst["part"])
        if entry is None:
            missing.append(inst["part"])
            continue
        shape, source = entry
        obj = doc.addObject("Part::Feature", "p_" + inst["part"])
        obj.Label = inst["part"]
        obj.Shape = shape.copy()
        m = inst["matrix"]
        obj.Placement = App.Placement(App.Matrix(*m))
        containers[inst["body"]].addObject(obj)
        placed += 1
        by_source[source] = by_source.get(source, 0) + 1

    doc.recompute()
    roots = [containers[b["name"]] for b in data["bodies"] if b["parent"] is None]
    if parts_report is not None:
        parts_report.update(export_parts(shapes))

    os.makedirs(OUT, exist_ok=True)
    # STEP only for the two real configurations. `stand` and `crouch` are the
    # same parts at different joint angles, and a 95 MB STEP each to say so is
    # not worth it - the FCStd and the GLB already carry the pose.
    step = os.path.join(OUT, f"microduck_{pose_label}.step")
    if pose_label in STEP_BUILDS:
        import Import
        Import.export(roots, step)
    doc.saveAs(os.path.join(OUT, f"microduck_{pose_label}.FCStd"))

    # one fused solid is what most measurement tools want to see
    allshapes = [o.Shape.copy() for o in doc.Objects
                 if o.isDerivedFrom("Part::Feature") and not o.Shape.isNull()]
    comp = Part.Compound(allshapes)
    bb = comp.BoundBox
    return {
        "pose": pose_label,
        "placed": placed,
        "instances": len(data["instances"]),
        "missing": sorted(set(missing)),
        "sources": by_source,
        "step_mb": (round(os.path.getsize(step) / 1024 / 1024, 2)
                    if os.path.exists(step) else None),
        "bbox_mm": [round(bb.XLength, 2), round(bb.YLength, 2), round(bb.ZLength, 2)],
        "bbox_min": [round(bb.XMin, 2), round(bb.YMin, 2), round(bb.ZMin, 2)],
        "bbox_max": [round(bb.XMax, 2), round(bb.YMax, 2), round(bb.ZMax, 2)],
        "volume_mm3": round(sum(abs(s.Volume) for s in allshapes), 1),
    }


def main():
    poses = sys.argv[1:] or ["zero", "stand", "crouch", "rollers"]
    parts = {}
    report = [build(p, parts if i == 0 else None) for i, p in enumerate(poses)]
    with open(os.path.join(ROOT, "work", "parts_report.json"), "w") as fh:
        json.dump(parts, fh, indent=2)
    with open(os.path.join(ROOT, "work", "assembly_report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    lines = []
    for r in report:
        step = f"{r['step_mb']} MB" if r["step_mb"] else "-"
        lines.append(f"{r['pose']:8s} placed={r['placed']}/{r['instances']} step={step} "
                     f"bbox={r['bbox_mm']} vol={r['volume_mm3']} mm3 "
                     f"sources={r['sources']} missing={r['missing']}")
    with open(os.path.join(ROOT, "work", "assembly_report.txt"), "w") as fh:
        fh.write("\n".join(lines))


main()
