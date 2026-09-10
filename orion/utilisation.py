"""Where the load actually goes, and which material is not earning its place.

The useful half of a topology study, without the part nobody has solved. Real
density-based optimisation returns a voxel field, and turning that back into an
editable feature tree with stable interfaces is a research problem — but the
*question* it answers is not exotic. An engineer wants to know which member is
sizing the design, which one is along for the ride, and whether making the part
lighter means removing material or moving it. All three are answerable from a
frame solution the system already computes.

**Utilisation is stress over allowable**, where allowable is the material's
yield divided by the safety factor the design actually asked for. So 1.0 means
"exactly at the limit you specified", not "about to break": a bracket at 0.5 is
carrying half what its own requirement permits.

**"Oversized" means carrying little stress. It does not mean "remove it".**
That distinction is the whole reason this module is written carefully rather
than as a one-line ratio. A member can be lightly stressed and still necessary:

* it may be sized by **stiffness** — if a deflection limit is what binds, a
  low-stress member is holding the part still and thinning it makes the
  deflection worse while the stress stays comfortable. That case is detected
  and named, because acting on the stress number alone would be exactly wrong.
* it may be sized by **manufacture** — a minimum wall for the process
* it may be an **interface** — a face that bolts to something, whose size was
  never a structural decision at all

So this reports and does not prescribe. It says "the upright carries 11% of
what it is allowed to" and leaves the decision where it belongs.

**And it is only as good as the model underneath.** The frame gives nominal
section stress: no stress concentration, no plate behaviour, a fully fixed
support where a bolted joint really is. A member reported at 30% has 30% of
its *nominal* allowable, and a real fillet or bolt hole peaks higher. Every
figure here inherits that and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: Suffix marking a per-member stress in a calculator's result. ``orion.calc``
#: writes ``base_stress_mpa`` and ``upright_stress_mpa`` alongside the scalar
#: summary, because an engineering row can only carry flat values — a nested
#: list of members would be stripped before it reached anything.
MEMBER_SUFFIX = "_stress_mpa"

#: Keys that end in the suffix but are not members.
_NOT_MEMBERS = frozenset({"max_stress_mpa"})

# --------------------------------------------------------------------------- #
# What a utilisation figure means
#
# Thresholds are judgements and are written down so they can be argued with.
# They are round numbers chosen to be legible, not derived from anything.
# --------------------------------------------------------------------------- #

#: Past the limit the design itself asked for.
OVERLOADED = "overloaded"
#: High enough that this member is what sets the size of the part.
BINDING = "binding"
#: Doing real work, with margin.
WORKING = "working"
#: Carrying so little that its size came from something other than this load.
OVERSIZED = "oversized"

_BINDING_AT = 0.75
_OVERSIZED_BELOW = 0.35


@dataclass(frozen=True)
class MemberUse:
    """One member's share of the load it is allowed to carry."""

    name: str
    stress_mpa: float
    allowable_mpa: float
    utilisation: float

    @property
    def verdict(self) -> str:
        if self.utilisation > 1.0:
            return OVERLOADED
        if self.utilisation >= _BINDING_AT:
            return BINDING
        if self.utilisation < _OVERSIZED_BELOW:
            return OVERSIZED
        return WORKING

    @property
    def percent(self) -> float:
        return 100.0 * self.utilisation


@dataclass
class Utilisation:
    """The load path of one design."""

    members: list = field(default_factory=list)
    allowable_mpa: float = 0.0
    yield_mpa: float = 0.0
    required_factor: float = 0.0
    #: Utilisation of the deflection limit, when the design declared one.
    #: ``None`` when it did not — most designs do not, and inventing a limit to
    #: divide by would manufacture a constraint nobody asked for.
    deflection_use: Optional[float] = None
    deflection_mm: Optional[float] = None
    deflection_limit_mm: Optional[float] = None
    #: What the numbers rest on, carried from the calculator.
    basis: str = ""
    notes: list = field(default_factory=list)

    @property
    def binding(self):
        """The member that sizes the design, or ``None`` if nothing does."""
        return max(self.members, key=lambda m: m.utilisation, default=None)

    @property
    def oversized(self) -> list:
        return [m for m in self.members if m.verdict == OVERSIZED]

    @property
    def stiffness_driven(self) -> bool:
        """Whether deflection binds harder than stress does.

        The case that makes a naive reading of these numbers dangerous. When it
        is true, the lightly stressed member is holding the part still, and
        thinning it because "the stress is low" makes the thing it was actually
        sized for worse.
        """
        if self.deflection_use is None:
            return False
        worst = self.binding
        return worst is not None and self.deflection_use > worst.utilisation

    @property
    def imbalance(self) -> Optional[float]:
        """Highest utilisation over lowest.

        The single number that says whether material is in the wrong place. A
        frame where one member is at 90% and another at 10% is not a part that
        needs less material; it is a part that needs it moved.
        """
        if len(self.members) < 2:
            return None
        low = min(m.utilisation for m in self.members)
        high = max(m.utilisation for m in self.members)
        return high / low if low > 0 else float("inf")


