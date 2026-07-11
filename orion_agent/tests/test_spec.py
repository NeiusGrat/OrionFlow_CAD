"""Offline tests for the Engineering Intent Parser (network-free, CI-safe).

Run with:  pytest orion_agent/tests/test_spec.py -v
"""

import json

from orion_agent.harness.llm.mock import MockClient
from orion_agent.harness.llm.base import LLMResponse
from orion_agent.harness.spec import (
    EngineeringSpec,
    SpecParser,
    extract_quantities,
    _first_json_object,
)
from orion_agent.harness.tools.registry import build_registry
from orion_agent.harness.agent.loop import AgentLoop
from orion_agent.harness.agent.verify import EditVerifier
from orion_agent.evals.synthetic import SyntheticBridge, SyntheticModel


DRONE_ARM = ("Design a drone arm in 6061-T6 aluminum for CNC machining. "
             "Arm length 140 mm, wall thickness 4 mm, motor mount uses a "
             "16x19 mm bolt pattern with 4 holes and a 28 mm boss.")


# --------------------------------------------------------------------------- #
# deterministic extraction
# --------------------------------------------------------------------------- #
def test_extract_quantities_units_and_patterns():
    q = extract_quantities("length 140 mm, width 14 cm, bore 1 in, pad 16x19 mm, M5")
    assert 140.0 in q["mm"]            # mm passthrough
    assert 140.0 in q["mm"]            # 14 cm -> 140 mm
    assert 25.4 in q["mm"]             # 1 in -> 25.4 mm
    assert 16.0 in q["mm"] and 19.0 in q["mm"]   # AxB pattern, trailing unit
    assert 5.0 in q["raw"]             # M5 thread nominal


def test_extract_counts():
    q = extract_quantities("a plate with 4 holes and 2 slots")
    assert q["counts"] == {"holes": 4, "slots": 2}


def test_regex_fallback_spec():
    spec = SpecParser(llm=None).parse(DRONE_ARM)
    assert spec.source == "regex"
    assert "6061-T6" in spec.material and "alumin" in spec.material
    assert spec.manufacturing == "CNC"
    assert 140.0 in spec.dimensions.values()
    assert 4.0 in spec.dimensions.values()
    assert spec.counts.get("holes") == 4
    assert not spec.is_empty()


# --------------------------------------------------------------------------- #
# LLM extraction + grounding guard
# --------------------------------------------------------------------------- #
def _llm_spec_json(dimensions, counts=None, unresolved=None):
    return json.dumps({
        "part": "drone arm",
        "material": "6061-T6 aluminum",
        "manufacturing": "CNC",
        "dimensions": dimensions,
        "counts": counts or {},
        "interfaces": [{"name": "motor mount", "detail": "16x19 mm bolt pattern"}],
        "constraints": ["fully parametric"],
        "unresolved": unresolved or [],
    })


def test_llm_spec_parsed_and_normalized():
    llm = MockClient().queue(_llm_spec_json(
        {"arm_length": {"value": 140, "unit": "mm"},
         "wall_thickness": "4 mm"},
        counts={"mount holes": 4},
        unresolved=["arm height"],
    ))
    spec = SpecParser(llm).parse(DRONE_ARM)
    assert spec.source == "llm"
    assert spec.part == "drone arm"
    assert spec.dimensions == {"arm_length": 140.0, "wall_thickness": 4.0}
    assert spec.counts == {"mount holes": 4}
    assert spec.interfaces == ["motor mount: 16x19 mm bolt pattern"]
    assert "arm height" in spec.unresolved


def test_grounding_drops_invented_dimension():
    # 55 mm appears nowhere in the request -> must be stripped, not trusted.
    llm = MockClient().queue(_llm_spec_json(
        {"arm_length": 140, "boss_height": 55}))
    spec = SpecParser(llm).parse(DRONE_ARM)
    assert "boss_height" not in spec.dimensions
    assert spec.dimensions == {"arm_length": 140.0}
    assert any("boss_height" in u for u in spec.unresolved)
    assert "boss_height" in spec.notes


