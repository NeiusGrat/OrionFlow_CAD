"""Which kind of bearing a designation names, and what that kind is good at.

"Support a rotating shaft" is not enough to choose a bearing. A deep groove ball
bearing and a taper roller can share an envelope — a 6205 and a 30205 are both
25 x 52 — and they are not interchangeable: the taper carries nearly three times
the radial load and takes thrust in one direction only, while the deep groove
takes light thrust either way and tolerates almost no misalignment.

Answering "radial load? axial load? speed? alignment?" *before* picking a part is
what an engineer does, and it needs the type as a first-class fact rather than a
prefix nobody reads.

The prefix rules are ISO/manufacturer convention. They are asserted here but not
trusted: a classification is checked against the row's own ratings, because the
types have different load signatures and a misfiled row shows up as one whose
numbers do not behave like its label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

DEEP_GROOVE_BALL = "deep_groove_ball_bearing"
ANGULAR_CONTACT_BALL = "angular_contact_ball_bearing"
SELF_ALIGNING_BALL = "self_aligning_ball_bearing"
TAPER_ROLLER = "taper_roller_bearing"
CYLINDRICAL_ROLLER = "cylindrical_roller_bearing"
SPHERICAL_ROLLER = "spherical_roller_bearing"
NEEDLE_ROLLER = "needle_roller_bearing"
THRUST_BALL = "thrust_ball_bearing"
THRUST_ROLLER = "thrust_roller_bearing"

#: Longest prefix wins, so 618 is matched before 61 and 302 before 30.
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("160", DEEP_GROOVE_BALL), ("618", DEEP_GROOVE_BALL),
    ("619", DEEP_GROOVE_BALL), ("622", DEEP_GROOVE_BALL),
    ("623", DEEP_GROOVE_BALL),
    ("302", TAPER_ROLLER), ("303", TAPER_ROLLER), ("304", TAPER_ROLLER),
    ("313", TAPER_ROLLER), ("320", TAPER_ROLLER), ("322", TAPER_ROLLER),
    ("323", TAPER_ROLLER), ("329", TAPER_ROLLER), ("330", TAPER_ROLLER),
    ("331", TAPER_ROLLER), ("332", TAPER_ROLLER),
    ("511", THRUST_BALL), ("512", THRUST_BALL), ("513", THRUST_BALL),
    ("514", THRUST_BALL), ("522", THRUST_BALL), ("532", THRUST_BALL),
    ("542", THRUST_BALL),
    ("292", THRUST_ROLLER), ("293", THRUST_ROLLER), ("294", THRUST_ROLLER),
    ("213", SPHERICAL_ROLLER), ("222", SPHERICAL_ROLLER),
    ("223", SPHERICAL_ROLLER), ("230", SPHERICAL_ROLLER),
    ("231", SPHERICAL_ROLLER), ("232", SPHERICAL_ROLLER),
    ("240", SPHERICAL_ROLLER), ("241", SPHERICAL_ROLLER),
    ("60", DEEP_GROOVE_BALL), ("62", DEEP_GROOVE_BALL),
    ("63", DEEP_GROOVE_BALL), ("64", DEEP_GROOVE_BALL),
    ("72", ANGULAR_CONTACT_BALL), ("73", ANGULAR_CONTACT_BALL),
    ("70", ANGULAR_CONTACT_BALL), ("71", ANGULAR_CONTACT_BALL),
    ("12", SELF_ALIGNING_BALL), ("13", SELF_ALIGNING_BALL),
    ("22", SPHERICAL_ROLLER), ("23", SPHERICAL_ROLLER),
    ("10", SELF_ALIGNING_BALL),
)


@dataclass(frozen=True)
class TypeProfile:
    """What a bearing type is for, in the terms a duty is stated in.

    ``axial_ratio`` is the share of the dynamic rating that may be taken as
    thrust — a rule of thumb, and labelled as one. It is here to let a planner
    *rule types out*, which is a much safer use than sizing to it.
    """

    kind: str
    carries_radial: bool
    axial_ratio: float                 # 0 = none, 1.0 = designed for thrust
    axial_both_directions: bool
    misalignment_deg: float            # what it tolerates before it complains
    relative_radial_capacity: float    # vs a deep groove of the same envelope
    #: Tiebreak when several types fit. A deep groove is the ordinary answer:
    #: cheapest, quietest, fastest, no preload to set and no opposed partner to
    #: mount. Reaching for a taper roller on a light radial duty is a more
    #: expensive bearing and a more expensive assembly around it, so ties go to
    #: the simpler part.
    preference: int = 50
    note: str = ""
    caution: str = ""


PROFILES: dict[str, TypeProfile] = {
    DEEP_GROOVE_BALL: TypeProfile(
        DEEP_GROOVE_BALL, True, 0.25, True, 0.05, 1.0,
        10,
        "the default: cheap, quiet, fast, takes light thrust either way",
        "tolerates almost no misalignment — a shaft that deflects needs "
        "a self-aligning or spherical type"),
    ANGULAR_CONTACT_BALL: TypeProfile(
        ANGULAR_CONTACT_BALL, True, 0.7, False, 0.03, 1.1,
        30,
        "designed for combined radial and one-directional thrust",
        "takes thrust in ONE direction; needs an opposed second bearing or a "
        "matched pair"),
    SELF_ALIGNING_BALL: TypeProfile(
        SELF_ALIGNING_BALL, True, 0.2, True, 2.5, 0.7,
        35,
        "two ball rows on a spherical outer raceway: accepts real "
        "misalignment",
        "lower radial capacity than a deep groove of the same size"),
    TAPER_ROLLER: TypeProfile(
        TAPER_ROLLER, True, 0.9, False, 0.05, 2.5,
        50,
        "line contact: heavy combined radial and axial load",
        "one direction only, and it must be mounted against an opposed "
        "bearing and set to the right preload"),
    CYLINDRICAL_ROLLER: TypeProfile(
        CYLINDRICAL_ROLLER, True, 0.0, False, 0.07, 2.2,
        40,
        "very high radial capacity; the rings can move axially",
        "carries NO thrust in the plain form — something else must locate "
        "the shaft"),
    SPHERICAL_ROLLER: TypeProfile(
        SPHERICAL_ROLLER, True, 0.25, True, 1.5, 2.8,
        60,
        "heavy load and real misalignment together",
        "large, expensive, and slower than a ball bearing"),
    NEEDLE_ROLLER: TypeProfile(
        NEEDLE_ROLLER, True, 0.0, False, 0.02, 1.8,
        45,
        "high radial capacity in a small radial envelope",
        "no thrust capacity, and it needs a hardened, ground raceway"),
    THRUST_BALL: TypeProfile(
        THRUST_BALL, False, 1.0, False, 0.0, 0.0,
        70,
        "pure axial load, one direction",
        "carries NO radial load at all — it cannot support a shaft on its own"),
    THRUST_ROLLER: TypeProfile(
        THRUST_ROLLER, False, 1.0, False, 0.03, 0.0,
        75,
        "heavy pure axial load",
        "carries no meaningful radial load"),
}


def classify(designation: str) -> Optional[str]:
    """The type a designation names, or None when the convention does not say."""
    core = re.match(r"^\s*(\d{3,5})", str(designation or ""))
    if not core:
        return None
    text = core.group(1)
    for prefix, kind in sorted(_PREFIXES, key=lambda p: -len(p[0])):
        if text.startswith(prefix):
            return kind
    return None


def profile(kind: str) -> Optional[TypeProfile]:
    return PROFILES.get(kind)


# --------------------------------------------------------------------------- #
def ratings_match_the_type(row: dict, kind: str) -> Optional[str]:
    """Check a classification against the row's own numbers.

    The types have different load signatures, so a misfiled row shows up as one
    whose ratings do not behave like its label:

    * a **thrust** bearing's static rating exceeds its dynamic one, because it
      is built to be loaded standing still along its axis. A radial bearing is
      the other way round.
    * a **roller** bearing makes line contact rather than point contact, so at
      the same envelope it out-rates a ball bearing substantially — a 30205
      rates 38.1 kN against a 6205's 14.8 kN on an identical 25x52.

    Returns the disagreement, or None when the label and the numbers agree.
    """
    c, c0 = row.get("C_N"), row.get("C0_N")
    if c is None or c0 is None:
        return None                       # unjudgeable, not wrong
    is_thrust = kind in (THRUST_BALL, THRUST_ROLLER)
    if is_thrust and c0 <= c:
        return (f"{row.get('designation')} is labelled {kind} but its static "
                f"rating {c0:g} does not exceed its dynamic {c:g}, which is "
                f"not how a thrust bearing behaves")
    if not is_thrust and c0 > c * 1.6:
        return (f"{row.get('designation')} is labelled {kind} but its static "
                f"rating {c0:g} far exceeds its dynamic {c:g} — that is a "
                f"thrust signature")
    return None


@dataclass
class TypeChoice:
    """A type the duty allows, with the reason it survived or did not."""

    kind: str
    suitable: bool
    reason: str
    profile: Optional[TypeProfile] = None
    concerns: list[str] = field(default_factory=list)


def choose_types(radial_N: float = 0.0, axial_N: float = 0.0,
                 misalignment_deg: float = 0.0,
                 speed_rpm: float = 0.0) -> list[TypeChoice]:
    """Which bearing types the duty permits, before any part is selected.

    This is the question that comes first. Asking it separately is what stops a
    search offering a thrust bearing to carry a radial load, or a deep groove to
    a shaft that deflects two degrees.
    """
    out: list[TypeChoice] = []
    for kind, spec in PROFILES.items():
        concerns: list[str] = []
        if radial_N > 0 and not spec.carries_radial:
            out.append(TypeChoice(kind, False,
                                  f"carries no radial load, and the duty has "
                                  f"{radial_N:g} N of it", spec))
            continue
        if axial_N > 0:
            if spec.axial_ratio <= 0.0:
                out.append(TypeChoice(kind, False,
                                      f"carries no thrust, and the duty has "
                                      f"{axial_N:g} N of it", spec))
                continue
            if radial_N > 0 and axial_N > radial_N * spec.axial_ratio:
                out.append(TypeChoice(
                    kind, False,
                    f"thrust {axial_N:g} N exceeds about {spec.axial_ratio:g} "
                    f"of the radial {radial_N:g} N, which is past what this "
                    f"type takes alongside a radial load", spec))
                continue
            if not spec.axial_both_directions:
                concerns.append("takes thrust in one direction only — it needs "
                                "an opposed bearing")
        if misalignment_deg > spec.misalignment_deg:
            out.append(TypeChoice(
                kind, False,
                f"tolerates {spec.misalignment_deg:g} deg of misalignment and "
                f"the duty has {misalignment_deg:g}", spec))
            continue
        if spec.caution:
            concerns.append(spec.caution)
        out.append(TypeChoice(kind, True, spec.note, spec, concerns))

    # Suitable first, then by radial capacity: the cheapest adequate type is
    # usually the smallest-capacity one that survives, and a planner reading
    # top-down should meet the ordinary answer before the exotic one.
    out.sort(key=lambda c: (not c.suitable,
                            c.profile.preference if c.profile else 99))
    return out
