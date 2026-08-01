"""Turn a conflict into a design, or into the reason there cannot be one.

Detecting that a 15 mm shaft cannot carry 80 Nm is worth something, but not
much: the engineer already has to work out what to do about it, and the work is
mechanical. Raise the shaft to what the key needs, re-select the bearing at the
new bore, take the housing from the new outer ring, take the shoulder from the
new abutment, and check that nothing the change touched has broken. All of it
is deterministic, and none of it is a judgement call.

So this is a solver, not an agent. No model is consulted anywhere in it. The
same request produces the same design, and every step of the propagation is
recorded with the constraint that forced it.

**There are three answers and "conflict" is not one of them.** A conflict is a
question the system has not finished answering. Either a valid design exists
and is returned; or several do, ranked, with what separates them stated,
because choosing between a lighter design and a cheaper one is the engineer's
call and not the solver's; or none does, and the answer is which constraint
made it impossible and the smallest change that would not.

**Raising is the only move.** The solver never lowers a requirement to make the
arithmetic work — a design that satisfies a weakened spec is not a solution to
the stated problem, it is a different problem. Floors go up, components are
re-selected against them, and if that runs out of catalogue the answer is
unsatisfiable rather than a quietly relaxed duty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from orion import planner as P

RESOLVED = "resolved"
ALTERNATIVES = "alternatives"
UNSATISFIABLE = "unsatisfiable"

#: What each variable is computed from. Declared rather than inferred, because
#: the propagation order has to be inspectable: when the shaft moves, this is
#: the list of things that are now stale, and an engineer reading the report is
#: entitled to check that nothing was left off it.
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "shaft_dia_mm": ("radial_load_N", "speed_rpm", "life_hours", "torque_Nm"),
    "housing_bore_mm": ("shaft_dia_mm",),
    "shoulder_dia_mm": ("housing_bore_mm",),
    "key_width_mm": ("shaft_dia_mm",),
    "key_height_mm": ("shaft_dia_mm",),
    "key_length_mm": ("shaft_dia_mm", "torque_Nm"),
    "retaining_groove_dia_mm": ("shaft_dia_mm",),
    "seal_bore_mm": ("shaft_dia_mm",),
    "fastener_circle_dia_mm": ("housing_bore_mm",),
}


def dependents(variable: str, seen: Optional[set] = None) -> list[str]:
    """Everything that becomes stale when ``variable`` changes, transitively."""
    seen = seen if seen is not None else set()
    out: list[str] = []
    for name, sources in DEPENDS_ON.items():
        if variable in sources and name not in seen:
            seen.add(name)
            out.append(name)
            out.extend(dependents(name, seen))
    return out


@dataclass
class Revision:
    """One variable raised, and the constraint that forced it."""

    variable: str
    was: Optional[float]
    now: float
    because: str
    invalidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"variable": self.variable, "was": self.was, "now": self.now,
                "because": self.because, "invalidates": self.invalidates}


@dataclass
class Candidate:
    """A design that satisfies every constraint, and what it costs."""

    floors: dict[str, float]
    plan: P.Plan
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        parts = [r.summary for r in self.plan.resolutions if r.resolved]
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {"floors": self.floors, "metrics": self.metrics,
                "summary": self.summary,
                "context": self.plan.context,
                "part_class": next((r.part_class for r in self.plan.resolutions
                                    if r.part_class), "")}


@dataclass
class Resolution:
    """What the solver concluded, and every step it took to get there."""

    request: str
    outcome: str
    revisions: list[Revision] = field(default_factory=list)
    chosen: Optional[Candidate] = None
    alternatives: list[Candidate] = field(default_factory=list)
    explanation: str = ""
    smallest_change: str = ""
    rounds: int = 0
    verification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"request": self.request, "outcome": self.outcome,
                "rounds": self.rounds,
                "revisions": [r.to_dict() for r in self.revisions],
                "chosen": self.chosen.to_dict() if self.chosen else None,
                "alternatives": [a.to_dict() for a in self.alternatives],
                "explanation": self.explanation,
                "smallest_change": self.smallest_change,
                "verification": self.verification}

    def explain(self) -> str:
        lines = [f"REQUEST: {self.request}", "",
                 f"OUTCOME: {self.outcome} in {self.rounds} round"
                 f"{'' if self.rounds == 1 else 's'}", ""]
        if self.revisions:
            lines.append("PROPAGATION")
            for r in self.revisions:
                was = f"{r.was:g}" if r.was is not None else "unset"
                lines.append(f"  {r.variable}: {was} -> {r.now:g}")
                lines.append(f"    because {r.because}")
                if r.invalidates:
                    lines.append(f"    recomputed: {', '.join(r.invalidates)}")
            lines.append("")
        if self.chosen:
            lines.append("RESOLVED DESIGN")
            for r in self.chosen.plan.resolutions:
                mark = "OK  " if r.resolved else "--  "
                lines.append(f"  {mark} {r.function:22s} {r.summary}")
            lines.append("")
            lines.append("  " + "  ".join(
                f"{k}={v:g}" for k, v in sorted(self.chosen.plan.context.items())
                if not k.endswith("__min")))
            if self.chosen.metrics:
                lines.append("  " + "  ".join(
                    f"{k} {v:g}" for k, v in sorted(self.chosen.metrics.items())))
        if self.alternatives:
            lines += ["", f"ALTERNATIVES ({len(self.alternatives)})"]
            for i, alt in enumerate(self.alternatives, 1):
                lines.append(f"  {i}. {alt.summary[:96]}")
                lines.append("     " + ", ".join(
                    f"{k} {v:g}" for k, v in sorted(alt.metrics.items())))
        if self.explanation:
            lines += ["", "EXPLANATION", "  " + self.explanation]
        if self.smallest_change:
            lines += ["", "SMALLEST CHANGE THAT WOULD HELP",
                      "  " + self.smallest_change]
        if self.verification:
            lines += ["", "VERIFICATION"]
            lines += [f"  {k}: {v}" for k, v in self.verification.items()]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
def _floors_from(plan: P.Plan) -> dict[str, float]:
    """The binding lower bound each conflict implies.

    Only the floor side is read. A conflict is always "something fixed X at a,
    something else needs at least b > a", and the resolution is b — never a,
    and never something between them.
    """
    floors: dict[str, float] = {}
    for conflict in plan.conflicts:
        demanded = max(conflict.values.values())
        floors[conflict.dimension] = max(floors.get(conflict.dimension, 0.0),
                                         demanded)
    return floors


def _metrics(plan: P.Plan) -> dict[str, float]:
    """What separates two valid designs.

    Envelope and mass, because those are what an engineer trades. Deliberately
    not a single score: collapsing them would make the choice for the caller,
    and the whole reason alternatives are returned is that it is not ours.
    """
    out: dict[str, float] = {}
    housing = plan.context.get("housing_bore_mm")
    if housing:
        out["housing_bore_mm"] = housing
    shaft = plan.context.get("shaft_dia_mm")
    if shaft:
        out["shaft_dia_mm"] = shaft
    carrier = next((r for r in plan.resolutions if r.variables), None)
    if carrier and carrier.variables.get("R"):
        import math

        v = carrier.variables
        radius, thickness = v["R"], v.get("T", 0.0)
        bore, seat, depth = v.get("rb", 0.0), v.get("rs", 0.0), v.get("ds", 0.0)
        volume = (math.pi * (radius ** 2 - bore ** 2) * (thickness - depth)
                  + math.pi * (radius ** 2 - seat ** 2) * depth)
        out["outside_dia_mm"] = 2 * radius
        out["mass_g"] = round(volume * 7.85e-3, 1)     # steel
    return out


def _verify(plan: P.Plan) -> dict[str, Any]:
    """Check the resolved design the same way any generated Blueprint is.

    The family's own preconditions are the cheap gate and they are the ones
    that catch a propagation that produced numbers the compiler would refuse —
    a seat wider than the body, a floor thinner than nothing. A resolution that
    cannot be built is not a resolution.
    """
    from orion.family_schema import check_guards

    carrier = next((r for r in plan.resolutions if r.variables), None)
    if carrier is None:
        return {"checked": "nothing buildable was resolved"}
    failures = [f"{g['id']}: {g['expr']} = {g['value']:.2f}"
                for g in check_guards(carrier.part_class, carrier.variables)
                if not g["holds"]]
    return {"part_class": carrier.part_class,
            "preconditions": "hold" if not failures else "; ".join(failures),
            "buildable": not failures}


def resolve(request: str, max_rounds: int = 4,
            alternatives: int = 3) -> Resolution:
    """Resolve a request into a design, ranked designs, or an explanation.

    Raises floors and re-plans until the conflicts clear. Bounded, because a
    propagation that does not converge in a few rounds is oscillating rather
    than approaching an answer, and saying so beats spinning.
    """
    plan = P.plan(request)
    result = Resolution(request=request, outcome=RESOLVED, rounds=0)

    floors: dict[str, float] = {}
    for round_ in range(1, max_rounds + 1):
        if not plan.conflicts:
            break
        wanted = _floors_from(plan)
        raised = {k: v for k, v in wanted.items() if v > floors.get(k, 0.0)}
        if not raised:
            # The same conflict survived a raise that should have cleared it.
            return _unsatisfiable(request, plan, floors, result, round_)
        for name, value in raised.items():
            conflict = next(c for c in plan.conflicts if c.dimension == name)
            was = min(conflict.values.values())
            result.revisions.append(Revision(
                variable=name, was=was, now=value,
                because=conflict.detail.split(".")[0],
                invalidates=dependents(name)))
        floors.update(raised)
        result.rounds = round_
        plan = P.plan(request, floors=floors)

    if plan.conflicts:
        return _unsatisfiable(request, plan, floors, result, max_rounds)

    # A resolver that ran and found nothing is a duty no component satisfies,
    # and no amount of raising floors changes that — 90 000 Nm has no key on
    # any shaft in DIN 6885. Reporting the rest of the design as resolved
    # around that hole would be the worst kind of wrong: complete-looking.
    failed = [r for r in plan.unresolved() if r.attempted]
    if failed:
        result.outcome = UNSATISFIABLE
        result.rounds = max(result.rounds, 1)
        result.explanation = (
            "; ".join(f"{r.function}: {r.summary}" for r in failed)
            + ". Raising the other requirements cannot fix this — no "
              "component satisfies the duty at any size.")
        result.smallest_change = next(
            (q for r in failed for q in r.asks), "")
        return result

    chosen = Candidate(floors=dict(floors), plan=plan, metrics=_metrics(plan))
    result.chosen = chosen
    result.verification = _verify(plan)
    result.alternatives = _alternatives(request, floors, plan, alternatives)
    if result.alternatives:
        result.outcome = ALTERNATIVES
        result.explanation = (
            f"{len(result.alternatives) + 1} designs satisfy every stated "
            f"requirement. They differ in envelope and mass, which is a "
            f"trade the engineer owns; the first is the smallest that works.")
    elif not result.revisions:
        result.explanation = "no conflict arose; the first plan was already "\
                             "consistent"
    else:
        result.explanation = (
            f"raising {', '.join(r.variable for r in result.revisions)} "
            f"cleared every conflict, and one design satisfies the result")
    return result


def _alternatives(request: str, floors: dict, best: P.Plan,
                  limit: int) -> list[Candidate]:
    """Other designs that also satisfy everything, ranked by envelope.

    Found by raising the binding floor past the chosen size and re-planning:
    the next bearing up is a real alternative, not a variation, because it
    changes the housing, the shoulder and the mass with it.
    """
    out: list[Candidate] = []
    shaft = best.context.get("shaft_dia_mm")
    if shaft is None:
        return out
    floor = shaft
    for _ in range(limit):
        trial = dict(floors)
        trial["shaft_dia_mm"] = floor + 0.01        # strictly larger
        plan = P.plan(request, floors=trial)
        if plan.conflicts or not any(r.resolved for r in plan.resolutions):
            break
        nxt = plan.context.get("shaft_dia_mm")
        if nxt is None or nxt <= floor:
            break
        out.append(Candidate(floors=trial, plan=plan, metrics=_metrics(plan)))
        floor = nxt
    # Envelope, then the shaft, then mass. Two designs can share a housing
    # bore and differ by 5 mm of shaft — and the smaller shaft is the better
    # design, because the shaft is material and inertia the housing metric
    # never sees.
    out.sort(key=lambda c: (c.metrics.get("outside_dia_mm", 1e9),
                            c.metrics.get("shaft_dia_mm", 1e9),
                            c.metrics.get("mass_g", 1e9)))
    return out


def _unsatisfiable(request: str, plan: P.Plan, floors: dict,
                   result: Resolution, rounds: int) -> Resolution:
    """Name the constraint that blocks, and the smallest change that would not.

    "Unsatisfiable" on its own is as unhelpful as "conflict". What an engineer
    needs is which requirement is doing the excluding, because that is the one
    to take back to whoever set it.
    """
    result.outcome = UNSATISFIABLE
    result.rounds = rounds
    blocking = plan.conflicts[0] if plan.conflicts else None
    unresolved = plan.unresolved()

    if blocking:
        demanded = max(blocking.values.values())
        result.explanation = (
            f"{blocking.dimension} cannot be satisfied: {blocking.detail} "
            f"Raising it to {demanded:g} did not clear the conflict, so the "
            f"requirements are mutually exclusive rather than merely tight.")
        result.smallest_change = (
            f"reduce whichever requirement drives {blocking.dimension} to "
            f"{demanded:g} — on this duty that is the larger of the torque and "
            f"the radial load.")
    elif unresolved:
        asks = [q for r in unresolved for q in r.asks]
        result.explanation = (
            f"{len(unresolved)} function(s) could not be resolved at any size "
            f"the floors reached: "
            + "; ".join(r.function for r in unresolved))
        result.smallest_change = asks[0] if asks else ""
    else:
        result.explanation = "the propagation did not converge within "\
                             f"{rounds} rounds"
    return result