def of_check(row: dict) -> Optional[Utilisation]:
    """Read the load path out of one engineering row.

    Returns ``None`` when the row carries nothing to read — a calculator with
    no stress, or one that ran under no declared factor. A utilisation with no
    allowable is not a small number, it is not a number, and returning zero
    would be a claim.
    """
    result = (row or {}).get("result") or {}
    expect = (row or {}).get("expect") or {}

    yield_mpa = _number(result.get("yield_mpa"))
    factor = _number((expect.get("safety_factor") or {}).get("min"))
    if not yield_mpa or not factor or factor <= 0:
        return None

    allowable = yield_mpa / factor
    out = Utilisation(allowable_mpa=allowable, yield_mpa=yield_mpa,
                      required_factor=factor,
                      basis=str(result.get("stress_basis") or ""))

    for key, value in result.items():
        if not key.endswith(MEMBER_SUFFIX) or key in _NOT_MEMBERS:
            continue
        stress = _number(value)
        if stress is None:
            continue
        out.members.append(MemberUse(
            name=key[:-len(MEMBER_SUFFIX)], stress_mpa=stress,
            allowable_mpa=allowable, utilisation=stress / allowable))

    if not out.members:
        # A single-member model — a plate — reports only its peak. That is one
        # member, not none, and treating it as none would leave every plate
        # with no load path at all.
        peak = _number(result.get("max_stress_mpa"))
        if peak is not None:
            out.members.append(MemberUse(
                name="section", stress_mpa=peak, allowable_mpa=allowable,
                utilisation=peak / allowable))

    out.members.sort(key=lambda m: (-m.utilisation, m.name))

    limit = _number((expect.get("deflection_mm") or {}).get("max"))
    deflection = _number(result.get("deflection_mm"))
    if limit and limit > 0 and deflection is not None:
        out.deflection_mm = deflection
        out.deflection_limit_mm = limit
        out.deflection_use = deflection / limit

    return out


def of_state(state) -> Optional[Utilisation]:
    """The load path of a design in the search environment."""
    from . import design_space as DS

    observation = DS.evaluate(state)
    for row in observation.checks:
        found = of_check(row)
        if found is not None:
            return found
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# --------------------------------------------------------------------------- #
# Saying it
# --------------------------------------------------------------------------- #


