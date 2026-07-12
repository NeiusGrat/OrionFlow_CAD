"""Focused contract coverage for the native linked-assembly bridge call."""

from orion_agent.harness.bridge_client import BridgeClient
from orion_agent.shared.contract import Capability


def test_assembly_compile_capability_is_mutating_and_client_preserves_explicit_bindings():
    client = object.__new__(BridgeClient)
    captured = {}

    def record(capability, params=None):
        captured["capability"] = capability
        captured["params"] = params
        return {"accepted": True}

    client._call = record
    result = client.compile_assembly_graph(
        {"id": "axis", "parts": []},
        bindings={"base": "BaseBody", "carriage": "CarriageBody"},
        root_part_id="base",
        joint_values={"slide": 125.0},
        label="Axis Arrangement",
    )

    assert Capability.COMPILE_ASSEMBLY_GRAPH in Capability.ALL
    assert Capability.COMPILE_ASSEMBLY_GRAPH not in Capability.READ_ONLY
    assert captured == {
        "capability": Capability.COMPILE_ASSEMBLY_GRAPH,
        "params": {
            "graph": {"id": "axis", "parts": []},
            "bindings": {"base": "BaseBody", "carriage": "CarriageBody"},
            "root_part_id": "base",
            "joint_values": {"slide": 125.0},
            "label": "Axis Arrangement",
        },
    }
    assert result == {"accepted": True}

    client.compile_assembly_graph(
        {"id": "neutral_pose", "parts": []},
        bindings={"base": "BaseBody"},
        root_part_id="base",
    )
    assert captured["params"]["joint_values"] is None
