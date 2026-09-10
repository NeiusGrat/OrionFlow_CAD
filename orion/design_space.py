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

Six families are described: ``l_bracket``, ``rect_plate``, ``disc``,
``shelled_box``, ``bearing_housing`` and ``manifold``. ``spur_gear`` is
deliberately absent — module, tooth count and pressure angle are mesh
compatibility rather than sizing, and a search that moved one would produce a
gear that no longer meshes with whatever it was cut to run against. A family
with no entry has no declared space, which reads as "nothing is known to be
safe to move" rather than "anything goes" — the same direction of silence as
the rest of the system.

**What a move costs.** :func:`space` asks the builder where the edge is, which
is about twenty builder calls per bound: ~15 ms for a full space and ~34 ms for
a :func:`step`, so roughly thirty moves a second. That is comfortable for an
interactive tool and slow for a search doing thousands of evaluations, which
will want to cache by parameter vector or pass ``probe=False`` to
:func:`bounds` and accept a space that may be wider than what builds. The
default is correctness, because a space that quietly disagrees with the builder
is the one failure this module cannot be allowed to have.
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

# --------------------------------------------------------------------------- #
# What is known about a candidate
#
# Deliberately not the verdict ladder's words. VERIFIED there means a measured
# solid agreed with its frozen contract; nothing in this module is measured or
# built, so reusing the term would claim evidence that does not exist.
# --------------------------------------------------------------------------- #

#: A builder relation does not hold. The part cannot exist.
BROKEN = "broken"
#: A duty was stated and nothing here can evaluate it. Not feasible: see
#: :attr:`Observation.feasible`.
UNJUDGED = "unjudged"
#: A declared check ran and did not pass.
FAILED = "failed"
#: Every declared check passed — analytically, on the closed form.
SCREENED = "screened"
#: Nothing was claimed, so nothing is owed. Buildable and unjudged, which is
#: the honest reading of a request that states no load.
NO_DUTY = "no_duty"
#: The move was never legal, so nothing was evaluated at all.
NOT_APPLIED = "not_applied"


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
        # .10g rather than g: a probed edge is a real number just short of the
        # boundary, and rounding 24.99997 to "25" would print the one value the
        # interval excludes.
        lo = "unbounded" if self.low is None else f"{self.low:.10g}"
        hi = "unbounded" if self.high is None else f"{self.high:.10g}"
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
    "rect_plate": ("L", "W", "T", "cr"),
    "disc": ("R", "T"),
    "shelled_box": ("L", "W", "H", "wall", "floor_t", "cr"),
    "bearing_housing": ("L", "W", "H"),
    "manifold": ("L", "W", "H"),
    # spur_gear is deliberately absent: see UNSAFE_TO_SEARCH. Module, tooth
    # count and pressure angle are mesh compatibility, not sizing.
}

#: Builder variable to the requirement that sets it. A parameter with no
#: requirement of its own cannot be moved by this environment at all — there is
#: no input to change — so every searchable name appears here.
_REQUIREMENT_OF: dict[str, dict[str, str]] = {
    "l_bracket": {
        "BL": "base_length", "BW": "base_width", "BT": "base_thickness",
        "UH": "upright_height", "UT": "upright_thickness",
        "UW": "upright_width", "in_r": "inside_fillet",
    },
    "rect_plate": {
        "L": "length", "W": "width", "T": "thickness", "cr": "corner_radius",
    },
    "disc": {"R": "outer_r", "T": "thickness"},
    "shelled_box": {
        "L": "length", "W": "width", "H": "height", "wall": "wall",
        "floor_t": "floor", "cr": "corner_radius",
    },
    "bearing_housing": {"L": "length", "W": "width", "H": "height"},
    "manifold": {"L": "length", "W": "width", "H": "height"},
}

#: Family design ranges. The softest bounds here and the only invented numbers
#: in this module: they exist so a search cannot wander somewhere absurd, not
#: because the boundary is physical. Stated as a judgement so it can be argued
#: with.
_FAMILY_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "l_bracket": {
        "BL": (20.0, 400.0), "BW": (20.0, 400.0), "BT": (1.0, 40.0),
        "UH": (10.0, 400.0), "UT": (1.0, 40.0), "UW": (10.0, 400.0),
        "in_r": (0.0, 40.0),
    },
    "rect_plate": {
        "L": (10.0, 1000.0), "W": (10.0, 1000.0), "T": (0.5, 100.0),
        "cr": (0.0, 200.0),
    },
    "disc": {"R": (5.0, 500.0), "T": (0.5, 100.0)},
    "shelled_box": {
        "L": (20.0, 600.0), "W": (20.0, 600.0), "H": (10.0, 600.0),
        "wall": (0.5, 40.0), "floor_t": (0.5, 40.0), "cr": (0.0, 200.0),
    },
    "bearing_housing": {
        "L": (20.0, 400.0), "W": (20.0, 400.0), "H": (5.0, 300.0),
    },
    "manifold": {"L": (20.0, 500.0), "W": (20.0, 500.0), "H": (20.0, 500.0)},
}

