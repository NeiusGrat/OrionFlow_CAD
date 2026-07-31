"""Score the planner on requirements, not on recovering a known part.

``eval_plan`` grades against the corpus, which has one blind spot it cannot fix:
those prompts state *dimensions*. There is nothing in them to reason about, so
they measure transcription and constraint repair — which is exactly what the
measurements showed, with the planner making four constraint-repair overrides
and zero tool calls across fifty cases.

This suite states *requirements* instead: a load and a safety factor, a bolt
size and full thread engagement, a mass budget. The dimensions that satisfy them
are not given and cannot be transcribed. They have to be derived, which is the
job the calculators exist for and the only job a model can do here that a lookup
table cannot.

The grading is objective because the requirement is a calculator call. A case
passes when the calculator, run on the specification the planner produced, meets
the stated threshold. There is no reference part and no similarity score: the
part either carries the load or it does not.

Baseline expectation is failure. The medians are sized for nothing in
particular, so a suite where they already pass would prove nothing.

    python -m orion.eval_requirements            # deterministic baseline
    python -m orion.eval_requirements --live     # with the served base model
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

from . import expr as E

DEFAULT_SUITE = os.path.join("benchmarks", "planner_requirements_v1.jsonl")

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def _value(spec_vars: dict, raw: Any) -> Any:
    """A literal, or an expression over the specification's own variables.

    Letting a threshold be an expression is what allows "the plate must be
    thicker than the required engagement" to be written as ``min_engagement_mm
    <= pt`` — a requirement that couples the calculator's output to a dimension
    the planner chose.
    """
    if not isinstance(raw, str):
        return raw
    # Only strings that are genuinely expressions over this specification get
    # evaluated. A material name is a string too, and treating it as arithmetic
    # turns "aluminium_6061_t6" into an unknown-name error rather than an
    # argument.
    try:
        names = E.names(raw)
    except E.ExprError:
        return raw
    if not names or not names <= set(spec_vars):
        return raw
    return E.evaluate(raw, spec_vars)


def check_requirement(requirement: dict, spec_vars: dict) -> dict:
    """Run the requirement's calculator against a specification."""
    from . import calc

    out = {"passed": False, "metric": requirement.get("metric"),
           "measured": None, "threshold": None, "error": ""}
    try:
        args = {k: _value(spec_vars, v)
                for k, v in (requirement.get("args") or {}).items()}
        result = calc.run(requirement["calculator"], **args)
        out["measured"] = result.get(requirement["metric"])
        out["threshold"] = _value(spec_vars, requirement["value"])
    except Exception as exc:  # noqa: BLE001 — a broken case must not stop the run
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    op = _OPS.get(requirement.get("op", ">="))
    if op is None or out["measured"] is None or out["threshold"] is None:
        out["error"] = "requirement could not be evaluated"
        return out
    out["passed"] = bool(op(float(out["measured"]), float(out["threshold"])))
    return out


def load_suite(path: str = DEFAULT_SUITE) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def score_one(case: dict, planner) -> dict:
    from .family_schema import check_guards

    out = {"id": case["id"], "family_ok": False, "requirement_ok": False,
           "guards_ok": False, "measured": None, "threshold": None,
           "applied": [], "tools_used": [], "error": ""}

    result = planner.plan(case["prompt"])
    if not result.ok or result.specification is None:
        out["error"] = result.error or "no specification"
        return out

    spec = result.specification
    out["chosen_family"] = spec.part_class
    out["family_ok"] = (spec.part_class == case.get("family")
                        if case.get("family") else True)
    out["applied"] = list(result.applied)
    out["tools_used"] = list(result.tools_used)
    out["variables"] = dict(spec.variables)

    verdict = check_requirement(case["requirement"], spec.variables)
    out.update({"requirement_ok": verdict["passed"],
                "measured": verdict["measured"],
                "threshold": verdict["threshold"],
                "error": verdict["error"]})
    guards = check_guards(spec.part_class, spec.variables)
    out["guards_ok"] = all(g["holds"] for g in guards) if guards else True
    return out


def report(rows: list[dict], label: str) -> dict:
    n = len(rows)
    met = sum(r["requirement_ok"] for r in rows)
    fam = sum(r["family_ok"] for r in rows)
    guards = sum(r["guards_ok"] for r in rows)
    tools = sum(len(r["tools_used"]) for r in rows)
    overrides = sum(len(r["applied"]) for r in rows)

    print(f"\n=== {label} " + "=" * max(4, 44 - len(label)))
    print(f"  cases                {n}")
    print(f"  right family         {fam}/{n}")
    print(f"  REQUIREMENT MET      {met}/{n}   ({100.0 * met / n:.0f}%)")
    print(f"  guards hold          {guards}/{n}")
    print(f"  overrides applied    {overrides}")
    print(f"  tool calls made      {tools}")
    print("  " + "-" * 44)
    for r in rows:
        mark = "PASS" if r["requirement_ok"] else "FAIL"
        measured = ("n/a" if r["measured"] is None
                    else f"{float(r['measured']):.3f}")
        threshold = ("n/a" if r["threshold"] is None
                     else f"{float(r['threshold']):.3f}")
        print(f"  [{mark}] {r['id']:26s} {measured:>9s} vs {threshold:>9s}"
              + (f"  {r['error'][:40]}" if r["error"] else ""))
    return {"label": label, "n": n, "met": met, "family_ok": fam,
            "guards_ok": guards, "tool_calls": tools, "overrides": overrides}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", default=DEFAULT_SUITE)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    from app.services.planner import EngineeringPlanner, live_completion

    cases = load_suite(args.suite)
    print(f"{len(cases)} requirement cases from {args.suite}")

    rows = [score_one(c, EngineeringPlanner()) for c in cases]
    payload = {"baseline": {"summary": report(rows, "deterministic baseline"),
                            "rows": rows}}

    if args.live:
        planner = EngineeringPlanner(live_completion(args.model))
        live_rows = []
        for i, case in enumerate(cases, 1):
            live_rows.append(score_one(case, planner))
            print(f"  ...{i}/{len(cases)}", flush=True)
        payload["live"] = {"summary": report(live_rows, "planner (base model)"),
                           "rows": live_rows}
        base, live = payload["baseline"]["summary"], payload["live"]["summary"]
        print(f"\n  requirements met  {base['met']}/{base['n']}  ->  "
              f"{live['met']}/{live['n']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
