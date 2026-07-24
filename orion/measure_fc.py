"""FreeCAD-side measurement: the ONLY module that touches OCC.

Usage (FreeCAD's Python):
    freecad_python orion/measure_fc.py --dir freecad/data/fcstd --out m.json
    freecad_python orion/measure_fc.py --files a.FCStd b.FCStd --out m.json

Per document it records the final body volume and, per PartDesign feature,
the ``AddSubShape`` volume — the feature's boolean-free tool solid. That is
the quantity Tier-1 closed forms predict exactly, independent of how features
overlap downstream. Nothing here predicts anything; measurement and
prediction must never share code.
"""

import argparse
import glob
import json
import os
import sys

import FreeCAD as App  # type: ignore

SOLID_FEATURES = (
    "PartDesign::Pad", "PartDesign::Pocket",
    "PartDesign::Revolution", "PartDesign::Groove",
    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft",
    "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
    "PartDesign::AdditiveSphere", "PartDesign::SubtractiveSphere",
    "PartDesign::AdditiveBox", "PartDesign::AdditiveCylinder",
    "PartDesign::AdditiveCone", "PartDesign::AdditiveTorus",
    "PartDesign::Hole",
)


def _mesh_volume(shape, deflection):
    """Divergence-theorem volume of a tessellation — independent of OCC's
    analytic B-rep volume (uses only the tessellated vertices)."""
    verts, facets = shape.tessellate(deflection)
    v6 = 0.0
    for a, b, c in facets:
        p, q, r = verts[a], verts[b], verts[c]
        v6 += (p.x * (q.y * r.z - q.z * r.y)
               - p.y * (q.x * r.z - q.z * r.x)
               + p.z * (q.x * r.y - q.y * r.x))
    return abs(v6) / 6.0, len(facets)


def measure_document(path, mesh_body=False):
    doc = App.openDocument(path)
    try:
        rec = {"features": [], "body_volume": None, "bbox": None,
               "solids": None, "watertight": None, "valid": None}
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        if bodies:
            shape = bodies[0].Shape
            if shape is not None and not shape.isNull():
                rec["body_volume"] = float(shape.Volume)
                bb = shape.BoundBox
                rec["bbox"] = [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]
                try:
                    rec["solids"] = len(shape.Solids)
                    rec["watertight"] = bool(shape.Solids) and all(
                        s.isClosed() for s in shape.Solids)
                    rec["valid"] = bool(shape.isValid())
                except Exception:  # noqa: BLE001
                    pass
                if mesh_body:
                    # Fine tessellation is required to converge (the coarse-
                    # mesh plateau finding from verification_coverage_report).
                    series = []
                    for d in (0.06, 0.015, 0.004):
                        try:
                            v, nf = _mesh_volume(shape, d)
                            series.append({"defl": d, "V": v, "facets": nf})
                        except Exception as e:  # noqa: BLE001
                            series.append({"defl": d, "error": str(e)[:60]})
                    rec["mesh_series"] = series
        for o in doc.Objects:
            if o.TypeId not in SOLID_FEATURES:
                continue
            row = {"name": o.Name, "type_id": o.TypeId,
                   "addsub_volume": None, "cumulative_volume": None}
            tool = getattr(o, "AddSubShape", None)
            if tool is not None and not tool.isNull():
                try:
                    row["addsub_volume"] = float(tool.Volume)
                except Exception:  # noqa: BLE001
                    pass
            shp = getattr(o, "Shape", None)
            if shp is not None and not shp.isNull():
                try:
                    row["cumulative_volume"] = float(shp.Volume)
                except Exception:  # noqa: BLE001
                    pass
            rec["features"].append(row)
        return rec
    finally:
        App.closeDocument(doc.Name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paths = list(args.files or [])
    if args.dir:
        paths += sorted(glob.glob(os.path.join(args.dir, "*.FCStd")))
    out = {}
    for p in paths:
        key = os.path.splitext(os.path.basename(p))[0]
        try:
            out[key] = measure_document(os.path.abspath(p))
        except Exception as e:  # noqa: BLE001
            out[key] = {"error": str(e)[:300]}
        sys.stderr.write(f"measured {key}\n")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"wrote {args.out} ({len(out)} documents)")


if __name__ == "__main__":
    main()
