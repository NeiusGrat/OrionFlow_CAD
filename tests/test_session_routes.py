"""The session routes: who is refused, and with which status code.

The workflow itself is covered in ``test_design_sessions.py``. What is left is
the translation layer — that an anonymous caller cannot start a session, that a
domain refusal arrives as the status code it actually means, and that a client
can act on ``reason`` rather than matching on prose.

The status codes are the point. Flattening ``approval_required`` and
``stale_revision`` both to 400 would leave a client unable to tell "you may not
do this" from "the thing you were looking at moved", and those need different
handling in the UI: one is a bug in the client's flow, the other is a refresh.
"""

import importlib.util
import os
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_spec = importlib.util.spec_from_file_location(
    "app.api.v1.sessions",
    os.path.join(
        os.path.dirname(__file__), os.pardir, "app", "api", "v1", "sessions.py"
    ),
)
routes = importlib.util.module_from_spec(_spec)
sys.modules["app.api.v1.sessions"] = routes
_spec.loader.exec_module(routes)

from app.domain.design_session import (  # noqa: E402
    AlreadyBuilt,
    BlueprintDrifted,
    InvalidTransition,
    NotApproved,
    SessionError,
)
from app.services.studio_persistence import StudioGate  # noqa: E402

USER = uuid.uuid4()
SID = str(uuid.uuid4())

VIEW = {"id": SID, "state": "awaiting_approval", "current_revision": 1}


@pytest.fixture
def client(monkeypatch):
    """Build a client with only these routes and the service stubbed out.

    The stubs go through ``monkeypatch`` rather than a bare ``setattr``, which
    is not a style preference: an unwound ``setattr`` on a module attribute
    survives the test that made it, so ``design_sessions.create`` stayed
    replaced by a stub for the entire rest of the session. Every later test that
    used the real service got a canned dict back and failed with "no such design
    session" — a failure whose cause is in a different file and only appears
    when the two are run together.
    """
    from app.services import design_sessions
    from app.services.studio_persistence import studio_gate

    def _make(gate: StudioGate, **stubs) -> TestClient:
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/v1/studio/sessions")

        async def _gate():
            return gate

        app.dependency_overrides[studio_gate] = _gate

        for name, fn in stubs.items():
            monkeypatch.setattr(design_sessions, name, fn)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def allowed() -> StudioGate:
    return StudioGate(user_id=USER, allowed=True)


async def _ok(*a, **kw):
    return VIEW


