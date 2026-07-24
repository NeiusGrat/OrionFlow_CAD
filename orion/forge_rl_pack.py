"""Phase-5 RL corpus packer — formatting only, built ahead of the freeze.

Reads forge records and emits one JSONL with four record kinds:

* ``dpo_pair``        — chosen (clean, verified) vs rejected (faulted/stress)
                        matched within the same recipe family
* ``prm_sequence``    — the derivation chain as stepwise (state, action,
                        reasoning) with the verification trace as terminal
                        reward signal, predicted vs measured per assertion
* ``repair_pair``     — failure state + machine diagnosis + fix + reverified;
                        natural/stress failures carry 3x weight over injected
* ``reasoning_record``— design plan + derivation + verification for
                        reasoning-model experiments

This module never touches FreeCAD and never mutates records: packing is a
pure read. Per the Phase-4.5 directive it is smoke-tested on the pilot data
but the FINAL pack is not generated until the corpus passes acceptance.

Usage:
    python -m orion.forge_rl_pack --records data/forge/corpus_v1 \
        --out data/forge/rl_corpus_v1.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from typing import Any

NATURAL_WEIGHT = 3.0
INJECTED_WEIGHT = 1.0


def _spec_prompt(bp: dict) -> str:
    """The engineering ask, reconstructed from the blueprint's own plan —
    what a user would say, not a dump of the answer."""
    plan = bp.get("design_plan", {})
    lines = [f"Design a parametric {bp['part_class'].replace('_', ' ')}."]
    if plan.get("function"):
        lines.append(f"Function: {plan['function']}")
    if plan.get("manufacturing"):
        lines.append(f"Manufacturing: {plan['manufacturing']}")
    lines.append("Variables: " + ", ".join(
        f"{k}={v}" for k, v in sorted(bp.get("variables", {}).items())))
    lines.append("Every dimension must be an expression over the variables; "
                 "state the volume you expect and why.")
    return "\n".join(lines)


def _verification_trace(verdict: dict) -> list[dict]:
    out = []
    for a in verdict.get("assertions", []):
        row = {"id": a.get("id"), "kind": a.get("kind"),
               "tier": a.get("tier"), "passed": a.get("passed")}
        for k in ("target", "measured", "rel_err", "lo", "hi"):
            if a.get(k) is not None:
                row[k] = a[k]
        out.append(row)
    return out


def _load_dir(records_dir: str) -> list[dict]:
    paths = [p for p in glob.glob(os.path.join(records_dir, "*.json"))
             if not os.path.basename(p).startswith("_")]
    loaded = []
    for p in sorted(paths):
        r = json.load(open(p, encoding="utf-8"))
        r["_path"] = os.path.basename(p)
        loaded.append(r)
    return loaded


def _load_db(db_path: str) -> list[dict]:
    """Load every record's stored payload straight from the corpus DB — the
    same dicts the JSON-dir path yields, so packing is source-agnostic."""
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    loaded = []
    try:
        cur = con.execute("SELECT payload FROM records "
                          "WHERE payload IS NOT NULL")
        for i, (payload,) in enumerate(cur):
            try:
                r = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            if "verdict" not in r or "blueprint" not in r:
                continue
            # stable, unique key for deterministic DPO mate selection
            r["_path"] = f"{r['blueprint'].get('blueprint_hash', '')}_{i}"
            loaded.append(r)
    finally:
        con.close()
    return loaded


def pack(records_dir: str, out_path: str) -> dict:
    return pack_records(_load_dir(records_dir), out_path)


def pack_db(db_path: str, out_path: str) -> dict:
    return pack_records(_load_db(db_path), out_path)


def pack_records(loaded: list[dict], out_path: str) -> dict:
    clean_by_recipe: dict[str, list[dict]] = {}
    failures: list[dict] = []
    rows: list[dict] = []
    counts = {"dpo_pair": 0, "prm_sequence": 0, "repair_pair": 0,
              "reasoning_record": 0}

    for r in loaded:
        if r["verdict"].get("passed"):
            clean_by_recipe.setdefault(r.get("recipe", "?"), []).append(r)
            # Injected faults may ride INSIDE their clean record (JSON-dir
            # path); in the DB they are separate rows handled below.
            if r.get("repair_trace"):
                failures.append({**r, "_chosen_self": True})
        elif r.get("repair_trace"):
            failures.append(r)

    # ---- PRM sequences + reasoning records from clean builds ------------- #
    for r in loaded:
        if not r["verdict"].get("passed"):
            continue
        bp = r["blueprint"]
        deriv = bp.get("design_plan", {}).get("derivation", [])
        steps = []
        for i, step in enumerate(deriv):
            steps.append({
                "state": f"after_step_{i}",
                "action": step.get("eq", ""),
                "reasoning": step.get("why", ""),
                "reward": 1.0,
            })
        rows.append({
            "kind": "prm_sequence",
            "recipe": r.get("recipe"),
            "blueprint_hash": bp.get("blueprint_hash"),
            "prompt": _spec_prompt(bp),
            "steps": steps,
            "feature_seq": r.get("feature_seq", []),
            "terminal": {
                "passed": True,
                "verification": _verification_trace(r["verdict"]),
            },
        })
        counts["prm_sequence"] += 1
        rows.append({
            "kind": "reasoning_record",
            "recipe": r.get("recipe"),
            "blueprint_hash": bp.get("blueprint_hash"),
            "prompt": _spec_prompt(bp),
            "design_plan": bp.get("design_plan", {}),
            "datums": bp.get("datums", {}),
            "feature_rationales": [
                {"id": f.get("id"), "type": f.get("type"),
                 "rationale": f.get("rationale", "")}
                for f in bp.get("template", {}).get("features", [])
                if f.get("rationale")],
            "assertions": bp.get("assertions", []),
            "verification": _verification_trace(r["verdict"]),
        })
        counts["reasoning_record"] += 1

    # ---- DPO pairs: clean vs failure, same recipe ------------------------ #
    for f in failures:
        recipe = f.get("recipe", "?")
        if f.get("_chosen_self"):
            chosen = f          # the clean build the fault was injected into
        else:
            mates = clean_by_recipe.get(recipe, [])
            if not mates:
                continue
            chosen = mates[hash(f["_path"]) % len(mates)]
        trace = f.get("repair_trace", {})
        rows.append({
            "kind": "dpo_pair",
            "recipe": recipe,
            "prompt": _spec_prompt(chosen["blueprint"]),
            "chosen": {
                "blueprint_hash": chosen["blueprint"]["blueprint_hash"],
                "variables": chosen["blueprint"]["variables"],
                "template": chosen["blueprint"]["template"],
                "verified": True,
            },
            "rejected": {
                "blueprint_hash": trace.get("faulted_blueprint_hash")
                or f["blueprint"].get("blueprint_hash"),
                "variables": f["blueprint"].get("variables"),
                "fault": trace.get("fault"),
                "source": trace.get("source", "injected"),
                "failing": trace.get("failing", []),
            },
            "tier": max((a.get("tier") or 3)
                        for a in chosen["blueprint"].get("assertions", [{}])),
        })
        counts["dpo_pair"] += 1

    # ---- repair preference pairs ----------------------------------------- #
    for f in failures:
        trace = f.get("repair_trace", {})
        source = trace.get("source", "injected")
        weight = NATURAL_WEIGHT if source in ("natural", "stress_natural") \
            else INJECTED_WEIGHT
        rows.append({
            "kind": "repair_pair",
            "recipe": f.get("recipe"),
            "weight": weight,
            "source": source,
            "failure": {
                "blueprint_hash": f["blueprint"].get("blueprint_hash"),
                "variables": f["blueprint"].get("variables"),
                "fault": trace.get("fault"),
                "failing_assertions": trace.get("failing", []),
                "forced_past_preconditions": trace.get("forced_past", []),
                "build_errors": trace.get("build_errors", []),
                "occ_stderr": trace.get("build_stderr", "")[-800:],
            },
            "diagnosis": trace.get("diagnosis", ""),
            "fix": trace.get("fix", ""),
            "reverified": trace.get("reverified",
                                    trace.get("clean_blueprint_hash") is not None),
        })
        counts["repair_pair"] += 1

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    summary: dict[str, Any] = {"rows": len(rows), **counts,
                               "records_read": len(loaded),
                               "out": out_path}
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="",
                    help="directory of JSON forge records")
    ap.add_argument("--db", default="",
                    help="corpus SQLite DB (takes precedence over --records)")
    ap.add_argument("--out", default="data/forge/rl_corpus_v1.jsonl")
    args = ap.parse_args()
    if args.db:
        print(json.dumps(pack_db(args.db, args.out), indent=1))
    else:
        print(json.dumps(
            pack(args.records or "data/forge/corpus_v1", args.out), indent=1))


if __name__ == "__main__":
    main()
