"""Tests for the public waitlist endpoint.

Uses a minimal FastAPI app with only the waitlist router and a stubbed DB
session, following the pattern in test_ofl_api.py.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.v1 import waitlist as waitlist_mod
from app.db.session import get_db


class FakeSession:
    """Records adds/commits; optionally raises IntegrityError on commit."""

    def __init__(self, fail_commit: bool = False):
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("dup", None, Exception("unique violation"))
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _make_client(session: FakeSession) -> TestClient:
    app = FastAPI()
    app.include_router(waitlist_mod.router, prefix="/api/v1/waitlist")

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def test_valid_email_is_stored():
    session = FakeSession()
    client = _make_client(session)
    resp = client.post("/api/v1/waitlist", json={"email": "Eng@Example.COM"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert len(session.added) == 1
    assert session.added[0].email == "eng@example.com"  # normalized lowercase
    assert session.committed


def test_honeypot_drops_bots_silently():
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={"email": "bot@spam.com", "company": "Totally Real Inc"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}  # bot sees success
    assert session.added == []  # but nothing was stored


def test_invalid_email_rejected():
    session = FakeSession()
    client = _make_client(session)
    resp = client.post("/api/v1/waitlist", json={"email": "not-an-email"})
    assert resp.status_code == 422
    assert session.added == []


def test_duplicate_email_is_idempotent():
    session = FakeSession(fail_commit=True)
    client = _make_client(session)
    resp = client.post("/api/v1/waitlist", json={"email": "dup@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}  # no leak that the email exists
    assert session.rolled_back
