"""Tests for the source-aware mechanical knowledge layer."""

import math

import pytest

from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel
from orion_agent.harness import mechanical_knowledge as mk
from orion_agent.harness.agent.pillars import GENERATE_PILLAR, QUERY_PILLAR
from orion_agent.harness.tools.registry import build_registry


def test_knowledge_package_has_valid_sources_and_items():
    assert mk.validate_package() == []
    assert "asme_y14_5_2018_r2024" in mk.sources()
    assert mk.get("sheet_metal.bend_allowance.v1")["kind"] == "calculation"


def test_search_retains_authority_and_provenance():
    results = mk.search("datum reference frame", domain="gdt")
    assert results
    first = results[0]
    assert first["id"] == "gdt.datum_reference_frame.basics.v1"
    assert first["authority"] == "secondary_reference"
    assert first["source_records"][0]["id"] == "drafter_gdt_cheat_sheet_v2_2025"
    rendered = mk.render(results)
    assert "authority=secondary_reference" in rendered
    assert "Drafter's GD&T Cheat Sheet V2" in rendered


def test_bend_calculation_matches_packaged_formula():
    result = mk.calculate_bend(
        thickness_mm=1.5,
        inside_radius_mm=1.5,
        bend_angle_deg=90,
        k_factor=0.33,
        flange_a_mm=50,
        flange_b_mm=50,
    )
    expected_allowance = math.pi * (1.5 + 0.33 * 1.5) / 2
    expected_deduction = 2 * (1.5 + 1.5) - expected_allowance
    assert result["bend_allowance_mm"] == pytest.approx(expected_allowance)
    assert result["bend_deduction_mm"] == pytest.approx(expected_deduction)
    assert result["preliminary_flat_length_mm"] == pytest.approx(
        100 - expected_deduction
    )
    assert "fabricator" in mk.render_bend_calculation(result)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "thickness_mm": 0,
            "inside_radius_mm": 1,
            "bend_angle_deg": 90,
            "k_factor": 0.4,
        },
        {
            "thickness_mm": 1,
            "inside_radius_mm": 1,
            "bend_angle_deg": 180,
            "k_factor": 0.4,
        },
        {
            "thickness_mm": 1,
            "inside_radius_mm": 1,
            "bend_angle_deg": 90,
            "k_factor": 1.1,
        },
    ],
)
def test_bend_calculation_rejects_unsafe_inputs(kwargs):
    with pytest.raises(mk.KnowledgeInputError):
        mk.calculate_bend(**kwargs)


def test_sheet_metal_screen_marks_conflicting_edge_source_for_review():
    result = mk.check_sheet_metal_dfm(
        thickness_mm=2,
        inside_radius_mm=2,
        hole_diameter_mm=1.5,
        hole_spacing_mm=4,
        hole_edge_distance_mm=3,
        bend_relief_width_mm=1,
        bend_relief_depth_mm=4.508,
    )
    by_id = {check["id"]: check for check in result["checks"]}
    assert result["overall"] == "needs_attention"
    assert by_id["minimum_hole_diameter"]["status"] == "warning"
    assert by_id["minimum_hole_spacing"]["status"] == "pass"
    assert by_id["hole_to_edge_distance"]["status"] == "review_required"
    assert "supplier confirmation" in mk.render_dfm_check(result)


def test_agent_tools_are_available_and_preserve_limitations():
    reg = build_registry(SyntheticBridge(SyntheticModel(name="X")), sandbox=None)
    knowledge = reg.execute("lookup_mechanical_knowledge", {"query": "bend relief"})
    assert knowledge.ok
    assert "screening guideline" in knowledge.content.lower()

    bend = reg.execute(
        "calculate_sheet_metal_bend",
        {
            "thickness_mm": 1.5,
            "inside_radius_mm": 1.5,
            "bend_angle_deg": 90,
            "k_factor": 0.33,
        },
    )
    assert bend.ok and "bend allowance" in bend.content.lower()

    dfm = reg.execute(
        "check_sheet_metal_dfm",
        {
            "thickness_mm": 2,
            "hole_diameter_mm": 1.5,
        },
    )
    assert dfm.ok and "needs_attention" in dfm.content


def test_all_agent_routes_receive_the_mechanical_knowledge_tools():
    for tool_name in {
        "lookup_mechanical_knowledge",
        "calculate_sheet_metal_bend",
        "check_sheet_metal_dfm",
    }:
        assert tool_name in QUERY_PILLAR.tools
        assert tool_name in GENERATE_PILLAR.tools
