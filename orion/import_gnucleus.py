"""Import the REAL-WORLD corpus into the forge store (W8).

Two sources, both already verified by other parts of this repo:

* ``freecad/training/sample_*.json`` — 100 gNucleus masters extracted from
  human-authored FCStd files, with human descriptions and key parameters;
* ``freecad/variants/accepted.jsonl`` — parametric variants of those masters,
  each already accepted against an analytic volume within 1%.

These carry topology the synthetic generator structurally cannot produce —
B-splines, hand-drawn profiles, real manufacturing intent in prose — so they
are the corpus's only defence against learning "CAD looks like whatever
orion/recipes.py emits".

Verification is honest and per-record, never assumed:

  * ``tier1_exact``   — every extractable feature's tool volume matched the
    closed form to 1e-4 (from orion/verify_masters, which scored 229/229);
  * ``measured_only`` — the document measures cleanly but some feature is
    outside closed-form reach (B-spline profiles);
  * ``unverified``    — no measurement available.

Records land with status ``real`` / ``real_variant`` so the audit can weigh
them separately from generated data.

Usage:
    python -m orion.import_gnucleus --db data/forge/corpus_v2.db
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from typing import Any

from . import corpus_db, tier1
from .verify_masters import REL_TOL, _axis_2d


def _prompt(sample: dict) -> str:
    lines = [sample.get("description", "").strip()]
    kp = (sample.get("key_parameters") or "").strip()
    if kp:
        lines.append("\nKey parameters:\n" + kp)
    lines.append("\nProduce a parametric FeatureGraph whose dimensions derive "
                 "from these parameters.")
    return "\n".join(x for x in lines if x)


def _seq(graph: dict) -> list[str]:
    return [f.get("type") for f in graph.get("features", [])
            if f.get("type") not in ("Body",)]


def _verify(graph: dict, measured: dict) -> dict[str, Any]:
    """Re-derive each Pad/Pocket/Revolution/Groove tool volume from the
    sketch geometry and compare with the measured AddSubShape."""
    rows, skipped = [], []
    if not measured or measured.get("error"):
        return {"status": "unverified", "checked": 0, "skipped": 0,
                "max_rel_err": None, "rows": []}
    by_name = {f["name"]: f for f in measured.get("features", [])}
    sketches = {s["id"]: s for s in graph.get("sketches", [])}
    profile_of = {d["target"]: d["source"] for d in graph.get("dependencies", [])
                  if d.get("kind") == "profile"}
    for f in graph.get("features", []):
        ftype, fid = f.get("type"), f.get("id")
        if ftype not in ("Pad", "Pocket", "Revolution", "Groove"):
            continue
        meas = (by_name.get(fid) or {}).get("addsub_volume")
        sk = sketches.get(profile_of.get(fid))
        if not meas or sk is None:
            skipped.append({"feature": fid, "why": "no measurement/profile"})
            continue
        area, centroid, why = tier1.sketch_area(
            sk.get("geometry", []), sk.get("external_geometry", []))
        if area is None:
            skipped.append({"feature": fid, "why": why})
            continue
        params = f.get("parameters") or {}
        if ftype in ("Pad", "Pocket"):
            pred, why = tier1.extrusion_volume(area, params)
        else:
            axis = _axis_2d(sk.get("plane", "XY"), params.get("_ReferenceAxis"))
            gp = sk.get("global_placement")
            if axis is None or (gp and any(abs(v) > 1e-9
                                           for v in (gp.get("pos") or [0, 0, 0]))):
                skipped.append({"feature": fid, "why": "axis/placement"})
                continue
            pred, why = tier1.revolution_volume(area, centroid, axis, params)
        if pred is None:
            skipped.append({"feature": fid, "why": why})
            continue
        rows.append({"feature": fid, "type": ftype,
                     "predicted": round(pred, 6), "measured": round(meas, 6),
                     "rel_err": abs(pred - meas) / meas})
    if not rows:
        status = "measured_only" if measured.get("body_volume") else "unverified"
        mx = None
    else:
        mx = max(r["rel_err"] for r in rows)
        status = "tier1_exact" if (mx <= REL_TOL and not skipped) \
            else "measured_only"
    return {"status": status, "checked": len(rows), "skipped": len(skipped),
            "max_rel_err": mx, "rows": rows, "skips": skipped}


def _payload(sample: dict, measured: dict, verification: dict,
             source: str) -> dict:
    graph = sample["feature_graph"]
    seq = _seq(graph)
    sig = hashlib.sha256(
        ("|".join(seq) + "::real::" + sample["id"]).encode()).hexdigest()[:16]
    assertions = []
    if verification["rows"]:
        assertions = [{"id": f"tool_{r['feature']}", "kind": "feature_volume",
                       "feature": r["feature"], "tier": 1, "tol_rel": REL_TOL,
                       "target": r["predicted"], "measured": r["measured"],
                       "rel_err": r["rel_err"],
                       "passed": r["rel_err"] <= REL_TOL}
                      for r in verification["rows"]]
    return {
        "schema": "orion-forge-record-v1",
        "blueprint": {
            "version": "orion-real-v1",
            "part_class": sample.get("name") or sample["id"],
            # Real parts have no frozen blueprint: the hash identifies the
            # SOURCE, and no closed-form contract is claimed for them.
            "blueprint_hash": "real_" + sample["id"],
            "variables": {},
            "datums": {},
            "design_plan": {"source": "gNucleus human-authored CAD",
                            "description": sample.get("description", ""),
                            "key_parameters": sample.get("key_parameters", ""),
                            "verification": verification["status"]},
            "assertions": assertions,
            "template": {},
        },
        "feature_graph": graph,
        "analysis": {},
        "verdict": {
            "tag": sample["id"],
            "passed": verification["status"] == "tier1_exact",
            "assertions": assertions,
            "measured": measured,
            "build_ok": bool(measured.get("body_volume")),
            "elapsed_s": 0.0,
        },
        "recipe": source,
        "base_family": source,
        "attachments": [],
        "datum_strategy": {},
        "feature_seq": seq,
        "feature_sequence_hash": sig,
        "prompt": _prompt(sample),
        "verification": verification,
    }


def run(db_path: str, samples_glob: str, measured_path: str,
        variants_path: str = "", variant_limit: int = 0) -> dict:
    measured_all = {}
    if os.path.exists(measured_path):
        measured_all = json.load(open(measured_path, encoding="utf-8"))
    con = corpus_db.connect(db_path)
    stats: dict[str, Any] = {"masters": 0, "variants": 0,
                             "by_verification": {}}

    for p in sorted(glob.glob(samples_glob)):
        s = json.load(open(p, encoding="utf-8"))
        if not s.get("feature_graph"):
            continue
        m = measured_all.get(s["id"], {})
        v = _verify(s["feature_graph"], m)
        corpus_db.insert(con, _payload(s, m, v, "gnucleus_master"), "real")
        stats["masters"] += 1
        stats["by_verification"][v["status"]] = \
            stats["by_verification"].get(v["status"], 0) + 1

    if variants_path and os.path.exists(variants_path):
        with open(variants_path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if variant_limit and stats["variants"] >= variant_limit:
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                graph = row.get("graph") or row.get("feature_graph")
                if not graph:
                    continue
                vid = row.get("id") or f"variant_{i}"
                sample = {"id": vid, "name": row.get("name", vid),
                          "description": row.get("description", ""),
                          "key_parameters": row.get("key_parameters", ""),
                          "feature_graph": graph}
                # Variants were already accepted against an analytic volume
                # by freecad/variant_generator.py; record that, do not re-claim
                # a tier-1 proof we did not run here.
                ver = {"status": "measured_only", "checked": 0, "skipped": 0,
                       "max_rel_err": row.get("rel_err"), "rows": [],
                       "note": "accepted by variant_generator analytic gate"}
                meas = {"body_volume": row.get("volume")}
                corpus_db.insert(con, _payload(sample, meas, ver,
                                               "gnucleus_variant"),
                                 "real_variant")
                stats["variants"] += 1
    con.commit()
    stats["db"] = corpus_db.audit(con)
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    ap.add_argument("--samples", default="freecad/training/sample_*.json")
    ap.add_argument("--measured",
                    default="orion/reports/masters_measured.json")
    ap.add_argument("--variants", default="freecad/variants/accepted.jsonl")
    ap.add_argument("--variant-limit", type=int, default=600)
    args = ap.parse_args()
    s = run(args.db, args.samples, args.measured, args.variants,
            args.variant_limit)
    print(json.dumps({k: v for k, v in s.items() if k != "db"}, indent=1))
    print("corpus now:", s["db"]["records"], "records,",
          s["db"]["distinct_signatures"], "signatures")


if __name__ == "__main__":
    main()
