"""The seam between deciding a design and building it.

``StudioAgent.design`` used to be one method: it drew a Blueprint from the model
and handed it straight to FreeCAD in the same breath. Nothing was wrong with the
result, but there was no moment at which a design existed and had not yet been
built — and therefore nowhere to put an approval, a revision, or a check that
could have saved the build.

``propose`` and ``build`` are that moment. What these tests pin down:

* a proposal is **frozen**, so it has an identity a decision can be attached to;
* the hash it carries is the same one the builder computes, which is the whole
  basis of "you are building what was approved";
* ``build`` refuses a payload that changed after the proposal;
* the critique settles what arithmetic can settle, before a container starts;
* and ``design`` still behaves exactly as it did — same repair budget, same
  keep-the-best-attempt rule.
"""

import pytest

from app.services import studio_agent as sa


# --------------------------------------------------------------------------- #
# fixtures: a Blueprint that freezes, and a model that returns whatever we say
# --------------------------------------------------------------------------- #
def blueprint(volume_expr: str = "width*width*thick", guard: str = "width - 10") -> dict:
    """A minimal Blueprint that passes the static check: one sketch, one pad."""
    return {
        "part_class": "plate",
        "variables": {"thick": 6.0, "width": 40.0},
        "datums": {},
        "design_plan": {"intent": "a flat plate"},
        "assertions": [
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": volume_expr,
            },
            {"id": "pre_w", "kind": "precondition", "tier": 1, "target": guard},
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad", "parameters": {"Length": "thick"}},
            ],
            "sketches": [
                {
                    "id": "s0",
                    "plane": "XY",
                    "profile": {
                        "builder": "rect",
                        "args": {"w": "width", "h": "width"},
                    },
                }
            ],
            "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"}],
        },
    }


def completion_for(payload: dict) -> str:
    """What the model actually emits: a derivation, then one JSON object."""
    import json

    return (
        "The plate is 40 by 40 by 6.\nPredicted volume: 9600.0 mm^3\n"
        "</think>\n" + json.dumps(payload)
    )


class _Response:
    def __init__(self, content: str, thinking: str = ""):
        self.content = content
        self.thinking = thinking
        self.finish_reason = "stop"
        self.tool_calls = []


@pytest.fixture
def agent(monkeypatch):
    """A StudioAgent whose model returns scripted completions, in order."""
    a = sa.StudioAgent()
    a.scripted: list = []
    a.draws = 0

    def _complete(messages, on_event, channel=None, max_tokens=None, model=None, tools=None):
        reply = a.scripted[min(a.draws, len(a.scripted) - 1)]
        a.draws += 1
        if reply is None:
            return None, ""
        return _Response(reply), "orionflow"

    monkeypatch.setattr(a, "_complete", _complete)
    return a


@pytest.fixture
def no_kernel(monkeypatch):
    """Record every call to the builder, and never actually run FreeCAD."""
    calls: list = []

    def _build_from_payload(payload, request_id=None):
        from orion.blueprint import Blueprint

        calls.append(payload)
        bp = Blueprint.from_dict(payload).freeze()
        return {
            "success": True,
            "request_id": "0123456789ab",
            "blueprint": bp.to_dict(),
            "part_class": bp.part_class,
            "variables": dict(bp.variables),
            "files": {"step": "/api/v1/artifacts/0123456789ab/part.step"},
            "stats": {"volume_mm3": 9600.0},
            "measured": {"features": []},
            "verification": {"verdict": "verified", "checks": []},
            "build_log": {},
            "error": None,
            "generation_time_ms": 10.0,
        }

    from app.services import blueprint_service

    monkeypatch.setattr(blueprint_service, "build_from_payload", _build_from_payload)
    return calls


@pytest.fixture(autouse=True)
def direct_route(monkeypatch):
    """Keep the reasoning chain out of it — routing has its own tests."""
    from app.services import design_router

    monkeypatch.setattr(
        design_router,
        "resolve",
        lambda _p: design_router.Route(design_router.DIRECT, "no load was stated"),
    )


# --------------------------------------------------------------------------- #
# propose: a design that exists before it is a solid
# --------------------------------------------------------------------------- #
def test_a_proposal_is_frozen_and_never_touches_the_kernel(agent, no_kernel):
    payload = blueprint()
    agent.scripted = [completion_for(payload)]

    proposal = agent.propose("a 40mm square plate 6mm thick")

    assert proposal.ok
    assert len(proposal.blueprint_hash) == 64, "a proposal must carry its hash"
    assert proposal.part_class == "plate"
    assert proposal.variables == {"thick": 6.0, "width": 40.0}
    assert [f["id"] for f in proposal.features] == ["pad"]
    assert no_kernel == [], "propose must not build anything"


