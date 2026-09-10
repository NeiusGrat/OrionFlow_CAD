"""What a part is allowed to become: bounds, relations, and the moves between.

The system can build a part, grade its duty and refuse it. What it cannot do is
answer the question that comes next — *given this objective and these
constraints, what am I allowed to change?* Every number in a Blueprint is
currently either stated or derived, and nothing anywhere says which of them a
search could move, how far, or what breaks first.

This module is that statement, and deliberately nothing more. There is no
optimizer here, no policy, no scoring of one candidate against another. It is
the environment a policy will later act in: it says what the legal moves are,
applies one, and reports what happened. Choosing among them is somebody else's
job and is not implemented.

**Bounds carry their source, because the four kinds are not interchangeable.**

``STATED``   the user fixed it. Not a bound, a decision — a search must not
             move it at all, whatever the other three permit.
``BUILDER``  a guard :mod:`orion.blueprint_gen` itself raises on. Violating one
             is a hard failure with a message, so these are the relations that
             are genuinely *enforced* rather than advisory.
``PROCESS``  a manufacturing limit, read from :mod:`orion.dfm` so there is one
             definition of the smallest end mill in the codebase.
``FAMILY``   the range this family is a sensible design within. The softest of
             the four and the only one that is a judgement; it is here so a
             search cannot wander to a 4 metre bracket, not because 401 mm is
             physically impossible.

The distinction matters most when a candidate is refused. "Your upright is
thicker than the base is long" is the builder telling you the part cannot
exist; "that is outside the family's range" is this file's opinion. Reporting
both as the same kind of failure would teach a policy to treat them alike.

**Feasibility here is necessary, not sufficient.** Everything below is closed
form: the relations are arithmetic over the parameters, the volume is the
expression the Blueprint already carries for its own assertions, and the
engineering check is :mod:`orion.calc` run on the frozen variables. No kernel
runs, nothing is measured, and a candidate that passes has only proved that it
is worth building — not that it built. The verdict still belongs to the build.
That is the correct division: this is cheap enough to call thousands of times,
and it screens rather than decides.

Only ``l_bracket`` is described so far. A family with no entry has no declared
space, which reads as "nothing is known to be safe to move" rather than
"anything goes" — the same direction of silence as the rest of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import expr as E

# --------------------------------------------------------------------------- #
# Where a bound comes from
# --------------------------------------------------------------------------- #

STATED = "stated"
BUILDER = "builder"
PROCESS = "process"
FAMILY = "family"
DEFAULT = "default"

#: Sources whose violation means the part cannot be built, as opposed to should
#: not be. Only the builder's own guards qualify: it raises on them.
HARD = frozenset({BUILDER})


@dataclass(frozen=True)
class Bound:
    """An interval one parameter may take, and who says so.

    Strictness is carried rather than approximated. The builder's guards are a
    mix — ``UT < BL`` is strict, ``UW <= BW`` is not — and reporting both as
    closed would put a value in the space that the builder then refuses. An
    epsilon would hide the same error behind a number nobody chose; a search
    told the truth about its own boundary can use it.
    """

    name: str
    low: Optional[float]
    high: Optional[float]
    source: str
    basis: str
    strict_low: bool = False
    strict_high: bool = False

    def holds(self, value: float) -> bool:
        if self.low is not None:
            if value < self.low or (self.strict_low and value == self.low):
                return False
        if self.high is not None:
            if value > self.high or (self.strict_high and value == self.high):
                return False
        return True


@dataclass(frozen=True)
class Relation:
    """A predicate over the whole parameter set.

    ``test`` is a callable rather than a string because several of these are
    conditional — the fillet relations only apply when there is a fillet — and
    encoding that in an expression language would mean inventing one. ``expr``
    is the human-readable form and is what gets reported.
    """

    id: str
    expr: str
    source: str
    basis: str
    test: Callable[[dict], bool]

    @property
    def enforced(self) -> bool:
        """Whether the builder itself refuses a part that violates this."""
        return self.source in HARD


@dataclass(frozen=True)
class Violation:
    id: str
    detail: str
    source: str

    @property
    def hard(self) -> bool:
        return self.source in HARD


@dataclass(frozen=True)
class Interval:
    """What one parameter may currently move to, everything else held fixed."""

    name: str
    low: Optional[float]
    high: Optional[float]
    #: Which bound produced each end, so a caller can say what is binding.
    low_from: str = ""
    high_from: str = ""
    #: Whether the end itself is excluded — see :class:`Bound`.
    strict_low: bool = False
    strict_high: bool = False
    #: A parameter the user stated is not searchable at any width.
    locked: bool = False
    lock_reason: str = ""

    @property
    def empty(self) -> bool:
        if self.low is None or self.high is None:
            return False
        if self.low > self.high:
            return True
        # A single point that either end excludes is no interval at all.
        return self.low == self.high and (self.strict_low or self.strict_high)

    def holds(self, value: float) -> bool:
        if self.locked or self.empty:
            return False
        if self.low is not None:
            if value < self.low or (self.strict_low and value == self.low):
                return False
        if self.high is not None:
            if value > self.high or (self.strict_high and value == self.high):
                return False
        return True

    def __str__(self) -> str:
        lo = "unbounded" if self.low is None else f"{self.low:g}"
        hi = "unbounded" if self.high is None else f"{self.high:g}"
        return (("(" if self.strict_low else "[") + lo + ", " + hi
                + (")" if self.strict_high else "]"))


# --------------------------------------------------------------------------- #
# l_bracket
# --------------------------------------------------------------------------- #

#: The parameters worth searching, in the builder's own variable names.
#:
#: These are the ones that change how the part carries a load. Everything else
#: the family accepts — hole diameters, bolt squares, counterbores, slots,
#: pilot bores — is deliberately absent, and the omission is the safety
#: property rather than an unfinished list. A hole is an *interface*: its size
#: is set by the fastener that goes through it and the mating part on the other
#: side, neither of which is visible here, so moving one to save mass would
#: silently redesign a joint the request already fixed. See
#: :data:`UNSAFE_TO_SEARCH`.
SEARCHABLE: dict[str, tuple[str, ...]] = {
    "l_bracket": ("BT", "UT", "UH", "UW", "BL", "BW", "in_r"),
}

#: Requirement names, for the parameters that have one. A user who stated a
#: dimension has made a decision, and a search may not overturn it.
_REQUIREMENT_OF = {
    "BL": "base_length",
    "BW": "base_width",
    "BT": "base_thickness",
    "UH": "upright_height",
    "UT": "upright_thickness",
    "UW": "upright_width",
    "in_r": "inside_fillet",
}

#: Family design ranges. The softest bounds here and the only invented ones:
#: they exist so a search cannot wander somewhere absurd, not because the
#: boundary is physical. Stated as a judgement so it can be argued with.
_FAMILY_BOUNDS: dict[str, tuple[float, float]] = {
    "BL": (20.0, 400.0),
    "BW": (20.0, 400.0),
    "BT": (1.0, 40.0),
    "UH": (10.0, 400.0),
    "UT": (1.0, 40.0),
    "UW": (10.0, 400.0),
    "in_r": (0.0, 40.0),
}


def _min_wall(process: Optional[str]) -> Optional[float]:
    """The thinnest wall a process holds, from :mod:`orion.dfm`.

    Read rather than restated: one definition of a minimum wall in the
    codebase, so a change to the DFM table moves the search space with it.
    """
    from . import dfm

    if not process:
        return None
    return dfm._MIN_WALL.get(str(process).strip().lower().replace(" ", "_"))


def _tool_radius() -> float:
    """Half the smallest common end mill. An internal radius below this cannot
    be cut by a tool that fits it — the same constant ``orion.dfm`` reasons
    about pocket corners with."""
    from . import dfm

    return dfm._SMALLEST_END_MILL_D / 2.0


# Every relation below is one the builder raises on, transcribed from
# ``blueprint_gen.l_bracket``. Nothing here is an engineering rule this system
# cannot check: a relation that only a solver could confirm would be a claim
# the environment is not entitled to make.
def _relations_l_bracket() -> list[Relation]:
    def pos(name: str) -> Callable[[dict], bool]:
        return lambda p, n=name: float(p.get(n, 0.0)) > 0.0

    rels = [
        Relation(f"positive:{n}", f"{n} > 0", BUILDER,
                 "blueprint_gen._assert_positive refuses a non-positive "
                 "dimension", pos(n))
        for n in ("BL", "BW", "BT", "UH", "UT")
    ]
    rels += [
        Relation(
            "upright_fits_base", "UT < BL", BUILDER,
            "an upright thicker than the base is long has no base left to "
            "stand on; blueprint_gen raises 'upright thickness exceeds the "
            "base length'",
            lambda p: float(p["UT"]) < float(p["BL"])),
        Relation(
            "upright_clears_base", "UH > BT", BUILDER,
            "the upright is measured from the ground, so it must rise above "
            "the base it sits on; blueprint_gen raises 'upright height must "
            "exceed the base thickness'",
            lambda p: float(p["UH"]) > float(p["BT"])),
        Relation(
            "upright_within_base", "UW <= BW", BUILDER,
            "an upright wider than the base overhangs into nothing; "
            "blueprint_gen raises 'the upright is W wide and the base only B'",
            lambda p: float(p.get("UW", p["BW"])) <= float(p["BW"])),
        Relation(
            "fillet_fits_upright", "in_r < UH - BT", BUILDER,
            "a fillet taller than the exposed upright has no corner left to "
            "round; blueprint_gen raises 'inside fillet is taller than the "
            "upright above the base'",
            lambda p: (not p.get("in_r")
                       or float(p["in_r"]) < float(p["UH"]) - float(p["BT"]))),
        Relation(
            "fillet_fits_base", "in_r < BL - UT", BUILDER,
            "a fillet longer than the base in front of the upright runs off "
            "the end; blueprint_gen raises 'inside fillet is longer than the "
            "base in front of the upright'",
            lambda p: (not p.get("in_r")
                       or float(p["in_r"]) < float(p["BL"]) - float(p["UT"]))),
    ]
    return rels


_RELATIONS: dict[str, Callable[[], list[Relation]]] = {
    "l_bracket": _relations_l_bracket,
}


def relations(family: str) -> list[Relation]:
    """Every relation declared for a family. Empty when none is."""
    build = _RELATIONS.get(family)
    return build() if build else []


def bounds(family: str, params: dict,
           requirements: Optional[dict] = None) -> list[Bound]:
    """Every bound in force, each carrying where it came from.

    Both the fixed kind (a family range, a process minimum) and the kind that
    depends on the current state — ``UT < BL`` is a bound on ``UT`` only once
    ``BL`` has a value.
    """
    if family not in SEARCHABLE:
        return []

    req = requirements or {}
    out: list[Bound] = []

    for name, (low, high) in _FAMILY_BOUNDS.items():
        out.append(Bound(name, low, high, FAMILY,
                         f"the range an {family.replace('_', ' ')} is a "
                         f"sensible design within"))

    wall = _min_wall(req.get("process"))
    if wall is not None:
        for name in ("BT", "UT"):
            out.append(Bound(name, wall, None, PROCESS,
                             f"{req.get('process')} holds a wall of "
                             f"{wall:g} mm (orion.dfm)"))
    if req.get("process") == "machined":
        r = _tool_radius()
        out.append(Bound("in_r", r, None, PROCESS,
                         f"an internal radius below {r:g} mm cannot be cut by "
                         f"the smallest common end mill (orion.dfm)"))

    # State-dependent bounds, transcribed from the same guards as the relations
    # so the two cannot disagree.
    def _f(name: str) -> Optional[float]:
        v = params.get(name)
        return float(v) if isinstance(v, (int, float)) else None

    BL, BW, BT, UH, UT = (_f("BL"), _f("BW"), _f("BT"), _f("UH"), _f("UT"))
    if BL is not None:
        out.append(Bound("UT", None, BL, BUILDER, "UT < BL", strict_high=True))
    if UT is not None:
        out.append(Bound("BL", UT, None, BUILDER, "UT < BL", strict_low=True))
    if BT is not None:
        out.append(Bound("UH", BT, None, BUILDER, "UH > BT", strict_low=True))
    if UH is not None:
        out.append(Bound("BT", None, UH, BUILDER, "UH > BT", strict_high=True))
    if BW is not None:
        # The one non-strict guard: an upright exactly as wide as the base is
        # the common case, not an edge case.
        out.append(Bound("UW", None, BW, BUILDER, "UW <= BW"))
    if _f("UW") is not None and req.get("upright_width"):
        # Only when the upright's width was actually asked for. Left unstated
        # it follows the base — ``UW = upright_width or BW`` — so narrowing the
        # base narrows the upright with it and no bound applies. Adding one
        # anyway would forbid a move that rebuilds perfectly well.
        out.append(Bound("BW", _f("UW"), None, BUILDER, "UW <= BW"))
    # Each fillet guard constrains all three of its terms, and every direction
    # has to be projected. Writing only the bound on ``in_r`` left an interval
    # for ``UT`` whose upper values broke ``in_r < BL - UT`` — legal against
    # the bound that mentions UT, refused by the one that does not.
    in_r = _f("in_r")
    if UH is not None and BT is not None:
        out.append(Bound("in_r", None, UH - BT, BUILDER, "in_r < UH - BT",
                         strict_high=True))
    if in_r:
        if BT is not None:
            out.append(Bound("UH", BT + in_r, None, BUILDER,
                             "in_r < UH - BT", strict_low=True))
        if UH is not None:
            out.append(Bound("BT", None, UH - in_r, BUILDER,
                             "in_r < UH - BT", strict_high=True))
    if BL is not None and UT is not None:
        out.append(Bound("in_r", None, BL - UT, BUILDER, "in_r < BL - UT",
                         strict_high=True))
    if in_r:
        if UT is not None:
            out.append(Bound("BL", UT + in_r, None, BUILDER,
                             "in_r < BL - UT", strict_low=True))
        if BL is not None:
            out.append(Bound("UT", None, BL - in_r, BUILDER,
                             "in_r < BL - UT", strict_high=True))

    return out


def violations(family: str, params: dict) -> list[Violation]:
    """Every declared relation this parameter set breaks.

    A relation that cannot be evaluated — a missing parameter — is reported as
    a violation rather than skipped. A predicate nobody could test is not a
    predicate that passed.
    """
    out: list[Violation] = []
    for rel in relations(family):
        try:
            ok = bool(rel.test(params))
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            out.append(Violation(rel.id, f"{rel.expr} does not hold: {rel.basis}",
                                 rel.source))
    return out


def feasible(family: str, params: dict) -> bool:
    """Whether every declared relation holds. Bounds are checked separately —
    a value outside the family's range is a judgement, not an impossibility."""
    return not violations(family, params)


