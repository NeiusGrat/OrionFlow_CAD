"""Focused safety-contract tests for the stdlib-only URDF exporter."""

from xml.etree import ElementTree as ET

import pytest

from orion_agent.harness.assembly_graph import AssemblyGraph
from orion_agent.harness.urdf_export import (
    URDFExportError,
    export_urdf,
    validate_urdf_export,
)


def _origin(xyz=(0, 0, 0), rpy=(0, 0, 0)):
    return {"urdf_origin": {"xyz": list(xyz), "rpy": list(rpy)}}


def _serial_robot_data():
    return {
        "id": "demo_axis",
        "units": "mm",
        "parts": [
            {"id": "base", "part_number": "BASE-001"},
            {"id": "slider", "part_number": "SLIDER-001"},
            {"id": "tool", "part_number": "TOOL-001"},
            {"id": "sensor", "part_number": "SENSOR-001"},
        ],
        "interfaces": [
            {"id": "base.rail", "part_id": "base", "kind": "rail"},
            {"id": "slider.rail", "part_id": "slider", "kind": "rail"},
            {"id": "slider.tool", "part_id": "slider", "kind": "planar"},
            {"id": "tool.mount", "part_id": "tool", "kind": "planar"},
            {"id": "tool.wrist", "part_id": "tool", "kind": "cylindrical"},
            {"id": "sensor.wrist", "part_id": "sensor", "kind": "shaft"},
        ],
        "joints": [
            {
                "id": "slide",
                "kind": "prismatic",
                "parent_interface": "base.rail",
                "child_interface": "slider.rail",
                "axis": [1, 0, 0],
                "limits": {"lower": 0, "upper": 400, "velocity": 250, "effort": 500},
                "metadata": _origin((0, 0, 30)),
            },
            {
                "id": "tool_mount",
                "kind": "fixed",
                "parent_interface": "slider.tool",
                "child_interface": "tool.mount",
                "metadata": _origin((0, 0, 15)),
            },
            {
                "id": "sensor_pan",
                "kind": "revolute",
                "parent_interface": "tool.wrist",
                "child_interface": "sensor.wrist",
                "axis": [0, 0, 1],
                "limits": {"lower": -1.57, "upper": 1.57, "velocity": 2, "effort": 7},
                "metadata": _origin((0, 0, 20), (0, 0, 0.25)),
            },
        ],
    }


def _graph(data=None):
    return AssemblyGraph.from_dict(data or _serial_robot_data())


def test_exports_parseable_kinematic_only_urdf_with_explicit_metre_conversion():
    xml = export_urdf(_graph())
    root = ET.fromstring(xml)

    assert "Source/provenance" in xml
    assert root.tag == "robot"
    assert root.attrib == {"name": "demo_axis"}
    assert [link.attrib["name"] for link in root.findall("link")] == [
        "base",
        "slider",
        "tool",
        "sensor",
    ]

    slide = root.find("joint[@name='slide']")
    assert slide is not None
    assert slide.attrib["type"] == "prismatic"
    assert slide.find("origin").attrib == {"xyz": "0 0 0.03", "rpy": "0 0 0"}
    assert slide.find("parent").attrib == {"link": "base"}
    assert slide.find("child").attrib == {"link": "slider"}
    assert slide.find("axis").attrib == {"xyz": "1 0 0"}
    assert slide.find("limit").attrib == {
        "lower": "0",
        "upper": "0.4",
        "effort": "500",
        "velocity": "0.25",
    }

    fixed = root.find("joint[@name='tool_mount']")
    assert fixed is not None
    assert fixed.find("axis") is None
    assert fixed.find("limit") is None

    revolute = root.find("joint[@name='sensor_pan']")
    assert revolute is not None
    assert revolute.attrib["type"] == "revolute"
    assert revolute.find("origin").attrib == {"xyz": "0 0 0.02", "rpy": "0 0 0.25"}
    assert revolute.find("axis").attrib == {"xyz": "0 0 1"}
    assert revolute.find("limit").attrib == {
        "lower": "-1.57",
        "upper": "1.57",
        "effort": "7",
        "velocity": "2",
    }
    assert root.findall(".//visual") == []
    assert root.findall(".//collision") == []
    assert root.findall(".//inertial") == []


def test_rejects_joint_without_explicit_urdf_origin_metadata():
    data = _serial_robot_data()
    data["joints"][0].pop("metadata")

    with pytest.raises(
        URDFExportError, match=r"requires explicit metadata\.urdf_origin"
    ):
        export_urdf(_graph(data))


def test_rejects_movable_joint_without_axis_and_full_numeric_limits():
    data = _serial_robot_data()
    data["joints"][0].pop("axis")
    data["joints"][0]["limits"] = {"lower": 0, "upper": 400}

    errors = validate_urdf_export(_graph(data))

    assert any("requires a non-zero finite axis" in error for error in errors)
    assert any(
        "requires numeric lower, upper, velocity, and effort limits" in error
        for error in errors
    )


def test_rejects_closed_loop_non_tree_topology():
    data = _serial_robot_data()
    data["interfaces"].extend(
        [
            {"id": "base.loop", "part_id": "base", "kind": "planar"},
            {"id": "tool.loop", "part_id": "tool", "kind": "planar"},
        ]
    )
    data["joints"].append(
        {
            "id": "loop_closure",
            "kind": "fixed",
            "parent_interface": "tool.loop",
            "child_interface": "base.loop",
            "metadata": _origin(),
        }
    )

    with pytest.raises(URDFExportError, match="exactly one root link"):
        export_urdf(_graph(data))


def test_rejects_multiple_parent_joints_for_one_child_link():
    data = _serial_robot_data()
    data["interfaces"].extend(
        [
            {"id": "base.tool_secondary", "part_id": "base", "kind": "planar"},
            {"id": "tool.secondary", "part_id": "tool", "kind": "planar"},
        ]
    )
    data["joints"].append(
        {
            "id": "second_tool_parent",
            "kind": "fixed",
            "parent_interface": "base.tool_secondary",
            "child_interface": "tool.secondary",
            "metadata": _origin(),
        }
    )

    errors = validate_urdf_export(_graph(data))

    assert any(
        "child link 'tool' is referenced by multiple parent joints" in error
        for error in errors
    )
    with pytest.raises(URDFExportError):
        export_urdf(_graph(data))
