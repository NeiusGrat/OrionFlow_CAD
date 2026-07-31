"""create_bearing_seat — a housing that a specific bearing actually fits.

What a user asks for is "a housing for a 6205". What the CAD model needs is a
bore radius, a seat depth, a shoulder diameter, a wall, and a set of guards that
hold. Between those two sits about six lookups and three calculations, none of
which a language model should be doing from memory:

* the bearing's boundary dimensions (ISO 15);
* the housing fit class for the duty, and the numeric limits that class implies
  at this diameter (ISO 286, via the IT grade);
* the shoulder the outer ring may abut without fouling its corner radius — the
  manufacturer's ``Da max``, not the ring's own diameter;
* enough wall outside the seat, and enough floor under it, to satisfy the
  family's own preconditions.

Get the shoulder wrong and the housing presses on the outer ring's chamfer
instead of its face, which is a bearing that fails early for a reason nobody can
see in the model. That is exactly the class of mistake a skill exists to make
impossible.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from orion.skills.base import (
    Skill,
    SkillError,
    SkillGraph,
    SkillResult,
    registry,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_HERE, "bearings.json")
#: Boundary dimensions harvested from the SKF catalogue under the invariant
#: gate — 658 bearings, each cross-checked against the document's own mm/inch
#: and N/lbf columns. This is the authority for envelopes; bearings.json
#: supplies what the tables do not carry (fits, IT grades, abutment diameters).
_HARVEST = os.path.join(os.path.dirname(_HERE), "knowledge",
                        "skf_deep_groove.json")
#: ISO 286 seat deviations harvested from the catalogue's own fit tables, gated
#: on the definitional property that an H class is zero-to-IT. This is what lets
#: every duty be resolved instead of only the floating-outer-ring case.
_FITS = os.path.join(os.path.dirname(_HERE), "knowledge",
                     "iso286_seat_fits.json")
_CACHE: Optional[dict] = None
_HARVEST_CACHE: Optional[dict] = None
_FITS_CACHE: Optional[dict] = None


def catalogue() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_DATA, encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def harvested() -> dict:
    """The gated catalogue, or empty if it has not been generated."""
    global _HARVEST_CACHE
    if _HARVEST_CACHE is None:
        try:
            with open(_HARVEST, encoding="utf-8") as fh:
                _HARVEST_CACHE = json.load(fh).get("bearings", {})
        except (OSError, ValueError):
            _HARVEST_CACHE = {}
    return _HARVEST_CACHE


def seat_fits() -> dict:
    """The harvested ISO 286 deviations, or empty if not generated."""
    global _FITS_CACHE
    if _FITS_CACHE is None:
        try:
            with open(_FITS, encoding="utf-8") as fh:
                _FITS_CACHE = json.load(fh).get("fits", {})
        except (OSError, ValueError):
            _FITS_CACHE = {}
    return _FITS_CACHE


def deviations(kind: str, iso_class: str, nominal_mm: float
               ) -> Optional[tuple[float, float]]:
    """``(lower_um, upper_um)`` for a class at a diameter, or None."""
    # Narrowest matching band wins. The gate rejects span rows, but preferring
    # the tightest match means a stray one could never shadow a real size step
    # even if one got through.
    best = None
    for over, incl, low, high in seat_fits().get(kind, {}).get(iso_class, []):
        if over < nominal_mm <= incl:
            if best is None or (incl - over) < (best[1] - best[0]):
                best = (over, incl, low, high)
    return (float(best[2]), float(best[3])) if best else None


#: What each duty demands of the housing, and the class SKF recommends for it.
#: The condition is the engineering content: a fit is only correct for the load
#: case it was chosen under, so the case travels with the number.
DUTIES = {
    "stationary_outer": ("H7", "the load direction is fixed relative to the "
                                "outer ring, and the ring may be displaced "
                                "axially in the housing"),
    "indeterminate_light": ("J7", "the load direction is indeterminate under "
                                   "light to normal load; the ring may still "
                                   "be displaced"),
    "indeterminate_normal": ("K7", "the load direction is indeterminate under "
                                    "normal to heavy load; the ring is not "
                                    "displaceable"),
    "rotating_outer": ("M7", "the load rotates with the outer ring, or heavy "
                              "peak loads apply; the ring is not displaceable"),
    "rotating_outer_heavy": ("N7", "the load rotates with the outer ring under "
                                    "normal to heavy load, in a solid housing"),
    "rotating_outer_thin_wall": ("P7", "a rotating outer ring load in a "
                                        "thin-walled solid housing; maximum "
                                        "interference"),
}


def bearing(designation: str) -> dict:
    """Boundary dimensions for a designation, or a refusal naming what is known.

    The harvested catalogue is consulted first — it is larger and every row
    passed the gate — and the hand-maintained file is overlaid on top of it,
    because that is where abutment diameters and corner radii live. Where both
    carry a dimension, the harvest wins: it came from the manufacturer's own
    table with a checksum, not from a person typing.
    """
    key = str(designation).strip().upper().lstrip("B")
    # Tolerate suffixes: 6205-2RS, 6205 2Z, 6205ZZ all describe the same
    # envelope — seals and shields live inside the boundary dimensions.
    digits = "".join(ch for ch in key if ch.isdigit())
    hand = catalogue()["bearings"]
    gated = harvested()

    for core in (digits[:5], digits[:4]):
        if core in gated or core in hand:
            entry = {**hand.get(core, {}), **gated.get(core, {})}
            if "r_min" not in entry:
                # The chamfer is not in the harvested tables. Without it the
                # conservative shoulder construction cannot run, so say so
                # rather than assuming a value.
                entry["r_min"] = None
            return {"designation": core, **entry}

    known = len(set(gated) | set(hand))
    raise SkillError(
        f"no catalogue entry for bearing {designation!r} among {known} known "
        f"designations. Add it from the manufacturer's table rather than "
        f"estimating — a wrong envelope is a housing that does not fit.")


def it7_um(nominal_mm: float) -> float:
    """The IT7 tolerance at this diameter, in micrometres."""
    for lo, hi, value in catalogue()["it7_um"]:
        if lo < nominal_mm <= hi:
            return float(value)
    raise SkillError(f"no IT7 grade tabulated for {nominal_mm:g} mm")


def housing_fit(nominal_mm: float, duty: str = "stationary_outer") -> dict:
    """``H7`` limits at this diameter, with the condition it assumes.

    Only the stationary-outer-ring case is available. The other classes were not
    obtained from a source that could be corroborated, and a fit table that is
    subtly wrong produces a housing that assembles wrongly with nothing to
    indicate it.
    """
    if duty not in DUTIES:
        raise SkillError(
            f"unknown duty {duty!r}. Available: {', '.join(DUTIES)}.")
    iso_class, when = DUTIES[duty]
    band = deviations("housing", iso_class, nominal_mm)
    if band is None:
        raise SkillError(
            f"no {iso_class} deviations tabulated at {nominal_mm:g} mm. The fit "
            f"class is known but its numbers at this diameter are not, and a "
            f"class without numbers is not something anyone can machine to.")
    lower, upper = band
    return {"iso_class": iso_class, "when": when, "nominal_mm": nominal_mm,
            "lower_mm": lower / 1000.0, "upper_mm": upper / 1000.0,
            "min_mm": nominal_mm + lower / 1000.0,
            "max_mm": nominal_mm + upper / 1000.0}


def create_bearing_seat(bearing_designation: str,
                        wall_mm: float = 6.0,
                        floor_mm: float = 5.0,
                        duty: str = "stationary_outer",
                        shaft_clearance_mm: float = 1.0) -> SkillResult:
    """Resolve a housing that seats ``bearing_designation``.

    ``wall_mm`` is material outside the seat, ``floor_mm`` behind it. Both are
    the caller's design choice; everything else is derived.
    """
    from orion.family_schema import check_guards, for_family

    spec = bearing(bearing_designation)
    d, outer, width = spec["d"], spec["D"], spec["B"]
    fit = housing_fit(outer, duty)

    # The shoulder the outer ring abuts. Da max is the manufacturer's number and
    # accounts for the ring's corner radius; without it, back off the bore by
    # twice the chamfer, which is the conservative construction that guarantees
    # the shoulder meets the ring's flat face rather than its corner.
    warnings: list[str] = []
    if spec.get("Da_max") is not None:
        shoulder_dia = float(spec["Da_max"])
        shoulder_why = (f"Da max {shoulder_dia:g} mm — the manufacturer's "
                        f"abutment diameter for {spec['designation']}")
    elif spec.get("r_min") is not None:
        shoulder_dia = outer - 4.0 * float(spec["r_min"])
        shoulder_why = (f"derived: D - 4*r_min = {outer:g} - "
                        f"4*{spec['r_min']:g}; no sourced Da max for "
                        f"{spec['designation']}")
        warnings.append(
            f"no abutment diameter on file for {spec['designation']}; the "
            f"shoulder is a conservative construction from the corner radius, "
            f"not a manufacturer recommendation")
    else:
        # Neither the abutment nor the chamfer is known, and both routes to a
        # shoulder need one of them. A shoulder that fouls the outer ring's
        # corner is a bearing that fails early for a reason invisible in the
        # model, so this refuses rather than picking a plausible number.
        shoulder_dia = None
        shoulder_why = ""
        warnings.append(
            f"no abutment diameter or corner radius on file for "
            f"{spec['designation']}, so the shoulder cannot be sized — the "
            f"seat is otherwise complete. Supply Da max or r_min from the "
            f"manufacturer's mounting table before machining the shoulder.")

    seat_r = outer / 2.0
    bore_r = d / 2.0 + shaft_clearance_mm       # shaft passes through, clear
    body_r = seat_r + wall_mm
    thickness = width + floor_mm

    result = SkillResult(
        part_class="bearing_carrier",
        variables={"R": body_r, "rs": seat_r, "rb": bore_r,
                   "ds": float(width), "T": thickness},
        rationale={
            "rs": f"{spec['designation']} outer diameter {outer:g} mm, "
                  f"{fit['iso_class']} housing fit",
            "ds": f"{spec['designation']} width {width:g} mm — the seat takes "
                  f"the full ring",
            "rb": f"shaft {d:g} mm plus {shaft_clearance_mm:g} mm clearance so "
                  f"the bore does not touch the shaft",
            "R": f"{wall_mm:g} mm of wall outside the seat",
            "T": f"seat {width:g} mm plus {floor_mm:g} mm of floor behind it",
        },
        citations=[
            f"ISO 15 boundary dimensions for {spec['designation']} "
            f"({d:g} x {outer:g} x {width:g} mm)",
            f"ISO 286 {fit['iso_class']} housing bore: "
            f"{fit['min_mm']:.3f}..{fit['max_mm']:.3f} mm "
            f"({fit['lower_mm'] * 1000:+.0f}/{fit['upper_mm'] * 1000:+.0f} um)",
        ],
        derived={
            "bearing": spec["designation"],
            "housing_bore_mm": f"{fit['min_mm']:.3f}..{fit['max_mm']:.3f} "
                               f"({fit['iso_class']})",
            "fit_applies_when": fit["when"],
            "shoulder_diameter_mm": (round(shoulder_dia, 2)
                                     if shoulder_dia is not None else None),
            "shoulder_basis": shoulder_why or "not determinable from the data "
                                              "on file",
            "corner_radius_min_mm": spec.get("r_min"),
            "seat_depth_mm": width,
            # Carried through so the caller can size life without a second
            # lookup: calc_bearing_life_l10 takes C directly.
            "dynamic_load_rating_C_N": spec.get("C_N"),
            "static_load_rating_C0_N": spec.get("C0_N"),
        },
        warnings=warnings,
    )

    # The family's own guards decide whether this is buildable. A skill that
    # returns parameters the compiler will refuse has moved the failure, not
    # removed it.
    for guard in check_guards("bearing_carrier", result.variables):
        if not guard["holds"]:
            raise SkillError(
                f"a {spec['designation']} does not fit these proportions: "
                f"{guard['id']} requires {guard['expr']} > 0 but it is "
                f"{guard['value']:.2f}. Increase wall_mm or floor_mm.")

    schema = for_family("bearing_carrier")
    for name, value in result.variables.items():
        stat = schema.variables.get(name) if schema else None
        if stat and not (stat.lo <= value <= stat.hi):
            result.warnings.append(
                f"{name}={value:g} is outside the range seen in verified "
                f"bearing_carrier parts ({stat.lo:g}..{stat.hi:g}); it "
                f"satisfies every constraint but has no precedent in the corpus")
    return result


registry.register(Skill(
    name="create_bearing_seat",
    description=(
        "Resolve a housing that seats a specific rolling bearing. Give the "
        "designation (e.g. 6205) and it returns buildable housing dimensions "
        "with the ISO 286 bore fit, the shoulder the outer ring abuts, and the "
        "corner radius to clear — each with the standard it came from. Use this "
        "instead of choosing bearing seat dimensions yourself."),
    parameters={
        "type": "object",
        "properties": {
            "bearing_designation": {
                "type": "string",
                "description": "Bearing number, e.g. '6205' or '6205-2RS'.",
            },
            "wall_mm": {"type": "number",
                        "description": "Material outside the seat. Default 6."},
            "floor_mm": {"type": "number",
                         "description": "Material behind the seat. Default 5."},
            "shaft_clearance_mm": {
                "type": "number",
                "description": "Radial clearance between the through-bore and "
                               "the shaft. Default 1.",
            },
        },
        "required": ["bearing_designation"],
    },
    run=create_bearing_seat,
    graph=SkillGraph(
        functions=["SupportsRotation", "CentersComponent"],
        inputs=["bearing_designation", "duty", "wall_mm", "floor_mm"],
        calculators=["calc_bearing_life_l10"],
        standards=["ISO 15 boundary dimensions",
                   "ISO 286 seat tolerances",
                   "SKF rolling bearing catalogue"],
        outputs=["bearing_carrier variables", "housing bore limits",
                 "shoulder diameter", "corner radius"],
    ),
))
