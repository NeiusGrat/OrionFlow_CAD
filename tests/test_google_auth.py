"""Tests for POST /api/v1/auth/google (Sign in with Google).

Follows the stubbed-DB pattern from test_waitlist_api.py; Google's tokeninfo
call is monkeypatched so no network access happens.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import auth as auth_mod
from app.config import settings
from app.db.models import User, UserRole, UserStatus
from app.db.session import get_db

CLIENT_ID = "test-client-id.apps.googleusercontent.com"

VALID_CLAIMS = {
    "aud": CLIENT_ID,
    "iss": "accounts.google.com",
    "email": "Engineer@Example.COM",
    "email_verified": "true",
    "name": "Test Engineer",
    "picture": "https://lh3.googleusercontent.com/a/photo",
}


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    """Minimal async-session stub: one user lookup + add/flush/commit."""

    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        return FakeResult(self.existing_user)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass


def _make_client(session: FakeSession) -> TestClient:
    app = FastAPI()
    app.include_router(auth_mod.router, prefix="/api/v1/auth")

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _stub_claims(monkeypatch, claims):
    async def fake_fetch(credential):
        return dict(claims)

    monkeypatch.setattr(auth_mod, "_fetch_google_claims", fake_fetch)


@pytest.fixture
def google_enabled(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)


def test_disabled_without_client_id(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    client = _make_client(FakeSession())
    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})
    assert resp.status_code == 503


def test_new_user_created_and_active(google_enabled, monkeypatch):
    session = FakeSession(existing_user=None)
    _stub_claims(monkeypatch, VALID_CLAIMS)
    client = _make_client(session)

    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]

    users = [o for o in session.added if isinstance(o, User)]
    assert len(users) == 1
    user = users[0]
    assert user.email == "engineer@example.com"  # normalized lowercase
    assert user.email_verified is True
    assert user.status == UserStatus.ACTIVE  # no email-verification gate
    assert user.name == "Test Engineer"
    assert session.committed


def test_wrong_audience_rejected(google_enabled, monkeypatch):
    session = FakeSession()
    _stub_claims(monkeypatch, {**VALID_CLAIMS, "aud": "someone-else"})
    client = _make_client(session)
    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})
    assert resp.status_code == 401
    assert session.added == []


def test_unverified_email_rejected(google_enabled, monkeypatch):
    session = FakeSession()
    _stub_claims(monkeypatch, {**VALID_CLAIMS, "email_verified": "false"})
    client = _make_client(session)
    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})
    assert resp.status_code == 401
    assert session.added == []


def test_existing_pending_user_is_activated(google_enabled, monkeypatch):
    existing = User(
        id=uuid.uuid4(),
        email="engineer@example.com",
        password_hash="$2b$12$existinghash",
        name="Old Name",
        role=UserRole.USER,
        status=UserStatus.PENDING_VERIFICATION,
        email_verified=False,
    )
    session = FakeSession(existing_user=existing)
    _stub_claims(monkeypatch, VALID_CLAIMS)
    client = _make_client(session)

    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})

    assert resp.status_code == 200
    assert existing.email_verified is True
    assert existing.status == UserStatus.ACTIVE
    # No second user row was created for the same email.
    assert not any(isinstance(o, User) for o in session.added)


def test_suspended_user_rejected(google_enabled, monkeypatch):
    existing = User(
        id=uuid.uuid4(),
        email="engineer@example.com",
        password_hash="$2b$12$existinghash",
        name="Suspended",
        role=UserRole.USER,
        status=UserStatus.SUSPENDED,
        email_verified=True,
    )
    session = FakeSession(existing_user=existing)
    _stub_claims(monkeypatch, VALID_CLAIMS)
    client = _make_client(session)
    resp = client.post("/api/v1/auth/google", json={"credential": "x" * 30})
    assert resp.status_code == 403
