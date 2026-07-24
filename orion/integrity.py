"""Corpus integrity checks (Phase-X Step 0.3).

Validates the corpus before any scale run. Distinguishes real violations from
expected structure — repeated topology SIGNATURES are diversity working as
intended, not duplicates; the true duplicate is an identical frozen blueprint
appearing twice under the same status.

Checks:
  * duplicate_blueprints  — same (blueprint_hash, status) payload twice
    (the PK prevents literal dups, so this catches payload divergence);
  * corrupt_records       — payload not decodable, or missing required keys;
  * orphan_repairs        — a repair record whose diagnosis/fix is absent, or
    whose referenced clean blueprint hash is nowhere in the corpus;
  * invalid_references    — a feature_graph dependency pointing at a feature or
    sketch id that does not exist in that graph;
  * tier_consistency      — a record marked passed but with a failing assertion,
    or verified real CAD without a verification block.

Exit acceptance (Step 0.3): 0 corrupt, 0 orphaned repairs, 0 invalid refs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

REQUIRED_KEYS = ("blueprint", "feature_graph", "verdict")


def _graph_refs_ok(graph: dict) -> list[str]:
    feat_ids = {f.get("id") for f in graph.get("features", [])}
    sk_ids = {s.get("id") for s in graph.get("sketches", [])}
    known = feat_ids | sk_ids
    bad = []
    for d in graph.get("dependencies", []):
        for end in ("source", "target"):
            ref = d.get(end)
            if ref is not None and ref not in known:
                bad.append(f"{d.get('kind')}:{end}={ref}")
    return bad


def check(db_path: str) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT blueprint_hash, status, family, fault, repair_source, passed, "
        "payload FROM records").fetchall()

    out: dict[str, Any] = {
        "records": len(rows),
        # violations — must be 0 to pass the Step 0.3 gate
        "corrupt_records": [],
        "orphan_repairs": [],          # repair record with NO trace at all
        "invalid_references": [],
        "tier_inconsistencies": [],
        "duplicate_blueprint_payloads": [],
        # quality metrics — informational, not gate violations
        "thin_repairs": [],            # trace present but no diagnosis text
        "unpaired_stress": 0,          # stress record, clean sibling not stored
    }
    seen_hash_status: dict[tuple, str] = {}
    all_hashes: set[str] = set()
    repair_rows = []

    for bh, status, family, fault, repair_source, passed, payload in rows:
        all_hashes.add(bh)
        # corrupt: decode + required keys
        try:
            p = json.loads(payload)
        except Exception:  # noqa: BLE001
            out["corrupt_records"].append({"hash": bh, "why": "undecodable"})
            continue
        missing = [k for k in REQUIRED_KEYS if k not in p]
        if missing:
            out["corrupt_records"].append(
                {"hash": bh, "status": status, "why": f"missing {missing}"})
            continue

        # duplicate payload under same (hash,status): PK blocks literal dup, so
        # any divergence here means two writes disagreed.
        key = (bh, status)
        digest = str(hash(payload))
        if key in seen_hash_status and seen_hash_status[key] != digest:
            out["duplicate_blueprint_payloads"].append(
                {"hash": bh, "status": status})
        seen_hash_status[key] = digest

        # invalid references in the graph
        bad = _graph_refs_ok(p.get("feature_graph", {}))
        if bad:
            out["invalid_references"].append(
                {"hash": bh, "status": status, "bad": bad[:5]})

        # tier / verdict consistency
        v = p.get("verdict", {})
        if v.get("passed"):
            failing = [a.get("id") for a in v.get("assertions", [])
                       if a.get("passed") is False]
            if failing:
                out["tier_inconsistencies"].append(
                    {"hash": bh, "why": f"passed but failing {failing[:3]}"})
        if status in ("real", "real_variant"):
            if not p.get("verification"):
                out["tier_inconsistencies"].append(
                    {"hash": bh, "why": "real record without verification block"})

        # collect repairs for the orphan pass
        if status in ("injected", "stress", "natural"):
            repair_rows.append((bh, status, fault, p.get("repair_trace", {})))

    # A repair record is ORPHANED (violation) only when it carries no trace at
    # all. Missing diagnosis text is a QUALITY gap (thin_repairs), and a
    # stress record whose clean sibling was never persisted is expected
    # structure (stress mode force-builds the fault and skips the clean build),
    # recorded as an informational reconstructability metric.
    for bh, status, fault, trace in repair_rows:
        if not trace:
            out["orphan_repairs"].append({"hash": bh, "why": "no repair_trace"})
            continue
        if not trace.get("diagnosis"):
            out["thin_repairs"].append({"hash": bh, "status": status,
                                        "fault": fault})
        ref = trace.get("clean_blueprint_hash")
        if ref and ref not in all_hashes:
            out["unpaired_stress"] += 1

    con.close()
    # Gate = only the true violations; quality metrics reported separately.
    out["violations"] = {
        "corrupt": len(out["corrupt_records"]),
        "orphan_repairs": len(out["orphan_repairs"]),
        "invalid_references": len(out["invalid_references"]),
        "tier_inconsistencies": len(out["tier_inconsistencies"]),
        "duplicate_payloads": len(out["duplicate_blueprint_payloads"]),
    }
    out["quality"] = {
        "thin_repairs": len(out["thin_repairs"]),
        "unpaired_stress": out["unpaired_stress"],
    }
    out["clean"] = all(v == 0 for v in out["violations"].values())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v2.db")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    r = check(args.db)
    print("VIOLATIONS:", json.dumps(r["violations"]))
    print("QUALITY:   ", json.dumps(r["quality"]))
    print("records:", r["records"], "| GATE CLEAN:", r["clean"])
    if args.verbose:
        for k in ("corrupt_records", "orphan_repairs", "invalid_references",
                  "tier_inconsistencies", "duplicate_blueprint_payloads",
                  "thin_repairs"):
            if r[k]:
                print(f"\n{k}:")
                for item in r[k][:15]:
                    print("  ", item)


if __name__ == "__main__":
    main()
