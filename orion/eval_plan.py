"""Score the planner, not the model that eventually draws the part.

``eval_blueprint`` answers "did a part get built and did it match its own
prediction". That says nothing about whether the *specification* handed to the
Blueprint model was any good, and a specification can be wrong in ways that
still build perfectly: the wrong family, a stated dimension quietly dropped, a
diameter stored where a radius belongs.

The corpus is the ground truth. Every ``design``-view row is a prose engineering
ask whose true family and true variables are known, because a verified part was
generated first and the prose written from it::

    I need a wheel hub.
    Dimensions (mm unless noted): barrel height 40, barrel radius 29,
    bc radius 48, bore radius 7, flange thickness 12.
    Choose sensible values for anything I have not given.

So the planner can be run on the prose and graded against the part it came from.

Three metrics, in descending order of how much they mean:

* **family** — did we pick the right one? Everything downstream is conditioned
  on this, so an error here makes the rest meaningless rather than merely wrong.
* **fidelity** — of the dimensions the user actually stated, how many reached
  the specification with the right value? This is the one that must be 100%.
  A dropped or mistranslated requirement is the worst failure the system can
  have, because the part builds and verifies and is simply not what was asked
  for.
* **agreement** — for values the user did *not* state, how close is the plan to
  the part the corpus built? Reported, never treated as correctness: the corpus
  value is *a* good answer, not the only one, and a planner that picks a
  different sensible wall thickness has not made a mistake.

The median baseline is the control arm. A planner that cannot beat it on
agreement, while holding fidelity at 100%, is not yet earning its latency.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from typing import Optional

#: "Dimensions (mm unless noted): barrel height 40, bc radius 48."
_DIMS_LINE = re.compile(r"Dimensions\s*\([^)]*\)\s*:\s*(.+)", re.I)
#: "barrel height 40" / "bc radius 48" / "end radius 4.25"
_DIM_ITEM = re.compile(r"^(.*?)[\s=]+(-?\d+(?:\.\d+)?)$")


def stated_dimensions(prompt: str) -> dict[str, float]:
    """The dimensions the ask actually gives, as ``{prose phrase: value}``."""
    match = _DIMS_LINE.search(prompt or "")
    if not match:
        return {}
    out: dict[str, float] = {}
    for chunk in match.group(1).rstrip(".").split(","):
        item = _DIM_ITEM.match(chunk.strip())
        if item:
            out[item.group(1).strip().lower()] = float(item.group(2))
    return out


def load_cases(path: str, limit: Optional[int] = None) -> list[dict]:
    """``design``-view rows with their true family and variables."""
    cases: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            meta = record.get("meta") or {}
            if meta.get("view") != "design":
                continue
            try:
                blueprint = json.loads(
                    record["messages"][2]["content"].split("</think>")[1].strip())
            except (IndexError, ValueError):
                continue
            prompt = record["messages"][1]["content"]
            cases.append({
                "family": meta["base_family"],
                "prompt": prompt,
                "stated": stated_dimensions(prompt),
                "truth": {k: float(v) for k, v in blueprint["variables"].items()
                          if not k.startswith("att")
                          and isinstance(v, (int, float))},
            })
            if limit and len(cases) >= limit:
                break
    return cases


def score_one(case: dict, planner) -> dict:
    """Run one case and grade it."""
    from orion.family_schema import check_guards, for_family, resolve

    out = {"family": case["family"], "family_ok": False,
           "stated_total": 0, "stated_ok": 0, "unresolved": [],
           "guards_ok": None, "agreement": [], "error": ""}

    result = planner.plan(case["prompt"])
    if not result.ok or result.specification is None:
        out["error"] = result.error or "no specification"
        return out

    spec = result.specification
    out["chosen_family"] = spec.part_class
    out["family_ok"] = spec.part_class == case["family"]
    # What the planner actually did, kept so a score can be interrogated rather
    # than only compared. A run that improves a metric without a readable reason
    # is not evidence of anything.
    out["applied"] = list(result.applied)
    out["refused"] = [{"variable": r.get("variable"), "reason": r.get("reason")}
                      for r in result.refused]
    out["tools_used"] = list(result.tools_used)
    if not out["family_ok"]:
        return out          # the rest is not comparable across families

    # --- fidelity: every stated dimension must survive, exactly ------------- #
    # Attachment dimensions ("first feature rib height" = att0_rh) are counted
    # separately, not excused. A base-family planner does not place attachments,
    # so scoring them as failures would measure the wrong thing — but hiding
    # them would conceal a real limit on what the layer can currently accept.
    from orion.family_schema import _ATTACHMENT_PHRASE

    for phrase, value in case["stated"].items():
        if _ATTACHMENT_PHRASE.match(phrase.strip().lower()):
            out["attachment_dims"] = out.get("attachment_dims", 0) + 1
            continue
        match = resolve(case["family"], phrase)
        if match is None:
            out["unresolved"].append(phrase)
            continue
        out["stated_total"] += 1
        planned = spec.variables.get(match.variable)
        if planned is not None and abs(planned - match.apply(value)) < 1e-6:
            out["stated_ok"] += 1

    # --- precision: a value invented and labelled as the user's ------------ #
    # Fidelity alone measures recall. It stays at 100% while the layer quietly
    # adds a variable nobody mentioned, takes a number that belongs to a
    # different dimension, and marks it "stated by the user" — which is how ten
    # guard failures survived a perfect fidelity score.
    truth = case["truth"]
    invented = []
    for name, why in (spec.rationale or {}).items():
        if why != "stated by the user" or name not in truth:
            continue
        if abs(spec.variables.get(name, 0.0) - truth[name]) > 1e-6:
            invented.append(name)
    out["invented"] = invented

    # --- agreement on what the user did not state -------------------------- #
    schema = for_family(case["family"])
    stated_vars = {resolve(case["family"], p).variable
                   for p in case["stated"]
                   if resolve(case["family"], p) is not None}
    for name, true_value in case["truth"].items():
        if name in stated_vars or name not in spec.variables:
            continue
        if abs(true_value) < 1e-9:
            continue
        planned = spec.variables[name]
        median = schema.variables[name].median if schema and name in schema.variables \
            else planned
        out["agreement"].append({
            "variable": name,
            "planned_err": abs(planned - true_value) / abs(true_value),
            "median_err": abs(median - true_value) / abs(true_value),
        })

    guards = check_guards(spec.part_class, spec.variables)
    out["guards_ok"] = all(g["holds"] for g in guards) if guards else True
    return out


def report(rows: list[dict], label: str) -> dict:
    n = len(rows)
    fam_ok = sum(r["family_ok"] for r in rows)
    comparable = [r for r in rows if r["family_ok"]]
    stated_total = sum(r["stated_total"] for r in comparable)
    stated_ok = sum(r["stated_ok"] for r in comparable)
    unresolved = sum(len(r["unresolved"]) for r in rows)
    attachment_dims = sum(r.get("attachment_dims", 0) for r in rows)
    invented = sum(len(r.get("invented") or []) for r in rows)

    # Absent is not zero. Rows written before the capture existed have no
    # ``applied``/``tools_used`` key at all, and summing them with ``.get(k, 0)``
    # reports a confident "0 tool calls" that was never measured. Distinguish
    # the two, because the difference is between a finding and a fabrication.
    captured = [r for r in rows if "tools_used" in r]
    tool_calls = (sum(len(r["tools_used"]) for r in captured)
                  if captured else None)
    overrides = (sum(len(r.get("applied") or []) for r in captured)
                 if captured else None)
    guards_ok = sum(1 for r in comparable if r["guards_ok"])
    agree = [a for r in comparable for a in r["agreement"]]
    wins = sum(1 for a in agree if a["planned_err"] < a["median_err"] - 1e-12)
    ties = sum(1 for a in agree if abs(a["planned_err"] - a["median_err"]) <= 1e-12)

    summary = {
        "label": label, "n": n,
        "family_pct": 100.0 * fam_ok / n if n else 0.0,
        "fidelity_pct": 100.0 * stated_ok / stated_total if stated_total else 0.0,
        "stated_total": stated_total,
        "unresolved_phrases": unresolved,
        "attachment_dims": attachment_dims,
        "tool_calls": tool_calls,
        "overrides_applied": overrides,
        "invented_values": invented,
        "guards_pct": 100.0 * guards_ok / len(comparable) if comparable else 0.0,
        "agreement_n": len(agree),
        "median_err": statistics.median(
            [a["planned_err"] for a in agree]) if agree else None,
        "beats_median_pct": 100.0 * wins / len(agree) if agree else 0.0,
        "ties_median_pct": 100.0 * ties / len(agree) if agree else 0.0,
    }
    print(f"\n=== {label} " + "=" * (46 - len(label)))
    print(f"  cases                    {n}")
    print(f"  family chosen correctly  {summary['family_pct']:6.1f}%")
    print(f"  stated dimensions kept   {summary['fidelity_pct']:6.1f}%  "
          f"({stated_ok}/{stated_total})")
    print(f"  phrases it could not map {unresolved}")
    print(f"  values invented as 'stated' {invented}")
    print(f"  attachment dims (out of scope) {attachment_dims}")
    print(f"  guards hold              {summary['guards_pct']:6.1f}%")
    print(f"  overrides applied        "
          f"{'not captured' if overrides is None else overrides}")
    print(f"  tool calls made          "
          f"{'not captured' if tool_calls is None else tool_calls}")
    if agree:
        print(f"  agreement with the corpus part (n={len(agree)} unstated values)")
        print(f"    median relative error  {summary['median_err']:.3f}")
        print(f"    beats the median       {summary['beats_median_pct']:6.1f}%")
        print(f"    ties the median        {summary['ties_median_pct']:6.1f}%")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    from orion.family_schema import DEFAULT_DATA

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out")
    ap.add_argument("--live", action="store_true",
                    help="also run the served base model as a second arm")
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)

    from app.services.planner import EngineeringPlanner, live_completion

    cases = load_cases(args.data, args.n)
    print(f"{len(cases)} design-view cases from {args.data}")

    baseline = EngineeringPlanner()          # no model: medians only
    rows = [score_one(c, baseline) for c in cases]
    summaries = [report(rows, "baseline (corpus medians, no model)")]
    payload = {"baseline": {"summary": summaries[0], "rows": rows}}

    if args.live:
        planner = EngineeringPlanner(live_completion(args.model))
        live_rows = []
        for i, case in enumerate(cases, 1):
            live_rows.append(score_one(case, planner))
            if i % 10 == 0 or i == len(cases):
                print(f"  ...{i}/{len(cases)}", flush=True)
        summaries.append(report(live_rows, "planner (served base model)"))
        payload["live"] = {"summary": summaries[-1], "rows": live_rows}

        base, live = summaries[0], summaries[-1]
        print("\n=== baseline vs planner " + "=" * 30)
        for key, name in (("fidelity_pct", "stated dimensions kept"),
                          ("guards_pct", "guards hold"),
                          ("beats_median_pct", "beats the median")):
            print(f"  {name:26s} {base[key]:6.1f}%  ->  {live[key]:6.1f}%")
        errors = sum(1 for r in live_rows if r["error"])
        print(f"  cases with a planner error {errors}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
