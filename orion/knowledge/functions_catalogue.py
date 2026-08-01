"""What the ingested families are for, and when they are actually up to it.

Two separate claims per family, kept apart deliberately:

* ``declares`` — the function a component performs, and the interfaces the
  design owes it in return. Every deep-groove bearing supports rotation.
* ``satisfies`` — whether *this* component meets *this* duty, which is
  arithmetic. Only some bearings survive 3 kN at 1500 rpm for 20 000 hours.

Collapsing the two would give a search that answers every query with the whole
catalogue.
"""

from __future__ import annotations

from typing import Optional

from orion.knowledge.functions import (
    CENTERS_COMPONENT,
    LOCATES_PART,
    SEALS_FLUID,
    SUPPORTS_ROTATION,
    Duty,
    Implements,
    Requires,
    declares,
    satisfies,
)

BEARING = "rolling_bearing"
GLAND = "o_ring_gland"

#: Every bearing type performs the same functions; what differs is which duties
#: it can take, which is decided by the type profile rather than by the
#: function. Registering each separately is what lets a search say "a taper
#: roller, because the thrust is too high for a deep groove".
from orion.knowledge.bearing_types import classify as _classify  # noqa: E402
from orion.knowledge.bearing_types import profile as _profile  # noqa: E402


# --------------------------------------------------------------------------- #
# deep groove ball bearings
# --------------------------------------------------------------------------- #
@declares(BEARING)
def bearing_functions(row: dict) -> list[Implements]:
    """A bearing supports rotation and centres what it carries.

    The functional claim is true of every rolling bearing — deep groove, taper
    roller, thrust — which is exactly why it does not distinguish between them.
    What differs is the *duty* each type can take, and that is decided in
    ``_type_allows`` against the type profile, before any arithmetic. Keeping
    the two apart is the point: a thrust bearing genuinely supports rotation,
    and genuinely cannot support a shaft.

    The ``requires`` list is the debt: choosing a 6205 obliges a 25 mm shaft
    seat, a 52 mm housing bore and a shoulder that clears the outer ring's
    corner. A planner tracking these has a task list; one that does not
    produces a bearing floating in space.
    """
    d, D, B = row.get("d"), row.get("D"), row.get("B")
    return [
        Implements(
            function=SUPPORTS_ROTATION,
            requires=[
                Requires("shaft_seat", f"{d:g} mm, interference so the inner "
                                       f"ring cannot creep"),
                Requires("housing_seat", f"{D:g} mm, class chosen for the load "
                                         f"case"),
                Requires("shoulder", "must clear the ring's corner radius, or "
                                     "it presses on the chamfer"),
                Requires("axial_retention", "the ring must be held against "
                                            "thrust"),
                Requires("lubrication", "grease or oil; sealed variants carry "
                                        "their own", optional=True),
            ],
            limits={"bore_mm": d, "outside_dia_mm": D, "width_mm": B,
                    "dynamic_load_rating_N": row.get("C_N")},
            note="rolling elements between hardened raceways carry the load "
                 "through rolling rather than sliding contact, so friction is "
                 "nearly independent of speed and the shaft can turn under "
                 "load indefinitely",
        ),
        Implements(
            function=CENTERS_COMPONENT,
            requires=[Requires("shaft_seat", f"{d:g} mm"),
                      Requires("housing_seat", f"{D:g} mm")],
            note="a rolling bearing holds concentricity as a side effect of "
                 "supporting rotation, within its running clearance",
        ),
    ]


@satisfies(BEARING, SUPPORTS_ROTATION)
def bearing_supports_rotation(row: dict, duty: Duty) -> Optional[tuple]:
    """Does this bearing carry the duty's load for the duty's life?

    ISO 281 basic rating life, computed rather than asserted. A bearing with no
    rating on file cannot be judged, so it is excluded rather than assumed
    adequate — the whole point of the confidence model is that a missing number
    is not a passing one.
    """
    from orion import calc

    if _type_allows(row, duty) is not None:
        return None
    envelope = _envelope_fits(row, duty)
    if envelope is None:
        return None

    load = duty.radial_load_N
    if load is None:
        # No load stated: the envelope is all we can judge on, and the margin
        # is how little material is wasted rather than how much life is left.
        return True, {"basis": "envelope only; no load stated"}, envelope

    rating = row.get("C_N")
    if rating is None:
        return None                     # unjudgeable, so not a candidate
    life = calc.bearing_life_l10(rating, load, duty.speed_rpm or 1500.0)
    hours = life["l10_hours"]
    wanted = duty.life_hours or 10000.0
    if hours < wanted:
        return None
    # Rank by the SMALLEST envelope that survives, not the longest life. An
    # engineer asking for 20 000 hours does not want the bearing that lasts
    # 170 000 — that one is heavier, needs a bigger housing and costs more to
    # do the same job. Life is a gate; size is the ranking.
    return True, {
        "bearing_type": _classify(row.get("designation", "")),
        "dynamic_load_rating_N": rating,
        "l10_hours": round(hours),
        "required_hours": wanted,
        "life_margin": round(hours / wanted, 1),
        "at_rpm": duty.speed_rpm or 1500.0,
        "outside_dia_mm": row.get("D"),
    }, envelope


