"""Studio routes to the deterministic generator, and falls through when it must.

`StudioAgent.propose` is what `/studio/chat` calls. This pins which of three
things a request gets — a compiled Blueprint, a question, or a refusal naming
the number that is wrong — and that anything outside the schema still reaches
the model path.

The model is stubbed: what matters here is the routing and the shape of each
outcome, not whether a live endpoint reads a prompt correctly.
"""

import pytest

from app.services import studio_agent
from orion import blueprint_gen, interview


class _Stub:
    """Answers the interview's two calls: identify, then extract."""

    model = "orionflow-base"

    def __init__(self, family, slots):
        self._family = family
        self._slots = slots
        self.calls = 0

    def chat(self, messages, **kw):
        import json

        self.calls += 1
        body = json.dumps({"family": self._family} if self.calls == 1 else self._slots)
        return type(
            "R",
            (),
            {
                "content": body,
                "thinking": "",
                "tool_calls": [],
                "finish_reason": "stop",
                "usage": {},
            },
        )()


@pytest.fixture
def agent(monkeypatch):
    a = studio_agent.StudioAgent()
    monkeypatch.setattr(studio_agent, "_providers", lambda: ("vllm", ""))
    return a


def _route(agent, monkeypatch, family, slots):
    monkeypatch.setattr(agent, "_client", lambda provider: _Stub(family, slots))
    return agent._deterministic("a request", None)


def test_a_complete_request_is_compiled_not_generated(agent, monkeypatch):
    p = _route(
        agent, monkeypatch, "rect_plate", {"length": 100, "width": 60, "thickness": 5}
    )

    assert p is not None and p.ok
    assert p.part_class == "rect_plate"
    assert p.blueprint_hash
    assert "compiled deterministically" in p.route["why"]


def test_an_incomplete_request_becomes_questions(agent, monkeypatch):
    p = _route(agent, monkeypatch, "rect_plate", {"length": 100})

    assert p is not None and not p.ok
    assert p.failure == "questions"
    assert "How wide should the plate be?" in p.questions


def test_impossible_geometry_is_returned_as_the_answer(agent, monkeypatch):
    """Not handed to the model.

    Falling back would answer "your seat does not fit" with a part that quietly
    did something else — the failure mode this path replaces. The LoRA, given
    exactly this request, returned bearing_housing_plus_vent_slot and reported
    success.
    """
    p = _route(
        agent,
        monkeypatch,
        "bearing_housing",
        {"length": 160, "width": 80, "height": 60, "bore_d": 200.0, "seat_depth": 15},
    )

    assert p is not None and p.failure == "questions"
    assert "does not fit" in p.error


def test_a_family_with_no_builder_falls_through_to_the_model(agent, monkeypatch):
    """A closed list with no way out forces every request into it — a helical
    spring came back as a bearing housing and was asked for its overall width.
    ``None`` means "not mine", and the model path still serves the rest of the
    vocabulary."""
    p = _route(agent, monkeypatch, "other", {})
    assert p is None

    p = _route(agent, monkeypatch, "flange", {"length": 10})
    assert p is None


def test_the_identify_prompt_offers_a_way_out():
    """Pinned because removing it is silent: every request would still be
    classified, just wrongly."""
    assert "other" in interview.IDENTIFY_SYSTEM
    assert set(interview.FAMILY_NAMES) <= set(blueprint_gen.BUILDERS)


def test_a_dead_endpoint_falls_through_rather_than_refusing(agent, monkeypatch):
    """An unreachable model is not a statement about the part."""

    def boom(provider):
        raise RuntimeError("endpoint unreachable")

    monkeypatch.setattr(agent, "_client", boom)
    assert agent._deterministic("a plate 10 x 10 x 2 mm", None) is None
