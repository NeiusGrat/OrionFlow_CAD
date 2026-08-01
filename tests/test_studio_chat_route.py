"""The studio route's contract: who is refused, and what gets recorded.

The recording path is the reason this file exists. ``/studio/chat`` returns a
``StreamingResponse`` and registers a ``BackgroundTasks`` callback, and whether
FastAPI runs that callback for a *streamed* response is a framework detail, not
something the code can assert about itself. If it silently did not, every build
would go unrecorded and unbilled with nothing to show for it — so it is asserted
here against the real router rather than assumed.

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

from app.services import studio_persistence as sp  # noqa: E402

BUNDLE = {
    "success": True,
    "request_id": "0123456789ab",
    "part_class": "plate",
    "variables": {"L": 10.0},
    "blueprint": {
        "part_class": "plate",
        "template": {"features": []},
        "variables": {"L": 10.0},
        "blueprint_hash": "abc",
    },
    "files": {"step": "/api/v1/artifacts/0123456789ab/part.step"},
    "stats": {"volume_mm3": 1000.0},
    "verification": {"verdict": "verified", "checks": []},
    "measured": {"features": []},
    "build_log": {"where": "modal", "build_report": {}},
    "narrative": None,
    "thinking": "",
    "generation_time_ms": 1234.0,
    "model": "orionflow",
    "attempts": 1,
}


class _Agent:
    """Stands in for the real agent: no model, no kernel, same shape."""

    def __init__(self, bundle=None):
        self.bundle = bundle or BUNDLE
        self.prompts: list[str] = []

    def design(self, prompt, on_event=None):
        self.prompts.append(prompt)
        return dict(self.bundle)


@pytest.fixture
def client(monkeypatch):
    """A studio app whose gate, agent and recorder are all under our control."""
    app = FastAPI()
    app.include_router(studio.router, prefix="/api/v1/studio")

    state: dict = {"recorded": [], "agent": _Agent()}

    monkeypatch.setattr(
        "app.services.studio_agent.get_studio_agent", lambda: state["agent"]
    )

    async def _record(bundle, prompt, user_id):
        state["recorded"].append(
            {"bundle": bundle, "prompt": prompt, "user_id": user_id}
        )

    monkeypatch.setattr(sp, "record_studio_build", _record)

    def _gate(verdict: sp.StudioGate):
        app.dependency_overrides[studio.studio_gate] = lambda: verdict

    _gate(sp.StudioGate(user_id=uuid.uuid4(), allowed=True))
    return TestClient(app), state, _gate


def _events(response) -> list[str]:
    return [
        line.split(": ", 1)[1]
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]


def test_a_signed_in_design_turn_streams_and_is_recorded(client):
    tc, state, _ = client
    response = tc.post("/api/v1/studio/chat", json={"message": "a 10mm plate"})

    assert response.status_code == 200
    assert "done" in _events(response)
    # The assertion this file exists for: the background task ran.
    assert len(state["recorded"]) == 1
    assert state["recorded"][0]["prompt"] == "a 10mm plate"
    assert state["recorded"][0]["bundle"]["request_id"] == "0123456789ab"


def test_the_done_event_carries_a_feature_tree(client):
    tc, _, _ = client
    response = tc.post("/api/v1/studio/chat", json={"message": "a 10mm plate"})
    assert '"feature_tree"' in response.text


def test_an_anonymous_caller_is_refused(client):
    tc, state, gate = client
    gate(sp.StudioGate())  # no user_id
    response = tc.post("/api/v1/studio/chat", json={"message": "a plate"})

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "authentication_required"
    # Nothing was designed, so nothing is recorded or charged.
    assert state["recorded"] == []
    assert state["agent"].prompts == []


def test_an_over_quota_design_turn_is_refused_before_the_model_runs(client):
    tc, state, gate = client
    gate(
        sp.StudioGate(
            user_id=uuid.uuid4(),
            allowed=False,
            reason="free_tier_limit_reached",
            message="You've reached the free tier limit of 10.",
            used=10,
            limit=10,
        )
    )
    response = tc.post("/api/v1/studio/chat", json={"message": "a plate"})

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["reason"] == "free_tier_limit_reached"
    assert detail["used"] == 10 and detail["limit"] == 10
    # Refused before the expensive part: the model was never called.
    assert state["agent"].prompts == []
    assert state["recorded"] == []


def test_an_over_quota_user_can_still_ask_about_the_open_part(client):
    """Conversation is free. Metering it would tax asking whether a part is right."""
    tc, state, gate = client
    gate(
        sp.StudioGate(
            user_id=uuid.uuid4(),
            allowed=False,
            reason="free_tier_limit_reached",
            message="limit",
        )
    )

    explained: dict = {}

    def _explain(prompt, part=None, history=None, on_event=None):
        explained["prompt"] = prompt
        return {
            "success": True,
            "answer": "because it is 10 mm thick",
            "model": "orionflow",
            "error": None,
        }

    state["agent"].explain = _explain

    response = tc.post(
        "/api/v1/studio/chat",
        json={
            "message": "why is it 10mm?",
            "part": {"part_class": "plate"},
        },
    )

    assert response.status_code == 200
    assert explained["prompt"] == "why is it 10mm?"
    # An explain turn is not a build: nothing recorded, nothing charged.
    assert state["recorded"] == []


def test_a_failed_build_is_still_recorded(client):
    """The failures are the ones worth having a record of."""
    tc, state, _ = client
    state["agent"] = _Agent(
        {
            **BUNDLE,
            "success": False,
            "error": "the kernel did not converge within 180s",
            "verification": {},
            "files": {},
        }
    )

    response = tc.post("/api/v1/studio/chat", json={"message": "an impossible part"})

    assert response.status_code == 200
    assert "error" in _events(response)
    assert len(state["recorded"]) == 1
    assert state["recorded"][0]["bundle"]["success"] is False


def test_health_redacts_the_inference_endpoint_from_anonymous_callers(monkeypatch):
    """It is our own GPU host; an open route must not publish it."""
    app = FastAPI()
    app.include_router(studio.router, prefix="/api/v1/studio")

    class _Stub:
        def health(self):
            return {
                "provider": "vllm",
                "model": "orionflow",
                "endpoint": "http://10.0.0.7:8100/v1",
                "builder": "freecad",
                "builder_mode": "modal",
                "fallback": "",
                "serving_our_model": True,
            }

    monkeypatch.setattr("app.services.studio_agent.get_studio_agent", lambda: _Stub())
    tc = TestClient(app)

    anonymous = tc.get("/api/v1/studio/health").json()
    assert "endpoint" not in anonymous
    # The rest of the report is still public — that is the point of a health check.
    assert anonymous["builder"] == "freecad"

    monkeypatch.setattr(
        "app.services.ofl_telemetry.user_id_from_auth_header",
        lambda _auth: uuid.uuid4(),
    )
    signed_in = tc.get(
        "/api/v1/studio/health", headers={"Authorization": "Bearer x"}
    ).json()
    assert signed_in["endpoint"] == "http://10.0.0.7:8100/v1"


def test_a_structured_refusal_survives_the_global_error_handler():
    """The refusal a client actually receives, not the one we raised.

    ``HTTPException(detail={...})`` is rewritten by the global handler in
    app/main.py before it reaches the browser. That handler used to call
    ``str()`` on the detail, so a structured refusal arrived as the literal text
    ``{'error': 'sign in to design with OrionFlow', 'reason': ...}`` — a Python
    repr shown to the user, with none of its fields readable by the client.
    Asserted end to end through the real handler, because testing the raise
    alone is what let this ship.
    """
    from fastapi import HTTPException as _HTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from app.main import http_exception_handler

    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    @app.get("/refuse")
    def _refuse():
        raise _HTTPException(
            status_code=429,
            detail={
                "error": "You've reached the free tier limit of 10 generations.",
                "reason": "free_tier_limit_reached",
                "used": 10,
                "limit": 10,
            },
        )

    @app.get("/plain")
    def _plain():
        raise _HTTPException(status_code=404, detail="Design not found")

    tc = TestClient(app, raise_server_exceptions=False)

    body = tc.get("/refuse").json()["error"]
    assert body["message"] == "You've reached the free tier limit of 10 generations."
    # The fields beside the message survive, so the UI can act on them.
    assert body["reason"] == "free_tier_limit_reached"
    assert body["used"] == 10 and body["limit"] == 10
    # No Python repr anywhere in what the user is shown.
    assert "{'" not in body["message"]

    # A plain string detail still behaves exactly as before.
    assert tc.get("/plain").json()["error"]["message"] == "Design not found"
