"""The planner decides numbers; it must not be able to decide a broken part.

Driven with an injected completion so the behaviour under test is the harness,
not a model. What a model would emit varies; what the harness does with a given
emission must not.
"""

import os

import pytest

from app.services.planner import (
    EngineeringPlanner,
    apply_overrides,
    calculator_tools,
    _parse_overrides,
)
from orion.family_schema import DEFAULT_DATA, check_guards

needs_corpus = pytest.mark.skipif(
    not os.path.exists(DEFAULT_DATA), reason="training corpus not present")

ASK = ("aluminium mounting plate for a NEMA 17, 112 mm long, 66 wide, "
       "10 mm thick, milled")


class _Reply:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _answering(payload: str):
    """A completion that ignores the brief and returns ``payload``."""
    def complete(_messages, _tools):
        return _Reply(payload)
    return complete


# --------------------------------------------------------------------------- #
def test_calculator_tools_expose_real_signatures():
    tools = calculator_tools()
    assert tools
    names = {t["function"]["name"] for t in tools}
    assert "calc_thread_engagement" in names
    by_name = {t["function"]["name"]: t for t in tools}
    props = by_name["calc_thread_engagement"]["function"]["parameters"]["properties"]
    assert set(props) == {"d_mm", "pitch_mm", "bolt_uts_mpa", "nut_material"}
    # nothing structured leaks in as a scalar
    assert "args" not in {p for t in tools
                          for p in t["function"]["parameters"]["properties"]}
    assert "calc_kutzbach_mobility" not in names   # takes list[dict]


@needs_corpus
def test_baseline_alone_is_a_working_part():
    """No model configured is not a failure — the medians build."""
    result = EngineeringPlanner().plan(ASK)
    assert result.ok
    assert result.specification.part_class == "mount_plate"
    assert result.specification.variables["pl"] == 112.0
    assert all(g["holds"] for g in result.guards)
    assert result.applied == [] and result.refused == []


@needs_corpus
def test_a_justified_override_is_applied():
    planner = EngineeringPlanner(_answering(
        '[{"variable": "pt", "value": 6.0, '
        '"why": "6 mm is the thinnest section giving full M4 engagement"}]'))
    result = planner.plan(ASK)
    assert result.specification.variables["pt"] == 6.0
    assert result.applied[0]["variable"] == "pt"
    assert "M4" in result.specification.rationale["pt"]
    assert all(g["holds"] for g in result.guards)


@needs_corpus
def test_an_override_that_would_break_a_guard_is_refused_with_the_arithmetic():
    """The whole point: the planner is told what it did, at the moment it did
    it, instead of the verifier refusing the part three stages later."""
    # mount_plate: corner_margin = min(pl/2 - mx, pw/2 - my) - hr - 2.
    # Pushing the hole centre out to the edge drives it negative.
    planner = EngineeringPlanner(_answering(
        '[{"variable": "mx", "value": 55.0, "why": "wider bolt spacing"}]'))
    result = planner.plan(ASK)

    assert result.applied == []
    assert len(result.refused) == 1
    reason = result.refused[0]["reason"]
    assert "corner_margin" in reason and "must be > 0" in reason
    # the specification is untouched and still builds
    assert result.specification.variables["mx"] != 55.0
    assert all(g["holds"] for g in result.guards)


@needs_corpus
def test_an_invented_variable_is_refused():
    planner = EngineeringPlanner(_answering(
        '[{"variable": "thickness", "value": 8.0, "why": "thicker"}]'))
    result = planner.plan(ASK)
    assert result.applied == []
    assert "not a mount_plate variable" in result.refused[0]["reason"]


@needs_corpus
def test_non_numeric_value_is_refused():
    planner = EngineeringPlanner(_answering(
        '[{"variable": "pt", "value": "8 mm", "why": "thicker"}]'))
    result = planner.plan(ASK)
    assert result.applied == []
    assert "not a number" in result.refused[0]["reason"]


@needs_corpus
def test_empty_override_list_keeps_the_baseline():
    result = EngineeringPlanner(_answering("[]")).plan(ASK)
    assert result.applied == [] and result.refused == []
    assert result.specification.variables == result.baseline


@needs_corpus
def test_planner_output_never_reaches_the_design_prompt():
    planner = EngineeringPlanner(_answering(
        '[{"variable": "pt", "value": 6.0, "why": "per ISO 2768-mK and a '
        'calculated 5.9 mm engagement"}]'))
    result = planner.plan(ASK)
    prompt = result.specification.to_prompt()
    assert "pt=6" in prompt
    # NB "why" is not a canary: the trained sentence itself ends
    # "...state the volume you expect and why."
    for leaked in ("ISO 2768", "engagement", "5.9", "calculated"):
        assert leaked not in prompt
    # the justification is kept, just not in the prompt
    assert "ISO 2768" in result.specification.rationale["pt"]


@needs_corpus
def test_model_failure_leaves_the_baseline_standing():
    def explode(_messages, _tools):
        raise RuntimeError("endpoint down")

    result = EngineeringPlanner(explode).plan(ASK)
    assert "endpoint down" in result.error
    assert result.specification is not None
    assert result.specification.variables["pl"] == 112.0


# --------------------------------------------------------------------------- #
def test_override_parsing_tolerates_fences_and_prose():
    assert _parse_overrides('[{"variable":"pt","value":6}]')[0]["value"] == 6
    fenced = 'Here you go:\n```json\n[{"variable":"pt","value":6}]\n```\n'
    assert _parse_overrides(fenced)[0]["variable"] == "pt"
    assert _parse_overrides("<think>hmm</think>\n[]") == []
    assert _parse_overrides("no json here") == []


@needs_corpus
def test_apply_overrides_is_pure():
    from app.services.engineering_spec import EngineeringSpecification
    from orion.family_schema import for_family

    schema = for_family("mount_plate")
    original = EngineeringSpecification(
        "mount_plate", {n: schema.variables[n].median for n in schema.required()})
    before = dict(original.variables)
    updated, applied, _ = apply_overrides(
        original, [{"variable": "pt", "value": 7.0, "why": "x"}])
    assert original.variables == before          # untouched
    assert updated.variables["pt"] == 7.0
    assert applied and all(
        g["holds"] for g in check_guards("mount_plate", updated.variables))
