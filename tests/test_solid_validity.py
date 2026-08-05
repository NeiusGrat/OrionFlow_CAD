"""The kernel's own opinion of the solid, as checks that count.

Enabled 2026-08-05. Until then ``COUNT_SOLID_VALIDITY`` was False and a part
could satisfy every authored assertion to 1e-16 and still be invalid, or in
fourteen disconnected pieces, and be reported VERIFIED.

Both failures were observed, not hypothesised:

* a Blueprint with two overlapping holes built, reported ``watertight: true``,
  ``solids: 1``, volume matching its closed form to 1e-16 — and ``valid: false``.
  OCC had removed two full disks instead of merging the overlapping wires, so
  the arithmetic agreed while the topology did not.
* a shelled enclosure built fillet-then-shell came back as 14 solids with a face
  of negative area, and passed.

Turning this on re-defines VERIFIED, so the published figures were re-measured
rather than re-labelled.
"""

import pytest

from orion_physical_ai import verify


@pytest.fixture
def not_counting(monkeypatch):
    """Restore the pre-2026-08-05 behaviour for one test."""
    monkeypatch.setattr(verify, "COUNT_SOLID_VALIDITY", False)


# --------------------------------------------------------------------------- #
# geometric validity
# --------------------------------------------------------------------------- #
def test_an_invalid_solid_fails_even_when_the_arithmetic_agrees():
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": False})

    assert report["verdict"] != "verified"
    assert "solid:valid" in [c["id"] for c in report["failed"]]


def test_a_valid_solid_still_verifies():
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": True, "solids": 1})

    assert report["verdict"] == "verified"


def test_watertight_does_not_already_cover_this():
    """Why an existing check is not enough.

    Both invalid solids in the local sample were watertight, with ``solids: 1``.
    The two checks that look closest to this one catch neither.
    """
    rows = [{"kind": "watertight", "id": "wt", "passed": True}]
    report = verify.from_assertion_rows(
        rows, measured={"valid": False, "watertight": True, "solids": 1}
    )

    assert report["verdict"] != "verified"


# --------------------------------------------------------------------------- #
# connectedness
# --------------------------------------------------------------------------- #
def test_a_shattered_body_fails():
    """The enclosure case: every assertion agreed, the part was in 14 pieces."""
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-12}]
    report = verify.from_assertion_rows(rows, measured={"valid": True, "solids": 14})

    assert report["verdict"] != "verified"
    failed = [c for c in report["failed"] if c["id"] == "solid:count"]
    assert failed and "14" in failed[0]["detail"]


def test_a_body_with_no_solid_fails():
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 0.0}]
    report = verify.from_assertion_rows(rows, measured={"valid": True, "solids": 0})

    assert report["verdict"] != "verified"
    assert "solid:count" in [c["id"] for c in report["failed"]]


def test_a_single_solid_passes():
    checks = verify.solid_validity_checks({"valid": True, "solids": 1})

    assert [c["status"] for c in checks] == ["pass", "pass"]


# --------------------------------------------------------------------------- #
# the migration hazard
# --------------------------------------------------------------------------- #
def test_an_unmeasured_solid_is_unknown_not_failed():
    """``None`` means the measurement never ran — older records, and any build
    whose measurement pass was skipped. Counting that as a failure would refuse
    parts nobody checked, which is the error this codebase refuses to make
    elsewhere: a check that did not run is not a check that passed, and equally
    not one that failed.
    """
    rows = [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}]
    report = verify.from_assertion_rows(rows, measured={"valid": None, "solids": None})

    assert report["verdict"] == "verified"
    assert not any(c["id"].startswith("solid:") for c in report["checks"])


def test_a_partial_measurement_grades_only_what_it_has():
    """Validity known, count absent — grade the one, stay silent on the other."""
    checks = verify.solid_validity_checks({"valid": False})

    assert [c["id"] for c in checks] == ["solid:valid"]


def test_the_flag_still_disables_everything(not_counting):
    """The rollback path, kept executable."""
    assert verify.solid_validity_checks({"valid": False, "solids": 14}) == []


# --------------------------------------------------------------------------- #
# the wiring — this is the bug that made the flag a no-op
# --------------------------------------------------------------------------- #
def test_the_live_path_hands_the_grader_the_kernel_facts():
    """``blueprint_service`` once passed the grader only volume and extent.

    ``solid_validity_checks`` treats a missing key as "never measured", so the
    checks returned nothing on the live path: the flag could be on and the gate
    would still be open, with no test failing to say so. Flipping the flag
    without this is a no-op, which is why it is pinned here rather than left to
    the integration tests, all of which mock the build out entirely.
    """
    from app.services.blueprint_service import observations

    measured = {
        "body_volume": 48000.0,
        "bbox": [0, 0, 0, 60, 40, 20],
        "valid": False,
        "solids": 14,
        "watertight": True,
    }
    obs = observations(measured, measured["body_volume"], [60.0, 40.0, 20.0])

    assert obs["valid"] is False
    assert obs["solids"] == 14

    report = verify.from_assertion_rows(
        [{"kind": "body_volume", "id": "body", "passed": True, "rel_err": 1e-16}],
        measured=obs,
    )
    assert report["verdict"] != "verified"
    assert {"solid:valid", "solid:count"} <= {c["id"] for c in report["failed"]}


def test_observations_omit_what_was_never_measured():
    """Absent must stay absent, or old records get retroactively refused."""
    from app.services.blueprint_service import observations

    obs = observations({"body_volume": 100.0}, 100.0, [1.0, 1.0, 1.0])

    assert "valid" not in obs and "solids" not in obs
    assert verify.solid_validity_checks(obs) == []
