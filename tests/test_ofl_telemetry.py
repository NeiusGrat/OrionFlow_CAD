"""OFL telemetry must attribute users best-effort and never break generation."""

import asyncio

from app.domain.ofl_models import OFLGenerateResponse, OFLGeometryStats
from app.services.ofl_telemetry import log_ofl_event, user_id_from_auth_header


def _response(success=True):
    return OFLGenerateResponse(
        success=success,
        ofl_code="part = 1",
        generation_time_ms=123.4,
        repair_attempts=1,
        stats=(
            OFLGeometryStats(
                watertight=True, volume_mm3=517.5, bbox_mm=[20, 20, 2], triangles=100
            )
            if success
            else None
        ),
    )


def test_user_id_none_without_header():
    assert user_id_from_auth_header(None) is None
    assert user_id_from_auth_header("") is None
    assert user_id_from_auth_header("Basic abc") is None
    assert user_id_from_auth_header("Bearer not-a-jwt") is None


def test_user_id_from_valid_token():
    import uuid

    from app.auth.jwt import create_access_token

    uid = str(uuid.uuid4())
    token = create_access_token(uid, "t@example.com", "user")
    assert user_id_from_auth_header(f"Bearer {token}") == uuid.UUID(uid)


def test_log_swallows_db_failure(monkeypatch):
    """A dead DB must never surface an exception into the request path."""
    import app.db.session as session_mod

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(session_mod, "get_db_context", boom)
    # Must not raise
    asyncio.run(log_ofl_event("generate", _response(), prompt="washer"))


def test_log_writes_event(monkeypatch):
    """Happy path: one OFLEvent is added with the response fields mapped."""
    from contextlib import asynccontextmanager

    added = []

    class FakeSession:
        def add(self, obj):
            added.append(obj)

    @asynccontextmanager
    async def fake_ctx():
        yield FakeSession()

    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "get_db_context", fake_ctx)
    asyncio.run(
        log_ofl_event("edit", _response(), prompt="add a hole", input_code="part = 0")
    )

    assert len(added) == 1
    ev = added[0]
    assert ev.event_type == "edit"
    assert ev.prompt == "add a hole"
    assert ev.input_code == "part = 0"
    assert ev.success is True
    assert ev.repair_attempts == 1
    assert ev.watertight is True
    assert ev.volume_mm3 == 517.5
    assert ev.bbox_mm == [20, 20, 2]
    assert ev.user_id is None
