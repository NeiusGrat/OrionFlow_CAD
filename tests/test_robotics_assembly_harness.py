"""Integration tests for the robotics knowledge and AssemblyGraph harness layer."""

from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel
from orion_agent.harness import assembly_graph as ag
from orion_agent.harness import robotics_knowledge as rk
from orion_agent.harness.agent.pillars import GENERATE_PILLAR, QUERY_PILLAR
from orion_agent.harness.spec import SpecParser
from orion_agent.harness.tools.registry import build_registry


def _minimal_linear_axis_assembly():
    return {
        "id": "reviewed_axis_plan",
        "parts": [
            {
                "id": "structure",
                "part_number": "OF-STRUCTURE-001",
                "name": "Reviewed structural frame",
                "definition": {"kind": "feature_graph", "id": "structure_v1"},
            },
            {
                "id": "carriage",
                "part_number": "OF-CARRIAGE-001",
                "name": "Reviewed carriage plate",
                "definition": {"kind": "feature_graph", "id": "carriage_v1"},
            },
        ],
        "interfaces": [
            {
                "id": "structure.travel",
                "part_id": "structure",
                "kind": "rail",
                "frame": {
                    "origin": [0, 0, 0],
                    "x_axis": [1, 0, 0],
                    "z_axis": [0, 0, 1],
                },
            },
            {
                "id": "carriage.travel",
                "part_id": "carriage",
                "kind": "rail",
                "frame": {
                    "origin": [0, 0, 0],
                    "x_axis": [1, 0, 0],
                    "z_axis": [0, 0, 1],
                },
            },
        ],
        "joints": [
            {
                "id": "axis_travel",
                "kind": "prismatic",
                "parent_interface": "structure.travel",
                "child_interface": "carriage.travel",
                "axis": [1, 0, 0],
                "limits": {"lower": 0, "upper": 400},
            },
        ],
    }


def _urdf_ready_linear_axis_assembly():
    graph = _minimal_linear_axis_assembly()
    graph["joints"][0]["limits"].update({"velocity": 250, "effort": 500})
    graph["joints"][0]["metadata"] = {
        "urdf_origin": {"xyz": [0, 0, 30], "rpy": [0, 0, 0]}
    }
    return graph


def test_robotics_assets_validate_and_retain_status_boundaries():
    assert rk.validate_package() == []

    results = rk.search("NEMA 23 belt linear axis")
    demo = next(item for item in results if item["record_kind"] == "demo")
    assert demo["id"] == "robotics.demo.nema23_belt_linear_axis.v1"
    assert demo["data_status"] == "illustrative"
    assert demo["source_records"]

    component = rk.get(
        "component", "robotics.component.harmonic_drive_csg_17_100_2a_r.v1"
    )
    assert component["data_status"] == "source_specific"
    assert component["engineering_review"] == "required"


def test_demo_is_a_composition_graph_not_a_mate_solved_assembly():
    demo = rk.get("demo", "robotics.demo.nema23_belt_linear_axis.v1")
    assert rk.validate_demo_graph(demo) == []
    text = rk.summarize_demo_topology(demo)
    assert "Concept composition graph" in text
    assert "select exact part numbers" in text


def test_explicit_assembly_graph_is_validated_separately_from_demo_topology():
    graph = ag.parse_assembly_graph(_minimal_linear_axis_assembly())

    assert graph.validate() == []
    assert graph.bom()[0].part_number == "OF-CARRIAGE-001"
    summary = ag.summarize(graph)
    assert "1 modeled degree(s) of freedom" in summary


def test_robotics_tools_return_source_status_and_validate_assembly_plan():
    registry = build_registry(SyntheticBridge(SyntheticModel(name="X")), sandbox=None)

    lookup = registry.execute(
        "lookup_robotics_knowledge", {"query": "parallel jaw gripper"}
    )
    assert lookup.ok
    assert "data_status=" in lookup.content

    demo = registry.execute(
        "get_robotics_demo",
        {
            "demo_id": "robotics.demo.nema23_belt_linear_axis.v1",
        },
    )
    assert demo.ok
    assert "Concept composition graph" in demo.content
    assert "composition_graph" in demo.raw

    assembly = registry.execute(
        "validate_assembly_graph",
        {
            "graph": _minimal_linear_axis_assembly(),
        },
    )
    assert assembly.ok
    assert "BOM:" in assembly.content
    assert assembly.raw["assembly_graph"]["id"] == "reviewed_axis_plan"

    readiness = registry.execute(
        "assess_robotics_assembly",
        {
            "graph": _minimal_linear_axis_assembly(),
        },
    )
    assert readiness.ok
    assert (
        "planning_only" not in readiness.content
    )  # custom parts require review, not fake selection
    assert "engineering_review_required" in readiness.content

    urdf = registry.execute(
        "export_assembly_urdf",
        {
            "graph": _urdf_ready_linear_axis_assembly(),
            "robot_name": "orion_axis",
        },
    )
    assert urdf.ok
    assert '<robot name="orion_axis">' in urdf.content
    assert "Kinematic-only" in urdf.content


def test_compile_assembly_tool_requires_explicit_source_bindings_and_is_generate_only():
    registry = build_registry(SyntheticBridge(SyntheticModel(name="X")), sandbox=None)
    graph = _minimal_linear_axis_assembly()

    compiled = registry.execute(
        "compile_assembly_graph",
        {
            "graph": graph,
            "bindings": {"structure": "StructureBody", "carriage": "CarriageBody"},
            "root_part_id": "structure",
            "joint_values": {"axis_travel": 120},
            "label": "Reviewed Axis Arrangement",
        },
    )

    assert compiled.ok
    assert compiled.raw["assembly"]["root_part_id"] == "structure"
    assert compiled.raw["created"] == [
        "OrionAssembly",
        "structure_link",
        "carriage_link",
    ]
    assert registry.get("compile_assembly_graph").doc_mutating is True
    assert "compile_assembly_graph" in GENERATE_PILLAR.tools
    assert "compile_assembly_graph" not in QUERY_PILLAR.tools


def test_spec_parser_attaches_only_a_robotics_demo_candidate():
    spec = SpecParser(llm=None).parse(
        "Design a belt driven linear axis for a robotics fixture with an unselected NEMA 23 motor."
    )

    assert spec.robotics[0]["demo_id"] == "robotics.demo.nema23_belt_linear_axis.v1"
    assert "Robotics demo candidates" in spec.render()
    assert "NEMA 23 belt-driven linear axis" in spec.render()


def test_all_agent_routes_can_retrieve_and_validate_robotics_knowledge():
    for tool_name in {
        "lookup_robotics_knowledge",
        "get_robotics_demo",
        "validate_assembly_graph",
        "assess_robotics_assembly",
        "export_assembly_urdf",
    }:
        assert tool_name in QUERY_PILLAR.tools
        assert tool_name in GENERATE_PILLAR.tools
