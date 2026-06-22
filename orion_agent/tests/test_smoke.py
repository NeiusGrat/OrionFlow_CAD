"""Offline smoke tests for the OrionFlow harness (network-free, CI-safe).

Run with:  pytest orion_agent/tests/ -v
The single sandbox test is marked integration (needs build123d, slow).
"""

import time

import pytest

from orion_agent.shared.contract import (
    BridgeRequest, BridgeResponse, Capability, ErrorCode, ModelTier,
)
from orion_agent.shared.trajectory import Trajectory, Message, ValidationBlock
from orion_agent.harness.llm.base import LLMMessage
from orion_agent.harness.llm.mock import MockClient
from orion_agent.harness.llm.tool_protocol import parse_tool_calls, strip_tool_calls
from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.loop import AgentLoop
from orion_agent.harness.agent.router import PillarRouter
from orion_agent.harness.agent.verify import EditVerifier
from orion_agent.harness.trajectory_logger import TrajectoryLogger
from orion_agent.harness.flywheel import FlywheelExporter
from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel
from orion_agent.evals.harness import EvalHarness
from orion_agent.evals.query_suite import cases as query_cases


# --------------------------------------------------------------------------- #
# contracts
# --------------------------------------------------------------------------- #
def test_contract_roundtrip():
    req = BridgeRequest(Capability.PING, {"x": 1})
    assert BridgeRequest.from_dict(req.to_dict()).capability == Capability.PING
    resp = BridgeResponse.success({"pong": True})
    assert BridgeResponse.from_dict(resp.to_dict()).result["pong"] is True
    fail = BridgeResponse.failure(ErrorCode.NO_DOCUMENT, "no doc")
    assert not fail.ok and fail.error_code == ErrorCode.NO_DOCUMENT


def test_trajectory_validates():
    t = Trajectory(user_request="how many holes?", pillar="query")
    t.add_message(Message(role="user", content="how many holes?"))
    assert t.validate() == []
    bad = Trajectory(user_request="", pillar="nonsense")
    assert bad.validate()


def test_bridge_roundtrip_with_mock_caps():
    from orion_agent.addon.bridge_server import BridgeServer
    from orion_agent.harness.bridge_client import BridgeClient
    from orion_agent.shared.contract import BridgeError

    class Caps:
        def dispatch(self, cap, params):
            if cap == "ping":
                return {"pong": True}
            if cap == "get_capabilities":
                return {"capabilities": ["ping"], "version": "1.0"}
            from orion_agent.addon.capabilities import CapabilityError
            raise CapabilityError(ErrorCode.UNKNOWN_CAPABILITY, cap)

    srv = BridgeServer(port=8801, capabilities=Caps())
    srv.start()
    time.sleep(0.3)
    try:
        c = BridgeClient(port=8801)
        assert c.is_alive()
        assert c.ping()["pong"] is True
        with pytest.raises(BridgeError):
            c._call("nope")
    finally:
        srv.stop()


# --------------------------------------------------------------------------- #
# tool protocol (the parser bugs that broke the eval)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected_name,expected_args", [
    ('<tool_call>{"name": "list_objects", "arguments": {}}', "list_objects", {}),
    ('x </think> <tool_call>{"name": "expand_topology", "arguments": {"name": "P"}}</tool_call>',
     "expand_topology", {"name": "P"}),
    ('<tool_call>{"name":"write_code","arguments":{"code":"x = {1:2}"}}', "write_code",
     {"code": "x = {1:2}"}),
])
def test_tool_parse(text, expected_name, expected_args):
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == expected_name
    assert calls[0].arguments == expected_args


def test_strip_tool_calls():
    assert strip_tool_calls("answer <tool_call>{}</tool_call>") == "answer"
    assert strip_tool_calls("just text") == "just text"


# --------------------------------------------------------------------------- #
# tool registry
# --------------------------------------------------------------------------- #
def test_registry_schemas_and_exec():
    bridge = SyntheticBridge(SyntheticModel(holes=2, faces=12))
    reg = build_registry(bridge, sandbox=None)
    schemas = reg.schemas(allow={"inspect_topology"})
    assert schemas[0]["type"] == "function"
    res = reg.execute("inspect_topology", {})
    assert res.ok and "12 faces" in res.content


