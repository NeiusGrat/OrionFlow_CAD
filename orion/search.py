"""Choosing among the moves the environment allows.

:mod:`orion.design_space` says what a part may become and refuses to have an
opinion about which of those is better. This is the opinion, and it is the
smallest one that answers the question a user actually asks: *make it lighter,
and show me more than one way.*

**Deterministic, and no dependency.** No random sampling, no population, no
learned policy, no external optimizer. The same request produces the same
alternatives, byte for byte, which matters more here than sophistication: an
engineer who reruns a design and gets different numbers has no reason to trust
either run. Every ordering below is total — ties break on the parameter vector
— so nothing depends on dictionary iteration order or on floating-point noise
deciding a sort.

**It is a local search and says so.** Moves are single-parameter, because that
is the only transition the environment offers, and a multi-parameter change
happens only as a sequence of them. That makes this a beam search over a
neighbourhood, not a global optimizer: it will find a lighter bracket, and it
will not find the *lightest* one, and no part of the output should be read as
claiming otherwise. When a real optimizer is wanted, it replaces
:func:`explore` and leaves everything else — the environment, the evidence
tiers, the selection — standing.

**What ranking means here.** The objective is a closed-form quantity: mass from
the volume expression the Blueprint grades itself against, times a table
density. Nothing is measured and nothing is built, so a candidate that comes
back is ``screened`` rather than verified. The build still decides, and the
report a user sees must say which of the two it is looking at.

**Alternatives are different designs, not one design nudged.** A ranked list
alone returns near-duplicates: the same bracket at 6.0, 6.1 and 6.2 mm. So
candidates are grouped by *which parameters they changed*, the best of each
group is taken, and the groups are ranked. Two alternatives in the result
always differ in what was done to them, not only in how much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import design_space as DS

MINIMIZE = "minimize"
MAXIMIZE = "maximize"


@dataclass(frozen=True)
class Objective:
    """What "better" means. One metric, one direction, named explicitly.

    ``mass_g`` is the default because it is the one quantity every family can
    now produce — it needs a material and the closed-form volume, not a duty —
    and because "lighter" is what people ask for. Any key an
    :class:`~orion.design_space.Observation` puts in ``metrics`` works, so
    ``deflection_mm`` or ``safety_factor`` are equally available to a caller
    that wants them.
    """

    metric: str = "mass_g"
    direction: str = MINIMIZE

    def better(self, a: float, b: float) -> bool:
        return a < b if self.direction == MINIMIZE else a > b

    def key(self, value: float) -> float:
        """Sortable ascending, whichever direction is wanted."""
        return value if self.direction == MINIMIZE else -value


@dataclass(frozen=True)
class Candidate:
    """One evaluated design, and how it was reached."""

    params: dict
    evidence: str
    metrics: dict
    #: The moves from the starting state, in order. A candidate's whole
    #: provenance: an engineer reading the result can see it was "upright
    #: thickness 8 to 6, base thickness 8 to 5" rather than a set of numbers
    #: that arrived from nowhere.
    path: tuple
    requirements: dict = field(default_factory=dict, repr=False)

    @property
    def feasible(self) -> bool:
        return self.evidence in (DS.SCREENED, DS.NO_DUTY)

    def value(self, objective: Objective) -> Optional[float]:
        v = self.metrics.get(objective.metric)
        return float(v) if isinstance(v, (int, float)) else None

    def changed(self, start: "Candidate") -> frozenset:
        """Which parameters differ from where the search began.

        The descriptor alternatives are grouped by. Two designs that moved the
        same dimensions are variations on one idea however far apart their
        numbers are; two that moved different ones are different ideas.
        """
        return frozenset(
            name for name, value in self.params.items()
            if not _same(value, start.params.get(name))
        )


@dataclass
class Result:
    """Everything one search produced, including what it cost."""

    start: Candidate
    objective: Objective
    #: Every distinct design evaluated, feasible or not, in the order found.
    considered: list[Candidate] = field(default_factory=list)
    #: The k chosen for a user to look at — see :func:`select`.
    alternatives: list[Candidate] = field(default_factory=list)
    #: Evaluations actually run, against those served from cache. Reported
    #: because the honest way to describe a search is by what it looked at.
    evaluated: int = 0
    cached: int = 0
    notes: list[str] = field(default_factory=list)
    #: Searchable parameters no declared check responds to. A search will drive
    #: every one of them to a bound, and nothing in the evidence objects — so
    #: they are named here and repeated in :func:`explain`. See
    #: :func:`unconstrained`.
    unconstrained: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> list[Candidate]:
        return [c for c in self.considered if c.feasible]

    @property
    def improved(self) -> bool:
        """Whether anything beat the starting point on the objective."""
        best = self.best
        start = self.start.value(self.objective)
        if best is None or start is None:
            return False
        value = best.value(self.objective)
        return value is not None and self.objective.better(value, start)

    @property
    def best(self) -> Optional[Candidate]:
        ranked = _ranked(self.feasible, self.objective)
        return ranked[0] if ranked else None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9
    return a == b


def _fingerprint(params: dict) -> tuple:
    """A parameter vector as a hashable key.

    Rebuilds are deterministic, so identical parameters produce identical
    geometry and this is an *exact* cache key rather than an approximate one —
    the same property that makes the Blueprint hash a cache key downstream.
    Rounded well below any dimension anybody designs to, so 6.0 and
    6.0000000001 are one design rather than two.
    """
    return tuple(sorted(
        (name, round(float(value), 6) if isinstance(value, (int, float))
         and not isinstance(value, bool) else value)
        for name, value in params.items()
    ))


def _ranked(candidates: list, objective: Objective) -> list:
    """Best first, with a total order.

    The fingerprint tie-break is not decoration. Two designs of identical mass
    are common — a search moves one dimension up and another down — and leaving
    their order to chance would make the whole result unreproducible.
    """
    scored = [(c, c.value(objective)) for c in candidates]
    scored = [(c, v) for c, v in scored if v is not None]
    scored.sort(key=lambda cv: (objective.key(cv[1]),
                                _fingerprint(cv[0].params)))
    return [c for c, _ in scored]


def explore(state: DS.State, objective: Optional[Objective] = None,
            depth: int = 2, steps: int = 4, beam: int = 4,
            budget: int = 600) -> Result:
    """Search the neighbourhood of a design, breadth first, deterministically.

    From the starting state, every legal single-parameter move is enumerated
    and evaluated. The best ``beam`` feasible results are expanded again, up to
    ``depth`` rounds. ``steps`` is how finely each parameter's interval is
    sampled; ``budget`` caps evaluations so a wide space cannot run away.

    The space is computed once per state and handed to
    :func:`~orion.design_space.step`, because probing the builder is most of
    what a move costs and every move from one state shares the same answer.

    Infeasible candidates are kept in ``considered`` rather than discarded. A
    search that reports only what worked cannot explain why the alternatives
    look the way they do, and "every lighter version failed its duty" is the
    most useful thing this can tell someone.
    """
    objective = objective or Objective()

    seen: dict[tuple, Candidate] = {}
    result = Result(start=_candidate(state, ()), objective=objective)
    seen[_fingerprint(state.params)] = result.start
    result.considered.append(result.start)
    # Found once, before anything moves: it is a property of the declared duty
    # and the starting geometry, not of any candidate.
    result.unconstrained = unconstrained(state)

    if result.start.value(objective) is None:
        result.notes.append(
            f"the starting design has no {objective.metric}, so nothing can be "
            f"ranked against it"
            + ("; a material is what a mass needs"
               if objective.metric == "mass_g" else ""))
        return result

    frontier = [(state, result.start)]
    for round_no in range(max(0, depth)):
        expanded: list[tuple] = []
        for current, parent in frontier:
            intervals = DS.space(current.family, current.params,
                                 current.requirements, current.unlocked)
            for action in DS.actions(current, steps=steps):
                if result.evaluated >= budget:
                    result.notes.append(
                        f"stopped at the {budget}-evaluation budget during "
                        f"round {round_no + 1}")
                    result.alternatives = select(result, k=3)
                    return result

                obs = DS.step(current, action, intervals=intervals)
                if not obs.applied:
                    continue
                key = _fingerprint(obs.state.params)
                if key in seen:
                    result.cached += 1
                    continue
                result.evaluated += 1

                candidate = _candidate(obs.state, parent.path + (action,), obs)
                seen[key] = candidate
                result.considered.append(candidate)
                if candidate.feasible:
                    expanded.append((obs.state, candidate))

        if not expanded:
            break
        # Deterministic: best first, ties broken on the parameter vector.
        ranked = _ranked([c for _, c in expanded], objective)
        keep = {id(c) for c in ranked[:max(1, beam)]}
        frontier = [(s, c) for s, c in expanded if id(c) in keep]

    result.alternatives = select(result, k=3)
    return result


def unconstrained(state: DS.State) -> list[str]:
    """Searchable parameters that no declared check responds to.

    The first thing this search did, given a bracket carrying 400 N, was thin
    the base plate to 1 mm. That is not a bug in the search: the declared duty
    is a beam check on the *upright*, so nothing in the evidence reads the base
    thickness at all, and a parameter nothing reads is free mass. A real 1 mm
    base would fail through bending and bolt pull-out, and no closed form here
    describes either.

    So it is found and reported rather than quietly exploited. Whichever way a
    search is later implemented, this is the property that has to survive: an
    optimizer will always drive an unconstrained parameter to its bound, and
    the only defence is to know which parameters those are and say so.

    Found by perturbation rather than by reading the check's expressions: it
    asks whether any declared result actually moves, which is the real question
    and cannot be fooled by a variable that appears in an expression without
    affecting it.
    """
    baseline = DS.evaluate(state)
    if not baseline.checks:
        return []                       # nothing is constrained by nothing

    def results(obs: DS.Observation) -> dict:
        return {row.get("id"): dict(row.get("result") or {})
                for row in obs.checks}

    before = results(baseline)
    intervals = DS.space(state.family, state.params, state.requirements,
                         state.unlocked)
    loose: list[str] = []

    for name, interval in sorted(intervals.items()):
        if interval.locked or interval.empty:
            continue
        current = state.params.get(name)
        if not isinstance(current, (int, float)):
            continue
        probe = _nudge(float(current), interval)
        if probe is None:
            continue
        moved = DS.step(state, DS.Action(name, probe), intervals=intervals)
        if not moved.applied:
            continue
        if results(moved) == before:
            loose.append(name)
    return loose


def _nudge(current: float, interval: DS.Interval) -> Optional[float]:
    """A value near ``current`` that the interval allows, or None.

    Ten percent, then one percent, then the interval's own ends: enough to move
    any check that reads the parameter at all, and small enough that it stays
    inside a narrow interval when there is one.
    """
    for factor in (1.10, 0.90, 1.01, 0.99):
        value = round(current * factor, 6)
        if value != current and interval.holds(value):
            return value
    for end in (interval.high, interval.low):
        if end is not None and interval.holds(end) and end != current:
            return end
    return None


def _candidate(state: DS.State, path: tuple,
               obs: Optional[DS.Observation] = None) -> Candidate:
    if obs is None:
        obs = DS.evaluate(state)
    return Candidate(params=dict(state.params), evidence=obs.evidence,
                     metrics=dict(obs.metrics), path=path,
                     requirements=dict(state.requirements))


def select(result: Result, k: int = 3) -> list[Candidate]:
    """``k`` feasible designs that differ in what was done to them.

    Ranking alone returns the same design three times at slightly different
    dimensions, which is not a choice. Candidates are grouped by which
    parameters they changed — the closest thing this environment has to the
    report's "descriptors an engineer would recognise" — the best of each group
    is taken, and the groups are ranked against each other.

    The starting design is never an alternative to itself. If fewer than ``k``
    groups exist, that is what is returned: three near-identical brackets
    presented as three options would be a worse answer than one.
    """
    groups: dict[frozenset, list[Candidate]] = {}
    for candidate in result.feasible:
        if not candidate.path:
            continue                      # the starting design
        groups.setdefault(candidate.changed(result.start), []).append(candidate)

    best_of_each = [
        _ranked(members, result.objective)[0]
        for _, members in sorted(groups.items(), key=lambda kv: sorted(kv[0]))
        if _ranked(members, result.objective)
    ]
    return _ranked(best_of_each, result.objective)[:max(0, k)]


def explain(result: Result) -> list[str]:
    """The search, in sentences. What was looked at, what won, and why.

    Every number here came from an evaluation in ``considered``; nothing is
    restated from memory and nothing is rounded into a claim. The wording says
    ``screened`` rather than verified on purpose — see the module docstring.
    """
    objective = result.objective
    lines: list[str] = []
    start = result.start.value(objective)

    lines.append(
        f"Searched {len(result.considered)} designs "
        f"({result.evaluated} evaluated, {result.cached} already seen); "
        f"{len(result.feasible)} were feasible.")

    if start is not None:
        lines.append(f"Started at {objective.metric} = {start:.4g}.")

    best = result.best
    if best is None:
        lines.append("Nothing feasible was found, so the starting design "
                     "stands.")
    elif not result.improved:
        lines.append("Nothing beat the starting design on "
                     f"{objective.metric}.")
    else:
        value = best.value(objective)
        delta = 100.0 * (value - start) / start if start else 0.0
        lines.append(
            f"Best is {objective.metric} = {value:.4g} ({delta:+.1f}%), "
            f"reached by {_path_words(best.path)}.")

    blocked = [c for c in result.considered if c.evidence == DS.FAILED]
    if blocked:
        lines.append(f"{len(blocked)} designs were lighter or equal but failed "
                     f"their declared duty.")
    unjudged = [c for c in result.considered if c.evidence == DS.UNJUDGED]
    if unjudged:
        lines.append(
            f"{len(unjudged)} could not be judged: a load was stated and this "
            f"family has no closed form for it.")

    if result.unconstrained:
        names = ", ".join(result.unconstrained)
        lines.append(
            f"No declared check reads {names}, so nothing here objects to any "
            f"value the search chose for {'them' if len(result.unconstrained) > 1 else 'it'}. "
            f"Treat {'those dimensions' if len(result.unconstrained) > 1 else 'that dimension'} "
            f"as unverified.")

    for i, alt in enumerate(result.alternatives, start=1):
        value = alt.value(objective)
        lines.append(
            f"Alternative {i}: {objective.metric} = {value:.4g}, "
            f"{_path_words(alt.path)}.")

    lines.append("All of these are screened on closed-form arithmetic, not "
                 "built. The build decides.")
    return lines


def _path_words(path: tuple) -> str:
    if not path:
        return "no change"
    return ", ".join(
        f"{a.parameter} {'' if a.frm is None else f'{a.frm:g} to '}{a.to:g}"
        for a in path
    )
