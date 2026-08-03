"""PROPOSAL — treating OCC's ``isValid()`` as a verification failure.

Nothing here changes production. ``COUNT_SOLID_VALIDITY`` is False, and with it
False the verification report is byte-identical to what it has always been.
These tests encode what turning it on would mean, so the decision can be made
against something executable rather than a description.

**The gap it closes.** ``check_assertions`` grades the closed form against the
measurement — volume, extent, the guards the model authored. Nothing asks the
kernel whether the solid is sound. ``measured["valid"]`` carries exactly that
and nothing consumes it.

Observed, not hypothesised: a Blueprint with two overlapping holes built,
reported ``watertight: true``, ``solids: 1``, volume matching its closed form to
1e-16 — and ``valid: false``. It was reported VERIFIED. OCC had removed two full
disks instead of merging the overlapping wires, so the arithmetic agreed while
the topology did not.

**Why this is a decision and not a bugfix.** Every published number was measured
under the current definition — live 88%, the fine-tune's 95.3% and 94.0%.
Flipping the flag re-defines VERIFIED, so those must be re-measured, not
re-labelled.
"""

import pytest

from orion_physical_ai import verify


@pytest.fixture
def counting(monkeypatch):
    """Turn the proposed behaviour on for one test."""
    monkeypatch.setattr(verify, "COUNT_SOLID_VALIDITY", True)


# --------------------------------------------------------------------------- #
# what production does today — must not change
# --------------------------------------------------------------------------- #
def test_today_an_invalid_solid_is_not_counted():
    """The current contract, pinned so this proposal cannot leak into it."""
    assert verify.COUNT_SOLID_VALIDITY is False
    assert verify.solid_validity_checks({"valid": False}) == []


def test_today_a_verified_report_is_unaffected_by_validity():
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": False})

    assert report["verdict"] == "verified", (
        "this is the behaviour the proposal questions — an invalid solid "
        "passing every assertion — and it must stay until the flag is flipped "
        "deliberately"
    )
    assert not any(c["id"].startswith("solid:") for c in report["checks"])


# --------------------------------------------------------------------------- #
# what the proposal would do
# --------------------------------------------------------------------------- #
def test_proposed_an_invalid_solid_fails_even_when_the_arithmetic_agrees(counting):
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": False})

    assert report["verdict"] != "verified"
    failed = [c["id"] for c in report["failed"]]
    assert "solid:valid" in failed


def test_proposed_a_valid_solid_still_verifies(counting):
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": True})

    assert report["verdict"] == "verified"


def test_proposed_an_unmeasured_solid_is_unknown_not_failed(counting):
    """The migration hazard.

    ``valid: None`` means the measurement never ran — older records, and any
    build whose measurement pass was skipped. Counting that as a failure would
    refuse parts nobody checked, which is the error this codebase refuses to
    make elsewhere ("a check that did not run is not a check that passed" —
    equally, it is not a check that failed).

    Of 182 local build records: 179 valid, 2 invalid, 1 unmeasured.
    """
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": None})

    assert report["verdict"] == "verified"
    assert not any(c["id"].startswith("solid:") for c in report["checks"])


def test_proposed_watertight_does_not_already_cover_this(counting):
    """Why an existing check is not enough.

    Both invalid solids in the local sample were watertight. ``watertight`` and
    ``solids: 1`` are the checks that look closest to this one and neither
    catches it, which is the whole argument for adding a third.
    """
    rows = [{"kind": "watertight", "id": "wt", "passed": True}]
    report = verify.from_assertion_rows(
        rows, measured={"valid": False, "watertight": True, "solids": 1}
    )

    assert report["verdict"] != "verified"
