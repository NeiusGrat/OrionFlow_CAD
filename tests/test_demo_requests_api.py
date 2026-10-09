"""Tests for the public "Book a demo" endpoint.

Minimal FastAPI app with only the demo router and a stubbed DB session, the
same pattern as test_waitlist_api.py. The mail send is stubbed so the tests
prove the notification is scheduled without touching a provider.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import demo as demo_mod
from app.db.session import get_db


class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def _make_client(session, sent, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        demo_mod, "send_email", lambda to, subject, html: sent.append((to, subject, html))
    )
    app = FastAPI()
    app.include_router(demo_mod.router, prefix="/api/v1/demo-requests")

    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


VALID = {
    "name": " Ada Lovelace ",
    "email": "Ada@Example.COM",
    "company": " Analytical Engines ",
    "role": "Head of Mechanical",
    "message": "Drawing checks on <b>castings</b>",
}


def test_valid_request_is_stored_and_announced(monkeypatch):
    session, sent = FakeSession(), []
    client = _make_client(session, sent, monkeypatch)
    resp = client.post("/api/v1/demo-requests", json=VALID)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert session.committed
    row = session.added[0]
    assert (row.name, row.email, row.company) == (
        "Ada Lovelace",
        "ada@example.com",
        "Analytical Engines",
    )
    assert row.source == "landing"
    assert len(sent) == 1
    to, subject, html = sent[0]
    assert "Ada Lovelace" in subject and "Analytical Engines" in subject
    # Visitor-supplied text is escaped before it lands in an HTML email.
    assert "<b>castings</b>" not in html and "&lt;b&gt;castings" in html


def test_honeypot_stores_nothing_and_sends_nothing(monkeypatch):
    session, sent = FakeSession(), []
    client = _make_client(session, sent, monkeypatch)
    resp = client.post("/api/v1/demo-requests", json={**VALID, "website": "spam.biz"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert session.added == [] and sent == []


def test_missing_required_fields_are_refused(monkeypatch):
    session, sent = FakeSession(), []
    client = _make_client(session, sent, monkeypatch)
    for field in ("name", "email", "company"):
        body = {k: v for k, v in VALID.items() if k != field}
        assert client.post("/api/v1/demo-requests", json=body).status_code == 422
    assert client.post(
        "/api/v1/demo-requests", json={**VALID, "email": "not-an-email"}
    ).status_code == 422
    assert session.added == []


def test_optional_fields_may_be_blank(monkeypatch):
    session, sent = FakeSession(), []
    client = _make_client(session, sent, monkeypatch)
    resp = client.post(
        "/api/v1/demo-requests",
        json={"name": "A", "email": "a@b.co", "company": "C", "role": " ", "message": ""},
    )
    assert resp.status_code == 200
    assert session.added[0].role is None and session.added[0].message is None
