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

from orion.skills.base import Skill, SkillError, SkillResult, registry

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bearings.json")
_CACHE: Optional[dict] = None


def catalogue() -> dict:
    global _CACHE
    if _CACHE is None:
        with open(_DATA, encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def bearing(designation: str) -> dict:
    """Boundary dimensions for a designation, or a refusal naming what is known."""
    data = catalogue()
    key = str(designation).strip().upper().lstrip("B")
    # Tolerate suffixes: 6205-2RS, 6205 2Z, 6205ZZ all describe the same
    # envelope — seals and shields live inside the boundary dimensions.
    core = "".join(ch for ch in key if ch.isdigit())[:4]
    entry = data["bearings"].get(core)
    if entry is None:
        raise SkillError(
            f"no catalogue entry for bearing {designation!r}. Known: "
            f"{', '.join(sorted(data['bearings']))}. Add it from ISO 15 rather "
            f"than estimating — a wrong envelope is a housing that does not fit.")
    return {"designation": core, **entry}


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
    fits = catalogue()["housing_fits"]
    if duty not in fits:
        raise SkillError(
            f"no sourced fit for duty {duty!r}. Available: "
            f"{', '.join(fits)}. The remaining ISO 286 classes "
            f"({', '.join(catalogue()['unsourced']['housing_classes'])}) are "
            f"deliberately absent until their deviations are taken from "
            f"ISO 286-2 directly.")
    fit = fits[duty]
    it = it7_um(nominal_mm)
    return {"iso_class": fit["iso_class"], "when": fit["when"],
            "nominal_mm": nominal_mm,
            "lower_mm": 0.0, "upper_mm": it / 1000.0,
            "min_mm": nominal_mm, "max_mm": nominal_mm + it / 1000.0}


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
    if "Da_max" in spec:
        shoulder_dia = float(spec["Da_max"])
        shoulder_why = (f"Da max {shoulder_dia:g} mm — the manufacturer's "
                        f"abutment diameter for {spec['designation']}")
    else:
        shoulder_dia = outer - 4.0 * float(spec["r_min"])
        shoulder_why = (f"derived: D - 4*r_min = {outer:g} - "
                        f"4*{spec['r_min']:g}; no sourced Da max for "
                        f"{spec['designation']}")
        warnings.append(
            f"no abutment diameter on file for {spec['designation']}; the "
            f"shoulder is a conservative construction from the corner radius, "
            f"not a manufacturer recommendation")

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
            f"(+{fit['upper_mm'] * 1000:.0f} um / 0)",
        ],
        derived={
            "bearing": spec["designation"],
            "housing_bore_mm": f"{fit['min_mm']:.3f}..{fit['max_mm']:.3f} "
                               f"({fit['iso_class']})",
            "fit_applies_when": fit["when"],
            "shoulder_diameter_mm": round(shoulder_dia, 2),
            "shoulder_basis": shoulder_why,
            "corner_radius_min_mm": spec["r_min"],
            "seat_depth_mm": width,
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
))