def space(family: str, params: dict,
          requirements: Optional[dict] = None,
          unlocked: Optional[frozenset] = None) -> dict[str, Interval]:
    """**The question this module exists to answer.**

    For each searchable parameter, the interval it may move to with every other
    parameter held where it is — the intersection of every bound in force, with
    the tightest end of each attributed to whichever bound produced it.

    A parameter the user stated comes back ``locked``. That is not a narrow
    interval, it is a different fact: the width of the range says nothing about
    whether a search is entitled to move it.

    ``unlocked`` names parameters a stated value may be moved anyway, and it
    exists because the alternative is a dead end. A fully dimensioned request
    locks every parameter, so "make this 20% lighter" would have nothing to act
    on — the user has asked for a change and every change is forbidden. Naming
    them is deliberate and it is recorded on the interval, so a candidate that
    moved a dimension somebody typed can always be told from one that filled in
    a blank. Nothing here decides to unlock anything; the caller does.

    One parameter at a time is a real limitation and is stated rather than
    hidden. ``UT`` may not exceed ``BL``, so raising both together is legal
    while raising ``UT`` alone is not, and this reports only the second. A
    caller that wants a joint move applies the actions in sequence and checks
    :func:`feasible` at the end.
    """
    if family not in SEARCHABLE:
        return {}

    req = requirements or {}
    freed = unlocked or frozenset()
    all_bounds = bounds(family, params, req)
    stated = {
        name for name, slot in _REQUIREMENT_OF.items()
        if _is_stated(req, slot) and name not in freed
    }

    out: dict[str, Interval] = {}
    for name in SEARCHABLE[family]:
        low: Optional[float] = None
        high: Optional[float] = None
        low_from = high_from = ""
        strict_low = strict_high = False
        for b in all_bounds:
            if b.name != name:
                continue
            # Tightest end wins; at a tie the strict one does, because an end
            # excluded by any bound in force is excluded.
            if b.low is not None and (
                    low is None or b.low > low
                    or (b.low == low and b.strict_low and not strict_low)):
                low, low_from = b.low, f"{b.source}: {b.basis}"
                strict_low = b.strict_low or (b.low == low and strict_low)
            if b.high is not None and (
                    high is None or b.high < high
                    or (b.high == high and b.strict_high and not strict_high)):
                high, high_from = b.high, f"{b.source}: {b.basis}"
                strict_high = b.strict_high or (b.high == high and strict_high)
        out[name] = Interval(
            name=name, low=low, high=high,
            low_from=low_from, high_from=high_from,
            strict_low=strict_low, strict_high=strict_high,
            locked=name in stated,
            lock_reason=(f"the request states {_REQUIREMENT_OF[name]}"
                         if name in stated else ""),
        )
    return out


