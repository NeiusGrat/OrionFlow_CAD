"""Backfill diagnoses onto natural-failure repair records (Step 0.3 quality).

The 14 natural failures were saved with the failing assertion id(s) and build
errors but no diagnosis text — they came from clean draws that failed, so no
synthetic label was attached. A natural failure is the highest-value repair
signal, so give each a concrete diagnosis derived from what actually failed:
the assertion, its measured-vs-target, or the OCC build error.

Writes to the working db only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from . import corpus_db


def _diagnose(payload: dict) -> tuple[str, str]:
    v = payload.get("verdict", {})
    trace = payload.get("repair_trace", {}) or {}
    build_errors = trace.get("build_errors") or (
        v.get("build_log", {}) or {}).get("build_report", {}).get(
        "recompute_errors", [])
    if build_errors:
        err = build_errors[0].get("error", "unknown")
        fid = build_errors[0].get("id", "?")
        return (f"natural build failure: feature {fid} did not recompute "
                f"({err}); OCC rejected the geometry as authored",
                "adjust the parameters so the feature builds (the guard that "
                "would have prevented this draw is the fix target)")
    # otherwise a verification mismatch: name the failing assertion + numbers
    failing = [a for a in v.get("assertions", []) if a.get("passed") is False]
    if failing:
        a = failing[0]
        meas = a.get("measured")
        tgt = a.get("target")
        if meas is not None and tgt is not None:
            return (f"natural verification failure: assertion '{a.get('id')}' "
                    f"({a.get('kind')}) measured {meas:.4g} vs expected "
                    f"{tgt:.4g} — the built solid does not match its "
                    f"closed-form prediction",
                    f"the '{a.get('id')}' relationship is violated by the "
                    f"sampled parameters; constrain them so measured meets "
                    f"predicted")
        return (f"natural verification failure: assertion '{a.get('id')}' "
                f"({a.get('kind')}) did not hold on the built solid",
                f"correct the parameters so '{a.get('id')}' is satisfied")
    fp = trace.get("failing") or []
    return (f"natural failure on {fp}: the clean draw did not pass its own "
            f"assertions", "constrain the parameters to satisfy the "
            "failing assertion(s)")


def run(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(corpus_db.SCHEMA)
    rows = con.execute(
        "SELECT blueprint_hash, status, payload FROM records "
        "WHERE status='natural'").fetchall()
    n = 0
    for bh, status, payload in rows:
        p = json.loads(payload)
        trace = p.get("repair_trace", {}) or {}
        if trace.get("diagnosis"):
            continue
        diag, fix = _diagnose(p)
        trace["diagnosis"] = diag
        trace["fix"] = fix
        trace["diagnosis_source"] = "backfilled_from_failure"
        p["repair_trace"] = trace
        corpus_db.insert(con, p, status)
        n += 1
    con.commit()
    con.close()
    return {"natural_records": len(rows), "backfilled": n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    args = ap.parse_args()
    print(json.dumps(run(args.db), indent=1))


if __name__ == "__main__":
    main()
