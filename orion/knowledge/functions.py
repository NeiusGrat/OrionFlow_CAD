"""What a component is *for*, as a first-class node.

The catalogue can answer "what is a 6205" and cannot answer "what supports a
rotating shaft carrying 3 kN". Those are different questions, and only the
second is the one an engineer actually starts from. A designer does not decide
to use a bearing and then work out why; they have a shaft that must turn under
a load, and a bearing is the answer they arrive at.

So a function is a node, not a tag. A component **implements** a function, and
implementing it **requires** interfaces that something else must provide: a
bearing supports rotation only if a shaft seat, a housing seat and a shoulder
exist for it. That requirement is the part worth modelling, because it is what
turns "pick a bearing" into "pick a bearing and then you owe it a shoulder".

Capability is separate from suitability. ``implements`` says a bearing supports
rotation; ``satisfies`` says whether *this* bearing supports *this* load for
*this* long, which is arithmetic and belongs in a calculator. Conflating them
gives you a search that returns confident nonsense — every bearing "supports
rotation", and only some survive 3 kN at 1500 rpm for 20 000 hours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# the vocabulary
# --------------------------------------------------------------------------- #
SUPPORTS_ROTATION = "SupportsRotation"
SUPPORTS_LINEAR_MOTION = "SupportsLinearMotion"
SEALS_FLUID = "SealsFluid"
TRANSMITS_TORQUE = "TransmitsTorque"
LOCATES_PART = "LocatesPart"
PROVIDES_CLAMP_FORCE = "ProvidesClampForce"
RETAINS_AXIALLY = "RetainsAxially"
TRANSFERS_POWER = "TransfersPower"
CENTERS_COMPONENT = "CentersComponent"
GUIDES_MOTION = "GuidesMotion"

FUNCTIONS = (
    SUPPORTS_ROTATION, SUPPORTS_LINEAR_MOTION, SEALS_FLUID, TRANSMITS_TORQUE,
    LOCATES_PART, PROVIDES_CLAMP_FORCE, RETAINS_AXIALLY, TRANSFERS_POWER,
    CENTERS_COMPONENT, GUIDES_MOTION,
)

#: One line each, for a planner that has to choose between them.
INTENT = {
    SUPPORTS_ROTATION: "something must turn while carrying a load",
    SUPPORTS_LINEAR_MOTION: "something must slide along an axis under load",
    SEALS_FLUID: "a fluid or gas must not pass a joint",
    TRANSMITS_TORQUE: "rotation must be carried from one part to another",
    LOCATES_PART: "a part must sit in a repeatable position",
    PROVIDES_CLAMP_FORCE: "two parts must be held together against a load",
    RETAINS_AXIALLY: "a part must not move along its axis",
    TRANSFERS_POWER: "power must cross a distance, at a ratio",
    CENTERS_COMPONENT: "two parts must share an axis",
    GUIDES_MOTION: "motion must follow a defined path",
}


@dataclass(frozen=True)
class Requires:
    """An interface the design must provide for a function to actually work.

    This is the debt a component takes on. Choosing a 6205 is not free: it
    obliges a 25 mm shaft seat, a 52 mm housing bore and a shoulder that clears
    the outer ring's corner. A planner that tracks these has a task list; one
    that does not produces a bearing floating in space.
    """

    interface_kind: str
    detail: str = ""
    optional: bool = False

    def to_dict(self) -> dict:
        out = {"interface": self.interface_kind}
        if self.detail:
            out["detail"] = self.detail
        if self.optional:
            out["optional"] = True
        return out


@dataclass
class Implements:
    """A component's claim to perform a function, and what it costs."""

    function: str
    requires: list[Requires] = field(default_factory=list)
    #: Bounds within which the claim holds at all, before any calculation.
    limits: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"function": self.function,
                               "requires": [r.to_dict() for r in self.requires]}
        if self.limits:
            out["limits"] = self.limits
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Duty:
    """What the design actually demands. The other half of a search.

    Deliberately loose: a planner rarely knows every figure at the point it
    starts looking, and a search that requires all of them answers nothing.
    """

    function: str
    radial_load_N: Optional[float] = None
    #: Thrust, and how far the shaft may be out of line. These are the
    #: questions that decide the TYPE, and they must be asked before a part is
    #: chosen: a thrust bearing cannot carry a radial load at all, and a deep
    #: groove tolerates almost no misalignment.
    axial_load_N: Optional[float] = None
    misalignment_deg: Optional[float] = None
    speed_rpm: Optional[float] = None
    life_hours: Optional[float] = None
    bore_mm: Optional[float] = None
    max_outside_dia_mm: Optional[float] = None
    torque_Nm: Optional[float] = None
    pressure_bar: Optional[float] = None
    cord_dia_mm: Optional[float] = None


@dataclass
class Candidate:
    """A component that satisfies a duty, and the arithmetic that says so."""

    designation: str
    family: str
    function: str
    evidence: dict[str, Any] = field(default_factory=dict)
    requires: list[dict] = field(default_factory=list)
    margin: float = 0.0             # how comfortably it satisfies, for ranking
    confidence: str = ""

    def to_dict(self) -> dict:
        return {"designation": self.designation, "family": self.family,
                "function": self.function, "evidence": self.evidence,
                "requires": self.requires, "margin": round(self.margin, 3),
                "confidence": self.confidence}


