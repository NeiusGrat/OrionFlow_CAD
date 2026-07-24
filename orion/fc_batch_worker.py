"""Batched FreeCAD worker (Phase-X W6) — runs under FreeCAD's Python.

Processes a MANIFEST of build jobs in a single FreeCAD process, so the ~1.5 s
interpreter + reconstruct import startup is paid once per batch instead of once
per record. reconstruct.py and measure_fc.py are loaded exactly once; each job
compiles a graph, saves the FCStd, and measures.

Results are written incrementally, one file per job, so if the process is
killed (a per-job OCC hang tripping the producer's watchdog) every completed
job in the slice is still on disk — nothing already built is lost.

Manifest entry: {"graph_path", "tag", "mesh_body"}.
Result file  <out_dir>/<tag>.json: {"tag","ok","measured"|"error"}.

Usage (invoked by orion/parallel_forge.py):
    freecad_python fc_batch_worker.py --manifest m.json --out-dir r/ --scratch s/
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
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scratch", required=True)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    recon = _load(os.path.join(repo, "freecad", "reconstruct.py"),
                  "_orion_recon")
    meas = _load(os.path.join(here, "measure_fc.py"), "_orion_measure")
    import FreeCAD as App  # noqa: PLC0415

    jobs = json.load(open(args.manifest, encoding="utf-8"))
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(args.scratch, exist_ok=True)
    done = 0
    for job in jobs:
        tag = job["tag"]
        out_path = os.path.join(args.out_dir, f"{tag}.json")
        try:
            graph = json.load(open(job["graph_path"], encoding="utf-8"))
            doc, report = recon.compile_graph(graph, tag)
            fcstd = os.path.join(args.scratch, f"{tag}.FCStd")
            doc.saveAs(fcstd)
            App.closeDocument(doc.Name)
            measured = meas.measure_document(fcstd,
                                             mesh_body=job.get("mesh_body"))
            measured["build_report"] = {
                "unsupported": report.get("unsupported", []),
                "recompute_errors": report.get("recompute_errors", []),
                "built": report.get("built", []),
            }
            result = {"tag": tag, "ok": True, "measured": measured}
        except Exception as e:  # noqa: BLE001 - a bad graph fails only its job
            result = {"tag": tag, "ok": False, "error": str(e)[:300]}
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        done += 1
    print(f"BATCH DONE {done}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