def test_the_proposed_hash_is_the_one_the_builder_computes(agent, no_kernel):
    """The binding an approval will rely on.

    If these two could differ, "the user approved this Blueprint" and "we built
    that Blueprint" would be two unrelated statements, and every guarantee built
    on the hash would be decoration.
    """
    payload = blueprint()
    agent.scripted = [completion_for(payload)]

    proposal = agent.propose("a plate")
    bundle = agent.build(proposal)

    assert bundle["blueprint"]["blueprint_hash"] == proposal.blueprint_hash


def test_build_refuses_a_payload_that_changed_after_the_proposal(agent, no_kernel):
    """The seed of the approval gate: what is built must be what was proposed."""
    payload = blueprint()
    agent.scripted = [completion_for(payload)]
    proposal = agent.propose("a plate")

    # Someone widens the plate between the decision and the build.
    proposal.payload["variables"]["width"] = 80.0

    bundle = agent.build(proposal)

    assert bundle["success"] is False
    assert "changed between proposal and build" in bundle["error"]


def test_a_request_that_cannot_be_specified_asks_instead_of_guessing(
    agent, no_kernel, monkeypatch
):
    """A stopped chain ends the turn with questions, and never draws."""
    from app.services import design_router

    class _Chain:
        complete = False
        stopped_at = "select_component"
        variables: dict = {}
        citations: list = []
        warnings: list = []

        def asks(self):
            return ["what radial load must the bearing carry?"]

        def to_dict(self):
            return {"stopped_at": self.stopped_at}

    monkeypatch.setattr(
        design_router,
        "resolve",
        lambda _p: design_router.Route(
            design_router.CHAIN, "the request states a load", chain=_Chain()
        ),
    )

    proposal = agent.propose("a bearing housing")

    assert proposal.ok is False
    assert proposal.failure == "questions"
    assert proposal.questions == ["what radial load must the bearing carry?"]
    assert agent.draws == 0, "the model must not be asked to fill the gap"
    assert no_kernel == []


# --------------------------------------------------------------------------- #
# critique: what arithmetic settles before a container starts
# --------------------------------------------------------------------------- #
def _critique(payload: dict) -> dict:
    from orion.blueprint import Blueprint

    return sa.critique(Blueprint.from_dict(payload).freeze(), payload)


def test_a_violated_guard_is_named_before_anything_is_built():
    report = _critique(blueprint(guard="width - 100"))

    assert report["ok"] is False
    assert "preconditions" in report["blocking"]
    pre = next(c for c in report["checks"] if c["id"] == "preconditions")
    assert pre["status"] == "fail"
    assert "pre_w" in pre["detail"]


def test_a_derivation_that_disagrees_with_its_own_profile_is_caught():
    """The failure class SFT cannot teach away: a wrong closed form.

    Every corpus record is a verified one, so the model has never seen a bad
    derivation and its consequence. Here the authored volume is exactly twice
    the profile area times the length, and it costs a millisecond to notice.
    """
    report = _critique(blueprint(volume_expr="width*width*thick*2"))

    assert report["ok"] is False
    assert "volume" in report["blocking"]
    vol = next(c for c in report["checks"] if c["id"] == "volume")
    assert vol["status"] == "fail"
    assert "19200" in vol["detail"] and "9600" in vol["detail"]


def test_a_sound_blueprint_passes_every_check_that_can_run():
    report = _critique(blueprint())

    assert report["ok"] is True
    assert report["blocking"] == []
    assert {c["status"] for c in report["checks"]} == {"pass"}


def test_an_undecidable_volume_is_reported_as_unknown_not_as_a_pass():
    """Silence is not agreement.

    ``analytic_volume`` only answers for a single extrusion, because anywhere
    else the booleans can overlap and the closed form would be a guess. Saying
    "pass" there would put a check mark against something nobody checked.
    """
    payload = blueprint()
    payload["template"]["features"].append(
        {
            "id": "fillet",
            "type": "Fillet",
            "parameters": {"Radius": "thick", "_Edges": "all"},
        }
    )

    report = _critique(payload)

    vol = next(c for c in report["checks"] if c["id"] == "volume")
    assert vol["status"] == "unknown"
    assert "volume" not in report["blocking"]