# --------------------------------------------------------------------------- #
# router
# --------------------------------------------------------------------------- #
def test_router():
    r = PillarRouter()
    assert r.route("how many holes are there?", tier="B").pillar == "query"
    assert r.route("increase the wall thickness to 4mm", tier="B").pillar == "modify"
    assert r.route("reconstruct this 2D drawing", tier="C", has_image=True).pillar == "reconstruct"


# --------------------------------------------------------------------------- #
# agent loop with mock LLM (no network)
# --------------------------------------------------------------------------- #
def test_agent_loop_query_mock():
    bridge = SyntheticBridge(SyntheticModel(name="Plate", holes=2, faces=12, hole_spacing=30))
    reg = build_registry(bridge, sandbox=None)
    llm = MockClient().tool("inspect_topology").queue("This part has 2 holes.")
    loop = AgentLoop(llm, reg, bridge=bridge)
    result = loop.run("How many holes?", forced_pillar="query")
    assert "inspect_topology" in [c["name"] for c in result.tool_calls]
    assert "2 holes" in result.final_answer
    assert result.trajectory.validate() == []


def test_agent_loop_modify_verifies():
    model = SyntheticModel(name="Bar", tier="B", parameters={"Length": 100.0})
    bridge = SyntheticBridge(model)
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("set_parameter", {"name": "Bar", "property": "Length", "value": 80.0})
           .queue("Length changed to 80 mm."))
    loop = AgentLoop(llm, reg, bridge=bridge, verifier=EditVerifier(bridge))
    result = loop.run("Change the length to 80 mm.", forced_pillar="modify")
    assert bridge.model.parameters["Length"] == 80.0
    assert result.trajectory.validation.executed is True


# --------------------------------------------------------------------------- #
# logging + flywheel
# --------------------------------------------------------------------------- #
def test_trajectory_logger_and_flywheel(tmp_path):
    logger = TrajectoryLogger(root=str(tmp_path))
    t = Trajectory(user_request="how many holes?", pillar="query",
                   final_answer="2 holes")
    t.add_message(Message(role="user", content="how many holes?"))
    t.validation = ValidationBlock(grounded=True)
    assert logger.log(t)
    assert len(logger.read_all()) == 1
    stats = FlywheelExporter(logger=logger, out_dir=str(tmp_path / "exp")).export()
    assert stats.total == 1 and stats.sft == 1


# --------------------------------------------------------------------------- #
# eval harness with mock LLM
# --------------------------------------------------------------------------- #
def test_eval_harness_mock():
    # A mock that always answers "2" and calls inspect_topology.
    def responder(messages, tools):
        from orion_agent.harness.llm.base import LLMResponse, ToolCallRequest
        if messages[-1].role == "tool":      # we already have a tool result
            return LLMResponse(content="There are 2 holes.")
        return LLMResponse(tool_calls=[ToolCallRequest.new("inspect_topology", {})],
                           finish_reason="tool_calls")
    llm = MockClient(responder=responder)
    harness = EvalHarness(llm)
    case = query_cases()[0]   # holes_count, expects 2
    res = harness.run_case(case)
    assert res.grounded and res.accuracy and res.no_hallucination


# --------------------------------------------------------------------------- #
# reconstruct scoring
# --------------------------------------------------------------------------- #
def test_reconstruct_scoring():
    from orion_agent.harness.agent.reconstruct import parse_target, score_reconstruction
    target = parse_target("Plate 60 x 40 x 5 mm with 2 holes")
    assert target.dimensions == [60.0, 40.0, 5.0]
    assert target.holes == 2
    good = {"bounding_box": {"size": [60.0, 40.0, 5.0]}, "cylindrical_faces": 2}
    s = score_reconstruction(good, target)
    assert s.dimensional_match and s.confidence > 0.95
    bad = {"bounding_box": {"size": [30.0, 20.0, 5.0]}, "cylindrical_faces": 0}
    assert not score_reconstruction(bad, target).dimensional_match


# --------------------------------------------------------------------------- #
# sandbox (integration: needs build123d, slow)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
def test_sandbox_executes_build123d():
    from orion_agent.harness.sandbox import SandboxManager
    sm = SandboxManager()
    code = "from build123d import *\nwith BuildPart() as p:\n    Box(10,10,10)\nresult=p.part\n"
    r = sm.run_code(code, exports=["step"])
    assert r.ok
    assert r.topology["faces"] == 6
    assert r.artifact_path("step")