def _is_stated(requirements: dict, slot: str) -> bool:
    """Whether the user fixed this slot, per the provenance ledger.

    Reads the ledger rather than the presence of a value, because every value
    is present by the time a Blueprint exists — the ledger is the only record
    of which ones a person chose.
    """
    entry = ((requirements.get("provenance") or {}).get(slot) or {})
    return entry.get("source") == "stated"


# --------------------------------------------------------------------------- #
# The contract a search policy will act through
# --------------------------------------------------------------------------- #


@dataclass
class State:
    """Everything a policy may see before choosing a move.

    Deliberately a snapshot rather than a handle: a policy cannot reach through
    it into the builder, the ledger or the kernel, and cannot mutate anything
    by holding one. :func:`step` returns a new State and leaves this one alone.
    """

    family: str
    #: Builder variable names to values — ``{"BT": 8.0, "UT": 6.0, ...}``.
    params: dict[str, float]
    #: The resolved requirements this part came from, provenance included. The
    #: source of what the user stated, and therefore of what is locked.
    requirements: dict = field(default_factory=dict)
    #: What the part must survive: the engineering block's own declaration.
    engineering: dict = field(default_factory=dict)
    #: Rows from the last evaluation, in ``orion.engineering``'s shape.
    results: list[dict] = field(default_factory=list)
    #: Process and the dimensions the DFM rules read.
    manufacturing: dict = field(default_factory=dict)
    #: What a policy is trying to do. Not used here — nothing in this module
    #: ranks anything — but carried so an Observation can report against it.
    objective: str = ""
    #: Stated parameters a caller has explicitly granted permission to move.
    #: Empty by default: a dimension the user typed is not a search variable
    #: until somebody says so. See :func:`space`.
    unlocked: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class Action:
    """One parameter, moved. The only move this environment accepts.

    Single-parameter by design. A policy that wants to raise two dimensions
    together issues two actions and reads the Observation after each, so every
    intermediate state is checked rather than only the destination. It costs
    nothing — no kernel runs — and it means a policy can never step through an
    impossible part to reach a possible one without being told.
    """

    parameter: str
    to: float
    #: Filled in by :func:`step` from the state it was applied to, so an action
    #: read back from a log says what it actually did.
    frm: Optional[float] = None
    why: str = ""