#: Which parameters are a *wall* — the thing a process has a minimum for.
_WALL_VARS: dict[str, tuple[str, ...]] = {
    "l_bracket": ("BT", "UT"),
    "rect_plate": ("T",),
    "disc": ("T",),
    "shelled_box": ("wall", "floor_t"),
    "bearing_housing": (),
    "manifold": (),
}

#: Which are an *internal* radius, and so cannot be smaller than the tool that
#: has to cut them. An external corner is not one of these: a cutter rounds the
#: outside of a plate by going around it, at any radius it likes.
_INTERNAL_RADIUS_VARS: dict[str, tuple[str, ...]] = {
    "l_bracket": ("in_r",),
    "rect_plate": (),
    "disc": (),
    "shelled_box": ("cr",),
    "bearing_housing": (),
    "manifold": (),
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


# --------------------------------------------------------------------------- #
# Named relations
#
# Every one is transcribed from a guard the builder already raises on, and the
# transcription is deliberately partial: these are the relations a person should
# see named, not the complete feasible set. The complete set is whatever the
# builder accepts, and ``_probe`` below asks it directly rather than trying to
# restate it. There are far more guards than are written here — a plate's pocket
# depth against its thickness, a housing's bolt pattern against its footprint, a
# box's bore against its wall — and each one nobody transcribed would otherwise
# be a hole in the space.
# --------------------------------------------------------------------------- #


def _positive(names: tuple[str, ...]) -> list[Relation]:
    return [
        Relation(f"positive:{n}", f"{n} > 0", BUILDER,
                 "blueprint_gen._assert_positive refuses a non-positive "
                 "dimension", lambda p, n=n: float(p.get(n, 0.0)) > 0.0)
        for n in names
    ]


def _relations_l_bracket() -> list[Relation]:
    return _positive(("BL", "BW", "BT", "UH", "UT")) + [
        Relation(
            "upright_fits_base", "UT < BL", BUILDER,
            "an upright thicker than the base is long has no base left to "
            "stand on; blueprint_gen raises 'upright thickness exceeds the "
            "base length'",
            lambda p: float(p["UT"]) < float(p["BL"])),
        Relation(
            "upright_clears_base", "UH > BT", BUILDER,
            "the upright is measured from the ground, so it must rise above "
            "the base it sits on",
            lambda p: float(p["UH"]) > float(p["BT"])),
        Relation(
            "upright_within_base", "UW <= BW", BUILDER,
            "an upright wider than the base overhangs into nothing",
            lambda p: float(p.get("UW", p["BW"])) <= float(p["BW"])),
        Relation(
            "fillet_fits_upright", "in_r < UH - BT", BUILDER,
            "a fillet taller than the exposed upright has no corner left to "
            "round",
            lambda p: (not p.get("in_r")
                       or float(p["in_r"]) < float(p["UH"]) - float(p["BT"]))),
        Relation(
            "fillet_fits_base", "in_r < BL - UT", BUILDER,
            "a fillet longer than the base in front of the upright runs off "
            "the end",
            lambda p: (not p.get("in_r")
                       or float(p["in_r"]) < float(p["BL"]) - float(p["UT"]))),
    ]


def _relations_rect_plate() -> list[Relation]:
    return _positive(("L", "W", "T")) + [
        Relation(
            "corner_fits_plate", "cr <= min(L, W) / 2", BUILDER,
            "a corner radius past half the shorter side has consumed the "
            "side; blueprint_gen raises 'corner radius exceeds half the "
            "shorter side'",
            lambda p: (not p.get("cr")
                       or float(p["cr"]) <= min(float(p["L"]),
                                                float(p["W"])) / 2.0)),
    ]


def _relations_disc() -> list[Relation]:
    return _positive(("R", "T"))


def _relations_shelled_box() -> list[Relation]:
    return _positive(("L", "W", "H", "wall")) + [
        Relation(
            "floor_positive", "floor_t > 0", BUILDER,
            "blueprint_gen raises 'floor thickness must be positive'",
            lambda p: float(p.get("floor_t", 0.0)) > 0.0),
        Relation(
            "walls_leave_a_cavity", "2 * wall < min(L, W)", BUILDER,
            "walls that meet in the middle leave nothing to shell",
            lambda p: 2 * float(p["wall"]) < min(float(p["L"]),
                                                 float(p["W"]))),
        Relation(
            "floor_leaves_depth", "floor_t < H", BUILDER,
            "a floor as deep as the box is tall leaves no box",
            lambda p: float(p.get("floor_t", 0.0)) < float(p["H"])),
        Relation(
            "corner_fits_box", "cr <= min(L, W) / 2", BUILDER,
            "as the plate: a corner radius past half the shorter side has "
            "consumed the side",
            lambda p: (not p.get("cr")
                       or float(p["cr"]) <= min(float(p["L"]),
                                                float(p["W"])) / 2.0)),
    ]


def _relations_bearing_housing() -> list[Relation]:
    return _positive(("L", "W", "H", "seat_r", "seat_d")) + [
        Relation(
            "bore_fits_footprint", "2 * seat_r < min(L, W)", BUILDER,
            "a bore wider than the block it sits in",
            lambda p: 2 * float(p["seat_r"]) < min(float(p["L"]),
                                                   float(p["W"]))),
        Relation(
            "seat_within_height", "seat_d < H", BUILDER,
            "blueprint_gen raises 'seat depth must be less than height'",
            lambda p: float(p["seat_d"]) < float(p["H"])),
    ]


def _relations_manifold() -> list[Relation]:
    return _positive(("L", "W", "H", "pr")) + [
        Relation(
            "passage_fits_block", "2 * pr < min(W, H)", BUILDER,
            "blueprint_gen raises 'main passage does not fit inside the "
            "block'",
            lambda p: 2 * float(p["pr"]) < min(float(p["W"]), float(p["H"]))),
    ]


_RELATIONS: dict[str, Callable[[], list[Relation]]] = {
    "l_bracket": _relations_l_bracket,
    "rect_plate": _relations_rect_plate,
    "disc": _relations_disc,
    "shelled_box": _relations_shelled_box,
    "bearing_housing": _relations_bearing_housing,
    "manifold": _relations_manifold,
}


def relations(family: str) -> list[Relation]:
    """Every relation declared for a family. Empty when none is."""
    build = _RELATIONS.get(family)
    return build() if build else []


# --------------------------------------------------------------------------- #
# Asking the builder where the edge is
# --------------------------------------------------------------------------- #

#: How close to the true boundary a probe gets, in mm. Finer than any dimension
#: anybody designs to, and about twenty bisection steps.
_PROBE_TOL = 1e-3


def _builds(family: str, requirements: dict, slot: str,
            value: float) -> Optional[str]:
    """``None`` if the builder accepts this value, else why it did not."""
    from . import blueprint_gen as G

    try:
        G.generate(family, {**requirements, slot: value})
        return None
    except Exception as exc:  # noqa: BLE001 - any refusal is a refusal
        return str(exc)


def _edge(family: str, requirements: dict, slot: str,
          good: float, bad: float) -> tuple[float, str]:
    """Bisect between a value that builds and one that does not.

    Returns the last value that builds and the message from the first that did
    not. Assumes the feasible set is connected in this one variable, which
    every guard in ``blueprint_gen`` satisfies: they are inequalities linear in
    one dimension once the others are fixed.
    """
    why = _builds(family, requirements, slot, bad) or ""
    while abs(bad - good) > _PROBE_TOL:
        mid = (good + bad) / 2.0
        msg = _builds(family, requirements, slot, mid)
        if msg is None:
            good = mid
        else:
            bad, why = mid, msg
    return good, why


def _probe(family: str, requirements: dict, name: str, slot: str,
           current: float, low: Optional[float],
           high: Optional[float]) -> list[Bound]:
    """The interval the builder itself accepts for one parameter.

    The builder is the authority on what exists, so rather than restate its
    guards this asks it. Every feature interaction comes for free — a pocket
    against a plate's thickness, a bolt circle against its footprint — including
    the ones nobody transcribed, and the bound comes back carrying the builder's
    own sentence as its basis.

    Bounded by the declared range so a probe cannot run off to infinity. A
    parameter whose whole declared range builds simply keeps it.
    """
    out: list[Bound] = []
    if _builds(family, requirements, slot, current) is not None:
        # The state does not build as it stands. Probing outward from an
        # infeasible point measures nothing, so the declared bounds are all
        # that can honestly be said.
        return out

    if low is not None and _builds(family, requirements, slot, low) is not None:
        edge, why = _edge(family, requirements, slot, current, low)
        out.append(Bound(name, edge, None, BUILDER, _trim(why)))
    if high is not None and _builds(family, requirements, slot,
                                    high) is not None:
        edge, why = _edge(family, requirements, slot, current, high)
        out.append(Bound(name, None, edge, BUILDER, _trim(why)))
    return out


def _trim(message: str) -> str:
    one = " ".join(str(message).split())
    return one if len(one) <= 160 else one[:157] + "..."


def bounds(family: str, params: dict, requirements: Optional[dict] = None,
           probe: bool = True) -> list[Bound]:
    """Every bound in force, each carrying where it came from.

    The declared kinds — a family range, a process minimum — are cheap and come
    from the tables above. The builder's own limit is found by asking it (see
    :func:`_probe`); ``probe=False`` skips that, which is faster and reports a
    space that may be wider than what actually builds.
    """
    if family not in SEARCHABLE:
        return []

    req = requirements or {}
    out: list[Bound] = []
    label = family.replace("_", " ")

    for name, (low, high) in _FAMILY_BOUNDS.get(family, {}).items():
        out.append(Bound(name, low, high, FAMILY,
                         f"the range a {label} is a sensible design within"))

    wall = _min_wall(req.get("process"))
    if wall is not None:
        for name in _WALL_VARS.get(family, ()):
            out.append(Bound(name, wall, None, PROCESS,
                             f"{req.get('process')} holds a wall of "
                             f"{wall:g} mm (orion.dfm)"))
    if req.get("process") == "machined":
        r = _tool_radius()
        for name in _INTERNAL_RADIUS_VARS.get(family, ()):
            out.append(Bound(name, r, None, PROCESS,
                             f"an internal radius below {r:g} mm cannot be cut "
                             f"by the smallest common end mill (orion.dfm)"))

    if probe:
        declared = _FAMILY_BOUNDS.get(family, {})
        for name in SEARCHABLE[family]:
            slot = _REQUIREMENT_OF.get(family, {}).get(name)
            value = params.get(name)
            if slot is None or not isinstance(value, (int, float)):
                continue
            low, high = declared.get(name, (None, None))
            # Probe from the tightest floor already in force, so a builder edge
            # below a process minimum is never reported as reachable.
            floors = [b.low for b in out if b.name == name and b.low is not None]
            floor = max(floors) if floors else low
            out.extend(_probe(family, req, name, slot, float(value),
                              floor, high))

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
        name for name, slot in _REQUIREMENT_OF.get(family, {}).items()
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
            lock_reason=(
                f"the request states "
                f"{_REQUIREMENT_OF.get(family, {}).get(name, name)}"
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
    #: Whether a duty was stated that nothing here can evaluate. Set by
    #: :func:`evaluate`; see :attr:`evidence`.
    unjudged_duty: str = ""

    @property
    def evidence(self) -> str:
        """*Why* this candidate is or is not acceptable, not just whether.

        A bare boolean cannot carry the difference between "every check passed"
        and "no check ran", and the difference is the whole safety question for
        a search. Four of the six families have no closed form for a load, so a
        policy ranking on a boolean would drive them to minimum size with
        nothing objecting — silence reading as approval.

        The names are deliberately not the verdict ladder's. ``VERIFIED`` in
        this codebase means a measured solid matched its frozen contract;
        nothing here is measured and nothing is built, so borrowing the word
        would be the same mistake ``orion.dfm`` refuses when it declines to say
        "refused" about machining cost.
        """
        if not self.applied:
            return NOT_APPLIED
        if self.violations:
            return BROKEN
        if self.unjudged_duty:
            return UNJUDGED
        if any(r.get("passed") is False for r in self.checks):
            return FAILED
        return SCREENED if self.checks else NO_DUTY

    @property
    def feasible(self) -> bool:
        """Nothing that was asked of this candidate objected.

        ``UNJUDGED`` is not feasible, and that is the point of this change. A
        load the user stated and no model here can evaluate is a duty going
        unchecked, and :mod:`orion.engineering` already settles which way that
        falls: a thing a design says must hold, that cannot be evaluated, is a
        failure rather than a silence. Something nobody claimed is simply
        absent, which is why ``NO_DUTY`` is feasible and ``UNJUDGED`` is not.

        Analytic only either way. A feasible candidate has not been built, and
        the verdict still belongs to the build.
        """
        return self.evidence in (SCREENED, NO_DUTY)


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

    # A load the user stated that no model here can evaluate. Four of the six
    # families are in this position — a bearing housing fails through bore hoop
    # stress and bolt pull-out, a manifold through pressure, and neither is a
    # rectangular cantilever. Inventing a beam model for them would produce a
    # defensible-looking safety factor describing loading the part never sees,
    # which is the mistake ``_BEAM_MODEL`` exists to avoid.
    #
    # So the duty is reported unjudged rather than either faked or ignored.
    # Ignoring it was the real hazard: a search minimising mass on one of those
    # four had nothing objecting and would thin the part until only the family
    # range stopped it.
    if not obs.checks:
        load = state.requirements.get("load_n")
        if isinstance(load, (int, float)) and not isinstance(load, bool) \
                and load > 0:
            obs.unjudged_duty = (
                f"a load of {float(load):g} N was stated and {state.family} "
                f"has no closed form for it, so nothing here can say whether "
                f"the part carries it")

    volume = _volume_of(state)
    if volume is not None:
        obs.metrics["volume_mm3"] = volume
        mass = _mass_of(state, volume)
        if mass is not None:
            obs.metrics["mass_g"] = mass
    return obs


def _mass_of(state: State, volume: float) -> Optional[float]:
    """Mass from the material, whether or not a duty was declared.

    It used to come only from the engineering block, so the four families with
    no closed form for a load reported no mass either — leaving a search with
    neither a constraint nor an objective on two thirds of the catalogue.

    A material is stated far more often than a load, and it is all a mass
    needs: the volume is the closed form the Blueprint already grades itself
    against and the density is a table lookup. The block is still preferred
    when there is one, because its material name has already been resolved and
    frozen into the hash.
    """
    from . import calc

    named = ((state.engineering or {}).get("material")
             or (state.requirements or {}).get("material"))
    if not named:
        return None
    try:
        return calc.mass_properties(volume, str(named))["mass_g"]
    except (KeyError, TypeError, ValueError):
        # An unresolvable or ambiguous material is no mass, not a guessed one.
        return None


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


def step(state: State, action: Action,
         intervals: Optional[dict] = None) -> Observation:
    """Apply one action and report. The environment's only transition.

    An action outside the parameter's current interval is **refused** rather
    than applied and marked infeasible, and the two are different facts: a
    refusal says the move was never available, while an infeasible result says
    it was available and turned out badly. A policy that cannot tell them apart
    would learn to avoid legal moves because an illegal one near them failed.

    ``intervals`` lets a caller that has already computed the space for *this
    state* pass it back in. Probing is most of what a step costs and a search
    enumerating many moves from one state would otherwise recompute the same
    answer for each of them. It must be the space of this state; passing
    another's would check the move against the wrong bounds, so callers other
    than :mod:`orion.search` should leave it alone.
    """
    if intervals is None:
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
    slot = _REQUIREMENT_OF.get(state.family, {}).get(action.parameter)
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

    # disc, rect_plate
    "bore_r": "a bore is sized to the shaft, bearing or pipe that passes "
              "through it.",
    "pcd_r": "a bolt circle matches the flange it bolts to. Moving it makes a "
             "part that no longer mates.",
    "hole_pitch": "as pcd_r: the pattern belongs to the mating part.",
    "pd": "pocket depth is a clearance or a weight-saving decision somebody "
          "made; this module cannot tell which.",

    # bearing_housing — the whole reason only L, W and H are searchable
    "seat_r": "the seat is the bearing's outside diameter, from a catalogue. "
              "Changing it does not resize a bearing, it selects a different "
              "one, and nothing here is entitled to do that.",
    "seat_d": "seat depth is the bearing's width, from the same catalogue "
              "row.",
    "shoulder": "the shoulder is what the bearing's inner ring abuts. Its "
                "size comes from the manufacturer's permissible abutment, not "
                "from what would be lighter.",
    "recess_r": "a seal or cover recess, sized to the part that sits in it.",
    "recess_depth": "as recess_r.",

    # manifold
    "pr": "a flow passage is sized by the flow it has to carry and the "
          "pressure drop that is acceptable. Neither is visible here, and "
          "narrowing a passage to save material would change what the part "
          "does rather than how heavy it is.",
    "port_r": "as pr, and additionally set by the fitting that threads into "
              "it.",

    # shelled_box
    "end_bore_r": "a bore through a wall is a cable gland, a bearing or a "
                  "connector. All three are interfaces.",
    "bore_height": "where a bore sits is set by what lines up with it.",

    # spur_gear — excluded entirely, which is why the family has no space
    "module": "module is mesh compatibility. Two gears mesh only at the same "
              "module, so changing it does not resize a gear, it stops it "
              "engaging with whatever it was cut to run against.",
    "teeth": "tooth count sets the ratio, which is the thing the gear was "
             "specified to achieve.",
    "pressure_angle": "as module: a mesh property shared with the mating "
                      "gear, not a free dimension.",
}
