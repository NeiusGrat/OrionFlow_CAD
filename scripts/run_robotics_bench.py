"""Run the robotics bench through the Physical AI agent.

Usage:
    python scripts/run_robotics_bench.py                 # local agent (needs LLM key)
    python scripts/run_robotics_bench.py --only nema17-bracket pulley-keyway
    python scripts/run_robotics_bench.py --no-llm-reasoning   # deterministic plan only

Writes per-case JSON + URDF/SDF into benchmarks/results/robotics_<timestamp>/
and prints a summary table.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BENCH = ROOT / "benchmarks" / "robotics_bench_v1.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run only these case ids")
    ap.add_argument("--max-repairs", type=int, default=2)
    ap.add_argument("--no-llm-reasoning", action="store_true")
    args = ap.parse_args()

    from orion_physical_ai import PhysicalAIAgent

    agent = PhysicalAIAgent(use_llm_reasoning=not args.no_llm_reasoning)

    cases = [json.loads(line) for line in open(BENCH, encoding="utf-8")]
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "benchmarks" / "results" / f"robotics_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for case in cases:
        print(f"\n=== {case['id']} ===")
        t0 = time.time()
        try:
            bundle = agent.design(case["prompt"], max_repairs=args.max_repairs)
        except Exception as e:
            bundle = {"success": False, "error": f"agent crashed: {e}"}
        elapsed = time.time() - t0

        ok = bundle.get("success", False)
        stats = bundle.get("stats") or {}
        analysis = bundle.get("analysis") or {}
        row = {
            "id": case["id"],
            "success": ok,
            "watertight": stats.get("watertight"),
            "volume_mm3": stats.get("volume_mm3"),
            "bbox_mm": stats.get("bbox_mm"),
            "repairs": bundle.get("repair_attempts"),
            "dfm_score": analysis.get("manufacturability_score"),
            "has_urdf": bool(bundle.get("urdf")),
            "elapsed_s": round(elapsed, 1),
            "error": (bundle.get("error") or "")[:200],
        }
        rows.append(row)
        print(json.dumps(row, indent=2))

        case_path = out_dir / f"{case['id']}.json"
        with open(case_path, "w", encoding="utf-8") as f:
            json.dump({**case, **bundle}, f, indent=1, default=str)
        for key, ext in (("urdf", "urdf"), ("sdf", "sdf"), ("ofl_code", "ofl.py")):
            content = bundle.get(key)
            if content:
                with open(out_dir / f"{case['id']}.{ext}", "w", encoding="utf-8") as f:
                    f.write(content)

    passed = sum(1 for r in rows if r["success"])
    urdfs = sum(1 for r in rows if r["has_urdf"])
    print(f"\n{'=' * 60}")
    print(f"robotics bench: {passed}/{len(rows)} generated, {urdfs} with URDF/SDF")
    print(f"results: {out_dir}")
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
