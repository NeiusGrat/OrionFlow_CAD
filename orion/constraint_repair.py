"""Make a variable set satisfy its family's guards, without asking a model.

Measured over 50 asks, every single thing the LLM planner did was this: nudge a
variable until an inequality came back positive. Four overrides, all of them
constraint repairs, no calculations and no lookups. That is a solver's job. The
guards are already closed-form expressions over named variables, evaluated by
:mod:`orion.expr`, so satisfying them is a search over a handful of scalars —
not a reasoning task.

Doing it here rather than there is better on every axis that matters: it is
exact, it is instant instead of twenty seconds, it needs no endpoint, and it
finds a solution whenever one exists in range. The model left three of seven
violations unfixed; this does not get tired.

The rules it works under come from what the specification means:

* **A pinned variable never moves.** Those are the numbers the user gave. A
  repairer that "fixes" a part by quietly changing a stated dimension has
  produced something that builds and is not what was asked for — the worst
  failure this system can have.
* **Stay in the verified region.** Each variable's observed range comes from
  parts that built and matched their own predictions. Search there first, and
  only widen if there is no solution inside, saying so when that happens.
* **Prefer the smallest change.** The defaults are medians of working parts;
  moving one further than necessary trades a known-good value for an arbitrary
  one.
"""

from __future__ import annotations

from typing import Iterable, Optional

from . import expr as E
from .family_schema import check_guards, for_family

#: How finely to scan a variable's range. The guards are smooth and low-degree,
#: so a few hundred samples locates a satisfying value far more robustly than
#: bisection would on the non-monotonic ones (``2*bc_r*sin(pi/hole_n)`` is not
#: monotonic in ``hole_n``).
_SAMPLES = 240

#: How far outside the observed range to look when nothing inside works. Beyond
#: this the value has left the region any evidence covers, and reporting failure
#: is more useful than returning a number nobody has verified.
_WIDEN = 2.0


def _candidates(lo: float, hi: float, integral: bool,
                current: float) -> list[float]:
    """Values to try, nearest the current one first."""
    if hi <= lo:
        return []
    if integral:
        values = [float(v) for v in range(int(round(lo)), int(round(hi)) + 1)]
    else:
        step = (hi - lo) / _SAMPLES
        values = [lo + i * step for i in range(_SAMPLES + 1)]
    return sorted(values, key=lambda v: abs(v - current))


def repair(part_class: str, variables: dict, pinned: Iterable[str] = (),
           max_passes: int = 4) -> dict:
    """Move free variables until every guard holds.

    Returns ``{"variables", "changes", "guards", "ok", "widened"}``. ``changes``
    lists ``{variable, from, to, guard}`` so the result can be explained rather
    than merely used.
    """
    schema = for_family(part_class)
    result = {"variables": dict(variables), "changes": [], "ok": True,
              "guards": [], "widened": False, "why": ""}
    if schema is None:
        result["why"] = f"no schema for {part_class!r}"
        result["ok"] = False
        return result

    fixed = set(pinned)
    working = dict(variables)

    for _pass in range(max_passes):
        guards = check_guards(part_class, working)
        broken = [g for g in guards if not g["holds"]]
        if not broken:
            break

        progressed = False
        for guard in broken:
            try:
                referenced = E.names(guard["expr"])
            except E.ExprError:
                continue
            movable = [n for n in sorted(referenced)
                       if n not in fixed and n in working
                       and n in schema.variables]
            if not movable:
                continue

            for name in movable:
                stat = schema.variables[name]
                current = float(working[name])
                spans = [(stat.lo, stat.hi)]
                span = max(stat.hi - stat.lo, abs(current) or 1.0)
                spans.append((stat.lo - _WIDEN * span, stat.hi + _WIDEN * span))

                chosen: Optional[float] = None
                widened = False
                for index, (lo, hi) in enumerate(spans):
                    for value in _candidates(lo, hi, stat.integral, current):
                        if value == current:
                            continue
                        if stat.integral and value < 1 and "count" in stat.role:
                            continue
                        trial = {**working, name: value}
                        rows = check_guards(part_class, trial)
                        if all(r["holds"] for r in rows):
                            chosen, widened = value, index > 0
                            break
                    if chosen is not None:
                        break

                if chosen is not None:
                    result["changes"].append({
                        "variable": name, "from": current, "to": chosen,
                        "guard": guard["id"],
                        "why": (f"{guard['id']} required "
                                f"{guard['expr']} > 0; it was "
                                f"{guard['value']:.3f} at {name}={current:g}"),
                        "outside_observed_range": widened,
                    })
                    result["widened"] = result["widened"] or widened
                    working[name] = chosen
                    progressed = True
                    break

        if not progressed:
            break

    guards = check_guards(part_class, working)
    result["variables"] = working
    result["guards"] = guards
    result["ok"] = all(g["holds"] for g in guards)
    if not result["ok"]:
        stuck = [g["id"] for g in guards if not g["holds"]]
        result["why"] = (
            "no value inside or near the verified range satisfies "
            + ", ".join(stuck)
            + (" while holding the stated dimensions fixed" if fixed else ""))
    return result
