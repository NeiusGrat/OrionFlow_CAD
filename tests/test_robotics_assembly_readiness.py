"""Tests for source/review gates on explicit robotics AssemblyGraphs."""

from orion_agent.harness import robotics_assembly as ra


def _assembly(component_id: str):
    return {
        "id": "robotics_plan",
        "parts": [
            {
                "id": "gear",
                "part_number": "ASSEMBLY-PLACEHOLDER",
                "definition": {"kind": "robotics_component", "id": component_id},
            },
            {"id": "housing", "part_number": "OF-HOUSING-001"},
        ],
        "interfaces": [
            {"id": "gear.output", "part_id": "gear", "kind": "rotary"},
            {"id": "housing.output", "part_id": "housing", "kind": "rotary"},
        ],
        "joints": [
            {
                "id": "output",
                "kind": "revolute",
                "parent_interface": "housing.output",
                "child_interface": "gear.output",
                "axis": [0, 0, 1],
                "limits": {"lower": -3.14, "upper": 3.14},
            },
        ],
    }


def test_candidate_component_keeps_plan_in_planning_only_state():
    result = ra.assess_readiness(
        _assembly("robotics.component.bldc_motor_candidate.v1")
    )

    assert result["status"] == "planning_only"
    assert any(issue["severity"] == "blocking" for issue in result["issues"])
    assert "planning_only" in ra.render_readiness(result)


def test_source_specific_component_still_requires_engineering_review():
    result = ra.assess_readiness(
        _assembly("robotics.component.harmonic_drive_csg_17_100_2a_r.v1")
    )

    assert result["status"] == "engineering_review_required"
    assert not any(issue["severity"] == "blocking" for issue in result["issues"])
    assert any("not approved" in issue["message"] for issue in result["issues"])


def test_unknown_component_blocks_readiness():
    result = ra.assess_readiness(_assembly("robotics.component.unknown.v1"))

    assert result["status"] == "planning_only"
    assert "not in the controlled knowledge package" in ra.render_readiness(result)
