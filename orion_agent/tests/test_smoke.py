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
    # A passing edit commits, never rolls back.
    assert result.trajectory.validation.checks.get("rolled_back") is False


def test_agent_loop_modify_rolls_back_on_failure():
    """A hard verification failure must abort the transaction and restore the
    document — the answer note has to say what actually happened."""
    model = SyntheticModel(name="Bar", tier="B", parameters={"Length": 100.0})
    bridge = SyntheticBridge(model)
    orig = bridge.set_parameter

    def breaking(name, property, value):  # noqa: A002 - matches bridge surface
        out = orig(name, property, value)
        bridge._error = True          # the "recompute" broke the object
        return out

    bridge.set_parameter = breaking
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("set_parameter", {"name": "Bar", "property": "Length", "value": 80.0})
           .queue("Length changed to 80 mm."))
    loop = AgentLoop(llm, reg, bridge=bridge, verifier=EditVerifier(bridge))
    result = loop.run("Change the length to 80 mm.", forced_pillar="modify")
    assert result.trajectory.validation.executed is False
    assert result.trajectory.validation.checks.get("rolled_back") is True
    assert bridge.model.parameters["Length"] == 100.0   # restored by abort
    assert "rolled back" in result.final_answer


def test_verifier_intent_hole_count():
    model = SyntheticModel(name="Plate", holes=2, faces=12)
    bridge = SyntheticBridge(model)
    v = EditVerifier(bridge)
    snap = v.snapshot()
    assert v._intent_consistent("drill 2 holes in the plate", snap, snap, {"Plate"}) is True
    assert v._intent_consistent("drill 6 holes in the plate", snap, snap, {"Plate"}) is False


def test_verifier_catches_moved_object():
    """Same size, different position, outside the edited set => unintended change."""
    model = SyntheticModel(name="Plate")
    bridge = SyntheticBridge(model)
    v = EditVerifier(bridge)
    before = v.snapshot()
    import copy
    after = copy.deepcopy(before)
    info = after.objects["Plate"]
    info["bbox_min"] = [x + 5 for x in info["bbox_min"]]
    info["bbox_max"] = [x + 5 for x in info["bbox_max"]]
    assert v._no_unintended_change(before, after, edited=set()) is False
    assert v._no_unintended_change(before, after, edited={"Plate"}) is True


def test_context_packer_injects_document_memory(tmp_path):
    from orion_agent.harness.context import ContextPacker
    from orion_agent.harness.memory import MemoryStore
    from orion_agent.harness.agent.pillars import QUERY_PILLAR

    store = MemoryStore(root=str(tmp_path))
    store.set_fact("Plate.FCStd", "units", "mm")
    bridge = SyntheticBridge(SyntheticModel(name="Plate"))
    packer = ContextPacker(store)
    msgs = packer.pack(QUERY_PILLAR, "how many holes?", "B", None, bridge,
                       document="Plate.FCStd")
    assert "units=mm" in msgs[0].content


def test_get_parameters_truncates_to_valid_json():
    import json as _json
    model = SyntheticModel(name="Big",
                           parameters={f"Prop{i}": "x" * 40 for i in range(100)})
    bridge = SyntheticBridge(model)
    reg = build_registry(bridge, sandbox=None)
    res = reg.execute("get_parameters", {"name": "Big"})
    assert res.ok
    parsed = _json.loads(res.content)          # must always be valid JSON
    assert parsed["_omitted_properties"] > 0


def test_generate_auto_imports(tmp_path):
    """If the model builds in the sandbox but forgets import_shape, the harness
    imports the artifact itself and records it in the validation block."""
    step_file = tmp_path / "orion_result.step"

    class FakeResult:
        ok = True
        error = ""
        topology = {"solids": 1, "faces": 6}
        artifacts = [{"kind": "step", "path": str(step_file)}]

        def to_dict(self):
            return {"ok": True, "topology": self.topology}

        def artifact_path(self, kind):
            return str(step_file) if kind == "step" else None

    class FakeSandbox:
        def run_code(self, code, result_var="result", exports=None):
            step_file.write_text("dummy step")
            return FakeResult()

    bridge = SyntheticBridge(SyntheticModel(name="Box"))
    reg = build_registry(bridge, FakeSandbox())
    llm = (MockClient()
           .tool("write_code", {"code": "result = Box(1, 1, 1)"})
           .queue("Built a 1mm box."))
    loop = AgentLoop(llm, reg, bridge=bridge, verifier=EditVerifier(bridge))
    result = loop.run("make me a small box", forced_pillar="generate")
    vb = result.trajectory.validation
    assert vb.checks.get("auto_imported") is True
    assert vb.checks.get("imported") is True
    # The auto-import is a harness action: it must NOT appear as a model
    # message (the flywheel would otherwise teach the model to skip imports).
    assert not any(m.role == "tool" and m.name == "import_shape"
                   for m in result.trajectory.messages)