# --------------------------------------------------------------------------- #
# who may call at all
# --------------------------------------------------------------------------- #
def test_an_anonymous_caller_cannot_start_a_session(client):
    """A session is keyed to an account in the schema, and both its calls cost
    money. There is no anonymous one to fall back to."""
    tc = client(StudioGate(), create=_ok)
    resp = tc.post("/api/v1/studio/sessions", json={"prompt": "a plate"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["reason"] == "authentication_required"


def test_an_over_quota_caller_is_refused_before_the_model_runs(client):
    called = {"n": 0}

    async def _count(*a, **kw):
        called["n"] += 1
        return VIEW

    gate = StudioGate(
        user_id=USER, allowed=False, reason="limit_reached", used=10, limit=10
    )
    tc = client(gate, create=_count)

    resp = tc.post("/api/v1/studio/sessions", json={"prompt": "a plate"})

    assert resp.status_code == 429
    assert resp.json()["detail"]["reason"] == "limit_reached"
    assert called["n"] == 0


def test_an_over_quota_caller_may_still_read_and_decide(client):
    """Reading a session and rejecting a plan cost nothing, and making them
    unavailable at the limit would trap a design mid-flight."""
    gate = StudioGate(user_id=USER, allowed=False, reason="limit_reached")
    tc = client(gate, get=_ok, reject=_ok)

    assert tc.get(f"/api/v1/studio/sessions/{SID}").status_code == 200
    assert (
        tc.post(
            f"/api/v1/studio/sessions/{SID}/reject",
            json={"revision": 1, "note": "wrong"},
        ).status_code
        == 200
    )


def test_an_over_quota_caller_cannot_build(client):
    gate = StudioGate(user_id=USER, allowed=False, reason="limit_reached")
    tc = client(gate, build=_ok)
    assert tc.post(f"/api/v1/studio/sessions/{SID}/build").status_code == 429


# --------------------------------------------------------------------------- #
# refusals keep their meaning
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc,status,reason",
    [
        (NotApproved("not approved"), 403, "approval_required"),
        (AlreadyBuilt("already built"), 409, "already_built"),
        (BlueprintDrifted("drifted"), 409, "blueprint_drifted"),
        (
            InvalidTransition("bad move", current="built", target="approved"),
            409,
            "invalid_transition",
        ),
        (
            SessionError("stale", reason="stale_revision", current=2),
            409,
            "stale_revision",
        ),
    ],
)
def test_a_domain_refusal_arrives_as_the_code_it_means(client, exc, status, reason):
    async def _raise(*a, **kw):
        raise exc

    tc = client(allowed(), build=_raise, approve=_raise)

    resp = tc.post(f"/api/v1/studio/sessions/{SID}/build")
    assert resp.status_code == status
    detail = resp.json()["detail"]
    assert detail["reason"] == reason
    assert detail["error"], "a refusal must say something a person can read"


def test_the_refusal_carries_the_fields_a_client_needs(client):
    async def _raise(*a, **kw):
        raise InvalidTransition(
            "a session in built cannot move to approved",
            current="built",
            target="approved",
            allowed=["completed", "needs_revision"],
        )

    tc = client(allowed(), approve=_raise)
    detail = tc.post(
        f"/api/v1/studio/sessions/{SID}/approve", json={"revision": 1}
    ).json()["detail"]

    assert detail["current"] == "built"
    assert detail["allowed"] == ["completed", "needs_revision"]


# --------------------------------------------------------------------------- #
# the shape of a request
# --------------------------------------------------------------------------- #
def test_a_decision_must_name_its_revision(client):
    """Defaulting to "the current one" is how an approval silently transfers to
    a design the user never saw."""
    tc = client(allowed(), approve=_ok)
    assert tc.post(f"/api/v1/studio/sessions/{SID}/approve", json={}).status_code == 422


def test_a_malformed_session_id_is_a_404_not_a_500(client):
    tc = client(allowed(), get=_ok)
    resp = tc.get("/api/v1/studio/sessions/not-a-uuid")
    assert resp.status_code == 404
    assert resp.json()["detail"]["reason"] == "not_found"


def test_build_passes_force_through(client):
    seen = {}

    async def _build(user_id, session_id, force=False):
        seen["force"] = force
        return VIEW

    tc = client(allowed(), build=_build)

    tc.post(f"/api/v1/studio/sessions/{SID}/build")
    assert seen["force"] is False

    tc.post(f"/api/v1/studio/sessions/{SID}/build?force=true")
    assert seen["force"] is True


def test_the_routes_are_mounted_where_the_client_expects(client):
    """Guards the prefix, which nothing else would catch until a 404 in the UI.

    Read off the OpenAPI schema rather than by walking ``api_router.routes``.
    That walk assumed every entry exposes ``.path``, which is a FastAPI internal
    — a newer version wraps included routers in ``_IncludedRouter`` objects that
    do not, and the test failed on CI while passing locally purely because the
    two resolved different versions of an unpinned dependency. The schema is the
    published contract and is what a client actually reads, so asserting on it
    tests the thing that matters and cannot break on an internal again.
    """
    from fastapi import FastAPI as _FastAPI

    from app.api.v1 import api_router

    probe = _FastAPI()
    probe.include_router(api_router)
    paths = set(probe.openapi()["paths"])

    assert "/api/v1/studio/sessions" in paths
    assert "/api/v1/studio/sessions/{session_id}/build" in paths
    assert "/api/v1/studio/sessions/{session_id}/approve" in paths
    assert "/api/v1/studio/sessions/{session_id}/events" in paths
    # The one-shot route is untouched and still mounted beside it.
    assert "/api/v1/studio/chat" in paths