# --------------------------------------------------------------------------- #
# the graph
# --------------------------------------------------------------------------- #
#: family -> (function -> callable(row, duty) -> (ok, evidence, margin))
_SATISFIERS: dict[str, dict[str, Callable]] = {}


def satisfies(family: str, function: str):
    """Register the arithmetic that decides whether a row meets a duty.

    Separate from ``implements`` on purpose. Every deep-groove bearing supports
    rotation; whether a 6205 survives 3 kN at 1500 rpm for 20 000 hours is a
    calculation, and a search that skips it returns confident nonsense.
    """
    def register(fn):
        _SATISFIERS.setdefault(family, {})[function] = fn
        return fn
    return register


def search(duty: Duty, limit: int = 5) -> list[Candidate]:
    """Components that perform ``duty.function`` under the stated conditions.

    This is the query a designer starts from — "I need to support a rotating
    shaft carrying 3 kN" — rather than "find me a bearing". Ranked by margin, so
    the first answer is the one with the least waste rather than merely the
    first that fits.
    """
    from orion.knowledge.registry import rows_for_family

    found: list[Candidate] = []
    for family, functions in _SATISFIERS.items():
        decide = functions.get(duty.function)
        if decide is None:
            continue
        for row in rows_for_family(family):
            verdict = decide(row, duty)
            if verdict is None:
                continue
            ok, evidence, margin = verdict
            if not ok:
                continue
            found.append(Candidate(
                designation=str(row.get("designation")
                                or row.get("cord_dia_mm", "?")),
                family=family, function=duty.function,
                evidence=evidence, margin=margin,
                requires=[r.to_dict() for impl in implements_for(family, row)
                          if impl.function == duty.function
                          for r in impl.requires],
                confidence=row.get("confidence", "")))
    # Envelope first, then the simpler part. Two types can share an envelope —
    # a 6205 and a 30205 are both 25x52 — and reaching for the taper roller on
    # a light radial duty buys a costlier bearing and a costlier assembly
    # around it. Ties go to the ordinary answer.
    found.sort(key=lambda c: (-c.margin, _preference(c)))
    return found[:limit]


def _preference(candidate: Candidate) -> int:
    from orion.knowledge.bearing_types import classify, profile

    spec = profile(classify(candidate.designation) or "")
    return spec.preference if spec else 50


def explain_empty(duty: Duty) -> str:
    """Why a search found nothing. An empty list is an answer, not a silence.

    A planner that gets back nothing needs to know which requirement did the
    excluding, because that is the one to renegotiate with whoever set it.
    """
    from orion.knowledge.bearing_types import choose_types

    if duty.function != SUPPORTS_ROTATION:
        return f"no component in the catalogue performs {duty.function}"
    verdicts = choose_types(radial_N=duty.radial_load_N or 0.0,
                            axial_N=duty.axial_load_N or 0.0,
                            misalignment_deg=duty.misalignment_deg or 0.0,
                            speed_rpm=duty.speed_rpm or 0.0)
    allowed = [v for v in verdicts if v.suitable]
    if not allowed:
        lines = ["no bearing TYPE takes this combination of loads:"]
        lines += [f"  {v.kind}: {v.reason}" for v in verdicts]
        # The type that missed by the least, and only on one count, is the one
        # worth taking back to whoever set the requirement. Listing the first
        # five by preference buries it: here the taper roller takes the loads
        # comfortably and fails only on 0.1 deg against 0.05, which is a
        # question about the shaft rather than about the bearing.
        near = sorted((v for v in verdicts if len(v.failures) == 1),
                      key=lambda v: v.shortfall)
        if near and near[0].shortfall < float("inf"):
            closest = near[0]
            lines.append(f"closest is {closest.kind}, excluded only because it "
                         f"{closest.failures[0]}")
        lines.append("Relax the requirement that excludes every type — "
                     "usually the misalignment or the thrust share.")
        return "\n".join(lines)
    kinds = ", ".join(v.kind for v in allowed)
    return (f"types {kinds} could take this duty, but no catalogued size "
            f"satisfies the envelope, load and life together. Widen the "
            f"envelope, shorten the life, or reduce the load.")


#: family -> callable(row) -> list[Implements]
_IMPLEMENTS: dict[str, Callable[[dict], list[Implements]]] = {}


def declares(family: str):
    """Register what a family's components are for."""
    def register(fn):
        _IMPLEMENTS[family] = fn
        return fn
    return register


def implements_for(family: str, row: dict) -> list[Implements]:
    fn = _IMPLEMENTS.get(family)
    return fn(row) if fn else []


def families_for(function: str) -> list[str]:
    """Which families claim to perform a function at all."""
    return sorted(f for f, fns in _SATISFIERS.items() if function in fns)


def load_all() -> None:
    """Import the modules that register declarations."""
    from orion.knowledge import functions_catalogue  # noqa: F401
