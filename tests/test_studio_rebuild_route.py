"""``POST /studio/rebuild`` — the deterministic half of the studio.

Parameter sliders and the workbench tools both land here, so this route is what
makes a hand edit as accountable as a generated part: same kernel, same static
checker, same metering. The cases worth pinning down are the ones where being
sloppy would mislead a user about what was actually proved — a hand-added
feature reported under the model's old verdict, or an edit that was refused
before the kernel ran being presented as a failed build.

Built with a minimal app holding only the studio router, so the test does not
drag in auth/db/redis through ``app.api.v1.__init__``.
"""

import importlib.util
import os
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_spec = importlib.util.spec_from_file_location(
    "app.api.v1.studio",
    os.path.join(os.path.dirname(__file__), os.pardir, "app", "api", "v1", "studio.py"),
)
studio = importlib.util.module_from_spec(_spec)
sys.modules["app.api.v1.studio"] = studio
_spec.loader.exec_module(studio)

from app.services import blueprint_service  # noqa: E402
from app.services import studio_persistence as sp  # noqa: E402

BLUEPRINT = {
    "part_class": "plate",
    "variables": {"thick": 6.0, "width": 40.0},
    "datums": {},
    "design_plan": {},
    "assertions": [],
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
                "profile": {"builder": "rect", "args": {"w": "width", "h": "width"}},
            }
        ],
        "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"}],
    },
    "blueprint_hash": "abc",
}


@pytest.fixture
def client(monkeypatch):
    """A studio app whose gate, builder and recorder are all under our control."""
    app = FastAPI()
    app.include_router(studio.router, prefix="/api/v1/studio")

    state: dict = {"recorded": [], "built": []}

    def _build(payload, request_id=None):
        # Stands in for FreeCAD: records what it was asked to build and returns
        # a bundle of the shape the real builder produces.
        state["built"].append(payload)
        return {
            "success": True,
            "request_id": "0123456789ab",
            "part_class": payload.get("part_class", ""),
            "variables": payload.get("variables", {}),
            "blueprint": payload,
            "files": {"step": "/api/v1/artifacts/0123456789ab/part.step"},
            "stats": {"volume_mm3": 1000.0},
            "verification": {"verdict": "verified", "checks": []},
            "measured": {"features": []},
            "build_log": {"where": "modal", "build_report": {}},
            "generation_time_ms": 900.0,
            "error": None,
        }

    monkeypatch.setattr(blueprint_service, "build_from_payload", _build)

    async def _record(bundle, prompt, user_id):
        state["recorded"].append({"bundle": bundle, "prompt": prompt, "user_id": user_id})

    monkeypatch.setattr(sp, "record_studio_build", _record)

    def _gate(verdict: sp.StudioGate):
        app.dependency_overrides[studio.studio_gate] = lambda: verdict

    _gate(sp.StudioGate(user_id=uuid.uuid4(), allowed=True))
    return TestClient(app), state, _gate


def test_retuning_a_variable_rebuilds_with_the_new_value(client):
    tc, state, _ = client
    r = tc.post(
        "/api/v1/studio/rebuild",
        json={"blueprint": BLUEPRINT, "variables": {"thick": 9.5}},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert state["built"][0]["variables"]["thick"] == 9.5


def test_retuning_does_not_break_the_contract(client):
    tc, _, _ = client
    r = tc.post(
        "/api/v1/studio/rebuild",
        json={"blueprint": BLUEPRINT, "variables": {"thick": 9.5}},
    )
    # The assertions are expressions over the variables, so they still hold and
    # the verdict still grades this part.
    assert r.json()["contract_broken"] is False


def test_a_hand_added_feature_breaks_the_contract(client):
    tc, _, _ = client
    r = tc.post(
        "/api/v1/studio/rebuild",
        json={
            "blueprint": BLUEPRINT,
            "add_feature": {
                "type": "Fillet",
                "label": "Fillet 1",
                "variables": {"fillet_r_1": 2.0},
                "parameters": {"Radius": "fillet_r_1", "_Edges": "all"},
            },
        },
    )
    assert r.status_code == 200
    # The template changed, so the model's assertions no longer describe this
    # geometry. The UI needs this to stop showing the verdict as a grade.
    assert r.json()["contract_broken"] is True


def test_a_profile_operation_carries_its_sketch_to_the_builder(client):
    tc, state, _ = client
    r = tc.post(
        "/api/v1/studio/rebuild",
        json={
            "blueprint": BLUEPRINT,
            "add_feature": {
                "type": "Pocket",
                "variables": {"d1": 4.0, "r1": 5.0},
                "parameters": {"Length": "d1", "Type": "Length"},
                "sketch": {"builder": "circle", "plane": "XY", "args": {"r": "r1"}},
            },
        },
    )
    assert r.status_code == 200
    built = state["built"][0]["template"]
    assert any(s["profile"]["builder"] == "circle" for s in built["sketches"])
    assert any(d["kind"] == "profile" for d in built["dependencies"])


def test_a_rejected_edit_is_a_400_not_a_failed_build(client):
    tc, state, _ = client
    r = tc.post(
        "/api/v1/studio/rebuild",
        json={"blueprint": BLUEPRINT, "variables": {"nonexistent": 3.0}},
    )
    assert r.status_code == 400
    assert "no variable named" in r.json()["detail"]["error"]
    # The kernel never ran, so there is nothing to record or charge for.
    assert state["built"] == []
    assert state["recorded"] == []


def test_a_rebuild_is_recorded_like_any_other_build(client):
    tc, state, _ = client
    tc.post("/api/v1/studio/rebuild", json={"blueprint": BLUEPRINT, "variables": {"thick": 8.0}})
    # A rebuild is a FreeCAD container whether or not a model was called, and
    # the kernel is the expensive half.
    assert len(state["recorded"]) == 1


def test_an_anonymous_caller_is_refused(client):
    tc, state, gate = client
    gate(sp.StudioGate())
    r = tc.post("/api/v1/studio/rebuild", json={"blueprint": BLUEPRINT})
    assert r.status_code == 401
    assert state["built"] == []


def test_an_over_quota_caller_is_refused_before_the_kernel_runs(client):
    tc, state, gate = client
    gate(
        sp.StudioGate(
            user_id=uuid.uuid4(),
            allowed=False,
            reason="free_tier_limit_reached",
            message="limit",
        )
    )
    r = tc.post("/api/v1/studio/rebuild", json={"blueprint": BLUEPRINT})
    assert r.status_code == 429
    assert r.json()["detail"]["reason"] == "free_tier_limit_reached"
    assert state["built"] == []


def test_a_blueprint_with_no_template_is_refused(client):
    tc, _, _ = client
    r = tc.post("/api/v1/studio/rebuild", json={"blueprint": {"part_class": "x"}})
    assert r.status_code == 400
