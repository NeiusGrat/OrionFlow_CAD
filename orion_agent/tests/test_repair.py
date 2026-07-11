"""Offline tests for the typed repair policy (network-free, CI-safe).

Run with:  pytest orion_agent/tests/test_repair.py -v
"""

import pytest

from orion_agent.harness.agent.repair import (
    GRAPH_INVALID,
    IMPORT_FAILED,
    PARAMETER_REJECTED,
    RECOMPUTE_FAILED,
    RepairPolicy,
    SANDBOX_ERROR,
    SELECTOR_NO_MATCH,
    TRANSIENT,
    UNKNOWN,
    ZERO_VOLUME,
    classify,
)
from orion_agent.harness.llm.mock import MockClient
from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.loop import AgentLoop
from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel


def _plate_graph():
    """Known-valid compact graph: 80x50x10 plate with a 10 mm centre hole."""
    return {
        "features": [
            {"id": "sk_base", "type": "Sketch"},
            {"id": "pad_base", "type": "Pad", "parameters": {"Length": 10}},
            {"id": "sk_hole", "type": "Sketch"},
            {"id": "cut_hole", "type": "Pocket", "parameters": {"Length": 10}},
        ],
        "sketches": [
            {"id": "sk_base", "plane": "XY", "geometry": [
                {"type": "LineSegment", "sx": -40, "sy": -25, "ex": 40, "ey": -25},
                {"type": "LineSegment", "sx": 40, "sy": -25, "ex": 40, "ey": 25},
                {"type": "LineSegment", "sx": 40, "sy": 25, "ex": -40, "ey": 25},
                {"type": "LineSegment", "sx": -40, "sy": 25, "ex": -40, "ey": -25},
            ]},
            {"id": "sk_hole", "plane": "XY", "geometry": [
                {"type": "Circle", "cx": 0, "cy": 0, "radius": 5},
            ]},
        ],
        "dependencies": [
            {"source": "sk_base", "target": "pad_base", "kind": "profile"},
            {"source": "sk_hole", "target": "cut_hole", "kind": "profile"},
        ],
    }


def _bad_graph():
    g = _plate_graph()
    g["features"][1]["parameters"] = {"Length": -3}
    return g


# --------------------------------------------------------------------------- #
# classification
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool,content,error,expected", [
    ("create_featuregraph", "FeatureGraph invalid — fix and retry:\n- pad_base: "
     "Pad needs parameters.Length > 0 (got -3)", "FeatureGraph invalid", GRAPH_INVALID),
    ("create_featuregraph", "compile FAILED — the graph did not rebuild cleanly: "
     "cut_hole: recompute error", "recompute_failed", RECOMPUTE_FAILED),
    ("create_featuregraph", "compile FAILED — zero volume", "zero_volume", ZERO_VOLUME),
    ("create_featuregraph", "fillet1: selector 'top' matched no edges",
     "recompute_failed", SELECTOR_NO_MATCH),
    ("create_featuregraph", "something odd", "", UNKNOWN),
    ("write_code", "sandbox failed: NameError: name 'Bx' is not defined",
     "NameError", SANDBOX_ERROR),
    ("import_shape", "no STEP artifact found", "no_artifact", IMPORT_FAILED),
    ("set_parameter", "no such property 'Lenght'", "bad_property", PARAMETER_REJECTED),
    ("edit_feature", "feature not found", "not_found", PARAMETER_REJECTED),
    ("write_code", "bridge not running", "connection refused", TRANSIENT),
])
def test_classify(tool, content, error, expected):
    assert classify(tool, content, error) == expected