@dataclass
class Observation:
    """What one action produced. The whole of what a policy learns."""

    state: State
    #: Whether the action was applied at all. A refused action leaves the state
    #: untouched and says why — it is not a failed candidate, it is a move that
    #: was never legal.
    applied: bool
    #: Declared relations the new parameters break. Empty when feasible.
    violations: list[Violation] = field(default_factory=list)
    #: Analytic-tier engineering rows, in ``orion.engineering``'s shape.
    checks: list[dict] = field(default_factory=list)
    #: Closed-form quantities: mass, volume, and whatever the check computed.
    metrics: dict[str, float] = field(default_factory=dict)
    #: Why an action was refused, or a relation reported.
    notes: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        """Every declared relation holds and no declared check failed.

        Analytic only. A part that is feasible here has not been built, and the
        verdict still belongs to the build — see the module docstring.
        """
        return (self.applied and not self.violations
                and all(r.get("passed") is not False for r in self.checks))


def initial_state(family: str, requirements: dict) -> State:
    """A State from the requirements a part was designed from.

    Runs the builder once, so ``params`` are the variables the geometry
    actually uses rather than the slots someone typed.
    """
    from . import blueprint_gen as G

    payload = G.generate(family, requirements)
    plan = payload.get("design_plan") or {}
    return State(
        family=family,
        params=dict(payload.get("variables") or {}),
        requirements=dict(requirements),
        engineering=dict(plan.get("engineering") or {}),
        manufacturing=dict(plan.get("manufacturing") or {}),
    )


