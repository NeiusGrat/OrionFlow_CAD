"""Readiness gates that join AssemblyGraph plans to robotics knowledge records.

An AssemblyGraph can be structurally valid while still being unfit for CAD
release: a motor might be a family-level candidate, or a custom plate could
lack a selected mating component.  This module makes that distinction explicit
and deterministic.  It does not calculate strength, collision, or safety.
"""

from __future__ import annotations

from typing import Any

from orion_agent.harness import assembly_graph as ag
from orion_agent.harness import robotics_knowledge as rk


def assess_readiness(data: Any) -> dict[str, Any]:
    """Assess a structurally valid assembly plan's component provenance.

    Part definitions can reference robotics knowledge using either
    ``{"kind": "robotics_component", "id": "..."}`` or
    ``{"component_id": "..."}``.  A plan with candidates is valid for
    concept work but never release-ready.
    """
    graph = data if isinstance(data, ag.AssemblyGraph) else ag.parse_assembly_graph(data)
    structural_errors = graph.validate()
    if structural_errors:
        return {
            "status": "invalid_assembly_graph",
            "structural_errors": structural_errors,
            "issues": [],
            "summary": "AssemblyGraph must be structurally valid before readiness review.",
        }

    issues: list[dict[str, Any]] = []
    component_records: list[dict[str, Any]] = []
    for part in graph.parts:
        definition = dict(part.definition)
        component_id = definition.get("component_id", definition.get("id"))
        if definition.get("kind") not in {"robotics_component", "purchased_component"}:
            component_id = definition.get("component_id")
        if not component_id:
            issues.append({
                "severity": "review_required",
                "part_instance": part.id,
                "message": "No robotics component reference; custom part needs its selected interfaces, material, process, and verification evidence.",
            })
            continue
        record = rk.get("component", str(component_id))
        if record is None:
            issues.append({
                "severity": "blocking",
                "part_instance": part.id,
                "component_id": component_id,
                "message": "Referenced robotics component is not in the controlled knowledge package.",
            })
            continue
        component_records.append(record)
        status = record.get("data_status", "unknown")
        review = record.get("engineering_review", "required")
        if status != "source_specific":
            issues.append({
                "severity": "blocking",
                "part_instance": part.id,
                "component_id": component_id,
                "data_status": status,
                "message": "Component is not source-specific; exact manufacturer part number and controlled drawing are required.",
            })
        if review != "approved":
            issues.append({
                "severity": "review_required",
                "part_instance": part.id,
                "component_id": component_id,
                "engineering_review": review,
                "message": "Component engineering review is not approved for release.",
            })
        required = record.get("required_selection_inputs", [])
        if required and status != "source_specific":
            issues.append({
                "severity": "review_required",
                "part_instance": part.id,
                "component_id": component_id,
                "message": "Selection inputs still required: " + "; ".join(required),
            })

    if any(issue["severity"] == "blocking" for issue in issues):
        status = "planning_only"
    elif issues:
        status = "engineering_review_required"
    else:
        status = "provenance_ready_not_verified"
    return {
        "status": status,
        "structural_errors": [],
        "issues": issues,
        "components": component_records,
        "summary": _summary(status, len(component_records), len(issues)),
        "limitations": [
            "This review checks only AssemblyGraph structure and component provenance.",
            "It does not establish mate solution, collision clearance, loads, fatigue, DFM, electrical safety, functional safety, or supplier approval.",
        ],
    }


def _summary(status: str, components: int, issues: int) -> str:
    return (
        f"Robotics assembly readiness: {status}; {components} controlled component "
        f"record(s) examined; {issues} issue(s)."
    )


def render_readiness(result: dict[str, Any]) -> str:
    """Render provenance gates clearly in an LLM-safe tool observation."""
    lines = [result["summary"]]
    for error in result.get("structural_errors", []):
        lines.append("- invalid: " + error)
    for issue in result.get("issues", []):
        label = issue.get("severity", "review_required")
        target = issue.get("part_instance", "assembly")
        lines.append(f"- {label} [{target}]: {issue['message']}")
    if not result.get("issues") and not result.get("structural_errors"):
        lines.append("- provenance record checks passed; engineering verification remains required.")
    lines.append("- limitation: " + " ".join(result.get("limitations", [])))
    return "\n".join(lines)


__all__ = ["assess_readiness", "render_readiness"]
