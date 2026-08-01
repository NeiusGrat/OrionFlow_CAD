"""Decompose a request into functions, resolve each, and make them agree.

"Design a robotic shoulder joint" is not a bearing query. It is half a dozen
functions that have to be discovered before any of them is answered, and the
hard part is not the list — it is that the answers constrain each other. A
bearing chosen for its load fixes the shaft diameter; the key is then cut to
that diameter and not to a preference; the seal runs on it; the housing bore
follows the bearing's outer ring. Resolve them independently and you get six
correct components that do not fit together.

**The function list is derived, not guessed.** A planner that asks a model to
list the functions of a shoulder joint gets a plausible list, and a plausible
list is unfalsifiable. What is checkable is this: an interface that something
must *provide* is a function that something must *perform*. The graph already
records that a bearing requires a shaft seat, a shoulder and axial retention —
so locating the shaft and retaining it axially are not guesses about what a
shoulder joint needs, they are debts the bearing incurred. Only the entry point
is read from the request; the rest follows.

**Shared dimensions are reconciled, not averaged.** When two resolutions imply
different values for the same dimension, that is a conflict to report. Silently
taking one is how a drawing acquires a 25 mm bearing on a 30 mm shaft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from orion.knowledge import functions as F

STATED = "stated"
ENTAILED = "entailed"

#: The bridge from one function to the next. An interface a component demands
#: is work the design still owes, and that work is itself a function — which is
#: what lets the decomposition be derived rather than listed. Deliberately
#: small: an interface with no obvious owning function is left out rather than
#: mapped approximately, because a wrong entailment invents a requirement.
INTERFACE_ENTAILS: dict[str, str] = {
    "shaft_seat": F.LOCATES_PART,
    "housing_seat": F.LOCATES_PART,
    "shoulder": F.RETAINS_AXIALLY,
    "axial_retention": F.RETAINS_AXIALLY,
    "lubrication": F.SEALS_FLUID,
    "counterface": F.SEALS_FLUID,
    "groove": F.SEALS_FLUID,
}


@dataclass
class Need:
    """One function the design must perform, and why it is on the list."""

    function: str
    origin: str                      # stated | entailed
    because: str
    via: str = ""                    # the interface that entailed it

    def to_dict(self) -> dict:
        out = {"function": self.function, "origin": self.origin,
               "because": self.because}
        if self.via:
            out["via"] = self.via
        return out


@dataclass
class Decomposition:
    request: str
    needs: list[Need] = field(default_factory=list)

    def functions(self) -> list[str]:
        return [n.function for n in self.needs]

    def to_dict(self) -> dict:
        return {"request": self.request,
                "needs": [n.to_dict() for n in self.needs]}

    def explain(self) -> str:
        lines = [f"{self.request}", ""]
        for need in self.needs:
            mark = "asked for" if need.origin == STATED else "entailed "
            lines.append(f"  {mark}  {need.function:22s} {need.because}")
        return "\n".join(lines)


@dataclass
class Conflict:
    """Two resolutions that cannot both be built."""

    dimension: str
    values: dict[str, float]         # who claimed what
    detail: str

    def to_dict(self) -> dict:
        return {"dimension": self.dimension, "values": self.values,
                "detail": self.detail}


@dataclass
class Resolution:
    """What one function resolved to, or why it could not."""

    function: str
    resolved: bool
    summary: str
    part_class: str = ""
    variables: dict[str, float] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)
    #: Dimensions this resolution *fixes*. A bearing's bore is the shaft, and
    #: nothing downstream may choose otherwise.
    provides: dict[str, float] = field(default_factory=dict)
    #: Dimensions this resolution needs to be *at least* something. A key does
    #: not fix the shaft diameter, but 80 Nm cannot be carried on 15 mm however
    #: the rest of the design feels about it. Kept apart from ``provides``
    #: because a lower bound that is comfortably met is agreement, and treating
    #: it as an equality would report a conflict every time a shaft was
    #: generously sized.
    requires_at_least: dict[str, float] = field(default_factory=dict)
    asks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"function": self.function, "resolved": self.resolved,
                "summary": self.summary, "part_class": self.part_class,
                "variables": self.variables, "citations": self.citations,
                "provides": self.provides,
                "requires_at_least": self.requires_at_least,
                "asks": self.asks}


@dataclass
class Plan:
    request: str
    decomposition: Decomposition
    resolutions: list[Resolution] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    context: dict[str, float] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (bool(self.resolutions)
                and all(r.resolved for r in self.resolutions)
                and not self.conflicts)

    def unresolved(self) -> list[Resolution]:
        return [r for r in self.resolutions if not r.resolved]

    def to_dict(self) -> dict:
        return {"request": self.request,
                "decomposition": self.decomposition.to_dict(),
                "resolutions": [r.to_dict() for r in self.resolutions],
                "conflicts": [c.to_dict() for c in self.conflicts],
                "context": self.context, "complete": self.complete}

    def explain(self) -> str:
        lines = [f"PLAN: {self.request}", ""]
        lines.append("FUNCTIONS")
        for need in self.decomposition.needs:
            mark = "asked for" if need.origin == STATED else "entailed "
            lines.append(f"  {mark}  {need.function:22s} {need.because}")
        lines += ["", "RESOLUTION"]
        for r in self.resolutions:
            mark = "OK  " if r.resolved else "--  "
            lines.append(f"  {mark} {r.function:22s} {r.summary}")
            for q in r.asks:
                lines.append(f"       needs: {q}")
        if self.context:
            lines += ["", "AGREED DIMENSIONS"]
            lines += [f"  {k} = {v:g}" for k, v in sorted(self.context.items())]
        if self.conflicts:
            lines += ["", "CONFLICTS"]
            for c in self.conflicts:
                lines.append(f"  {c.dimension}: " + ", ".join(
                    f"{k} wants {v:g}" for k, v in c.values.items()))
                lines.append(f"    {c.detail}")
        done = sum(1 for r in self.resolutions if r.resolved)
        lines += ["", f"{done}/{len(self.resolutions)} functions resolved"
                      + (f", {len(self.conflicts)} conflict(s)"
                         if self.conflicts else "")]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# step 2 — functional decomposition
# --------------------------------------------------------------------------- #
def decompose(request: str, depth: int = 3) -> Decomposition:
    """The functions a request implies, entry point read and the rest derived.

    Iterated to a fixed point but bounded: an entailed function entails its own
    interfaces, and a seal that needs a groove that needs a seal is a loop
    rather than a requirement.
    """
    from orion import graph as G
    from orion import reasoning as R

    F.load_all()
    intent = R.read_intent(request)
    stated = intent.detail.get("functions") or []

    needs: list[Need] = []
    seen: set[str] = set()
    for function in stated:
        if function not in seen:
            seen.add(function)
            needs.append(Need(function, STATED, "read from the request"))

    frontier = list(stated)
    for _ in range(depth):
        nxt: list[str] = []
        for function in frontier:
            for component in G.components_for(function):
                for interface, _why in G.obligations(component.id):
                    entailed = INTERFACE_ENTAILS.get(interface.id)
                    if entailed is None or entailed in seen:
                        continue
                    seen.add(entailed)
                    # The edge's own detail is deliberately not quoted here. It
                    # was computed against whichever row the graph sampled as
                    # representative, so it carries that bearing's bore — a
                    # specific number masquerading as a general fact, in the one
                    # place where nothing specific has been chosen yet.
                    needs.append(Need(
                        entailed, ENTAILED,
                        f"a {component.id.replace('_', ' ')} requires: "
                        f"{interface.id.replace('_', ' ')}",
                        via=interface.id))
                    nxt.append(entailed)
        if not nxt:
            break
        frontier = nxt
    return Decomposition(request, needs)


# --------------------------------------------------------------------------- #
# step 5 — resolving a subsystem
# --------------------------------------------------------------------------- #
#: function -> resolver(duty, context) -> Resolution. A function with no
#: resolver is reported unresolved rather than skipped: the design still needs
#: it, and pretending otherwise produces a subsystem that looks finished.
_RESOLVERS: dict[str, Callable[[Any, dict], Resolution]] = {}


def resolves(function: str):
    def register(fn):
        _RESOLVERS[function] = fn
        return fn
    return register


@resolves(F.SUPPORTS_ROTATION)
def _resolve_rotation(duty: Any, context: dict) -> Resolution:
    """Select a bearing, and publish the shaft and housing diameters it fixes.

    This is usually the first thing resolved and the reason the order matters:
    the bearing's bore is not a preference downstream, it is the shaft.
    """
    from orion import reasoning as R
    from orion.knowledge.registry import rows_for_family

    stated = dict(duty)
    if "bore_mm" not in stated and "shaft_dia_mm" in context:
        stated["bore_mm"] = context["shaft_dia_mm"]
    d = F.Duty(function=F.SUPPORTS_ROTATION, **{
        k: v for k, v in stated.items()
        if k in F.Duty.__dataclass_fields__ and k != "function"})

    found = F.search(d, limit=1)
    if not found:
        return Resolution(F.SUPPORTS_ROTATION, False,
                          "no bearing satisfies the duty",
                          asks=[F.explain_empty(d).splitlines()[0]])
    best = found[0]
    row = next((r for r in rows_for_family(best.family)
                if r.get("designation") == best.designation), {})

    spec = R.write_specification(R.Step(
        R.SELECTION, "", {"_candidate": best}))
    if spec.asks:
        return Resolution(F.SUPPORTS_ROTATION, False,
                          f"{best.designation} selected but not buildable",
                          asks=spec.asks)
    result = spec.detail["_result"]
    return Resolution(
        F.SUPPORTS_ROTATION, True,
        f"{best.designation} — L10 {best.evidence.get('l10_hours', '?')} h, "
        f"{row.get('d', '?')}x{row.get('D', '?')}x{row.get('B', '?')}",
        part_class=result.part_class, variables=dict(result.variables),
        citations=list(result.citations),
        provides={"shaft_dia_mm": float(row["d"]),
                  "housing_bore_mm": float(row["D"])} if row.get("d") else {})


@resolves(F.TRANSMITS_TORQUE)
def _resolve_torque(duty: Any, context: dict) -> Resolution:
    """A parallel key, cut to the shaft the bearing already fixed.

    No catalogue is involved and none is needed: DIN 6885 *sets* the section
    from the shaft diameter rather than offering a choice. What the design
    still has to decide is the length, which follows from the torque.
    """
    from orion import calc

    shaft = context.get("shaft_dia_mm") or duty.get("bore_mm")
    if not shaft:
        return Resolution(F.TRANSMITS_TORQUE, False,
                          "a key is sized from the shaft diameter, "
                          "which is not yet fixed",
                          asks=["shaft diameter — resolve the bearing first, "
                                "or state it"])
    width, height = calc.key_for_shaft(float(shaft))
    torque = duty.get("torque_Nm")
    if not torque:
        return Resolution(
            F.TRANSMITS_TORQUE, False,
            f"DIN 6885 {width:g}x{height:g} for a {shaft:g} mm shaft; the "
            f"length needs the torque",
            provides={"key_width_mm": width, "key_height_mm": height},
            asks=["torque to be transmitted, in Nm — it sets the key length"])

    # Length from bearing pressure on the keyway side, per the key capacity
    # calculator; stepped up to the next even millimetre.
    length = 0.0
    for trial in range(4, 201, 2):
        if calc.key_capacity(float(shaft), float(trial))["torque_nm"] >= torque:
            length = float(trial)
            break
    if not length:
        # Worth saying which way out this is. A key longer than about 1.5 shaft
        # diameters stops helping anyway — the torque is not shared evenly along
        # it — so the honest answer is nearly always a bigger shaft.
        return Resolution(
            F.TRANSMITS_TORQUE, False,
            f"{torque:g} Nm exceeds what one DIN 6885 key on a {shaft:g} mm "
            f"shaft carries in any practical length",
            provides={"key_width_mm": width, "key_height_mm": height},
            asks=[f"a shaft larger than {shaft:g} mm, two keys at 120 degrees, "
                  f"or a spline — the shaft was sized by the bearing's radial "
                  f"load, which took no account of the torque"])

    capacity = calc.key_capacity(float(shaft), length)
    useful = 1.5 * float(shaft)
    needed = _shaft_for_torque(torque)
    resolution = Resolution(
        F.TRANSMITS_TORQUE, True,
        f"DIN 6885 key {width:g}x{height:g}x{length:g} — carries "
        f"{capacity['torque_nm']:.0f} Nm against {torque:g} required, "
        f"{capacity['governed_by']} governing",
        citations=[f"DIN 6885 key section for a {shaft:g} mm shaft",
                   f"key capacity by {capacity['governed_by']}: shear "
                   f"{capacity['torque_shear_nm']:.0f} Nm, bearing "
                   f"{capacity['torque_bearing_nm']:.0f} Nm"],
        provides={"key_width_mm": width, "key_height_mm": height,
                  "key_length_mm": length},
        requires_at_least=({"shaft_dia_mm": needed} if needed else {}))
    if length > useful:
        resolution.asks.append(
            f"the key is {length:g} mm on a {shaft:g} mm shaft; past about "
            f"{useful:g} mm the torque is not shared evenly along its length, "
            f"so the capacity above is optimistic")
    return resolution


def _shaft_for_torque(torque_Nm: float) -> float:
    """The smallest shaft on which one key of sane length carries the torque.

    "Sane" is a key no longer than 1.5 diameters. Past that the torque is not
    shared evenly along the key — the near end takes most of it — so a longer
    key buys much less capacity than the arithmetic suggests, and quoting the
    linear figure is how a joint gets signed off at twice its real rating.
    """
    from orion import calc
    from orion.families import DIN_6885

    # The candidate diameters come from the standard's own bands rather than a
    # list written here: a shaft outside the table has no key section defined,
    # and inventing the sizes to search would be inventing the answer.
    for _lo, hi, _b, _h in DIN_6885:
        if calc.key_capacity(hi, 1.5 * hi)["torque_nm"] >= torque_Nm:
            return float(hi)
    return 0.0


def _context_from(resolutions: list[Resolution]) -> tuple[dict, list[Conflict]]:
    """Merge what each resolution publishes, and refuse to average.

    Two resolutions claiming different values for the same dimension is the
    thing this exists to catch. Taking one silently is how a drawing acquires a
    25 mm bearing on a 30 mm shaft.
    """
    context: dict[str, float] = {}
    claims: dict[str, dict[str, float]] = {}
    floors: dict[str, dict[str, float]] = {}
    for r in resolutions:
        for name, value in r.provides.items():
            claims.setdefault(name, {})[r.function] = value
        for name, value in r.requires_at_least.items():
            floors.setdefault(name, {})[r.function] = value

    conflicts: list[Conflict] = []
    for name, by_function in claims.items():
        distinct = sorted(set(by_function.values()))
        if len(distinct) > 1:
            conflicts.append(Conflict(
                name, by_function,
                f"{name} cannot be both {' and '.join(f'{v:g}' for v in distinct)}"
                f"; the components would not assemble"))
        else:
            context[name] = distinct[0]

    # A floor above a fixed value is the interesting case, and it is the one a
    # subsystem gets wrong when each function is resolved on its own: the
    # bearing is sized by the radial load and never hears about the torque.
    for name, by_function in floors.items():
        fixed = context.get(name)
        demanded = max(by_function.values())
        if fixed is None:
            context[name] = demanded
            continue
        if demanded > fixed + 1e-9:
            wanted_by = [f for f, v in by_function.items() if v == demanded]
            fixed_by = [f for f, v in claims.get(name, {}).items()
                        if v == fixed]
            conflicts.append(Conflict(
                name, {**claims.get(name, {}), **by_function},
                f"{' and '.join(fixed_by)} fixes {name} at {fixed:g}, but "
                f"{' and '.join(wanted_by)} needs at least {demanded:g}. "
                f"Resolving each function alone cannot find this — the bearing "
                f"is sized by the radial load and never hears about the torque."))

    # Nothing is agreed about a dimension that is in dispute. Leaving the fixed
    # value in the context would let a later stage read it as settled, which is
    # the silent-substitution failure this whole reconciliation exists to stop.
    for conflict in conflicts:
        context.pop(conflict.dimension, None)
    return context, conflicts


def plan(request: str) -> Plan:
    """Decompose, resolve in dependency order, and reconcile.

    Order is not cosmetic. A bearing fixes the shaft, and a key sized before
    the bearing is a key sized to nothing — so functions that publish
    dimensions are resolved before the ones that consume them.
    """
    from orion import reasoning as R

    F.load_all()
    decomposition = decompose(request)
    intent = R.read_intent(request)
    duty = dict(intent.detail.get("duty") or {})

    #: Publishers first. Ranking by what a function contributes to the shared
    #: context rather than by the order it was mentioned.
    order = {F.SUPPORTS_ROTATION: 0, F.TRANSMITS_TORQUE: 1}
    ordered = sorted(decomposition.functions(),
                     key=lambda f: (order.get(f, 5), f))

    context: dict[str, float] = {}
    resolutions: list[Resolution] = []
    for function in ordered:
        resolver = _RESOLVERS.get(function)
        if resolver is None:
            resolutions.append(Resolution(
                function, False,
                "no resolver — the design needs this and nothing here "
                "provides it",
                asks=[f"{function}: {F.INTENT.get(function, '')}"]))
            continue
        resolution = resolver(duty, context)
        resolutions.append(resolution)
        context.update(resolution.provides)

    context, conflicts = _context_from(resolutions)
    return Plan(request, decomposition, resolutions, conflicts, context)
