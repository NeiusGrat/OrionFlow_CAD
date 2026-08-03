"""Metering and the build record: what gets charged, and what gets remembered.

The properties asserted here are the ones whose failure modes are silent. A
gate that closes when the database hiccups takes the product down; a gate that
never opens charges nobody; an evidence writer that drops the per-feature rows
leaves a feature tree with nothing to show and no error to explain why.
"""

import uuid

import pytest

from app.services import studio_persistence as sp


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_anonymous_caller_is_reported_as_unknown():
    """The gate reports; the route decides. /studio/chat refuses these."""
    gate = await sp.studio_gate(authorization=None)
    assert gate.known is False
    assert gate.user_id is None


@pytest.mark.asyncio
async def test_garbage_token_is_treated_as_anonymous():
    gate = await sp.studio_gate(authorization="Bearer not-a-jwt")
    assert gate.known is False


@pytest.mark.asyncio
async def test_over_limit_user_is_refused(monkeypatch):
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.ofl_telemetry.user_id_from_auth_header",
        lambda _auth: user_id,
    )

    async def _limit_reached(_db, _uid):
        return {
            "allowed": False,
            "reason": "limit_reached",
            "message": "You've reached your monthly limit of 10 generations.",
            "used": 10,
            "limit": 10,
        }

    monkeypatch.setattr("app.billing.usage.check_usage_limit", _limit_reached)

    gate = await sp.studio_gate(authorization="Bearer x")
    assert gate.allowed is False
    assert gate.reason == "limit_reached"
    assert gate.used == 10 and gate.limit == 10
    assert gate.known is True


@pytest.mark.asyncio
async def test_gate_fails_open_when_the_database_is_down(monkeypatch):
    """A billing outage must never stop a user designing.

    The opposite choice — refuse when the quota cannot be read — turns every
    database blip into a total outage of the product's only feature.
    """
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.services.ofl_telemetry.user_id_from_auth_header",
        lambda _auth: user_id,
    )

    async def _explode(_db, _uid):
        raise ConnectionError("could not connect to the database")

    monkeypatch.setattr("app.billing.usage.check_usage_limit", _explode)

    gate = await sp.studio_gate(authorization="Bearer x")
    assert gate.allowed is True
    assert gate.user_id == user_id


# --------------------------------------------------------------------------- #
# the evidence
# --------------------------------------------------------------------------- #
def _bundle(**over) -> dict:
    base = {
        "success": True,
        "request_id": "0123456789ab",
        "part_class": "pillow_block",
        "variables": {"L": 80.0, "W": 40.0},
        "attempts": 1,
        "measured": {
            "features": [
                {
                    "name": "Pad",
                    "type_id": "PartDesign::Pad",
                    "addsub_volume": 1000.0,
                    "cumulative_volume": 1000.0,
                },
                {
                    "name": "Pocket",
                    "type_id": "PartDesign::Pocket",
                    "addsub_volume": -120.0,
                    "cumulative_volume": 880.0,
                },
            ],
        },
        "build_log": {
            "where": "modal",
            "build_report": {
                "recompute_errors": [{"id": "Fillet1", "error": "invalid"}],
                "unsupported": [],
                "built": ["Pad", "Pocket"],
            },
        },
        "verification": {"verdict": "verified", "checks": [], "failed": []},
        "assertions": [{"id": "vol", "passed": True}],
        "stats": {"volume_mm3": 880.0},
        "model": "orionflow",
    }
    base.update(over)
    return base


def test_evidence_keeps_the_per_feature_rows():
    """The volumes and the errors are the whole point of the record."""
    evidence = sp.build_evidence(_bundle())

    assert [f["name"] for f in evidence["features"]] == ["Pad", "Pocket"]
    assert evidence["features"][1]["addsub_volume"] == -120.0
    # Keyed by feature id, not by position — a tree marks the wrong node if
    # this is ever flattened to an index.
    assert evidence["recompute_errors"] == [{"id": "Fillet1", "error": "invalid"}]
    assert evidence["built_where"] == "modal"
    assert evidence["part_class"] == "pillow_block"


