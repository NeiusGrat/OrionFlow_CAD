"""Fault injection — deliberate, labeled damage to a resolved FeatureGraph.

Two jobs: (1) unit-test the verifier itself (a verifier that cannot catch a
known fault certifies nothing), and (2) manufacture repair-trace training
data with ground-truth diagnoses attached.

Each injector takes a resolved graph and returns
``(mutated_copy, {fault, feature, description, expected_signature})`` or
``None`` when the graph has no site for that fault. Injectors never modify
the input in place — the clean graph must survive for the comparison.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

FAULT_TAXONOMY = [
    "wrong_sidetype",             # two-sided pad rebuilt one-sided (half height)
    "missing_sections_dependency",  # loft with no section sketches
    "missing_spine_dependency",     # sweep with no path
    "pattern_overlap",              # pattern instances intersect
    "fillet_radius_exceeds_adjacent",
    "self_intersecting_sweep",
    "loft_twist_mismatch",
    "over_constrained_sketch",
    "draft_self_intersection",
]


def inject_wrong_sidetype(graph: dict[str, Any]) -> Optional[tuple]:
    """Strip SideType/Length2 from the first two-sided extrusion — the exact
    compiler bug found 2026-07-22 (half-height pad, recomputes clean)."""
    g = copy.deepcopy(graph)
    for f in g.get("features", []):
        p = f.get("parameters") or {}
        if f.get("type") in ("Pad", "Pocket") and p.get("SideType") == "Two sides":
            p.pop("SideType", None)
            p.pop("Length2", None)
            p.pop("Midplane", None)
            return g, {
                "fault": "wrong_sidetype",
                "feature": f["id"],
                "description": "two-sided extrusion stripped to one-sided; "
                               "builds clean at half the volume",
                "expected_signature": "feature tool volume ~= 50% of predicted",
            }
    return None


def inject_missing_sections(graph: dict[str, Any]) -> Optional[tuple]:
    g = copy.deepcopy(graph)
    for f in g.get("features", []):
        if f.get("type") == "Loft":
            (f.get("parameters") or {}).pop("_Sections", None)
            g["dependencies"] = [d for d in g.get("dependencies", [])
                                 if not (d.get("target") == f["id"]
                                         and d.get("kind") == "section")]
            return g, {
                "fault": "missing_sections_dependency", "feature": f["id"],
                "description": "loft stripped of its section list",
                "expected_signature": "compile error: Loft needs _Sections",
            }
    return None


def inject_missing_spine(graph: dict[str, Any]) -> Optional[tuple]:
    g = copy.deepcopy(graph)
    for f in g.get("features", []):
        if f.get("type") == "Sweep":
            (f.get("parameters") or {}).pop("_Spine", None)
            g["dependencies"] = [d for d in g.get("dependencies", [])
                                 if not (d.get("target") == f["id"]
                                         and d.get("kind") == "spine")]
            return g, {
                "fault": "missing_spine_dependency", "feature": f["id"],
                "description": "sweep stripped of its spine path",
                "expected_signature": "compile error: Sweep needs _Spine",
            }
    return None


INJECTORS = {
    "wrong_sidetype": inject_wrong_sidetype,
    "missing_sections_dependency": inject_missing_sections,
    "missing_spine_dependency": inject_missing_spine,
}
