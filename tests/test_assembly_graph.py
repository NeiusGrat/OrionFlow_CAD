"""Focused contract tests for the stdlib-only AssemblyGraph companion IR."""

import pytest
import json

from orion_agent.harness.assembly_graph import (
    SCHEMA_VERSION,
    AssemblyGraph,
    AssemblyGraphError,
    AssemblyGraphValidationError,
    aggregate_bom,
    normalize,
    parse_assembly_graph,
    summarize,
    validate,
)


def _linear_axis_data():
    """A small but complete graph with all v0.1 joint kinds."""
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "nema23_linear_axis",
        "name": "NEMA23 belt driven linear axis",
        "units": "mm",
        "parts": [
            {
                "id": "base",
                "part_number": "OF-BASE-001",
                "name": "Base plate",
                "definition": {"kind": "feature_graph", "id": "base_plate_v1"},
            },
            {"id": "arm", "part_number": "OF-ARM-001", "name": "Pivoting arm"},
            {"id": "carriage", "part_number": "OF-CARR-001", "name": "Carriage"},
            {"id": "screw_left", "part_number": "ISO4762-M5X16", "name": "M5 socket screw"},
            {"id": "screw_right", "part_number": "ISO4762-M5X16", "name": "M5 socket screw"},
        ],
        "interfaces": [
            {
                "id": "base.pivot",
                "part_id": "base",
                "kind": "cylindrical",
                "frame": {"origin": [0, 0, 0], "x_axis": [1, 0, 0], "z_axis": [0, 0, 1]},
            },
            {"id": "base.slide", "part_id": "base", "kind": "rail"},
            {"id": "base.screw_left", "part_id": "base", "kind": "threaded_hole"},
            {"id": "base.screw_right", "part_id": "base", "kind": "threaded_hole"},
            {"id": "arm.pivot", "part_instance": "arm", "kind": "shaft"},
            {"id": "carriage.guide", "part_id": "carriage", "kind": "rail"},
            {"id": "screw_left.thread", "part_id": "screw_left", "kind": "thread"},
            {"id": "screw_right.thread", "part_id": "screw_right", "kind": "thread"},
        ],
        "joints": [
            {
                "id": "shoulder",
                "type": "revolute",
                "parent_interface": "base.pivot",
                "child_interface": "arm.pivot",
                "axis": [0, 0, 1],
                "limits": {"lower": -1.570796, "upper": 1.570796, "velocity": 2.0},
            },
            {
                "id": "linear_guide",
                "kind": "prismatic",
                "parent_interface": "base.slide",
                "child_interface": "carriage.guide",
                "axis": [1, 0, 0],
                "limits": {"lower": 0, "upper": 400},
            },
            {
                "id": "left_fastener",
                "kind": "fixed",
                "parent_interface": "base.screw_left",
                "child_interface": "screw_left.thread",
            },
            {
                "id": "right_fastener",
                "kind": "fixed",
                "parent_interface": "base.screw_right",
                "child_interface": "screw_right.thread",
            },
        ],
    }


class TestAssemblyGraphParsing:
    def test_parse_valid_assembly_and_preserve_featuregraph_reference(self):
        graph = parse_assembly_graph(_linear_axis_data())

        assert graph.id == "nema23_linear_axis"
        assert graph.part("base").definition == {"kind": "feature_graph", "id": "base_plate_v1"}
        assert graph.interface("arm.pivot").part_id == "arm"
        assert [joint.kind for joint in graph.joints] == ["revolute", "prismatic", "fixed", "fixed"]
        assert graph.validate() == []
        assert graph.connected_components() == (("arm", "base", "carriage", "screw_left", "screw_right"),)

    def test_round_trip_is_plain_json_ready_and_canonical(self):
        graph = AssemblyGraph.from_dict(_linear_axis_data())
        emitted = graph.to_dict()

        assert emitted["schema_version"] == SCHEMA_VERSION
        assert emitted["interfaces"][4]["part_id"] == "arm"
        assert emitted["joints"][0]["kind"] == "revolute"
        assert AssemblyGraph.from_dict(emitted, validate=True).to_dict() == emitted
        assert normalize(_linear_axis_data()) == emitted

    def test_accepts_json_string_at_agent_boundary(self):
        graph = parse_assembly_graph(json.dumps(_linear_axis_data()))

        assert graph.id == "nema23_linear_axis"

    def test_invalid_json_shape_is_rejected_at_parse_time(self):
        with pytest.raises(AssemblyGraphError, match="parts must be an array"):
            AssemblyGraph.from_dict({"id": "bad", "parts": {}})


