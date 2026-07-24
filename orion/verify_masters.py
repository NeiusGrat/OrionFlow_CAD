"""Graph-analytic acceptance run: Tier-1 predictions vs the 100 real masters.

For every Pad/Pocket/Revolution/Groove in the corpus, predict the tool-solid
volume from extracted sketch geometry + parameters (pure math, system Python)
and compare against the measured ``AddSubShape`` from the reference FCStd
(FreeCAD Python, measure_fc.py). The two paths share nothing but the input
files.

This is the Phase-0 gate: the verifier is not done until the wrong_sidetype
fault injection on 83ca2dab2e is flagged by exactly this comparison.

Usage:
    python -m orion.verify_masters --measured orion/reports/masters_measured.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os

from . import tier1

REL_TOL = 1e-4


def _axis_2d(plane, ref_axis):
    """Map a Revolution/Groove reference axis into sketch-local 2D.

    Returns ((px, py), (dx, dy)) or None. Handles the body origin axes on the
    three principal planes plus the sketch's own H/V axes.
    """
    if not ref_axis:
        return None
    subs = ref_axis.get("subs") or [""]
    if ref_axis.get("is_sketch"):
        sub = subs[0] if subs else ""
        if sub in ("H_Axis", "X_Axis"):
            return ((0.0, 0.0), (1.0, 0.0))
        if sub in ("V_Axis", "Y_Axis"):
            return ((0.0, 0.0), (0.0, 1.0))
        return None
    role = ref_axis.get("role")
    mapping = {
        "XY": {"X_Axis": (1.0, 0.0), "Y_Axis": (0.0, 1.0)},
        "XZ": {"X_Axis": (1.0, 0.0), "Z_Axis": (0.0, 1.0)},
        "YZ": {"Y_Axis": (1.0, 0.0), "Z_Axis": (0.0, 1.0)},
    }.get(plane, {})
    d = mapping.get(role)
    return ((0.0, 0.0), d) if d else None


def verify_corpus(samples_glob, measured):
    rows, skips = [], []
    for path in sorted(glob.glob(samples_glob)):
        s = json.load(open(path, encoding="utf-8"))
        sid = s["id"]
        graph = s.get("feature_graph") or {}
        m = measured.get(sid)
        if not m or m.get("error"):
            skips.append({"id": sid, "why": "no measurement"})
            continue
        m_by_name = {f["name"]: f for f in m.get("features", [])}
        sketches = {sk["id"]: sk for sk in graph.get("sketches", [])}
        profile_of = {}
        for d in graph.get("dependencies", []):
            if d.get("kind") == "profile":
                profile_of[d["target"]] = d["source"]

        for f in graph.get("features", []):
            ftype, fid = f.get("type"), f.get("id")
            if ftype not in ("Pad", "Pocket", "Revolution", "Groove"):
                continue
            meas = (m_by_name.get(fid) or {}).get("addsub_volume")
            if not meas:
                skips.append({"id": sid, "feature": fid,
                              "why": "no AddSubShape measurement"})
                continue
            sk = sketches.get(profile_of.get(fid))
            if sk is None:
                skips.append({"id": sid, "feature": fid, "why": "no profile"})
                continue
            area, centroid, why = tier1.sketch_area(
                sk.get("geometry", []), sk.get("external_geometry", []))
            if area is None:
                skips.append({"id": sid, "feature": fid,
                              "why": f"area: {why}"})
                continue
            params = f.get("parameters") or {}
            if ftype in ("Pad", "Pocket"):
                pred, why = tier1.extrusion_volume(area, params)
            else:
                axis = _axis_2d(sk.get("plane", "XY"),
                                params.get("_ReferenceAxis"))
                if axis is None:
                    skips.append({"id": sid, "feature": fid,
                                  "why": "axis unresolvable"})
                    continue
                gp = sk.get("global_placement")
                if gp and any(abs(v) > 1e-9 for v in (gp.get("pos") or [0, 0, 0])):
                    skips.append({"id": sid, "feature": fid,
                                  "why": "offset sketch placement (Tier 2)"})
                    continue
                pred, why = tier1.revolution_volume(area, centroid, axis, params)
            if pred is None:
                skips.append({"id": sid, "feature": fid, "why": why})
                continue
            err = abs(pred - meas) / meas
            rows.append({"id": sid, "feature": fid, "type": ftype,
                         "predicted": round(pred, 6),
                         "measured": round(meas, 6),
                         "rel_err": round(err, 9),
                         "pass": err <= REL_TOL})
    return rows, skips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="freecad/training/sample_*.json")
    ap.add_argument("--measured", required=True)
    ap.add_argument("--out", default="orion/reports/masters_acceptance.json")
    args = ap.parse_args()

    measured = json.load(open(args.measured, encoding="utf-8"))
    rows, skips = verify_corpus(args.samples, measured)
    n_pass = sum(1 for r in rows if r["pass"])
    failures = [r for r in rows if not r["pass"]]
    summary = {
        "features_predicted": len(rows),
        "features_passed": n_pass,
        "features_failed": len(failures),
        "features_skipped": len(skips),
        "max_rel_err_passed": max((r["rel_err"] for r in rows if r["pass"]),
                                  default=None),
        "skip_reasons": {},
    }
    for s in skips:
        key = s["why"].split("(")[0].strip()
        summary["skip_reasons"][key] = summary["skip_reasons"].get(key, 0) + 1

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "failures": failures,
                   "skips": skips, "rows": rows}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    if failures:
        print("\nFAILURES:")
        for r in failures[:20]:
            print(f"  {r['id']}/{r['feature']} {r['type']}: "
                  f"pred {r['predicted']} vs meas {r['measured']} "
                  f"({r['rel_err']:.3%})")


if __name__ == "__main__":
    main()
