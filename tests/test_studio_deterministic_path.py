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


class _Dead:
    """An endpoint that accepts a client and then fails at the transport.

    The distinction this stub exists for: constructing a client against a dead
    box succeeds, because nothing connects until the first request. A fallback
    keyed on construction therefore never fires.
    """

    model = "orionflow"

    def chat(self, messages, **kw):
        return type(
            "R",
            (),
            {
                "content": "[vllm transport error: connection refused]",
                "thinking": "",
                "tool_calls": [],
                "finish_reason": "error",
                "usage": {},
            },
        )()


@pytest.fixture
def agent(monkeypatch):
    a = studio_agent.StudioAgent()
    monkeypatch.setattr(studio_agent, "_providers", lambda: ("vllm", ""))
    # The breaker is module state and would otherwise leak between tests.
    studio_agent._DOWN.clear()
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


def test_a_dead_endpoint_is_not_a_statement_about_the_part(agent, monkeypatch):
    """An unreachable model is not a statement about the part.

    This asserted ``is None`` and got the intent backwards. Falling through
    hands the request to the caller, which answers "This part has no
    deterministic builder, and the fine-tuned model ... is not currently being
    served" — a claim about our capability, made about a request nobody ever
    read. A rate-limited endpoint made "Rectangular plate 100 x 60 x 5 mm"
    report that it could not be built deterministically, and it is a compiled
    family: the bench scored it 0/1 until the 429 that caused it was fixed.

    So the intent is pinned instead of the mechanism. Unread means unread: the
    failure is classed at the model, and nothing is claimed about the family.
    """

    def boom(provider):
        raise RuntimeError("endpoint unreachable")

    monkeypatch.setattr(agent, "_client", boom)
    p = agent._deterministic("a plate 10 x 10 x 2 mm", None)

    assert p is not None, "an unread request must not fall through as 'not mine'"
    assert p.failure == "model", "an outage is an environment failure"
    assert not p.ok
    # The part is a rectangular plate and we compile rectangular plates. The
    # answer must never suggest otherwise.
    assert "no deterministic builder" not in p.error
    assert "rectangular plate" in p.error.lower()


def test_a_dead_primary_is_compiled_by_the_fallback(agent, monkeypatch):
    """The whole architecture hung on this and nothing pinned it.

    A client constructs fine against a dead endpoint, so falling back only on
    construction failure meant the primary always won and then failed at the
    transport. With the GPU down that skipped the deterministic path for every
    request and handed each one to a general model asked to author Blueprint
    JSON — the 1-of-5 outcome this module exists to replace. Compiled geometry
    was unreachable while looking entirely healthy.
    """
    monkeypatch.setattr(studio_agent, "_providers", lambda: ("vllm", "k2think"))
    live = _Stub("rect_plate", {"length": 100, "width": 60, "thickness": 5})
    monkeypatch.setattr(
        agent, "_client", lambda provider: _Dead() if provider == "vllm" else live
    )

    p = agent._deterministic("a plate 100 x 60 x 5 mm", None)

    assert p is not None and p.ok
    assert p.part_class == "rect_plate"
    assert p.model == "compiled:k2think"
    assert studio_agent._is_down("vllm")


def test_a_provider_that_just_failed_is_not_retried_first(agent, monkeypatch):
    """Rediscovering a dead endpoint costs a full connect timeout — 21.4s
    against the torn-down GPU — on every call of every turn. Once is enough."""
    monkeypatch.setattr(studio_agent, "_providers", lambda: ("vllm", "k2think"))
    studio_agent._mark_down("vllm")

    assert studio_agent._in_health_order(("vllm", "k2think")) == ["k2think", "vllm"]


def test_an_unbuildable_family_says_so_when_no_model_can_author_one(
    agent, monkeypatch
):
    """Only our own weights were trained to author a Blueprint. With them
    unserved, a general model spends two sampling rounds arriving at "no
    Blueprint JSON in completion" — measured 22-49s for a spur gear. Naming the
    limit costs 1.5s and tells the user what they can ask for instead."""
    monkeypatch.setattr(studio_agent, "_providers", lambda: ("k2think", ""))
    monkeypatch.setattr(agent, "_client", lambda provider: _Stub("other", {}))

    p = agent.propose("a spur gear, 20 teeth, module 2", None)

    assert not p.ok and p.failure == "model"
    assert "rectangular plate" in p.error  # names what it CAN build
    # And it never reached the model path.
    assert p.completion == ""


def test_a_compiled_blueprint_that_fails_is_never_re_authored_by_the_model(
    agent, monkeypatch
):
    """The repair loop was a way back to model-authored geometry.

    ``_deterministic`` writes no ``base_messages``, so ``repropose`` built the
    repair turn from an empty base: the model received two turns — an empty
    assistant reply and a diagnosis — with no system prompt and no original
    request, and was asked to author a Blueprint out of nothing. A reply that
    happened to parse and verify would have outranked the compiled attempt and
    replaced deterministic geometry with a guess.
    """
    from app.services import blueprint_service

    monkeypatch.setattr(agent, "_client", lambda provider: _Stub(
        "rect_plate", {"length": 100, "width": 60, "thickness": 5}))
    monkeypatch.setattr(
        blueprint_service,
        "build_from_payload",
        lambda payload: {
            "success": False, "error": "OCC: boolean failed",
            "verification": {}, "files": {}, "stats": {}, "assertions": [],
        },
    )
    calls = []
    monkeypatch.setattr(
        agent,
        "_complete",
        lambda *a, **kw: (calls.append(kw.get("model")), (None, ""))[1],
    )

    out = agent.design("a plate 100 x 60 x 5 mm")

    assert calls == [], "a compiled Blueprint was handed to the model to re-author"
    assert "OCC: boolean failed" in str(out.get("error"))


def test_a_provider_on_cooldown_is_still_tried_when_it_is_all_there_is():
    """Moved to the back of the queue, never dropped from it: a blip must not
    leave the studio reporting that no model exists."""
    studio_agent._DOWN.clear()
    studio_agent._mark_down("k2think")
    assert studio_agent._in_health_order(("k2think",)) == ["k2think"]
    studio_agent._DOWN.clear()