class TestAssemblyGraphValidation:
    def test_reports_joint_reference_axis_limit_and_connectivity_errors(self):
        invalid = {
            "id": "invalid",
            "parts": [
                {"id": "base", "part_number": "BASE"},
                {"id": "slide", "part_number": "SLIDE"},
                {"id": "loose", "part_number": "LOOSE"},
            ],
            "interfaces": [
                {"id": "base.guide", "part_id": "base", "kind": "rail"},
                {"id": "slide.guide", "part_id": "slide", "kind": "rail"},
            ],
            "joints": [
                {
                    "id": "bad_slide",
                    "kind": "prismatic",
                    "parent_interface": "base.guide",
                    "child_interface": "slide.guide",
                    "axis": [0, 0, 0],
                    "limits": {"lower": 50, "upper": 0},
                },
                {
                    "id": "missing_interface",
                    "kind": "fixed",
                    "parent_interface": "base.guide",
                    "child_interface": "nope",
                },
            ],
        }

        errors = validate(invalid)

        assert any("axis must be non-zero" in error for error in errors)
        assert any("lower must be less" in error for error in errors)
        assert any("unknown child interface 'nope'" in error for error in errors)
        assert any("disconnected" in error and "loose" in error for error in errors)
        with pytest.raises(AssemblyGraphValidationError):
            parse_assembly_graph(invalid)

    def test_detects_duplicate_pairs_and_same_part_joint(self):
        data = _linear_axis_data()
        data["interfaces"].append({"id": "base.extra", "part_id": "base", "kind": "planar"})
        data["joints"].extend(
            [
                {
                    "id": "same_part",
                    "kind": "fixed",
                    "parent_interface": "base.pivot",
                    "child_interface": "base.extra",
                },
                {
                    "id": "shoulder_duplicate",
                    "kind": "revolute",
                    "parent_interface": "arm.pivot",
                    "child_interface": "base.pivot",
                    "axis": [0, 0, 1],
                },
            ]
        )

        errors = AssemblyGraph.from_dict(data).validate()

        assert any("same part instance" in error for error in errors)
        assert any("duplicates an existing interface pair" in error for error in errors)

    def test_closed_kinematic_loop_is_reported_but_not_rejected(self):
        data = {
            "id": "four_bar",
            "parts": [
                {"id": part_id, "part_number": part_id.upper()}
                for part_id in ("a", "b", "c")
            ],
            "interfaces": [
                {"id": "a.b", "part_id": "a", "kind": "pin"},
                {"id": "a.c", "part_id": "a", "kind": "pin"},
                {"id": "b.a", "part_id": "b", "kind": "pin"},
                {"id": "b.c", "part_id": "b", "kind": "pin"},
                {"id": "c.a", "part_id": "c", "kind": "pin"},
                {"id": "c.b", "part_id": "c", "kind": "pin"},
            ],
            "joints": [
                {"id": "ab", "kind": "fixed", "parent_interface": "a.b", "child_interface": "b.a"},
                {"id": "bc", "kind": "fixed", "parent_interface": "b.c", "child_interface": "c.b"},
                {"id": "ca", "kind": "fixed", "parent_interface": "c.a", "child_interface": "a.c"},
            ],
        }

        graph = parse_assembly_graph(data)

        assert graph.has_kinematic_cycle() is True
        assert graph.validate() == []


class TestAssemblyGraphBom:
    def test_aggregate_bom_combines_instances_by_part_identity(self):
        lines = aggregate_bom(_linear_axis_data())
        screws = next(line for line in lines if line["part_number"] == "ISO4762-M5X16")

        assert screws["quantity"] == 2
        assert screws["instance_ids"] == ["screw_left", "screw_right"]
        assert len(lines) == 4

    def test_summary_reports_dof_and_bom(self):
        text = summarize(_linear_axis_data())

        assert "5 part instance(s)" in text
        assert "2 modeled degree(s) of freedom" in text
        assert "4 unique line item(s)" in text