# --------------------------------------------------------------------------- #
# featuregraph authoring path
# --------------------------------------------------------------------------- #
def _plate_with_hole_graph():
    """The canonical authoring example: 80x50x10 plate, 10mm centre hole."""
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


def test_featuregraph_normalize_and_validate():
    from orion_agent.harness import featuregraph as fg

    canonical, notes = fg.normalize(_plate_with_hole_graph())
    assert fg.validate(canonical) == []
    assert notes == []                       # fully explicit graph needs no repairs
    # canonical form carries the schema-required boilerplate
    pad = next(f for f in canonical["features"] if f["id"] == "pad_base")
    assert pad["type_id"] == "PartDesign::Pad"
    geo = canonical["sketches"][0]["geometry"]
    assert all("index" in g for g in geo)


def test_featuregraph_infers_missing_profile_dep():
    from orion_agent.harness import featuregraph as fg

    graph = _plate_with_hole_graph()
    graph["dependencies"] = graph["dependencies"][:1]   # drop the pocket's edge
    canonical, notes = fg.normalize(graph)
    assert any("inferred profile sk_hole -> cut_hole" in n for n in notes)
    assert fg.validate(canonical) == []


def test_featuregraph_validation_catches_defects():
    from orion_agent.harness import featuregraph as fg

    # open profile: drop one wall of the rectangle
    graph = _plate_with_hole_graph()
    graph["sketches"][0]["geometry"].pop()
    canonical, _ = fg.normalize(graph)
    errs = fg.validate(canonical)
    assert any("not closed" in e for e in errs)

    # Pad without Length
    graph = _plate_with_hole_graph()
    graph["features"][1]["parameters"] = {}
    canonical, _ = fg.normalize(graph)
    assert any("Length" in e for e in fg.validate(canonical))

    # unsupported feature type (Loft/Sweep/Mirrored/Draft are supported now)
    graph = _plate_with_hole_graph()
    graph["features"].append({"id": "f1", "type": "Helix", "parameters": {}})
    canonical, _ = fg.normalize(graph)
    assert any("unsupported feature type 'Helix'" in e for e in fg.validate(canonical))


def test_featuregraph_dressup_validation():
    from orion_agent.harness import featuregraph as fg

    graph = _plate_with_hole_graph()
    graph["features"].append({"id": "fil1", "type": "Fillet",
                              "parameters": {"Radius": 2, "_Edges": "vertical"}})
    canonical, _ = fg.normalize(graph)
    assert fg.validate(canonical) == []

    # missing radius
    graph["features"][-1] = {"id": "fil1", "type": "Fillet",
                             "parameters": {"_Edges": "top"}}
    canonical, _ = fg.normalize(graph)
    assert any("Radius" in e for e in fg.validate(canonical))

    # bad selector
    graph["features"][-1] = {"id": "fil1", "type": "Fillet",
                             "parameters": {"Radius": 2, "_Edges": "sideways"}}
    canonical, _ = fg.normalize(graph)
    assert any("_Edges" in e for e in fg.validate(canonical))

    # chamfer needs Size, and a dressup cannot precede all solids
    early = {
        "features": [
            {"id": "ch1", "type": "Chamfer", "parameters": {"Size": 1, "_Edges": "all"}},
            {"id": "sk", "type": "Sketch"},
            {"id": "pad", "type": "Pad", "parameters": {"Length": 5}},
        ],
        "sketches": [{"id": "sk", "plane": "XY", "geometry": [
            {"type": "Circle", "cx": 0, "cy": 0, "radius": 10}]}],
        "dependencies": [{"source": "sk", "target": "pad", "kind": "profile"}],
    }
    canonical, _ = fg.normalize(early)
    assert any("after a solid feature" in e for e in fg.validate(canonical))


