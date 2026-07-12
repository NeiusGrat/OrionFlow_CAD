"""Retrieval and deterministic calculations for OrionFlow's knowledge layer.

The data lives in :mod:`orion_agent.knowledge.mechanical`, while this module
provides the stable, stdlib-only API exposed to the agent.  It intentionally
keeps a source's authority and maturity visible: a supplier guideline is useful
for screening but is never silently promoted to a standards-compliance claim.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


_ROOT = Path(__file__).resolve().parents[1] / "knowledge" / "mechanical"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_REQUIRED_ITEM_FIELDS = {
    "id", "domain", "kind", "title", "summary", "authority", "maturity",
    "sources", "tags", "agent_guidance",
}
_ALIASES = {
    "bending": "bend",
    "bends": "bend",
    "gdt": "gdt",
    "gd": "gdt",
    "tolerance": "tolerancing",
    "tolerances": "tolerancing",
    "thread": "threads",
    "threads": "threads",
}


class KnowledgeInputError(ValueError):
    """Raised for invalid calculator or validator inputs."""


def _read_json(name: str) -> dict[str, Any]:
    with (_ROOT / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def sources() -> dict[str, dict[str, Any]]:
    """Return source records keyed by stable source identifier."""
    data = _read_json("sources.json")
    return {record["id"]: dict(record) for record in data["sources"]}


@lru_cache(maxsize=1)
def items() -> tuple[dict[str, Any], ...]:
    """Return immutable-in-practice copies of the packaged knowledge items."""
    data = _read_json("knowledge.json")
    return tuple(dict(item) for item in data["items"])


def validate_package() -> list[str]:
    """Validate package integrity without requiring a JSON-schema dependency."""
    errors: list[str] = []
    source_ids = set(sources())
    seen: set[str] = set()
    for item in items():
        item_id = item.get("id", "<missing id>")
        missing = _REQUIRED_ITEM_FIELDS - set(item)
        if missing:
            errors.append(f"{item_id}: missing {', '.join(sorted(missing))}")
        if item_id in seen:
            errors.append(f"duplicate knowledge item id: {item_id}")
        seen.add(item_id)
        for source_id in item.get("sources", []):
            if source_id not in source_ids:
                errors.append(f"{item_id}: unknown source {source_id}")
    return errors


def get(item_id: str) -> Optional[dict[str, Any]]:
    """Fetch one knowledge item by stable identifier."""
    for item in items():
        if item["id"] == item_id:
            return dict(item)
    return None


def _tokens(value: str) -> set[str]:
    out = set()
    for token in _TOKEN_RE.findall(value.lower()):
        out.add(token)
        if token in _ALIASES:
            out.add(_ALIASES[token])
    return out


def _searchable_text(item: dict[str, Any]) -> str:
    return " ".join([
        item["id"], item["domain"], item["kind"], item["title"],
        item["summary"], " ".join(item.get("tags", [])),
        " ".join(item.get("conditions", [])), item.get("agent_guidance", ""),
    ])


def search(query: str, domain: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """Search concise knowledge items and retain their provenance metadata."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    domain = domain.strip().lower()
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in items():
        if domain and item["domain"].lower() != domain:
            continue
        text_tokens = _tokens(_searchable_text(item))
        score = len(query_tokens & text_tokens)
        if query.lower() in item["title"].lower():
            score += 3
        if score:
            enriched = dict(item)
            enriched["source_records"] = [
                dict(sources()[source_id]) for source_id in item["sources"]
            ]
            ranked.append((score, item["id"], enriched))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [item for _, _, item in ranked[:max(1, min(limit, 10))]]


def render(results: list[dict[str, Any]]) -> str:
    """Render compact, source-aware retrieval observations for the model."""
    lines: list[str] = []
    for item in results:
        readable_authority = item["authority"].replace("_", " ")
        source_text = "; ".join(
            f"{source['title']} [{source['kind']}]"
            for source in item.get("source_records", [])
        )
        lines.append(
            f"- {item['title']} ({item['id']}; authority={item['authority']}; "
            f"{readable_authority}; maturity={item['maturity']}): {item['summary']}"
        )
        if item.get("conditions"):
            lines.append("  Conditions: " + " ".join(item["conditions"]))
        lines.append("  Agent guidance: " + item["agent_guidance"])
        lines.append("  Sources: " + source_text)
    return "\n".join(lines)