@satisfies(BEARING, CENTERS_COMPONENT)
def bearing_centers(row: dict, duty: Duty) -> Optional[tuple]:
    envelope = _envelope_fits(row, duty)
    if envelope is None:
        return None
    return True, {"bore_mm": row.get("d"), "outside_dia_mm": row.get("D")}, envelope


def _type_allows(row: dict, duty: Duty) -> Optional[str]:
    """Whether this bearing's TYPE can take the duty at all.

    Asked before any arithmetic. A thrust bearing offered for a radial load is
    not a marginal answer, it is a wrong one, and no amount of life calculation
    makes it right.

    An unrecognised designation is excluded rather than waved through. This is
    the same rule the ingest gate runs on — a missing fact is not a passing one
    — and it is not hypothetical: 53307 is a thrust bearing whose prefix the
    table did not know, and while "unclassified means judge it on the numbers"
    it was offered as the best answer to a 3 kN radial duty. Life arithmetic
    cannot catch that, because the arithmetic was never the thing in doubt.
    """
    designation = row.get("designation", "")
    spec = _profile(_classify(designation) or "")
    if spec is None:
        needs_type = ((duty.radial_load_N or 0) > 0
                      or (duty.axial_load_N or 0) > 0
                      or (duty.misalignment_deg or 0) > 0)
        if needs_type:
            return (f"{designation} is not a recognised bearing type, so "
                    f"whether it carries this load cannot be established")
        return None                       # no load stated: type does not decide
    if (duty.radial_load_N or 0) > 0 and not spec.carries_radial:
        return f"{spec.kind} carries no radial load"
    axial = duty.axial_load_N or 0.0
    if axial > 0:
        if spec.axial_ratio <= 0:
            return f"{spec.kind} carries no thrust"
        radial = duty.radial_load_N or 0.0
        if radial > 0 and axial > radial * spec.axial_ratio:
            return (f"{spec.kind} takes about {spec.axial_ratio:g} of its "
                    f"radial load as thrust; this duty asks for more")
    if (duty.misalignment_deg or 0) > spec.misalignment_deg:
        return (f"{spec.kind} tolerates {spec.misalignment_deg:g} deg of "
                f"misalignment, the duty has {duty.misalignment_deg:g}")
    return None


def _envelope_fits(row: dict, duty: Duty) -> Optional[float]:
    """Bore and outside diameter against what the design allows.

    Returns a crude margin — smaller is tighter — or None when the component
    physically cannot go where it must.
    """
    d, D = row.get("d"), row.get("D")
    if d is None or D is None:
        return None
    if duty.bore_mm is not None and abs(d - duty.bore_mm) > 0.01:
        return None
    if duty.max_outside_dia_mm is not None and D > duty.max_outside_dia_mm:
        return None
    # Prefer the smallest envelope that works: an oversized bearing is wasted
    # material, mass and housing.
    return 1000.0 / D if D else 0.0


# --------------------------------------------------------------------------- #
# O-ring glands
# --------------------------------------------------------------------------- #
@declares(GLAND)
def gland_functions(row: dict) -> list[Implements]:
    return [
        Implements(
            function=SEALS_FLUID,
            requires=[
                Requires("groove", f"{row['groove_width_b1_min']:g}.."
                                   f"{row['groove_width_b1_max']:g} mm wide, "
                                   f"{row['gland_depth_mm']:g} mm deep"),
                Requires("counterface", "the surface the cord seals against"),
                Requires("surface_finish", "Ra 0.4 or better on a dynamic "
                                           "surface, or the cord abrades"),
                Requires("lead_in_chamfer", "so the cord is not cut during "
                                            "assembly"),
            ],
            limits={"cord_dia_mm": row.get("cord_dia_mm"),
                    "compression_pct": [row.get("compression_min_pct"),
                                        row.get("compression_max_pct")]},
            note=f"applies to: {row.get('applies_to', 'unresolved')}",
        ),
        Implements(
            function=LOCATES_PART,
            requires=[Requires("groove", "the cord seats in it")],
            note="an O-ring locates lightly; it is not a locating feature and "
                 "must not be used as one",
        ),
    ]


@satisfies(GLAND, SEALS_FLUID)
def gland_seals(row: dict, duty: Duty) -> Optional[tuple]:
    """A gland is only a candidate when its arrangement is established.

    Every row currently reads AMBIGUOUS, so this returns nothing — which is the
    correct answer. A face-seal gland offered for a piston is a seal that fails
    invisibly, and an empty result is a far better outcome than a plausible
    wrong one.
    """
    if row.get("applies_to") in (None, "", "AMBIGUOUS"):
        return None
    cord = row.get("cord_dia_mm")
    if duty.cord_dia_mm is not None and cord != duty.cord_dia_mm:
        return None
    return True, {"cord_dia_mm": cord,
                  "applies_to": row.get("applies_to"),
                  "squeeze_pct": [row.get("compression_min_pct"),
                                  row.get("compression_max_pct")]}, 1.0


def why_no_glands() -> str:
    """Said plainly, because an empty search result should explain itself."""
    return ("no gland is offered for any duty: every ingested row has an "
            "AMBIGUOUS sealing arrangement, and offering a face-seal gland for "
            "a piston would be a seal that fails invisibly. Resolve the "
            "handbook table headings and these become searchable.")