def explain(use: Optional[Utilisation]) -> list:
    """The load path in sentences. Every number comes from the solution."""
    if use is None or not use.members:
        return ["No load path to report: nothing declared a duty this design "
                "could be measured against."]

    lines = [
        f"Allowable stress is {use.allowable_mpa:.4g} MPa "
        f"({use.yield_mpa:.4g} MPa yield at the safety factor of "
        f"{use.required_factor:g} this design asked for)."
    ]

    for member in use.members:
        lines.append(
            f"  {member.name}: {member.stress_mpa:.4g} MPa, "
            f"{member.percent:.0f}% of allowable — {member.verdict}.")

    binding = use.binding
    if binding is not None:
        if binding.verdict == OVERLOADED:
            lines.append(
                f"The {binding.name} is over its allowable and sets the "
                f"design: nothing gets lighter until it gets stronger.")
        else:
            lines.append(f"The {binding.name} is what sizes this part.")

    ratio = use.imbalance
    if ratio is not None and ratio >= 3.0:
        least = use.members[-1]
        lines.append(
            f"Utilisation across members varies {ratio:.0f}-fold "
            f"({binding.name} {binding.percent:.0f}%, {least.name} "
            f"{least.percent:.0f}%). Material is in the wrong place rather "
            f"than merely excessive — moving it from the {least.name} to the "
            f"{binding.name} buys more than removing it.")

    if use.oversized:
        names = ", ".join(m.name for m in use.oversized)
        lines.append(
            f"Carrying little of this load: {names}. That is a statement "
            f"about stress and not an instruction — a member can be sized by "
            f"stiffness, by a process minimum, or by what it bolts to.")

    if use.stiffness_driven:
        lines.append(
            f"This design is sized by stiffness, not strength: deflection is "
            f"at {100.0 * use.deflection_use:.0f}% of its "
            f"{use.deflection_limit_mm:g} mm limit while the worst stress is "
            f"at {binding.percent:.0f}%. Thinning a low-stress member here "
            f"makes the binding constraint worse, not better.")
    elif use.deflection_use is not None:
        lines.append(
            f"Deflection is {use.deflection_mm:.4g} mm, "
            f"{100.0 * use.deflection_use:.0f}% of its stated limit.")

    if use.basis:
        lines.append(f"Stress basis: {use.basis}. Every figure above inherits "
                     f"that.")
    return lines


def compare(before: Optional[Utilisation],
            after: Optional[Utilisation]) -> list:
    """What a change did to the load path.

    Mass alone does not say whether a design got better. A part that lost 20%
    of its weight by pushing one member from 40% to 95% utilisation has spent
    its whole margin, and the mass figure alone will not tell anyone that.
    """
    if before is None or after is None:
        return []

    lines = []
    was = {m.name: m for m in before.members}
    for member in after.members:
        old = was.get(member.name)
        if old is None:
            continue
        if abs(member.utilisation - old.utilisation) < 0.01:
            continue
        lines.append(
            f"  {member.name}: {old.percent:.0f}% -> {member.percent:.0f}% "
            f"of allowable ({old.verdict} -> {member.verdict}).")

    old_ratio, new_ratio = before.imbalance, after.imbalance
    if old_ratio and new_ratio and abs(new_ratio - old_ratio) > 0.5:
        moved = "more evenly" if new_ratio < old_ratio else "less evenly"
        lines.append(
            f"  Load is carried {moved} than before: {old_ratio:.0f}-fold "
            f"spread across members, now {new_ratio:.0f}-fold.")
    return lines


def report(result) -> list:
    """The load path of a search: where it started, where it ended, what moved.

    Takes an :class:`orion.search.Result`. This is the part an engineer reads
    after being told a part can be 27% lighter — *which* material went, and
    what the design is now living on.
    """
    from . import design_space as DS
    from . import search as S

    lines = ["Load path at the starting design:"]
    start_use = _use_of(result.start, result)
    lines.extend(explain(start_use))

    best = result.best
    if best is None or not best.path:
        lines.append("No lighter design was found, so the load path stands.")
        return lines

    best_use = _use_of(best, result)
    value_from = result.start.value(result.objective)
    value_to = best.value(result.objective)
    lines.append("")
    lines.append(
        f"After the search ({result.objective.metric} "
        f"{value_from:.4g} -> {value_to:.4g}):")
    lines.extend(explain(best_use))

    moved = compare(start_use, best_use)
    if moved:
        lines.append("")
        lines.append("What the search changed:")
        lines.extend(moved)

    if result.unconstrained:
        lines.append(
            f"  No declared check reads {', '.join(result.unconstrained)}, so "
            f"no utilisation can be given for "
            f"{'them' if len(result.unconstrained) > 1 else 'it'} at all.")
    return lines


def _use_of(candidate, result) -> Optional[Utilisation]:
    """A candidate's load path, rebuilt from its own requirements.

    ``interview.requirements`` writes the family into what it hands the
    builder, so a candidate already knows what it is — no need for the caller
    to carry it alongside.
    """
    from . import design_space as DS

    family = (candidate.requirements or {}).get("family")
    if not family:
        return None
    try:
        return of_state(DS.initial_state(family, candidate.requirements))
    except Exception:  # noqa: BLE001 - a candidate that cannot rebuild has none
        return None