# --------------------------------------------------------------------------- #
# design: the orchestration, unchanged
# --------------------------------------------------------------------------- #
def test_a_sound_design_builds_once_and_verifies(agent, no_kernel):
    agent.scripted = [completion_for(blueprint())]

    bundle = agent.design("a plate")

    assert bundle["success"] is True
    assert bundle["verification"]["verdict"] == "verified"
    assert agent.draws == 1 and len(no_kernel) == 1
    assert bundle["attempts"] == 1
    # The critique travels with the build, so a stored record carries what was
    # known before the kernel ran as well as what it measured.
    assert bundle["critique"]["ok"] is True


def test_a_reply_that_is_not_a_blueprint_is_repaired_without_a_build(agent, no_kernel):
    """A parse failure costs a model call and nothing else."""
    agent.scripted = ["I would suggest a plate of about 40mm.", completion_for(blueprint())]

    bundle = agent.design("a plate")

    assert bundle["success"] is True
    assert agent.draws == 2
    assert len(no_kernel) == 1, "the unparseable attempt must not reach the kernel"
    assert bundle["attempts"] == 2


def test_a_statically_rejected_blueprint_is_repaired_without_a_build(agent, no_kernel):
    """A bare number where an expression belongs never reaches FreeCAD."""
    bad = blueprint()
    bad["template"]["features"][2]["parameters"]["Length"] = 6.0  # a literal
    agent.scripted = [completion_for(bad), completion_for(blueprint())]

    bundle = agent.design("a plate")

    assert bundle["success"] is True
    assert agent.draws == 2
    assert len(no_kernel) == 1
    assert bundle["attempts"] == 2


def test_the_best_attempt_is_kept_not_the_last(agent, no_kernel, monkeypatch):
    """A later draw that fails must not throw away an earlier part that built.

    Geometry a user can look at beats nothing, even when it is refused.
    """
    from app.services import blueprint_service

    real = blueprint_service.build_from_payload

    def _refused(payload, request_id=None):
        bundle = real(payload, request_id=request_id)
        bundle["verification"] = {"verdict": "refused", "checks": []}
        return bundle

    monkeypatch.setattr(blueprint_service, "build_from_payload", _refused)
    # First draw builds but is refused; second draw is unparseable.
    agent.scripted = [completion_for(blueprint()), "sorry, I cannot do that"]

    bundle = agent.design("a plate")

    assert bundle["success"] is True, "the built part survives the failed repair"
    assert bundle["verification"]["verdict"] == "refused"
    assert bundle["attempts"] == 2, "the repair round is still counted"


def test_a_dead_endpoint_does_not_cost_a_part_that_already_built(agent, no_kernel, monkeypatch):
    from app.services import blueprint_service

    real = blueprint_service.build_from_payload

    def _refused(payload, request_id=None):
        bundle = real(payload, request_id=request_id)
        bundle["verification"] = {"verdict": "refused", "checks": []}
        return bundle

    monkeypatch.setattr(blueprint_service, "build_from_payload", _refused)
    agent.scripted = [completion_for(blueprint()), None]  # None: no model reachable

    bundle = agent.design("a plate")

    assert bundle["success"] is True
    assert bundle["files"]


def test_no_model_at_all_is_reported_as_such(agent, no_kernel):
    agent.scripted = [None]

    bundle = agent.design("a plate")

    assert bundle["success"] is False
    assert "no model is reachable" in bundle["error"]
    assert no_kernel == []


def test_the_event_stream_reports_the_proposal_before_the_build(agent, no_kernel):
    """Order is the contract: a client cannot show a plan it is told about late."""
    agent.scripted = [completion_for(blueprint())]
    seen: list = []

    agent.design("a plate", on_event=lambda kind, data: seen.append((kind, data)))

    kinds = [k for k, _ in seen]
    assert "proposal" in kinds
    assert kinds.index("proposal") < kinds.index("built")
    # The phase flips to building only after there is something to build.
    phases = [d["phase"] for k, d in seen if k == "phase"]
    assert phases == ["reasoning", "building"]

    proposal = next(d for k, d in seen if k == "proposal")
    assert len(proposal["blueprint_hash"]) == 64
    assert proposal["critique"]["ok"] is True
    assert proposal["variables"] == {"thick": 6.0, "width": 40.0}
