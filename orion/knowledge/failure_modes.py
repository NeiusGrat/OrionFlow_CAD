"""How the components we select actually break, and whether this one will.

A failure mode listed as a word is a wiki entry. "A bearing can fail by fatigue"
is true of every bearing ever made and changes no decision. What changes a
decision is *this* bearing, at *this* duty: a static safety factor of 0.8, a
required lubricant viscosity of 19 mm²/s, a load below the minimum at which the
rolling elements stop rolling and start skidding.

So every mode here carries an assessment where the data allows one, and states
exactly which input is missing where it does not. The three verdicts are
deliberate:

* ``ok`` / ``marginal`` / ``at_risk`` — computed, with the margin and the
  standard behind it.
* ``unknown`` — the mode is real and applies, but assessing it needs something
  nobody has supplied. Named as a question rather than dropped, because the
  modes you cannot compute are usually the ones that kill bearings:
  contamination, false brinelling, electrical erosion through a VFD.

The second kind matters more than it looks. Rating life answers one question
well, and an engineer who reads L10 = 38 000 h and stops has been told very
little about whether the bearing survives — the overwhelming majority of
bearings removed from service never reached their fatigue life. They were
starved, contaminated, over-preloaded, or run below minimum load. A system that
reports only the number it can compute quietly implies the others are fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

OK = "ok"
MARGINAL = "marginal"
AT_RISK = "at_risk"
UNKNOWN = "unknown"


@dataclass
class Assessment:
    """Whether this component, at this duty, is exposed to this mode."""

    mode: str
    verdict: str
    finding: str
    margin: Optional[float] = None       # >1 is comfortable, <1 is exceeded
    needs: list[str] = field(default_factory=list)
    basis: str = ""

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"mode": self.mode, "verdict": self.verdict,
                               "finding": self.finding}
        if self.margin is not None:
            out["margin"] = round(self.margin, 2)
        if self.needs:
            out["needs"] = self.needs
        if self.basis:
            out["basis"] = self.basis
        return out


@dataclass(frozen=True)
class FailureMode:
    id: str
    label: str
    applies_to: tuple[str, ...]
    driver: str                          # the one-line cause
    mechanism: str                       # what physically happens
    governed_by: str = ""                # the standard, if there is one
    calculator: str = ""                 # a registered calculator, if any
    mitigation: str = ""
    #: (row, duty) -> Assessment. Absent when the mode cannot be assessed from
    #: anything we hold, which is itself worth reporting.
    assess: Optional[Callable[[dict, Any], Assessment]] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label,
                "applies_to": list(self.applies_to), "driver": self.driver,
                "mechanism": self.mechanism, "governed_by": self.governed_by,
                "calculator": self.calculator, "mitigation": self.mitigation,
                "assessable": self.assess is not None}


# --------------------------------------------------------------------------- #
# rolling bearings
# --------------------------------------------------------------------------- #
_BEARING_FAMILIES = ("rolling_bearing", "deep_groove_ball_bearing",
                     "angular_contact_ball_bearing", "self_aligning_ball_bearing",
                     "taper_roller_bearing", "cylindrical_roller_bearing",
                     "spherical_roller_bearing", "needle_roller_bearing",
                     "thrust_ball_bearing", "thrust_roller_bearing")


def _is_roller(designation: str) -> bool:
    from orion.knowledge.bearing_types import classify

    return "roller" in (classify(designation) or "")


def _assess_fatigue(row: dict, duty: Any) -> Assessment:
    """ISO 281 basic rating life against the life the duty asked for."""
    from orion import calc

    c, load = row.get("C_N"), getattr(duty, "radial_load_N", None)
    if c is None or not load:
        return Assessment("fatigue", UNKNOWN,
                          "rating life needs the dynamic load rating and the "
                          "applied load",
                          needs=[n for n, v in (("C_N on file", c),
                                                ("radial load", load))
                                 if not v])
    speed = getattr(duty, "speed_rpm", None) or 1500.0
    wanted = getattr(duty, "life_hours", None) or 10000.0
    hours = calc.bearing_life_l10(c, load, speed)["l10_hours"]
    margin = hours / wanted
    verdict = OK if margin >= 1.5 else MARGINAL if margin >= 1.0 else AT_RISK
    return Assessment(
        "fatigue", verdict,
        f"L10 = {hours:,.0f} h at {load:g} N and {speed:g} rpm, against "
        f"{wanted:,.0f} h required",
        margin, basis="ISO 281 basic rating life, L10h = (C/P)^p x 10^6/(60n)")


def _assess_static_overload(row: dict, duty: Any) -> Assessment:
    """Permanent indentation of the raceway under a load applied at rest.

    Distinct from fatigue, and missed by rating life entirely: a bearing that
    survives a million revolutions can be ruined in one shock while stationary.
    """
    c0, load = row.get("C0_N"), getattr(duty, "radial_load_N", None)
    if c0 is None or not load:
        return Assessment("static_overload", UNKNOWN,
                          "the static safety factor needs C0 and the peak load",
                          needs=[n for n, v in (("C0_N on file", c0),
                                                ("peak load", load))
                                 if not v])
    s0 = c0 / load
    roller = _is_roller(str(row.get("designation", "")))
    # ISO 281 / SKF guidance: rollers make line contact and are held to a
    # higher factor than balls, because an indentation runs the length of the
    # contact rather than sitting in a point.
    wanted = 1.5 if roller else 1.0
    verdict = OK if s0 >= wanted * 1.5 else MARGINAL if s0 >= wanted else AT_RISK
    return Assessment(
        "static_overload", verdict,
        f"s0 = C0/P0 = {c0:g}/{load:g} = {s0:.1f}, against {wanted:g} for "
        f"{'roller' if roller else 'ball'} bearings in normal service",
        s0 / wanted,
        basis="ISO 76 static load rating; s0 guidance per ISO 281 / SKF. Raise "
              "to 1.5 (ball) or 3 (roller) where shock loads are expected.")


def _assess_minimum_load(row: dict, duty: Any) -> Assessment:
    """Too *little* load, which is a real and frequently missed failure.

    Rolling elements need a minimum load to keep rolling. Below it they skid
    across the raceway instead, and the smearing that follows destroys a bearing
    that every life calculation says is barely working.
    """
    c, load = row.get("C_N"), getattr(duty, "radial_load_N", None)
    if c is None or not load:
        return Assessment("skidding", UNKNOWN,
                          "the minimum load check needs C and the applied load",
                          needs=[n for n, v in (("C_N on file", c),
                                                ("applied load", load))
                                 if not v])
    roller = _is_roller(str(row.get("designation", "")))
    fraction = 0.02 if roller else 0.01
    minimum = fraction * c
    margin = load / minimum
    verdict = OK if margin >= 1.5 else MARGINAL if margin >= 1.0 else AT_RISK
    return Assessment(
        "skidding", verdict,
        f"applied {load:g} N against a minimum of about {minimum:,.0f} N "
        f"({fraction:.0%} of C) to keep the elements rolling",
        margin,
        basis="SKF minimum load rule of thumb: 0.01C for ball bearings, 0.02C "
              "for roller. A lightly loaded bearing on a vertical or unloaded "
              "shaft usually needs a spring or a preload.")


def _assess_lubrication(row: dict, duty: Any) -> Assessment:
    """The viscosity the lubricant must actually have at temperature.

    Not assessable as pass or fail — we do not know the oil or the running
    temperature — but the *requirement* is computable from the size and speed
    alone, and it is the number an engineer needs before choosing a grade.
    """
    d, outer = row.get("d"), row.get("D")
    speed = getattr(duty, "speed_rpm", None)
    if d is None or outer is None or not speed:
        return Assessment("lubrication_starvation", UNKNOWN,
                          "the required viscosity needs the bearing size and "
                          "the running speed",
                          needs=["running speed"] if not speed else [])
    dm = (d + outer) / 2.0
    # SKF / ISO 281 rated viscosity, split at 1000 rpm.
    nu1 = (45000 * speed ** -0.83 * dm ** -0.5 if speed < 1000
           else 4500 * speed ** -0.5 * dm ** -0.5)
    return Assessment(
        "lubrication_starvation", UNKNOWN,
        f"the lubricant must reach at least {nu1:.0f} mm2/s at running "
        f"temperature (dm = {dm:g} mm at {speed:g} rpm). Whether it does "
        f"depends on the grade and the temperature, neither of which is stated",
        needs=["lubricant grade (ISO VG)", "operating temperature"],
        basis="SKF rated viscosity nu1: 45000 n^-0.83 dm^-0.5 below 1000 rpm, "
              "4500 n^-0.5 dm^-0.5 above. The viscosity ratio kappa = nu/nu1 "
              "drives the a_ISO life factor in ISO 281.")


def _assess_misalignment(row: dict, duty: Any) -> Assessment:
    """Edge loading when the shaft does not run true to the housing."""
    from orion.knowledge.bearing_types import classify, profile

    spec = profile(classify(str(row.get("designation", ""))) or "")
    stated = getattr(duty, "misalignment_deg", None)
    if spec is None:
        return Assessment("edge_loading", UNKNOWN,
                          "the bearing type is not recognised, so its "
                          "misalignment tolerance is not known",
                          needs=["a recognised bearing type"])
    if stated is None:
        return Assessment(
            "edge_loading", UNKNOWN,
            f"this type tolerates about {spec.misalignment_deg:g} deg; how far "
            f"out of line the shaft actually runs is not stated",
            needs=["shaft misalignment under load, including deflection"],
            basis="manufacturer permissible misalignment by type")
    if spec.misalignment_deg <= 0:
        return Assessment("edge_loading", AT_RISK if stated > 0 else OK,
                          "this type tolerates no misalignment",
                          basis="manufacturer permissible misalignment by type")
    margin = spec.misalignment_deg / stated if stated else float("inf")
    verdict = OK if margin >= 2 else MARGINAL if margin >= 1 else AT_RISK
    return Assessment(
        "edge_loading", verdict,
        f"{stated:g} deg stated against about {spec.misalignment_deg:g} deg "
        f"tolerated by a {spec.kind}",
        margin if margin != float("inf") else None,
        basis="manufacturer permissible misalignment by type. Shaft deflection "
              "under load counts toward this, not just assembly error.")


MODES: tuple[FailureMode, ...] = (
    FailureMode(
        "fatigue", "subsurface rolling contact fatigue", _BEARING_FAMILIES,
        driver="revolutions under load",
        mechanism="cyclic Hertzian stress below the raceway initiates a crack "
                  "that propagates to the surface and spalls",
        governed_by="ISO 281", calculator="bearing_life_l10",
        mitigation="reduce the load, raise the size, or accept a shorter life — "
                   "life goes as the cube of the load ratio for ball bearings",
        assess=_assess_fatigue),
    FailureMode(
        "static_overload", "brinelling under static or shock load",
        _BEARING_FAMILIES,
        driver="a peak load applied while stationary or nearly so",
        mechanism="contact stress exceeds the yield of the raceway and leaves "
                  "a permanent indentation, which then becomes a noise and "
                  "vibration source for the rest of the bearing's life",
        governed_by="ISO 76",
        mitigation="size on the static safety factor s0 = C0/P0, not on rating "
                   "life; shock loads need s0 >= 1.5 (ball) or 3 (roller)",
        assess=_assess_static_overload),
    FailureMode(
        "skidding", "smearing from insufficient load", _BEARING_FAMILIES,
        driver="an applied load below the minimum needed to keep the elements "
               "rolling",
        mechanism="rolling elements slide rather than roll on entering the load "
                  "zone; the sliding tears metal from both surfaces",
        mitigation="apply a spring preload, or choose a smaller bearing — the "
                   "usual cause is an oversized bearing on a lightly loaded "
                   "shaft",
        assess=_assess_minimum_load),
    FailureMode(
        "lubrication_starvation", "inadequate lubricant film",
        _BEARING_FAMILIES,
        driver="viscosity too low at running temperature for the speed and size",
        mechanism="the elastohydrodynamic film thins until asperities touch; "
                  "adhesive wear and then surface-initiated fatigue follow",
        governed_by="ISO 281",
        mitigation="choose the grade from the required nu1 at the actual "
                   "running temperature, not at 40 C",
        assess=_assess_lubrication),
    FailureMode(
        "edge_loading", "edge loading from misalignment", _BEARING_FAMILIES,
        driver="shaft and housing axes not parallel, from assembly error or "
               "shaft deflection under load",
        mechanism="the load concentrates at one end of the contact instead of "
                  "spreading along it, multiplying the local stress",
        mitigation="a self-aligning or spherical type accommodates degrees "
                   "rather than minutes; otherwise tighten the alignment or "
                   "stiffen the shaft",
        assess=_assess_misalignment),
    FailureMode(
        "contamination", "indentation and abrasion by hard particles",
        _BEARING_FAMILIES,
        driver="solid contaminant in the lubricant",
        mechanism="particles are rolled into the raceway, each indentation "
                  "raising a stress concentration that initiates a spall",
        governed_by="ISO 281",
        mitigation="filtration and effective sealing. In ISO 281 this is the "
                   "eta_c factor, and in dirty conditions it can cut calculated "
                   "life by an order of magnitude — no geometry change "
                   "compensates for it"),
    FailureMode(
        "false_brinelling", "fretting at standstill under vibration",
        _BEARING_FAMILIES,
        driver="vibration while the bearing is not rotating",
        mechanism="micro-movement at the contacts wears through the lubricant "
                  "film and fret-corrodes the raceway at element spacing",
        mitigation="matters for machines transported or parked under vibration; "
                   "lock the shaft or rotate it periodically"),
    FailureMode(
        "electrical_erosion", "pitting and fluting from shaft current",
        _BEARING_FAMILIES,
        driver="current passing through the bearing to earth, typically from "
               "an inverter drive",
        mechanism="discharge across the lubricant film melts micro-craters, "
                  "which develop into fluting and a characteristic whine",
        mitigation="a hybrid (ceramic element) bearing, an insulated housing, "
                   "or a shaft grounding ring. Worth deciding at design time "
                   "because retrofitting means dismantling the machine"),
    FailureMode(
        "corrosion", "rust and chemical attack", _BEARING_FAMILIES,
        driver="water or aggressive fluid reaching the raceway",
        mechanism="corrosion pits act as stress raisers exactly as "
                  "contamination indentations do",
        mitigation="sealing, and a lubricant with the right rust inhibitors"),
)

BY_ID = {m.id: m for m in MODES}


def for_family(family: str) -> list[FailureMode]:
    return [m for m in MODES if family in m.applies_to]


def assess(family: str, row: dict, duty: Any) -> list[Assessment]:
    """Every mode that applies, in the order an engineer should read them.

    Sorted by what needs attention: risks first, then the unknowns worth
    chasing, then what is comfortable. A report that leads with a healthy
    fatigue life buries the static factor of 0.8 underneath it.
    """
    order = {AT_RISK: 0, MARGINAL: 1, UNKNOWN: 2, OK: 3}
    out = []
    for mode in for_family(family):
        if mode.assess is None:
            out.append(Assessment(
                mode.id, UNKNOWN, mode.driver,
                needs=["operating conditions — this mode is not computable "
                       "from catalogue data"],
                basis=mode.mitigation))
        else:
            out.append(mode.assess(row, duty))
    out.sort(key=lambda a: (order.get(a.verdict, 9), a.mode))
    return out


def summarise(assessments: list[Assessment]) -> str:
    """The block a designer reads after a component is chosen."""
    lines = []
    for a in assessments:
        mark = {OK: "OK  ", MARGINAL: "WARN", AT_RISK: "RISK",
                UNKNOWN: "?   "}.get(a.verdict, "    ")
        lines.append(f"  {mark} {a.mode:24s} {a.finding}")
        for need in a.needs:
            lines.append(f"       needs: {need}")
    risks = sum(1 for a in assessments if a.verdict == AT_RISK)
    unknowns = sum(1 for a in assessments if a.verdict == UNKNOWN)
    head = (f"{len(assessments)} failure modes: {risks} at risk, "
            f"{unknowns} not assessable from what is stated")
    return "\n".join([head] + lines)
