"""Tests for the public waitlist endpoint.

Uses a minimal FastAPI app with only the waitlist router and a stubbed DB
session, following the pattern in test_ofl_api.py.

The honeypot moved in the same change that added ``name`` and ``company``: it
used to be ``company``, which is now a real field collected by the ``/start``
intake. A bot trap that is also a real column silently stores every bot, so the
trap is ``website`` and these tests pin both halves of that — the new trap
drops, and the old trap's field is now kept.
"""

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
        self.executed = []
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise IntegrityError("dup", None, Exception("unique violation"))
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def execute(self, stmt):
        # The enrichment UPDATE on a duplicate email. Recorded rather than run;
        # what matters here is that it is attempted and that a failure to
        # enrich never turns a successful signup into an error.
        self.executed.append(stmt)
        return None


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


def test_email_only_signup_still_works():
    """The landing form sends no name or company, and must not be refused."""
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist", json={"email": "eng@example.com", "source": "landing"}
    )
    assert resp.status_code == 200
    assert len(session.added) == 1
    assert session.added[0].name is None
    assert session.added[0].company is None


def test_intake_stores_name_and_company():
    """The /start form's whole reason for existing."""
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={
            "email": "ada@analytical.co",
            "name": "  Ada Lovelace  ",
            "company": " Analytical Engines ",
            "source": "try",
        },
    )
    assert resp.status_code == 200
    entry = session.added[0]
    assert entry.email == "ada@analytical.co"
    assert entry.name == "Ada Lovelace"  # trimmed
    assert entry.company == "Analytical Engines"
    assert entry.source == "try"


def test_blank_name_and_company_become_null():
    """Whitespace is not an answer, and must not be stored as though it were."""
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={"email": "eng@example.com", "name": "   ", "company": ""},
    )
    assert resp.status_code == 200
    assert session.added[0].name is None
    assert session.added[0].company is None


def test_honeypot_drops_bots_silently():
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={"email": "bot@spam.com", "website": "http://totally-real.example"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}  # bot sees success
    assert session.added == []  # but nothing was stored


def test_company_is_no_longer_a_honeypot():
    """Regression: `company` used to drop the row. It is a real field now."""
    session = FakeSession()
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={"email": "eng@example.com", "company": "Real Engineering Ltd"},
    )
    assert resp.status_code == 200
    assert len(session.added) == 1
    assert session.added[0].company == "Real Engineering Ltd"


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
    # Nothing to enrich with, so no UPDATE is attempted.
    assert session.executed == []


def test_duplicate_with_identity_enriches_the_existing_row():
    """Someone who left an email months ago and has now told us who they are.

    The row is the same lead with more known about it, and dropping the new
    detail would discard the only thing this endpoint exists to collect.
    """
    session = FakeSession(fail_commit=True)
    client = _make_client(session)
    resp = client.post(
        "/api/v1/waitlist",
        json={
            "email": "dup@example.com",
            "name": "Ada Lovelace",
            "company": "Analytical Engines",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert session.rolled_back
    assert len(session.executed) == 1  # the enrichment UPDATE was attempted