def _positive(value: Any, name: str, *, allow_zero: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise KnowledgeInputError(f"{name} must be a finite number") from exc
    if not math.isfinite(parsed) or (parsed < 0 if allow_zero else parsed <= 0):
        comparator = "non-negative" if allow_zero else "greater than zero"
        raise KnowledgeInputError(f"{name} must be finite and {comparator}")
    return parsed


def calculate_bend(
    *,
    thickness_mm: Any,
    inside_radius_mm: Any,
    bend_angle_deg: Any,
    k_factor: Any,
    flange_a_mm: Any = None,
    flange_b_mm: Any = None,
) -> dict[str, Any]:
    """Calculate single-bend allowance/deduction from the packaged formula.

    ``flange_a_mm`` and ``flange_b_mm`` are optional outside flange dimensions.
    When both are supplied, the result includes their preliminary flat length.
    """
    thickness = _positive(thickness_mm, "thickness_mm")
    radius = _positive(inside_radius_mm, "inside_radius_mm", allow_zero=True)
    angle = _positive(bend_angle_deg, "bend_angle_deg")
    k_factor_value = _positive(k_factor, "k_factor", allow_zero=True)
    if angle >= 180:
        raise KnowledgeInputError("bend_angle_deg must be less than 180")
    if k_factor_value > 1:
        raise KnowledgeInputError("k_factor must be between 0 and 1")
    if (flange_a_mm is None) != (flange_b_mm is None):
        raise KnowledgeInputError("provide both flange_a_mm and flange_b_mm, or neither")

    allowance = math.pi * (radius + k_factor_value * thickness) * angle / 180.0
    deduction = 2.0 * (radius + thickness) * math.tan(math.radians(angle) / 2.0) - allowance
    result: dict[str, Any] = {
        "calculation": "sheet_metal.bend_allowance.v1",
        "inputs": {
            "thickness_mm": thickness,
            "inside_radius_mm": radius,
            "bend_angle_deg": angle,
            "k_factor": k_factor_value,
        },
        "bend_allowance_mm": allowance,
        "bend_deduction_mm": deduction,
        "authority": "secondary_reference",
        "maturity": "screening_calculator",
        "source_ids": ["drafter_sheet_metal_dfm_2025"],
        "limitations": [
            "K-factor must be validated for the material, thickness, tooling, and forming process.",
            "Confirm the flat pattern with the fabricator before release.",
        ],
    }
    if flange_a_mm is not None:
        flange_a = _positive(flange_a_mm, "flange_a_mm")
        flange_b = _positive(flange_b_mm, "flange_b_mm")
        result["inputs"]["flange_a_mm"] = flange_a
        result["inputs"]["flange_b_mm"] = flange_b
        result["preliminary_flat_length_mm"] = flange_a + flange_b - deduction
    return result


def render_bend_calculation(result: dict[str, Any]) -> str:
    """Render a calculation result for tool feedback, including limitations."""
    lines = [
        "Sheet-metal bend calculation (screening estimate, not release approval):",
        f"- bend allowance: {result['bend_allowance_mm']:.4f} mm",
        f"- bend deduction: {result['bend_deduction_mm']:.4f} mm",
    ]
    if "preliminary_flat_length_mm" in result:
        lines.append(
            f"- preliminary flat length: {result['preliminary_flat_length_mm']:.4f} mm"
        )
    lines.append("- source: Drafter Hardware FYI Sheet Metal DFM (secondary reference)")
    lines.append("- limitation: " + " ".join(result["limitations"]))
    return "\n".join(lines)


def check_sheet_metal_dfm(
    *,
    thickness_mm: Any,
    inside_radius_mm: Any = None,
    hole_diameter_mm: Any = None,
    hole_spacing_mm: Any = None,
    hole_edge_distance_mm: Any = None,
    bend_relief_width_mm: Any = None,
    bend_relief_depth_mm: Any = None,
) -> dict[str, Any]:
    """Run scoped, source-aware sheet-metal DFM screening checks.

    This intentionally reports hole-edge distance as ``review_required`` because
    the supplied source's text and illustration disagree.  It is safer to
    preserve that ambiguity than to invent a production threshold.
    """
    thickness = _positive(thickness_mm, "thickness_mm")
    radius = None if inside_radius_mm is None else _positive(
        inside_radius_mm, "inside_radius_mm", allow_zero=True
    )
    checks: list[dict[str, Any]] = []

    def compare(check_id: str, observed: Any, threshold: float, label: str) -> None:
        value = _positive(observed, check_id)
        checks.append({
            "id": check_id,
            "status": "pass" if value >= threshold else "warning",
            "observed_mm": value,
            "minimum_mm": threshold,
            "message": f"{label}: observed {value:g} mm; screening minimum {threshold:g} mm.",
            "source_ids": ["drafter_sheet_metal_dfm_2025"],
        })

    if hole_diameter_mm is not None:
        compare("minimum_hole_diameter", hole_diameter_mm, thickness, "Hole diameter")
    if hole_spacing_mm is not None:
        compare("minimum_hole_spacing", hole_spacing_mm, 2.0 * thickness, "Hole spacing")
    if bend_relief_width_mm is not None:
        compare("minimum_bend_relief_width", bend_relief_width_mm, thickness / 2.0,
                "Bend-relief width")
    if bend_relief_depth_mm is not None:
        if radius is None:
            raise KnowledgeInputError(
                "inside_radius_mm is required when bend_relief_depth_mm is provided"
            )
        compare("minimum_bend_relief_depth", bend_relief_depth_mm,
                thickness + radius + 0.508, "Bend-relief depth")
    if hole_edge_distance_mm is not None:
        value = _positive(hole_edge_distance_mm, "hole_edge_distance_mm")
        checks.append({
            "id": "hole_to_edge_distance",
            "status": "review_required",
            "observed_mm": value,
            "message": (
                "No automatic threshold applied: the supplied guide's text and diagram "
                "conflict on hole-to-edge distance. Confirm the supplier-specific rule."
            ),
            "source_ids": ["drafter_sheet_metal_dfm_2025"],
        })

    if any(check["status"] == "warning" for check in checks):
        overall = "needs_attention"
    elif any(check["status"] == "review_required" for check in checks):
        overall = "review_required"
    else:
        overall = "screening_passed"
    return {
        "overall": overall,
        "authority": "screening_guideline",
        "maturity": "screening_only",
        "checks": checks,
        "limitations": [
            "These are preliminary DFM screens, not supplier approval or compliance evidence.",
            "Material, process, tooling, and supplier capability can require stricter limits.",
        ],
    }


def render_dfm_check(result: dict[str, Any]) -> str:
    """Render source-aware screening results for the agent."""
    lines = [
        f"Sheet-metal DFM screening: {result['overall']} "
        "(guideline only; supplier confirmation required)."
    ]
    if not result["checks"]:
        lines.append("- no optional feature dimensions were supplied for checking")
    for check in result["checks"]:
        lines.append(f"- {check['status']}: {check['message']}")
    lines.append("- limitations: " + " ".join(result["limitations"]))
    return "\n".join(lines)
