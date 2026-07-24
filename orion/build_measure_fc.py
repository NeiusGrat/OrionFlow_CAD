"""One-process build + measure for the forge loop.

Compiles a FeatureGraph with the production compiler (freecad/reconstruct.py,
loaded by absolute path exactly as the agent addon does) and measures the
result in the same FreeCAD interpreter — saving a full interpreter startup
per cycle versus running reconstruct and measure_fc as separate subprocesses.

Usage (FreeCAD's Python):
    python build_measure_fc.py --graph g.json --fcstd out.FCStd --out m.json
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--fcstd", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mesh-body", action="store_true",
                    help="also mesh-sample the body at several deflections "
                         "(for Tier-2 convergence verification)")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    recon = _load(os.path.join(repo, "freecad", "reconstruct.py"), "_orion_recon")
    meas = _load(os.path.join(here, "measure_fc.py"), "_orion_measure")

    graph = json.load(open(args.graph, encoding="utf-8"))
    doc, report = recon.compile_graph(
        graph, os.path.splitext(os.path.basename(args.fcstd))[0])
    doc.saveAs(os.path.abspath(args.fcstd))

    import FreeCAD as App  # noqa: PLC0415
    App.closeDocument(doc.Name)
    measured = meas.measure_document(os.path.abspath(args.fcstd),
                                     mesh_body=args.mesh_body)
    measured["build_report"] = {
        "unsupported": report.get("unsupported", []),
        "recompute_errors": report.get("recompute_errors", []),
        "built": report.get("built", []),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(measured, fh)
    print("ok")


if __name__ == "__main__":
    main()