def test_generate_via_featuregraph():
    """Generate builds natively through the IR: no sandbox, no STEP import."""
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    llm = (MockClient()
           .tool("create_featuregraph", {"graph": _plate_with_hole_graph()})
           .queue("Built an 80x50x10 plate with a 10mm centre hole."))
    loop = AgentLoop(llm, reg, bridge=bridge, verifier=EditVerifier(bridge))
    result = loop.run("create a plate with a hole", forced_pillar="generate")
    vb = result.trajectory.validation
    assert vb.checks.get("native_build") is True
    assert vb.checks.get("imported") is True            # delivered
    assert vb.checks.get("auto_imported") is None       # no STEP fallback needed
    assert vb.checks.get("rolled_back") is False
    assert "compiled" in result.tool_calls[0]["result_preview"]


def test_create_featuregraph_rejects_invalid():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    bad = _plate_with_hole_graph()
    bad["features"][1]["parameters"] = {"Length": -3}
    res = reg.execute("create_featuregraph", {"graph": bad})
    assert not res.ok
    assert "Length" in res.content
    # nothing was sent to the bridge
    assert getattr(bridge, "_compiled_graph", None) is None


def test_get_featuregraph_summarizes():
    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    reg = build_registry(bridge, sandbox=None)
    from orion_agent.harness import featuregraph as fg
    canonical, _ = fg.normalize(_plate_with_hole_graph())
    bridge.compile_featuregraph(canonical)
    res = reg.execute("get_featuregraph", {})
    assert res.ok
    assert "pad_base (Pad, Length=10)" in res.content
    assert "<- profile sk_base" in res.content


# --------------------------------------------------------------------------- #
# exemplar retrieval (RAG-lite)
# --------------------------------------------------------------------------- #
def test_exemplars_all_validate():
    from orion_agent.harness import exemplars, featuregraph as fg
    for ex in exemplars.LIBRARY:
        canonical, _ = fg.normalize(ex.graph)
        assert fg.validate(canonical) == [], f"exemplar {ex.name} is invalid"


def test_exemplar_retrieval_matches_topic():
    from orion_agent.harness.exemplars import retrieve
    assert retrieve("make me a flange with 6 bolt holes")[0].name == "flange_bolt_circle"
    assert retrieve("a stepped shaft 25mm diameter")[0].name == "stepped_shaft"
    assert retrieve("block with rounded corners and a chamfer")[0].name == "rounded_block"
    # no topic hit -> still returns the generic fallback
    assert len(retrieve("xyzzy widget")) >= 1


def test_context_packer_injects_exemplars():
    from orion_agent.harness.context import ContextPacker
    from orion_agent.harness.agent.pillars import GENERATE_PILLAR, QUERY_PILLAR

    bridge = SyntheticBridge(SyntheticModel(name="Empty"))
    packer = ContextPacker(None)
    gen = packer.pack(GENERATE_PILLAR, "make a flange with bolt holes", "empty", None, bridge)
    assert "Worked examples" in gen[0].content
    assert "PolarPattern" in gen[0].content
    # read-only pillars don't pay the token cost
    q = packer.pack(QUERY_PILLAR, "how many holes?", "B", None, bridge)
    assert "Worked examples" not in q[0].content


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


def test_generate_eval_scoring():
    """The generate suite scores dimensions out of the compiled graph."""
    from orion_agent.evals.generate_suite import cases as gen_cases

    def responder(messages, tools):
        from orion_agent.harness.llm.base import LLMResponse, ToolCallRequest
        if messages[-1].role == "tool":
            return LLMResponse(content="Built the plate.")
        return LLMResponse(
            tool_calls=[ToolCallRequest.new("create_featuregraph",
                                            {"graph": _plate_with_hole_graph()})],
            finish_reason="tool_calls")

    harness = EvalHarness(MockClient(responder=responder))
    case = gen_cases()[0]              # plate_center_hole: expects 10 + 5 in graph
    res = harness.run_case(case)
    assert res.passed, res.detail

    # a graph missing the requested dimensions must fail the graph check
    case_flange = gen_cases()[1]       # expects flange radii, not plate numbers
    res2 = harness.run_case(case_flange)
    assert not res2.passed and "graph missing" in res2.detail


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
