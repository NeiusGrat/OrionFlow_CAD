"""Analysis: deterministic DFM checks and mass estimate for a generated part.

The skeptic layer — everything here is computed from the mesh and the rule
tables, never asserted by an LLM.
"""

from __future__ import annotations

import trimesh

from .knowledge import KnowledgeBase, get_knowledge_base


def select_process(material_key: str, kb: KnowledgeBase) -> str:
    return kb.material(material_key)["typical_processes"][0]


def analyze_part(
    stl_path: str,
    material_key: str,
    kb: KnowledgeBase | None = None,
    process: str | None = None,
) -> dict:
    """Return properties, issues (severity-rated), and a manufacturability score."""
    kb = kb or get_knowledge_base()
    material = kb.material(material_key)
    process = process or select_process(material_key, kb)
    rules = kb.dfm_rules.get(process, {})

    mesh = trimesh.load(stl_path)
    extents = [float(v) for v in (mesh.bounds[1] - mesh.bounds[0])]
    volume_mm3 = float(mesh.volume)
    mass_g = volume_mm3 / 1000.0 * material["density_g_cm3"]

    issues: list[dict] = []

    if not mesh.is_watertight:
        issues.append(
            {
                "severity": "critical",
                "issue": "Mesh is not watertight — geometry has open faces",
                "fix": "Check boolean operations for disjoint or tangent solids",
            }
        )

    min_extent = min(extents)
    min_wall = rules.get("min_wall_thickness_mm")
    if min_wall and min_extent < min_wall:
        issues.append(
            {
                "severity": "critical",
                "issue": f"Thinnest dimension {min_extent:.2f} mm is below the "
                f"{process} minimum wall of {min_wall} mm",
                "fix": f"Thicken to at least {min_wall} mm",
            }
        )

    # Solidity ratio: how much of the bbox is material. Very low = spindly.
    bbox_volume = extents[0] * extents[1] * extents[2]
    solidity = volume_mm3 / bbox_volume if bbox_volume > 0 else 0
    if solidity < 0.05:
        issues.append(
            {
                "severity": "warning",
                "issue": f"Material fills only {solidity:.0%} of the bounding box — "
                "part may be fragile or features may be disconnected",
                "fix": "Verify all features are fused to the main body",
            }
        )

    aspect = max(extents) / max(min_extent, 1e-6)
    if aspect > 25:
        issues.append(
            {
                "severity": "warning",
                "issue": f"Aspect ratio {aspect:.0f}:1 — long thin parts warp "
                f"({process})",
                "fix": "Add ribs or increase the thin dimension",
            }
        )

    score = 100
    for issue in issues:
        score -= 40 if issue["severity"] == "critical" else 10
    score = max(score, 0)

    return {
        "process": process,
        "material": material_key,
        "properties": {
            "volume_cm3": round(volume_mm3 / 1000.0, 2),
            "mass_g": round(mass_g, 1),
            "bbox_mm": [round(v, 1) for v in extents],
            "center_of_mass_mm": [round(float(v), 2) for v in mesh.center_mass],
            "watertight": bool(mesh.is_watertight),
            "solidity": round(solidity, 3),
        },
        "issues": issues,
        "manufacturability_score": score,
    }
