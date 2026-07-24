"""Milestone A — re-tier the six 0%-Tier-1 families' bodies in the corpus.

The recipes now carry the corrected body verification (recipes.py /
recipes_ext.py). This pass upgrades the ALREADY-GENERATED records in place so
the audit reflects the closure, without regenerating topology and without
rehashing the frozen blueprints — it records a ``body_tier`` and a
``body_verification`` overlay on each record, exactly as the real-CAD upgrade
did for measured_only records.

  * five closed-form families (pipe_bend, duct_reducer, twisted_vane,
    tray_shell, vented_enclosure): the exact body volume is evaluated from the
    stored variables and compared to the STORED measured body volume — no
    rebuild — and the body is retagged Tier 1 when it matches to 1e-6;
  * manifold_runner: the body is genuinely irreducible, so it is rebuilt with
    mesh sampling and its Tier-2 convergence verdict recorded.

Writes to the working db only; corpus_v1_frozen is never touched.
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from . import corpus_db
from .expr import evaluate
from .forge import _check_mesh_convergence, build_and_measure, workdir

REL_TOL = 1e-6

# Exact body-volume expressions, identical to the corrected recipe assertions.
EXACT_BODY = {
    "pipe_bend": "pi*section_r**2*radians(bend_deg)*bend_r",
    "duct_reducer": "pi*height/3*(bot_r**2 + bot_r*top_r + top_r**2)",
    "twisted_vane": "chord*thick_v*span/3*(1 + 2*cos(radians(twist_deg)/2)**2)",
    "tray_shell": "length*width*depth - (length-2*wall)*(width-2*wall)"
                  "*(depth-wall)",
    "vented_enclosure":
        "(enc_l*enc_w*enc_d - (enc_l-2*wall_e)*(enc_w-2*wall_e)"
        "*(enc_d-wall_e)) - vent_n*(vent_l*2*vent_r + pi*vent_r**2)*wall_e",
}
MESH_FAMILY = "manifold_runner"


def run(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(corpus_db.SCHEMA)
    fams = list(EXACT_BODY) + [MESH_FAMILY]
    qmarks = ",".join("?" * len(fams))
    rows = con.execute(
        f"SELECT blueprint_hash, status, family, payload FROM records "
        f"WHERE family IN ({qmarks}) AND status='clean'", fams).fetchall()
    wd = workdir()
    stats = {"scanned": 0, "tier1_closed_form": 0, "tier2_mesh": 0,
             "failed": 0, "by_family": {}}
    for bh, status, family, payload in rows:
        stats["scanned"] += 1
        fam = stats["by_family"].setdefault(
            family, {"tier1": 0, "tier2": 0, "failed": 0})
        p = json.loads(payload)
        v = p["blueprint"]["variables"]
        measured = p["verdict"].get("measured", {})

        if family in EXACT_BODY:
            occ = measured.get("body_volume")
            if not occ:
                stats["failed"] += 1
                fam["failed"] += 1
                continue
            pred = evaluate(EXACT_BODY[family], v)
            err = abs(pred - occ) / occ
            if err <= REL_TOL:
                p["body_tier"] = 1
                p["body_verification"] = {
                    "tier": 1, "method": "closed_form",
                    "predicted": pred, "measured": occ, "rel_err": err}
                corpus_db.insert(con, p, status)
                stats["tier1_closed_form"] += 1
                fam["tier1"] += 1
            else:
                stats["failed"] += 1
                fam["failed"] += 1
        else:  # manifold_runner — rebuild with mesh sampling
            _log, meas = build_and_measure(
                p["feature_graph"], wd, f"retier_{bh[:10]}", mesh_body=True)
            row = _check_mesh_convergence(
                {"id": "body", "kind": "body_mesh_converged", "tier": 2,
                 "tol_rel": 1e-3}, meas)
            if row.get("passed"):
                p["body_tier"] = 2
                p["body_verification"] = {
                    "tier": 2, "method": "mesh_converged",
                    "rel_err": row.get("rel_err"),
                    "monotone": row.get("monotone"),
                    "richardson_rel_err": row.get("richardson_rel_err"),
                    "facets": row.get("facets")}
                corpus_db.insert(con, p, status)
                stats["tier2_mesh"] += 1
                fam["tier2"] += 1
            else:
                stats["failed"] += 1
                fam["failed"] += 1
        if stats["scanned"] % 20 == 0:
            con.commit()
    con.commit()
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    args = ap.parse_args()
    print(json.dumps(run(args.db), indent=1))


if __name__ == "__main__":
    main()
