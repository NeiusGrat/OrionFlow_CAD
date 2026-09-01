"""Run the frozen benchmark through the STUDIO path, end to end.

``run_ofl_bench.py`` measures the OFL path — Groq, OFL Python, build123d. The
studio is a different system on the same prompts: our fine-tuned adapter emits a
Blueprint, ``Blueprint.freeze()`` static-checks it, ``resolve()`` turns symbolic
expressions into a graph, FreeCAD builds and measures it, and the model's own
frozen assertions decide the verdict. Nothing measured that path reproducibly,
which is how a live VERIFIED figure came to be quoted from an ad-hoc run that
predates several changes to the pipeline.

Same 50 prompts as the OFL bench, so the two systems stay comparable, and the
same tolerances where the bench froze an expected bbox or volume.

The headline is ``VERIFIED``: the model authored a parametric part, predicted
its own volume in closed form, and the kernel agreed. Everything else is the
funnel underneath it — how many produced geometry at all, and how many needed
the repair round to get there, which is the number that says whether repair is
carrying the result or merely present.

Runs the agent in-process rather than against a deployed API on purpose: that is
the code on this branch, not whatever is currently serving.

    python scripts/run_studio_bench.py                 # all 50
    python scripts/run_studio_bench.py --limit 5       # smoke
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BENCH = REPO / "benchmarks" / "ofl_bench_v1.jsonl"
RESULTS_DIR = REPO / "benchmarks" / "results"

BBOX_TOL_MM = 1.5
VOLUME_TOL_PCT = 5.0


def _load_key() -> None:
    """Endpoint key from .env, in-process. Never reaches a shell or argv."""
    if os.environ.get("ORION_LLM_API_KEY"):
        return
    env = REPO / ".env"
    if not env.exists():
        return
    with open(env, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("ORION_LLM_API_KEY="):
                os.environ["ORION_LLM_API_KEY"] = line.split("=", 1)[1].strip()
                return


def check_bbox(expected, actual) -> bool:
    """Sorted extents — the model may orient the part differently."""
    if not expected or not actual or len(actual) != 3:
        return False
    return all(abs(e - a) <= BBOX_TOL_MM
               for e, a in zip(sorted(expected), sorted(actual)))


def check_volume(expected, actual) -> bool:
    if not expected or not actual:
        return False
    return abs(actual - expected) / expected * 100.0 <= VOLUME_TOL_PCT


def run_case(agent, case: dict) -> dict:
    started = time.time()
    row = {"id": case.get("id"), "category": case.get("category"),
           "prompt": case["prompt"], "verified": False, "built": False,
           "repaired": False, "attempts": 0, "verdict": None,
           "part_class": "", "model": "", "error": None, "failure": "",
           "bbox_ok": None, "volume_ok": None, "volume_mm3": None,
           "checks": 0, "failed_checks": [], "elapsed_s": 0.0}
    try:
        bundle = agent.design(case["prompt"])
    except Exception as exc:  # noqa: BLE001 — one bad case must not end the run
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_s"] = round(time.time() - started, 1)
        return row

    report = bundle.get("verification") or {}
    stats = bundle.get("stats") or {}
    row.update({
        "built": bool(bundle.get("success")),
        "attempts": bundle.get("attempts", 0),
        "repaired": bool(bundle.get("attempts", 0) > 1),
        "verdict": report.get("verdict"),
        "verified": report.get("verdict") == "verified",
        "part_class": bundle.get("part_class", ""),
        "model": bundle.get("model", ""),
        "error": bundle.get("error"),
        "failure": bundle.get("failure") or "",
        "checks": len(report.get("checks") or []),
        "failed_checks": [c.get("id") for c in (report.get("failed") or [])],
        "volume_mm3": stats.get("volume_mm3"),
        "elapsed_s": round(time.time() - started, 1),
    })
    # The bench freezes an expected size for some prompts; where it does, an
    # independently correct part still has to be the RIGHT part.
    if case.get("expected_bbox_mm"):
        row["bbox_ok"] = check_bbox(case["expected_bbox_mm"], stats.get("bbox_mm"))
    if case.get("expected_volume_mm3"):
        row["volume_ok"] = check_volume(case["expected_volume_mm3"],
                                        stats.get("volume_mm3"))
    claim = bundle.get("volume_claim") or {}
    row["stated_volume_agrees"] = claim.get("agrees")
    return row


def is_environment_failure(row: dict) -> bool:
    """Did the deployment prevent this row from being attempted at all?

    Report section 15: an unreachable endpoint is an ENVIRONMENT failure, not a
    MODEL failure, and counting the two together understates the system. The
    2026-07-31 run scored five "no model is reachable" rows as capability
    failures, which is a real part of the gap between 36% and what the compiled
    path actually does.

    The failure class is authoritative; the error text is a fallback for rows
    recorded before ``_failed_bundle`` carried the class.
    """
    if row.get("failure") == "model":
        return True
    err = (row.get("error") or "").lower()
    return "no model is reachable" in err or "not currently being served" in err


def summarise(rows: list[dict], deployment: dict = None) -> dict:
    n = len(rows)
    got = lambda k: sum(1 for r in rows if r[k])          # noqa: E731
    pct = lambda k: 100.0 * got(k) / n if n else 0.0      # noqa: E731
    env = [r for r in rows if is_environment_failure(r)]
    attempted = [r for r in rows if not is_environment_failure(r)]
    att_verified = sum(1 for r in attempted if r["verified"])
    bbox = [r for r in rows if r["bbox_ok"] is not None]
    vol = [r for r in rows if r["volume_ok"] is not None]
    claims = [r for r in rows if r.get("stated_volume_agrees") is not None]

    summary = {
        "n": n,
        # Stamped so a number can never be compared across deployments by
        # accident: the same prompts on a served LoRA and on a fallback are
        # measuring two different systems.
        "deployment": deployment or {},
        "verified_pct": pct("verified"),
        # Over the rows this deployment could actually attempt. Equal to
        # ``verified_pct`` when nothing was blocked by the environment.
        "attempted_n": len(attempted),
        "verified_pct_attempted": (
            100.0 * att_verified / len(attempted) if attempted else 0.0),
        "environment_failed_n": len(env),
        "built_pct": pct("built"),
        "repaired_n": got("repaired"),
        "verified_without_repair": sum(
            1 for r in rows if r["verified"] and not r["repaired"]),
        "bbox_ok": sum(1 for r in bbox if r["bbox_ok"]), "bbox_n": len(bbox),
        "volume_ok": sum(1 for r in vol if r["volume_ok"]), "volume_n": len(vol),
        "stated_volume_agrees": sum(
            1 for r in claims if r["stated_volume_agrees"]),
        "stated_volume_n": len(claims),
        "median_s": sorted(r["elapsed_s"] for r in rows)[n // 2] if n else 0.0,
    }
    print("\n" + "=" * 60)
    print(f"  prompts              {n}")
    print(f"  VERIFIED             {summary['verified_pct']:6.1f}%   <- headline")
    if env:
        print(f"  VERIFIED (attempted) {summary['verified_pct_attempted']:6.1f}%"
              f"   <- excludes {len(env)} row(s) the deployment blocked")
        print(f"  environment failures {len(env)}/{n}   "
              f"(endpoint down / weights not served)")
    print(f"  built geometry       {summary['built_pct']:6.1f}%")
    print(f"  verified first try   {summary['verified_without_repair']}/{n}")
    print(f"  needed a repair turn {summary['repaired_n']}/{n}")
    if bbox:
        print(f"  bbox within {BBOX_TOL_MM} mm    "
              f"{summary['bbox_ok']}/{summary['bbox_n']}")
    if vol:
        print(f"  volume within {VOLUME_TOL_PCT}%   "
              f"{summary['volume_ok']}/{summary['volume_n']}")
    if claims:
        print(f"  stated volume right  {summary['stated_volume_agrees']}"
              f"/{summary['stated_volume_n']}   (the model's own arithmetic)")
    print(f"  median time          {summary['median_s']:.1f}s")
    print("=" * 60)

    failures = [r for r in rows if not r["verified"]]
    if failures:
        print("\n  not verified:")
        for r in failures:
            why = (r["error"] or ", ".join(map(str, r["failed_checks"]))
                   or r["verdict"] or "?")
            print(f"    [{r['id']}] {str(why)[:66]}")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(REPO))
    _load_key()
    from app.services.studio_agent import get_studio_agent

    agent = get_studio_agent()
    health = agent.health()
    print(f"model {health.get('model')} via {health.get('provider')} "
          f"(ours: {health.get('serving_our_model')}) | "
          f"builder {health.get('builder')}/{health.get('builder_mode')}")
    # This used to refuse outright, on the grounds that a number measured on a
    # fallback is not a number about this system. That was true when every
    # Blueprint was authored by our weights. It is not true now: the four
    # compiled families go through ``_deterministic``, which reads the request
    # with whatever provider is up and then compiles the Blueprint in Python,
    # so their result is provider-independent and *is* a number about this
    # system. Refusing made the bench unrunnable for as long as the GPU stays
    # down, which is how the headline came to be a month old.
    #
    # So: run, but stamp the deployment into the summary, and never let a row
    # the deployment could not attempt be scored as a capability failure.
    ours = bool(health.get("serving_our_model"))
    if not ours:
        print("NOTE: our weights are not being served. The compiled families "
              "are still measured exactly; rows that need the fine-tuned "
              "author are reported as environment failures, not as failures.")

    cases = [json.loads(line) for line in open(BENCH, encoding="utf-8")
             if line.strip()]
    if args.limit:
        cases = cases[:args.limit]
    print(f"{len(cases)} prompts from {BENCH.name}\n")

    rows = []
    for i, case in enumerate(cases, 1):
        row = run_case(agent, case)
        rows.append(row)
        mark = "OK  " if row["verified"] else "FAIL"
        extra = " (repaired)" if row["repaired"] else ""
        print(f"  [{mark}] {i:3d}/{len(cases)} {str(row['id'])[:24]:24s} "
              f"{row['elapsed_s']:5.1f}s{extra}", flush=True)

    summary = summarise(rows, deployment={
        "provider": health.get("provider"),
        "configured_model": health.get("configured_model"),
        "serving_our_model": ours,
        "builder": f"{health.get('builder')}/{health.get('builder_mode')}",
    })

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else (
        RESULTS_DIR / f"studio_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "rows": rows}, fh, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
