"""Step 5 — harvest REAL OCC kernel failures (occ_build_error / no_solid).

The repair corpus is thick with verification-mismatch faults (geometry that
BUILDS but measures wrong) and thin on genuine kernel failures — geometry the
OCC modeller REFUSES to build. Those come almost only from two mechanisms,
force-built past the guards that would normally refuse them:

  * dress-up radius exceeds the adjacent feature (fillet/chamfer larger than
    the hole it rounds or the wall it sits on) -> "invalid shape after
    recompute";
  * a draft steep enough that opposing walls meet below the top face ->
    self-intersection.

This module drives exactly those faults at volume and keeps the ones OCC
rejects, each with its machine diagnosis and repair. Every record lands as
status 'stress' / repair_origin stress_natural, classified occ_build_error or
no_solid by corpus_db._derive_metadata from the recompute-error signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3

from . import corpus_db
from .forge import run_blueprint, workdir
from .forge_loop import _refreeze
from .recipes import RECIPES

# Importing recipes_ext registers its families into the shared RECIPES dict.
try:  # pragma: no cover - import side effect only
    from . import recipes_ext  # noqa: F401
except Exception:  # noqa: BLE001
    pass

#: Fault classes whose force-built form makes OCC fail rather than mis-measure.
OCC_FAULTS = ("dressup_exceeds_adjacent", "draft_self_intersection",
              "self_intersecting_sweep")


def _occ_errors(rec: dict) -> list:
    return ((rec.get("build_log", {}) or {}).get("build_report", {}) or {}
            ).get("recompute_errors", []) or []


def _is_kernel_failure(rec: dict) -> bool:
    """A genuine build failure: OCC reported a recompute error, or the build
    produced no solid at all. NOT a verification mismatch (which builds fine)."""
    return bool(_occ_errors(rec)) or not rec.get("build_ok")


def _pack(bp, rec, graph, recipe, seq, fault, fmeta) -> dict:
    return {
        "schema": "orion-forge-record-v1",
        "blueprint": bp.to_dict(),
        "feature_graph": graph,
        "analysis": {},
        "verdict": {"tag": rec.get("tag", ""), "passed": False,
                    "assertions": rec.get("assertions", []),
                    "measured": rec.get("measured", {}),
                    "build_ok": bool(rec.get("build_ok")),
                    "build_log": rec.get("build_log", {})},
        "recipe": recipe, "base_family": recipe, "attachments": [],
        "datum_strategy": {},
        "feature_seq": list(seq),
        "feature_sequence_hash": hashlib.sha256(
            ("|".join(seq) + "::" + fault).encode()).hexdigest()[:16],
        "repair_trace": {
            "source": "stress_natural", "fault": fault, **fmeta,
            "build_errors": _occ_errors(rec),
            "build_stderr": ((rec.get("build_log", {}) or {})
                             .get("stderr", "") or "")[-1500:],
            "failing": [a["id"] for a in rec.get("assertions", [])
                        if not a["passed"]],
            "caught": not rec.get("passed", False),
            "clean_blueprint_hash": bp.blueprint_hash,
        },
    }


def _occ_recipes() -> list:
    """Recipes whose fault palette contains an OCC-failing mutator — probed
    once so the harvest never wastes a build on a recipe that cannot fail the
    kernel."""
    out = []
    for name in RECIPES:
        try:
            _bp, faults, _seq = RECIPES[name](random.Random(1))
        except Exception:  # noqa: BLE001
            continue
        if any(f in OCC_FAULTS for f in (faults or {})):
            out.append(name)
    return out


def harvest(con, wd, target: int = 160, seed0: int = 20000) -> dict:
    """Force-build OCC-failing faults until ``target`` kernel failures land."""
    stats = {"occ_error": 0, "no_solid": 0, "built_through": 0,
             "attempts": 0, "by_fault": {}}
    rng = random.Random(seed0)
    recipes = _occ_recipes()
    if not recipes:
        return stats
    s = seed0
    max_attempts = target * 80
    while (stats["occ_error"] + stats["no_solid"] < target
           and stats["attempts"] < max_attempts):
        s += 1
        stats["attempts"] += 1
        name = rng.choice(recipes)
        try:
            bp, faults, seq = RECIPES[name](random.Random(s))
        except Exception:  # noqa: BLE001
            continue
        occ = [f for f in (faults or {}) if f in OCC_FAULTS]
        if not occ:
            continue
        fault = rng.choice(occ)
        mutate, fmeta = faults[fault]
        try:
            stressed = _refreeze(bp, mutate)
            graph = stressed.resolve()
        except Exception:  # noqa: BLE001
            continue
        rec = run_blueprint(stressed, f"occ_{s}", wd, force=True)
        if _is_kernel_failure(rec):
            key = "occ_error" if _occ_errors(rec) else "no_solid"
            stats[key] += 1
            stats["by_fault"][fault] = stats["by_fault"].get(fault, 0) + 1
            corpus_db.insert(
                con, _pack(stressed, rec, graph, name, seq, fault, fmeta),
                "stress")
            if (stats["occ_error"] + stats["no_solid"]) % 25 == 0:
                con.commit()
        else:
            stats["built_through"] += 1
    con.commit()
    return stats


def run(db_path: str, target: int, timeout_s: int = 20,
        seed0: int = 20000) -> dict:
    # A genuine recompute error returns in ~1-2s; a build still grinding after
    # a few seconds is a near-hang that yields a timeout, not an occ error, and
    # only stalls the harvest. Cap the per-build wall clock low so hangs are
    # abandoned fast instead of burning the default 90s each.
    import orion.forge as _forge
    _forge.BUILD_TIMEOUT_S = timeout_s
    con = sqlite3.connect(db_path)
    con.executescript(corpus_db.SCHEMA)
    wd = workdir()
    out = harvest(con, wd, target=target, seed0=seed0)
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/forge/corpus_v3.db")
    ap.add_argument("--target", type=int, default=160)
    ap.add_argument("--timeout", type=int, default=20,
                    help="per-build wall-clock cap (s); hangs abandoned fast")
    ap.add_argument("--seed", type=int, default=20000)
    args = ap.parse_args()
    print(json.dumps(run(args.db, args.target, args.timeout, args.seed),
                     indent=1))


if __name__ == "__main__":
    main()
