"""§8.3 family registry. `family` doubles as the cluster key for
statistics (score/stats.py's clustered bootstrap) -- variants of one
master part are not independent samples. `tasks lint` uses this to catch
a typo'd family name before it silently creates a cluster of one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyInfo:
    name: str
    pillar: str
    description: str


FAMILIES: dict[str, FamilyInfo] = {
    "prismatic_plate": FamilyInfo(
        "prismatic_plate", "modify", "Sketch/pad/pocket/pattern plates and flanges"
    ),
    "feature_coverage": FamilyInfo(
        "feature_coverage",
        "modify",
        "One task per build123d feature with little/no training coverage "
        "(fillet, chamfer, pattern, mirror, loft, ...)",
    ),
    "tag_stability": FamilyInfo(
        "tag_stability",
        "modify",
        "A named feature (e.g. a labeled hole) must still resolve to the "
        "right geometry after rebuild",
    ),
    "bracket_gusseted": FamilyInfo(
        "bracket_gusseted", "design", "Load paths, fillets, feasibility under FEA targets"
    ),
    "flange_rotational": FamilyInfo(
        "flange_rotational", "reconstruct", "Existing strength family, capped at 15% of the suite"
    ),
    "envelope_fit": FamilyInfo(
        "envelope_fit", "design", "Keep-in/keep-out volumes, interface positions"
    ),
    "dfm_machinable": FamilyInfo(
        "dfm_machinable", "design", "Tool access, wall minimums, setup count"
    ),
    "spec_intake": FamilyInfo(
        "spec_intake", "query", "Messy brief -> spec; gated on well-posedness, not prose"
    ),
    "repair": FamilyInfo(
        "repair", "modify", "Given a failing artifact + structured failure summary, fix it"
    ),
}


def is_known_family(name: str) -> bool:
    return name in FAMILIES
