"""The automated forge loop — Phase 3/4 pilot driver.

For each sampled blueprint:

    freeze → [precondition refusal?] → build+measure (one FreeCAD process)
      → verdict vs frozen assertions
      → PASS: persist record; with probability FAULT_P also run one injected
              fault + repair trace (the injected repair corpus)
      → FAIL: the failure itself becomes a NATURAAL repair record — diagnosis
              from the failing assertions, no synthetic damage needed

Every record keeps blueprint hash, graph, build log, measurement, verdict,
and (when present) the repair trace. Pilot metrics are computed at the end
and written next to the records.

Usage:
    python -m orion.forge_loop --n 50 --seed 7
    python -m orion.forge_loop --n 5 --seed 1 --out data/forge/smoke
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time

from . import corpus_db
from .blueprint import Blueprint
from .forge import run_blueprint, save_record, workdir
from .sampler import TopologySampler

FAULT_P = 0.34    # fraction of passing parts that also get an injected fault
STRESS_RATE = 0.24  # fraction of draws force-built PAST their guards: the
                    # guard margins are deliberately bypassed so OCC fails for
                    # real, and the record captures genuine kernel behaviour


def _refreeze(bp: Blueprint, mutate) -> Blueprint:
    t = copy.deepcopy(bp.template)
    v = dict(bp.variables)
    mutate(t, v)
    return Blueprint(part_class=bp.part_class + "_faulted", variables=v,
                     datums=bp.datums, design_plan=bp.design_plan,
                     assertions=bp.assertions, template=t).freeze()


def _clean_count(db_path: str) -> int:
    """Passing (clean) synthetic records already in the corpus."""
    if not db_path or not os.path.exists(db_path):
        return 0
    import sqlite3
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM records "
                         "WHERE status='clean'").fetchone()[0]
    except Exception:  # noqa: BLE001 - table may not exist yet
        return 0
    finally:
        c.close()


def run_pilot(n: int, seed: int, out_dir: str, db_path: str = "",
              json_records: bool = True, target_total: int = 0) -> dict:
    # Resumable mode: when target_total is set, seed derives from how many
    # clean records already exist so a re-run after ANY interruption produces
    # NEW draws (never regenerating the same blueprints) and tops the corpus
    # up toward the target rather than adding a fixed batch. This, plus the
    # 50-record commits, is what makes a run survive sleep/kill with zero lost
    # records and no manual restart bookkeeping.
    already = _clean_count(db_path) if target_total else 0
    if target_total:
        n = max(0, target_total - already)
        seed = seed + already          # advance the stream past prior work
    sampler = TopologySampler(seed=seed)
    wd = workdir()
    os.makedirs(out_dir, exist_ok=True)
    con = corpus_db.connect(db_path) if db_path else None

    def _persist(rec, blueprint, graph, extras, status):
        """One place decides where a record lands: SQLite for scale runs,
        loose JSON when a human wants to read them."""
        if json_records:
            path = save_record(rec, blueprint, graph, out_dir, extras=extras)
        else:
            path = ""
        if con is not None:
            _persist.n += 1
            payload = {"schema": "orion-forge-record-v1",
                       "blueprint": blueprint.to_dict(),
                       "feature_graph": {k: v for k, v in graph.items()
                                         if k != "_analysis"},
                       "analysis": graph.get("_analysis", {}),
                       "verdict": rec, **(extras or {})}
            corpus_db.insert(con, payload, status)
            # Commit in batches: a single commit at the end means a crash
            # three hours in loses everything, and nothing is queryable
            # while the run is live.
            if _persist.n % 50 == 0:
                con.commit()
        return path
    _persist.n = 0

    stats = {
        "attempted": 0, "passed": 0, "failed_natural": 0, "stress_built": 0,
        "stress_flagged": 0, "stress_survived": [],
        "injected_faults": 0, "faults_caught": 0, "faults_missed": [],
        "refused_prebuild": 0, "records": [],
        "tier_totals": {"1": 0, "2": 0, "3": 0},
        "elapsed_s": 0.0,
    }
    t0 = time.time()
    i = 0
    while stats["passed"] < n:
        draw = sampler.draw()
        if draw is None:
            break
        bp, faults, seq, recipe, meta = draw
        i += 1
        tag = f"p{i:03d}_{recipe}"

        # ---- stress mode: force-build past the guards -------------------- #
        if faults and sampler.rng.random() < STRESS_RATE:
            fname = sampler.rng.choice(list(faults))
            mutate, fmeta = faults[fname]
            stressed = _refreeze(bp, mutate)
            srec = run_blueprint(stressed, f"{tag}_stress", wd, force=True)
            stats["stress_built"] += 1
            flagged = not srec["passed"]
            if flagged:
                stats["stress_flagged"] += 1
            else:
                stats["stress_survived"].append({"tag": tag, "fault": fname})
            sgraph = stressed.resolve()
            path = _persist(srec, stressed, sgraph, status="stress", extras={
                "recipe": recipe, "feature_seq": list(seq),
                "base_family": meta["base_family"],
                "attachments": meta["attachments"],
                "datum_strategy": meta["datum_strategy"],
                "feature_sequence_hash": meta["feature_sequence_hash"],
                "repair_trace": {
                    "source": "stress_natural", "fault": fname, **fmeta,
                    "forced_past": srec.get("forced_past_preconditions", []),
                    "build_errors": (srec.get("build_log", {})
                                     .get("build_report", {})
                                     .get("recompute_errors", [])),
                    "build_stderr": (srec.get("build_log", {})
                                     .get("stderr", ""))[-1500:],
                    "failing": [a["id"] for a in srec["assertions"]
                                if not a["passed"]],
                    "caught": flagged,
                    "clean_blueprint_hash": bp.blueprint_hash,
                }})
            stats["records"].append({"tag": f"{tag}_stress", "passed": False,
                                     "path": path})
            continue

        stats["attempted"] += 1
        rec = run_blueprint(bp, tag, wd)
        graph = bp.resolve()

        if not rec["passed"]:
            # Natural failure: the generator's own reject IS repair data.
            stats["failed_natural"] += 1
            failing = (rec.get("failed_preconditions")
                       or [a["id"] for a in rec["assertions"]
                           if not a["passed"]])
            path = _persist(rec, bp, graph, status="natural", extras={
                "repair_trace": {
                    "source": "natural",
                    "failing": failing,
                    "build_errors": (rec.get("build_log", {})
                                     .get("build_report", {})
                                     .get("recompute_errors", [])),
                },
                "recipe": recipe, "feature_seq": list(seq),
                "base_family": meta["base_family"],
                "attachments": meta["attachments"],
                "datum_strategy": meta["datum_strategy"],
                "feature_sequence_hash": meta["feature_sequence_hash"],
            })
            stats["records"].append({"tag": tag, "passed": False,
                                     "path": path})
            continue

        sampler.note_clean(meta["feature_sequence_hash"])
        sampler.accept(recipe, seq, bp, meta)
        stats["passed"] += 1
        for a in bp.assertions:
            stats["tier_totals"][str(a.get("tier"))] = \
                stats["tier_totals"].get(str(a.get("tier")), 0) + 1

        extras = {"recipe": recipe, "feature_seq": list(seq),
                  "base_family": meta["base_family"],
                  "attachments": meta["attachments"],
                  "datum_strategy": meta["datum_strategy"],
                  "feature_sequence_hash": meta["feature_sequence_hash"]}
        if faults and sampler.rng.random() < FAULT_P:
            fname = sampler.rng.choice(list(faults))
            mutate, fmeta = faults[fname]
            faulted = _refreeze(bp, mutate)
            frec = run_blueprint(faulted, f"{tag}_fault", wd)
            caught = not frec["passed"]
            stats["injected_faults"] += 1
            if caught:
                stats["faults_caught"] += 1
            else:
                stats["faults_missed"].append({"tag": tag, "fault": fname})
            extras["repair_trace"] = {
                "source": "injected", "fault": fname, **fmeta,
                "faulted_blueprint_hash": faulted.blueprint_hash,
                "caught": caught,
                "refused_before_build": bool(frec.get("refused")),
                "failing": (frec.get("failed_preconditions")
                            or [a["id"] for a in frec["assertions"]
                                if not a["passed"]]),
                "reverified": True,   # the clean record above IS the fix
            }
        path = _persist(rec, bp, graph, status=(
            "injected" if "repair_trace" in extras else "clean"), extras=extras)
        stats["records"].append({"tag": tag, "passed": True, "path": path})

    if con is not None:
        con.commit()
        stats["db_audit"] = corpus_db.audit(con)
        con.close()
    stats["elapsed_s"] = round(time.time() - t0, 1)
    stats["sampler"] = sampler.metrics()

    # ---- corpus health metrics ------------------------------------------ #
    total = (stats["passed"] + stats["failed_natural"]
             + stats["stress_built"] + stats["injected_faults"])
    natural = stats["failed_natural"] + stats["stress_built"]
    stats["metrics"] = {
        "total_records": total,
        "yield_rate": round(stats["passed"] / max(stats["attempted"], 1), 3),
        "fault_catch_rate": round(
            (stats["faults_caught"] + stats["stress_flagged"])
            / max(stats["injected_faults"] + stats["stress_built"], 1), 3),
        "natural_failure_rate": round(natural / max(total, 1), 3),
        "mix_clean_stress_injected": f"{stats['passed']}:"
                                     f"{natural}:{stats['injected_faults']}",
        "entropy_bits": stats["sampler"]["entropy_bits"],
        "signature_entropy_bits": stats["sampler"]["signature_entropy_bits"],
        "distinct_signatures": stats["sampler"]["distinct_signatures"],
        "volume_cv": stats["sampler"]["volume_cv"],
        "seconds_per_part": round(stats["elapsed_s"] / max(total, 1), 1),
    }
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/forge/pilot")
    ap.add_argument("--db", default="", help="SQLite corpus path")
    ap.add_argument("--no-json", action="store_true",
                    help="write only to SQLite (scale runs)")
    ap.add_argument("--target", type=int, default=0,
                    help="resumable: top the corpus up to this many clean "
                         "records total (re-run safe after any interruption)")
    args = ap.parse_args()

    stats = run_pilot(args.n, args.seed, args.out, db_path=args.db,
                      json_records=not args.no_json,
                      target_total=args.target)
    summary = {k: v for k, v in stats.items() if k != "records"}
    with open(os.path.join(args.out, "_pilot_summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