def test_grounding_accepts_unit_converted_value():
    # User says 14 cm; extractor normalizes to 140 mm — grounded, kept.
    llm = MockClient().queue(_llm_spec_json({"arm_length": 140}))
    spec = SpecParser(llm).parse("Design an arm, length 14 cm.")
    assert spec.dimensions == {"arm_length": 140.0}


def test_grounding_drops_invented_count():
    llm = MockClient().queue(_llm_spec_json({"arm_length": 140},
                                            counts={"ribs": 7}))
    spec = SpecParser(llm).parse(DRONE_ARM)
    assert "ribs" not in spec.counts
    assert any("ribs" in u for u in spec.unresolved)


def test_llm_failure_falls_back_to_regex():
    llm = MockClient().queue(LLMResponse(content="boom", finish_reason="error"))
    spec = SpecParser(llm).parse(DRONE_ARM)
    assert spec.source == "regex"
    assert 140.0 in spec.dimensions.values()


def test_llm_garbage_falls_back_to_regex():
    llm = MockClient().queue("Sure! Here is a design idea with no JSON at all.")
    spec = SpecParser(llm).parse(DRONE_ARM)
    assert spec.source == "regex"


def test_first_json_object_ignores_prose_and_fences():
    text = 'Sure:\n```json\n{"part": "arm", "dimensions": {}}\n```\ntrailing'
    assert _first_json_object(text) == {"part": "arm", "dimensions": {}}
    assert _first_json_object("no json here") is None


def test_render_contains_unresolved_warning():
    spec = EngineeringSpec(part="arm", dimensions={"length": 140.0},
                           unresolved=["height"])
    text = spec.render()
    assert "length: 140 mm" in text
    assert "height" in text
    assert "assumption" in text
    assert EngineeringSpec().render() == ""


# --------------------------------------------------------------------------- #
# loop integration
# --------------------------------------------------------------------------- #
def test_generate_runs_spec_stage_and_injects_prompt():
    bridge = SyntheticBridge(SyntheticModel(name="Blank"))
    reg = build_registry(bridge, sandbox=None)
    llm = MockClient().queue("Built the arm.")
    loop = AgentLoop(llm, reg, bridge=bridge, spec_parser=SpecParser(llm=None))
    result = loop.run(DRONE_ARM, forced_pillar="generate")

    spec = result.trajectory.spec
    assert spec and spec["source"] == "regex"
    assert 140.0 in spec["dimensions"].values()
    system = llm.calls[0][0].content
    assert "Engineering specification" in system
    assert "140 mm" in system
    assert result.trajectory.validate() == []


def test_query_skips_spec_stage():
    bridge = SyntheticBridge(SyntheticModel(name="Plate", holes=2))
    reg = build_registry(bridge, sandbox=None)
    llm = MockClient().queue("It has 2 holes.")
    loop = AgentLoop(llm, reg, bridge=bridge, spec_parser=SpecParser(llm=None))
    result = loop.run("How many holes does it have?", forced_pillar="query")
    assert result.trajectory.spec == {}
    assert "Engineering specification" not in llm.calls[0][0].content


# --------------------------------------------------------------------------- #
# verifier consumes the spec
# --------------------------------------------------------------------------- #
def test_verifier_uses_spec_counts_over_regex():
    bridge = SyntheticBridge(SyntheticModel(name="Plate", holes=2, faces=12))
    v = EditVerifier(bridge)
    snap = v.snapshot()
    ok = v._intent_consistent("make the plate", snap, snap, {"Plate"},
                              spec={"counts": {"mounting holes": 2}})
    bad = v._intent_consistent("make the plate", snap, snap, {"Plate"},
                               spec={"counts": {"mounting holes": 6}})
    assert ok is True
    assert bad is False