def test_evidence_survives_a_bundle_with_nothing_in_it():
    """A build that died before measuring still has to produce a record."""
    evidence = sp.build_evidence({})
    assert evidence["features"] == []
    assert evidence["recompute_errors"] == []
    assert evidence["verification"] == {}


@pytest.mark.parametrize(
    "error,expected",
    [
        ("blueprint rejected: bare numeric literal", "freeze"),
        ("blueprint could not be resolved: unknown variable", "resolve"),
        ("the kernel did not converge within 180s", "timeout"),
        ("no Blueprint JSON in completion: ...", "parse"),
        ("no model is reachable — the inference endpoint is down", "model_unreachable"),
        ("Standard_ConstructionError", "build"),
    ],
)
def test_failure_classes_match_the_repair_vocabulary(error, expected):
    """Same partition the repair loop switches on, so the two can be joined."""
    assert sp._error_code(_bundle(success=False, error=error)) == expected


def test_a_refused_part_is_classified_as_an_assertion_failure():
    bundle = _bundle(
        success=True,
        error="assertion vol missed by 3%",
        verification={"verdict": "refused", "checks": []},
    )
    assert sp._error_code(bundle) == "assert"


def test_no_error_means_no_class():
    assert sp._error_code(_bundle()) is None


# --------------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_anonymous_builds_are_not_recorded(monkeypatch):
    """Both tables demand a user; inventing one would corrupt every metric."""
    called = False

    def _fail(*_a, **_k):  # pragma: no cover — asserted by not running
        nonlocal called
        called = True

    monkeypatch.setattr("app.db.session.get_db_context", _fail)
    await sp.record_studio_build(_bundle(), "a pillow block", None)
    assert called is False


@pytest.mark.asyncio
async def test_a_billable_build_is_counted_under_the_action_the_quota_queries():
    """The bug this test exists for: a usage row nobody counts.

    ``track_usage`` accepts any action string, and the quota queries filter on
    exactly one. Recording a build under a descriptive name of its own —
    "studio_design" — writes a perfectly good row that the free-tier counter
    never sees, so the limit never trips. Nothing raises, nothing logs, and the
    only evidence is that metering does not work.

    Asserting on the constant rather than the literal is the point: if the
    billing side ever renames it, this fails here instead of in production.
    """
    from app.billing import usage as billing

    recorded: dict = {}

    async def _capture(
        _db, user_id, action=billing.BILLABLE_ACTION, quantity=1, metadata=None
    ):
        recorded.update(action=action, metadata=metadata or {})

    class _Session:
        def add(self, _row):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *_exc):
            return False

    import app.db.session as session_mod

    original_ctx = session_mod.get_db_context
    original_track = billing.track_usage
    session_mod.get_db_context = lambda: _Ctx()
    billing.track_usage = _capture
    try:
        await sp.record_studio_build(_bundle(), "a pillow block", uuid.uuid4())
    finally:
        session_mod.get_db_context = original_ctx
        billing.track_usage = original_track

    assert recorded.get("action") == billing.BILLABLE_ACTION
    # What kind of build it was still has to be recoverable, just not from the
    # column the quota depends on.
    assert recorded["metadata"]["source"] == "studio"
    assert recorded["metadata"]["part_class"] == "pillow_block"


@pytest.mark.asyncio
async def test_a_failed_build_is_not_charged():
    """We do not bill a user for our own failure to produce geometry."""
    from app.billing import usage as billing

    charged = False

    async def _capture(*_a, **_k):
        nonlocal charged
        charged = True

    class _Ctx:
        async def __aenter__(self):
            return type("S", (), {"add": lambda _s, _r: None})()

        async def __aexit__(self, *_exc):
            return False

    import app.db.session as session_mod

    original_ctx, original_track = session_mod.get_db_context, billing.track_usage
    session_mod.get_db_context = lambda: _Ctx()
    billing.track_usage = _capture
    try:
        await sp.record_studio_build(
            _bundle(success=False, error="no model is reachable"),
            "a pillow block",
            uuid.uuid4(),
        )
    finally:
        session_mod.get_db_context = original_ctx
        billing.track_usage = original_track

    assert charged is False