# --------------------------------------------------------------------------- #
# policy: escalation, budget, recovery
# --------------------------------------------------------------------------- #
def test_strategy_escalates_and_budget_exhausts():
    p = RepairPolicy(budget=3)
    h1 = p.observe_failure("create_featuregraph", "FeatureGraph invalid — x")
    h2 = p.observe_failure("create_featuregraph", "FeatureGraph invalid — x")
    h3 = p.observe_failure("create_featuregraph", "FeatureGraph invalid — x")
    h4 = p.observe_failure("create_featuregraph", "FeatureGraph invalid — x")
    assert h1.startswith("[repair 1/3 — graph_invalid]")
    assert h2.startswith("[repair 2/3 — graph_invalid]") and h2 != h1
    assert "FINAL repair attempt" in h3
    assert "budget exhausted" in h4
    s = p.summary()
    assert s["exhausted"] is True and s["recovered"] is False
    assert [a["attempt"] for a in s["attempts"]] == [1, 2, 3, 4]


def test_non_build_tools_are_not_tracked():
    p = RepairPolicy()
    assert p.observe_failure("inspect_topology", "boom") is None
    p.observe_success("list_objects")
    assert p.summary() is None


def test_recovery_flag():
    p = RepairPolicy()
    p.observe_failure("create_featuregraph", "FeatureGraph invalid — x")
    assert p.recovered is False
    p.observe_success("create_featuregraph")
    s = p.summary()
    assert s["recovered"] is True and s["exhausted"] is False


def test_success_without_prior_failure_is_not_recovery():
    p = RepairPolicy()
    p.observe_success("create_featuregraph")
    assert p.summary() is None


# --------------------------------------------------------------------------- #
# zero-volume compile is now a typed failure
# --------------------------------------------------------------------------- #
def test_zero_volume_compile_fails():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    original = bridge.compile_featuregraph

    def flat(graph):
        out = original(graph)
        out["report"]["volume"] = 0.0
        return out

    bridge.compile_featuregraph = flat
    reg = build_registry(bridge, sandbox=None)
    res = reg.execute("create_featuregraph", {"graph": _plate_graph()})
    assert not res.ok
    assert res.error == "zero_volume"
    assert classify("create_featuregraph", res.content, res.error) == ZERO_VOLUME


# --------------------------------------------------------------------------- #
# loop integration
# --------------------------------------------------------------------------- #
def test_loop_repairs_and_records_recovery():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("create_featuregraph", {"graph": _bad_graph()})
           .tool("create_featuregraph", {"graph": _plate_graph()})
           .queue("Built the plate."))
    loop = AgentLoop(llm, reg, bridge=bridge)
    result = loop.run("create a plate with a hole", forced_pillar="generate")

    rep = result.trajectory.validation.checks["repair"]
    assert rep["recovered"] is True
    assert rep["exhausted"] is False
    assert rep["attempts"][0]["error_class"] == GRAPH_INVALID

    # The model must have SEEN the guidance in the tool observation.
    tool_msgs = [m.content for m in result.trajectory.messages if m.role == "tool"]
    assert any("[repair 1/" in c for c in tool_msgs)
    # The final graph landed.
    assert result.trajectory.validation.checks.get("native_build") is True


def test_loop_budget_exhaustion_recorded():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("create_featuregraph", {"graph": _bad_graph()})
           .tool("create_featuregraph", {"graph": _bad_graph()})
           .tool("create_featuregraph", {"graph": _bad_graph()})
           .tool("create_featuregraph", {"graph": _bad_graph()})
           .queue("I could not build a valid model."))
    loop = AgentLoop(llm, reg, bridge=bridge)
    result = loop.run("create a plate with a hole", forced_pillar="generate")

    rep = result.trajectory.validation.checks["repair"]
    assert rep["recovered"] is False
    assert rep["exhausted"] is True
    assert len(rep["attempts"]) == 4

    tool_msgs = [m.content for m in result.trajectory.messages if m.role == "tool"]
    assert any("FINAL repair attempt" in c for c in tool_msgs)
    assert any("budget exhausted" in c for c in tool_msgs)


def test_no_repair_block_when_nothing_failed():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("create_featuregraph", {"graph": _plate_graph()})
           .queue("Built the plate."))
    loop = AgentLoop(llm, reg, bridge=bridge)
    result = loop.run("create a plate with a hole", forced_pillar="generate")
    assert "repair" not in result.trajectory.validation.checks