def evaluate(state: State) -> Observation:
    """Score a state where it stands, without moving anything.

    Closed form throughout: the relations are arithmetic, the volume is the
    expression the Blueprint carries for its own body assertion, and the checks
    are :mod:`orion.calc` on the frozen variables. No kernel, nothing measured.
    """
    from . import engineering as ENG

    obs = Observation(state=state, applied=True,
                      violations=violations(state.family, state.params))

    block = state.engineering
    if block:
        # ``run_checks`` needs no measurement for this block: every argument is
        # an expression over the variables, and the material comes from the
        # block itself.
        bp_like = {"design_plan": {"engineering": block}}
        try:
            obs.checks = ENG.run_checks(bp_like, state.params, None)
        except Exception as exc:  # noqa: BLE001 - an unevaluable check is a note
            obs.notes.append(f"the engineering checks could not be run: {exc}")

    for row in obs.checks:
        for key, value in (row.get("result") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                obs.metrics[key] = float(value)

    volume = _volume_of(state)
    if volume is not None:
        obs.metrics["volume_mm3"] = volume
        material = (block or {}).get("material")
        if material:
            from . import calc
            try:
                obs.metrics["mass_g"] = calc.mass_properties(
                    volume, material)["mass_g"]
            except (KeyError, TypeError, ValueError):
                pass
    return obs


def _volume_of(state: State) -> Optional[float]:
    """The closed form the Blueprint already grades itself against.

    Re-derived from the builder rather than stored, so it is the expression for
    *these* parameters — a fillet added or removed changes the formula, not
    only its value.

    It is a prediction. The build measures the solid and the assertion decides
    whether the two agree; a caller ranking candidates on this is ranking on
    the closed form, which is exactly what it is for and is only trustworthy
    because something later checks it.
    """
    from . import blueprint_gen as G

    try:
        payload = G.generate(state.family, state.requirements)
    except Exception:  # noqa: BLE001 - an unbuildable state has no volume
        return None
    for a in payload.get("assertions") or []:
        if a.get("kind") == "body_volume" and a.get("target"):
            try:
                return float(E.evaluate(str(a["target"]), state.params))
            except Exception:  # noqa: BLE001
                return None
    return None


def step(state: State, action: Action) -> Observation:
    """Apply one action and report. The environment's only transition.

    An action outside the parameter's current interval is **refused** rather
    than applied and marked infeasible, and the two are different facts: a
    refusal says the move was never available, while an infeasible result says
    it was available and turned out badly. A policy that cannot tell them apart
    would learn to avoid legal moves because an illegal one near them failed.
    """
    intervals = space(state.family, state.params, state.requirements,
                      state.unlocked)
    interval = intervals.get(action.parameter)

    if interval is None:
        return Observation(
            state=state, applied=False,
            notes=[f"{action.parameter} is not a searchable parameter of "
                   f"{state.family}; searchable: "
                   f"{', '.join(SEARCHABLE.get(state.family, ()))}"])
    if interval.locked:
        return Observation(
            state=state, applied=False,
            notes=[f"{action.parameter} is fixed: {interval.lock_reason}"])
    if not interval.holds(action.to):
        at_top = interval.high is not None and action.to >= interval.high
        return Observation(
            state=state, applied=False,
            notes=[f"{action.to:g} is outside {action.parameter}'s current "
                   f"range {interval}; "
                   + (f"upper end from {interval.high_from}" if at_top
                      else f"lower end from {interval.low_from}")])

    moved = State(
        family=state.family,
        params={**state.params, action.parameter: float(action.to)},
        requirements=_with_parameter(state, action),
        engineering=state.engineering,
        manufacturing=state.manufacturing,
        objective=state.objective,
        unlocked=state.unlocked,
    )
    # Rebuild from the moved requirements so the engineering block is the one
    # this geometry earns, not the one the previous geometry had.
    try:
        moved = initial_state(moved.family, moved.requirements)
        moved.objective = state.objective
        moved.unlocked = state.unlocked
    except Exception as exc:  # noqa: BLE001 - the builder is the authority
        return Observation(
            state=state, applied=False,
            notes=[f"the builder refused the move: {exc}"])

    obs = evaluate(moved)
    obs.notes.append(
        f"{action.parameter} {_show(state.params.get(action.parameter))} "
        f"-> {action.to:g}")
    return obs


def _with_parameter(state: State, action: Action) -> dict:
    """The requirements that would produce this parameter value.

    Only parameters with a requirement of their own can be moved this way, and
    :data:`SEARCHABLE` contains no others.
    """
    slot = _REQUIREMENT_OF.get(action.parameter)
    if slot is None:
        return dict(state.requirements)
    return {**state.requirements, slot: float(action.to)}


def actions(state: State, steps: int = 4) -> list[Action]:
    """Every legal single-parameter move, sampled across each interval.

    Not a strategy and not an ordering — the list is what is *available*, and
    choosing among it is the policy's whole job. ``steps`` says how finely each
    interval is sampled; a caller wanting a different granularity, or the
    endpoints only, reads :func:`space` and builds its own.

    Unbounded ends are not sampled. An interval open at the top is open because
    nothing in the declared bounds closes it, and inventing a ceiling to sample
    against would be this module having an opinion it does not have.
    """
    out: list[Action] = []
    for name, interval in space(state.family, state.params,
                                state.requirements, state.unlocked).items():
        if interval.locked or interval.empty:
            continue
        if interval.low is None or interval.high is None:
            continue
        current = state.params.get(name)
        for i in range(steps + 1):
            value = interval.low + (interval.high - interval.low) * i / steps
            value = round(value, 6)
            if current is not None and abs(value - float(current)) < 1e-9:
                continue
            # An excluded endpoint is not a move. Sampling it would hand a
            # policy a candidate the very next call refuses.
            if not interval.holds(value):
                continue
            out.append(Action(parameter=name, to=value,
                              frm=None if current is None else float(current)))
    return out


def _show(value: Optional[float]) -> str:
    return "unbounded" if value is None else f"{value:g}"


#: Parameters this module refuses to search, and why. Written down because the
#: reasons are not obvious from the geometry, and a later author adding them to
#: :data:`SEARCHABLE` should have to disagree with something.
UNSAFE_TO_SEARCH: dict[str, str] = {
    "hole_r": "a hole is an interface. Its diameter is set by the fastener and "
              "the mating part, neither of which this module can see, so "
              "moving it to save mass silently redesigns a joint the request "
              "fixed.",
    "bolt_square": "the bolt pattern matches something it bolts to. Changing "
                   "it produces a part that no longer mounts.",
    "bore_r": "a pilot bore is sized to what passes through it.",
    "cbore_r": "a counterbore is sized to the screw head, from a standards "
               "table, not to taste.",
    "cbore_d": "counterbore depth against head height, same table.",
    "slot_length": "a slot is an adjustment range someone asked for.",
    "slot_width": "as hole_r: sized to the fastener.",
    "slot_edge_gap": "moving it moves the mounting positions.",
    "base_hole_r": "as hole_r.",
    "base_hole_edge_gap": "as slot_edge_gap.",
}