@pytest.mark.asyncio
async def test_recording_failure_never_raises(monkeypatch):
    """Telemetry is not allowed to cost a user the part they just built."""

    def _explode(*_a, **_k):
        raise RuntimeError("the database is on fire")

    monkeypatch.setattr("app.db.session.get_db_context", _explode)
    # No exception escapes.
    await sp.record_studio_build(_bundle(), "a pillow block", uuid.uuid4())


# --------------------------------------------------------------------------- #
# the telemetry write itself
# --------------------------------------------------------------------------- #
def test_usage_records_is_mapped_to_the_column_that_exists():
    """``UsageRecord.extra_data`` must name the ``metadata`` column explicitly.

    Migration 001 created the column as ``metadata``. The attribute cannot be
    called that — SQLAlchemy reserves it for ``Base.metadata`` — so it was
    renamed to ``extra_data`` and the column name was never pinned. SQLAlchemy
    then derived the column from the attribute and every INSERT went at an
    ``extra_data`` column that has never existed.

    Asserted against the mapping rather than by writing a row, so it holds
    without a database and cannot be satisfied by a fixture that happens to have
    both columns.
    """
    from app.db.models import UsageRecord

    column = UsageRecord.__table__.c["metadata"]
    assert column is not None
    assert UsageRecord.extra_data.property.columns[0].name == "metadata"
    assert "extra_data" not in UsageRecord.__table__.c, (
        "the database has no extra_data column; mapping one would send every "
        "usage insert at a column that does not exist"
    )


def test_every_usage_column_exists_in_the_initial_migration():
    """Guards the whole table against the same drift, not just this one column.

    The mismatch survived because nothing compared the model to the schema. This
    does, cheaply, by reading the column names migration 001 creates.
    """
    import re

    from app.db.models import UsageRecord

    source = open("alembic/versions/001_initial_schema.py", encoding="utf-8").read()
    block = source[source.index("'usage_records'") :]
    block = block[
        : (
            block.index("op.create_table", 1)
            if "op.create_table" in block[1:]
            else len(block)
        )
    ]
    created = set(re.findall(r"sa\.Column\(\s*'([a-z_]+)'", block))

    mapped = {c.name for c in UsageRecord.__table__.columns}
    missing = mapped - created
    assert (
        not missing
    ), f"model columns with no column in migration 001: {sorted(missing)}"


@pytest.mark.asyncio
async def test_a_billing_failure_does_not_lose_the_build_record():
    """The property the production bug violated.

    ``track_usage`` used to run inside the same transaction as the history
    insert and commit it, so when its INSERT raised, both were rolled back — no
    usage row *and* no record of the build. A charge can be reconciled later
    from the record; the record cannot be reconstructed from anything.
    """
    from app.billing import usage as billing

    committed: list = []

    class _Session:
        """Staged rows are only committed if the block exits cleanly.

        Modelling the rollback is the whole point. A fake that recorded ``add``
        immediately would pass against the broken code too — the add *did*
        happen, it was the commit that took it away.
        """

        def __init__(self):
            self.staged: list = []

        def add(self, row):
            self.staged.append(type(row).__name__)

    class _Ctx:
        async def __aenter__(self):
            self.session = _Session()
            return self.session

        async def __aexit__(self, exc_type, *_rest):
            if exc_type is None:
                committed.extend(self.session.staged)
            return False

    async def _explode(*_a, **_kw):
        raise RuntimeError('column "extra_data" does not exist')

    import app.db.session as session_mod

    original_ctx, original_track = session_mod.get_db_context, billing.track_usage
    session_mod.get_db_context = lambda: _Ctx()
    billing.track_usage = _explode
    try:
        await sp.record_studio_build(_bundle(), "a pillow block", uuid.uuid4())
    finally:
        session_mod.get_db_context = original_ctx
        billing.track_usage = original_track

    assert "GenerationHistory" in committed, (
        "the build record must survive a billing failure — it is the half that "
        "cannot be reconstructed"
    )
