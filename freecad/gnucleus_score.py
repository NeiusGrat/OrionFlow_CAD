"""Score our reconstructed FCStds with the official gNucleus freecad-validator.

Builds the validator's batch layout (candidate = our rebuilt file, reference =
the original gNucleus FCStd, spec = the sample's name/description/params),
scores every case, and — critically — also scores each reference against
ITSELF to establish the validator's measurement ceiling per case. A candidate
that matches its ceiling is lossless per gNucleus's own metric, regardless of
the absolute number (gear specs cap below 1.0 because derived parameters like
module aren't recoverable from geometry alone).

Measured 2026-07-19: ceiling mean 0.867, ours 0.838, 97/100 at ceiling.
The 3 gaps are masters using features outside reconstruct.py's SUPPORTED set
(AdditivePipe / AdditiveLoft / AdditiveSphere parts).

Setup:
    pip install "git+https://github.com/gNucleus-AI/freecad-validator"
    set FREECAD_LIB to the FreeCAD bin+Lib dirs (auto-detect usually works)
Usage:
    python -m freecad.gnucleus_score            # score + ceiling, all masters
    python -m freecad.gnucleus_score --limit 10
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import statistics

from .config import FCSTD_DIR, PKG_DIR

TRAINING_DIR = PKG_DIR / "training"
REBUILT_DIR = PKG_DIR / "rebuilt"
EVAL_ROOT = PKG_DIR / "variants" / "gnucleus_eval"


def build_cases(limit: int = 0) -> int:
    files = sorted(glob.glob(str(TRAINING_DIR / "sample_*.json")))
    if limit:
        files = files[:limit]
    made = 0
    for f in files:
        s = json.load(open(f, encoding="utf-8"))
        sid = s["id"]
        cand = REBUILT_DIR / f"{sid}.FCStd"
        ref = FCSTD_DIR / f"{sid}.FCStd"
        if not (cand.exists() and ref.exists()):
            continue
        d = EVAL_ROOT / "data" / sid
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cand, d / "candidate.FCStd")
        shutil.copyfile(ref, d / "reference.FCStd")
        (d / "spec.json").write_text(json.dumps({
            "name": s["name"], "description": s["description"],
            "key_parameters": s["key_parameters"],
        }), encoding="utf-8")
        made += 1
    return made


def score() -> dict:
    from freecad_validator import Validator

    v = Validator()
    rows = []
    for d in sorted(glob.glob(str(EVAL_ROOT / "data" / "*"))):
        sid = os.path.basename(d)
        row: dict = {"id": sid}
        try:
            r = v.validate(candidate_fcstd=f"{d}/candidate.FCStd",
                           reference_fcstd=f"{d}/reference.FCStd",
                           spec_json=f"{d}/spec.json")
            row.update(geom=round(r.geometry_similarity, 3),
                       spec=round(r.cad_spec_consistency, 3),
                       ours=round(r.combined, 3))
            c = v.validate(candidate_fcstd=f"{d}/reference.FCStd",
                           reference_fcstd=f"{d}/reference.FCStd",
                           spec_json=f"{d}/spec.json")
            row["ceiling"] = round(c.combined, 3)
        except Exception as e:  # noqa: BLE001 - record and continue
            row["error"] = str(e)[:120]
        rows.append(row)
        print(row)

    ok = [r for r in rows if "ours" in r and "ceiling" in r]
    summary = {
        "n": len(rows),
        "scored": len(ok),
        "ours_mean": round(statistics.mean(r["ours"] for r in ok), 4) if ok else 0,
        "ceiling_mean": round(statistics.mean(r["ceiling"] for r in ok), 4) if ok else 0,
        "at_ceiling": sum(1 for r in ok if r["ours"] >= r["ceiling"] - 1e-6),
        "gaps": [r["id"] for r in ok if r["ours"] < r["ceiling"] - 1e-6],
    }
    out = EVAL_ROOT / "results.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1),
                   encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()
    if not args.skip_build:
        n = build_cases(args.limit)
        print(f"[cases] {n}")
    score()


if __name__ == "__main__":
    main()
