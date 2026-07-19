"""Integrity tests for the standalone robotics knowledge assets.

These tests deliberately use only the Python standard library so the package is
safe to load before a JSON Schema validator is added to the runtime harness.
"""

from __future__ import annotations

import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "orion_agent" / "knowledge" / "robotics"
STATUSES = {"source_specific", "candidate", "illustrative"}


def _load(name: str) -> dict:
    with (PACKAGE / name).open(encoding="utf-8") as file:
        return json.load(file)


def test_robotics_assets_are_parseable_and_versioned():
    for name in ("sources.json", "components.json", "interfaces.json", "demos.json"):
        payload = _load(name)
        assert payload["schema_version"] == "1.0"
        assert payload["package"] == "robotics-assembly-foundation"
        assert payload["version"] == "0.1.0"

    schema_dir = PACKAGE / "schemas"
    for path in schema_dir.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_component_and_interface_provenance_is_resolvable():
    sources = _load("sources.json")["sources"]
    components = _load("components.json")["components"]
    interfaces = _load("interfaces.json")["interfaces"]

    source_ids = {item["id"] for item in sources}
    component_ids = {item["id"] for item in components}
    interface_ids = {item["id"] for item in interfaces}

    assert len(source_ids) == len(sources)
    assert len(component_ids) == len(components)
    assert len(interface_ids) == len(interfaces)

    for component in components:
        assert component["data_status"] in STATUSES
        assert component["engineering_review"] in {
            "required",
            "not_started",
            "approved",
        }
        assert set(component["sources"]) <= source_ids
        assert set(component["interfaces"]) <= interface_ids
        if component["data_status"] == "source_specific":
            assert component["manufacturer_part_number"]
            assert component["sources"]
        for fact in component["facts"]:
            assert fact["basis"] in STATUSES
            if fact["basis"] == "source_specific":
                assert fact["source"] in source_ids

    for interface in interfaces:
        assert interface["data_status"] in STATUSES
        assert set(interface["sources"]) <= source_ids
        assert set(interface.get("applies_to", [])) <= component_ids
        contract = interface["contract"]
        assert contract["frame_convention"]
        assert contract["required_inputs"]
        assert contract["constraints"]
        assert contract["verification"]
        if interface["data_status"] == "source_specific":
            assert interface["sources"]


def test_demo_assembly_graphs_resolve_every_reference():
    components = _load("components.json")["components"]
    interfaces = _load("interfaces.json")["interfaces"]
    demos = _load("demos.json")["demos"]

    component_ids = {item["id"] for item in components}
    interface_ids = {item["id"] for item in interfaces}
    demo_ids = {item["id"] for item in demos}
    assert demo_ids == {
        "robotics.demo.nema23_belt_linear_axis.v1",
        "robotics.demo.parallel_jaw_gripper.v1",
        "robotics.demo.pan_tilt_sensor_head.v1",
        "robotics.demo.modular_bldc_harmonic_actuator.v1",
    }

    for demo in demos:
        assert demo["data_status"] in STATUSES
        assert demo["maturity"] == "concept_demo"
        nodes = demo["assembly_graph"]["nodes"]
        node_ids = {node["id"] for node in nodes}
        assert len(node_ids) == len(nodes)
        assert {node["component_ref"] for node in nodes} <= component_ids

        for edge in demo["assembly_graph"]["edges"]:
            assert edge["from"] in node_ids
            assert edge["to"] in node_ids
            assert edge["interface_ref"] in interface_ids

        for joint in demo["kinematic_model"]:
            assert joint["parent_node"] in node_ids
            assert joint["child_node"] in node_ids
            assert joint["status"] in STATUSES

        assert demo["required_inputs"]
        assert demo["verification_gates"]
        assert demo["exports"]


def test_source_specific_harmonic_drive_record_is_not_mislabelled_as_approved():
    components = _load("components.json")["components"]
    harmonic = next(
        component
        for component in components
        if component["id"] == "robotics.component.harmonic_drive_csg_17_100_2a_r.v1"
    )

    assert harmonic["data_status"] == "source_specific"
    assert harmonic["engineering_review"] == "required"
    assert harmonic["manufacturer_part_number"] == "CSG-17-100-2A-R"
    assert all(fact["basis"] == "source_specific" for fact in harmonic["facts"])
