"""Run the frozen OFL benchmark (benchmarks/ofl_bench_v1.jsonl).

Every model/prompt/pipeline change gets measured against the same 50 prompts,
so improvement claims are numbers, not anecdotes.

Usage:
    python scripts/run_ofl_bench.py                      # against prod API
    python scripts/run_ofl_bench.py --api http://localhost:8000
    python scripts/run_ofl_bench.py --local              # in-process service
    python scripts/run_ofl_bench.py --limit 5 --only washer

Pass criteria per prompt:
    success  — pipeline produced files
    watertight — trimesh says the mesh is closed
    bbox     — sorted extents match expected within tolerance (when frozen)
    volume   — within ±5% of analytic value (when frozen)

Results: benchmarks/results/bench_<timestamp>.jsonl + printed summary.
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BENCH = REPO / "benchmarks" / "ofl_bench_v1.jsonl"
RESULTS_DIR = REPO / "benchmarks" / "results"

DEFAULT_API = "https://sahilmaniyar57--orionflow-api-api.modal.run"
BBOX_TOL_MM = 1.5
VOLUME_TOL_PCT = 5.0


def load_bench() -> list[dict]:
    with open(BENCH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_bbox(expected: list[float], actual: list[float]) -> bool:
    """Compare sorted extents — the model may orient the part differently."""
    if not actual or len(actual) != 3:
        return False
    exp, act = sorted(expected), sorted(actual)
    return all(abs(e - a) <= BBOX_TOL_MM for e, a in zip(exp, act))


def check_volume(expected: float, actual: float) -> bool:
    if not actual:
        return False
    return abs(actual - expected) / expected * 100 <= VOLUME_TOL_PCT


def evaluate(case: dict, response: dict, elapsed_s: float) -> dict:
    stats = response.get("stats") or {}
    result = {
        "id": case["id"],
        "category": case["category"],
        "success": bool(response.get("success")),
        "watertight": bool(stats.get("watertight")),
        "repair_attempts": response.get("repair_attempts", 0),
        "time_s": round(elapsed_s, 1),
        "volume_mm3": stats.get("volume_mm3"),
        "bbox_mm": stats.get("bbox_mm"),
        "error": (response.get("error") or "")[:300] or None,
    }
    checks = [result["success"], result["watertight"]]
    if "expected_bbox_mm" in case:
        result["bbox_ok"] = check_bbox(case["expected_bbox_mm"], stats.get("bbox_mm"))
        checks.append(result["bbox_ok"])
    if "expected_volume_mm3" in case:
        result["volume_ok"] = check_volume(
            case["expected_volume_mm3"], stats.get("volume_mm3") or 0
        )
        checks.append(result["volume_ok"])
    result["pass"] = all(checks)
    return result


def run_api(case: dict, api: str) -> tuple[dict, float]:
    """POST one prompt; ride out transient network blips with backoff.

    A dropped connection mid-bench (observed: client-side outage killed 18
    consecutive cases) must not poison the run — a retried generate only
    costs one extra LLM call.
    """
    import requests

    t0 = time.time()
    last_exc: Exception = RuntimeError("no attempts")
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{api}/api/v1/ofl/generate",
                json={"prompt": case["prompt"]},
                timeout=280,  # Modal 303-redirects >150s requests; requests follows
            )
            resp.raise_for_status()
            return resp.json(), time.time() - t0
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            time.sleep(20 * (attempt + 1))
    raise last_exc


def run_local(case: dict, service) -> tuple[dict, float]:
    t0 = time.time()
    response = service.generate_from_prompt(case["prompt"])
    return response.model_dump(), time.time() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen OFL benchmark")
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL")
    parser.add_argument("--local", action="store_true", help="run the service in-process")
    parser.add_argument("--limit", type=int, help="run only the first N prompts")
    parser.add_argument("--offset", type=int, default=0, help="skip the first N prompts")
    parser.add_argument("--only", help="run only this prompt id")
    args = parser.parse_args()

    cases = load_bench()
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    if args.offset:
        cases = cases[args.offset:]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no matching benchmark cases")
        return 1

    service = None
    if args.local:
        sys.path.insert(0, str(REPO))
        from app.services.ofl_generation_service import OFLGenerationService

        service = OFLGenerationService(require_llm=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"bench_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} … ", end="", flush=True)
        try:
            if service:
                response, elapsed = run_local(case, service)
            else:
                response, elapsed = run_api(case, args.api)
            result = evaluate(case, response, elapsed)
        except Exception as e:
            result = {
                "id": case["id"], "category": case["category"],
                "success": False, "watertight": False, "pass": False,
                "repair_attempts": 0, "time_s": 0,
                "error": f"request failed: {e}"[:300],
            }
        results.append(result)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
        print("PASS" if result["pass"] else f"FAIL ({result.get('error') or 'checks'})")

    n = len(results)
    passed = sum(r["pass"] for r in results)
    succeeded = sum(r["success"] for r in results)
    watertight = sum(r["watertight"] for r in results)
    repaired = sum(1 for r in results if r["repair_attempts"])
    times = [r["time_s"] for r in results if r["time_s"]]

    print(f"\n{'=' * 52}")
    print(f"OFL bench v1 — {n} prompts")
    print(f"  pass (all checks) : {passed}/{n} ({passed / n * 100:.0f}%)")
    print(f"  executed          : {succeeded}/{n}")
    print(f"  watertight        : {watertight}/{n}")
    print(f"  needed repair     : {repaired}/{n}")
    if times:
        print(f"  median time       : {sorted(times)[len(times) // 2]:.1f}s")
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["pass"])
    for cat, vals in sorted(by_cat.items()):
        print(f"    {cat:<12} {sum(vals)}/{len(vals)}")
    print(f"results -> {out_path}")
    return 0 if passed == n else 1


if __name__ == "__main__":
    sys.exit(main())
