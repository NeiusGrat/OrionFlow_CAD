"""Build, measure AND export a FeatureGraph — the studio's FreeCAD worker.

``build_measure_fc.py`` exists to score the corpus: it builds and measures, and
nothing downstream ever needs the geometry itself. The studio does — a user is
waiting to see the part and download it. This adds STEP and STL export to that
same one-process cycle, so serving a request costs one FreeCAD startup rather
than three.

Deliberately reuses ``freecad/reconstruct.py`` and ``measure_fc.py`` untouched.
The corpus was verified through those exact modules; a second implementation of
the compile or the measurement would mean the geometry a user downloads is not
the geometry the model's assertions were checked against.

Usage (FreeCAD's Python):
    python build_export_fc.py --graph g.json --fcstd out.FCStd --out m.json \
        --step out.step --stl out.stl
"""

import argparse
import importlib.util
import json
import os
import sys


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _body_of(doc):
    """The PartDesign Body to export, or None if the compile produced no solid."""
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if not bodies:
        return None
    shape = getattr(bodies[0], "Shape", None)
    if shape is None or shape.isNull():
        return None
    return bodies[0]


def _export_step(body, path):
    import Part  # noqa: PLC0415

    Part.export([body], path)


def _export_stl(body, path, linear_deflection=0.05, angular_deflection=0.5):
    """Tessellate to STL.

    MeshPart is preferred because the deflection is explicit: the STL becomes
    the GLB the viewer shows, and FreeCAD's default deflection is coarse enough
    that a 5 mm fillet visibly facets. Falls back to the Mesh module when
    MeshPart is unavailable (it is a separate workbench in some builds).
    """
    try:
        import MeshPart  # noqa: PLC0415

        mesh = MeshPart.meshFromShape(
            Shape=body.Shape,
            LinearDeflection=linear_deflection,
            AngularDeflection=angular_deflection,
            Relative=False,
        )
        mesh.write(path)
    except ImportError:
        import Mesh  # noqa: PLC0415

        Mesh.export([body], path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--fcstd", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", help="write a STEP export here")
    ap.add_argument("--stl", help="write an STL export here")
    ap.add_argument("--deflection", type=float, default=0.05,
                    help="STL linear deflection in mm (default 0.05)")
    ap.add_argument("--mesh-body", action="store_true",
                    help="also mesh-sample the body for convergence checking")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    recon = _load(os.path.join(repo, "freecad", "reconstruct.py"), "_orion_recon")
    meas = _load(os.path.join(here, "measure_fc.py"), "_orion_measure")

    graph = json.load(open(args.graph, encoding="utf-8"))
    doc, report = recon.compile_graph(
        graph, os.path.splitext(os.path.basename(args.fcstd))[0])
    doc.saveAs(os.path.abspath(args.fcstd))

    # Export from the live document, before it is closed. Each export is
    # individually guarded: a part that measures correctly but cannot be
    # tessellated is still a real result, and losing the measurement because
    # STL writing failed would turn a partial success into a total one.
    exports, export_errors = {}, {}
    body = _body_of(doc)
    if body is None:
        export_errors["body"] = "no PartDesign::Body with a valid shape"
    else:
        if args.step:
            try:
                _export_step(body, os.path.abspath(args.step))
                exports["step"] = os.path.abspath(args.step)
            except Exception as e:  # noqa: BLE001
                export_errors["step"] = str(e)[:300]
        if args.stl:
            try:
                _export_stl(body, os.path.abspath(args.stl), args.deflection)
                exports["stl"] = os.path.abspath(args.stl)
            except Exception as e:  # noqa: BLE001
                export_errors["stl"] = str(e)[:300]

    import FreeCAD as App  # noqa: PLC0415

    App.closeDocument(doc.Name)

    measured = meas.measure_document(os.path.abspath(args.fcstd),
                                     mesh_body=args.mesh_body)
    measured["build_report"] = {
        "unsupported": report.get("unsupported", []),
        "recompute_errors": report.get("recompute_errors", []),
        "built": report.get("built", []),
    }
    measured["exports"] = exports
    if export_errors:
        measured["export_errors"] = export_errors
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(measured, fh)
    print("ok")


if __name__ == "__main__":
    main()
