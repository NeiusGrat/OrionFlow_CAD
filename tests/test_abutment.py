"""The constraint join, and what it is allowed to conclude.

Attribution here is a constraint satisfaction problem, not a table walk. These
tests exist to keep it that way: that a mapping is accepted only when it is the
unique physically valid one, that ambiguity and rejection are outcomes rather
than failures, and that nothing ever climbs above ATTRIBUTED.
"""

from __future__ import annotations

import json
import os

import pytest

from orion.knowledge import abutment as A
from orion.knowledge.contract import Confidence

_DATA = os.path.join("orion", "knowledge", "skf_abutment.json")


def _row(bore=25.0, r=1.0, da_min=30.0, Da_max=47.0, ra_max=1.0, page=1):
    return A.AbutmentRow(
        bore=bore, r_min=r, da_min=da_min, Da_max=Da_max, ra_max=ra_max, page=page
    )


def _bearing(d=25.0, D=52.0, B=15.0, designation="6205"):
    return {"designation": designation, "d": d, "D": D, "B": B}


# --------------------------------------------------------------------------- #
# the constraints themselves
# --------------------------------------------------------------------------- #
def test_a_shoulder_smaller_than_the_bore_is_refused():
    fail = A.CONSTRAINTS["shaft_shoulder_clears_the_bore"](
        _bearing(), _row(da_min=24.0)
    )
    assert fail and "does not exceed the bore" in fail


def test_a_shoulder_wider_than_the_bearing_is_refused():
    fail = A.CONSTRAINTS["housing_shoulder_inside_the_outside_diameter"](
        _bearing(D=52.0), _row(Da_max=52.0)
    )
    assert fail and "not inside" in fail


def test_a_fillet_larger_than_the_chamfer_is_refused():
    """The shoulder's own fillet has to sit within the ring's corner relief."""
    fail = A.CONSTRAINTS["fillet_fits_inside_the_chamfer"](
        _bearing(), _row(r=0.6, ra_max=1.0)
    )
    assert fail and "exceeds the chamfer" in fail


def test_a_shoulder_inside_the_chamfer_is_refused():
    """Standing off less than 2r puts the shoulder on the corner, not the face.
    That is the failure the shoulder exists to prevent."""
    fail = A.CONSTRAINTS["shaft_shoulder_clears_the_chamfer"](
        _bearing(d=25.0), _row(bore=25.0, r=1.5, da_min=26.0)
    )
    assert fail and "press on the corner" in fail


def test_the_stand_off_is_equal_on_both_sides():
    """da min - d equals D - Da max on every row checkable without
    attribution: 90x140 stands off 5 and 5, 8x22 stands off 2 and 2."""
    check = A.CONSTRAINTS["both_shoulders_stand_off_equally"]
    # 90x140 with da min 95 and Da max 135: 5 and 5.
    assert (
        check(
            _bearing(d=90.0, D=140.0), _row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0)
        )
        is None
    )
    # The same row against a 150 outside diameter stands off 15 on one side.
    fail = check(
        _bearing(d=90.0, D=150.0), _row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0)
    )
    assert fail and "belongs to the outside diameter 140" in fail


# --------------------------------------------------------------------------- #
# the join: exactly one, or nothing
# --------------------------------------------------------------------------- #
def test_a_unique_physically_valid_row_is_attributed():
    bearing = _bearing(d=90.0, D=140.0, designation="6018")
    rows = [
        _row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0),
        _row(bore=90.0, r=2.0, da_min=101.0, Da_max=149.0),
    ]  # a 160 OD
    match = A.attribute(bearing, rows)
    assert match.verdict == A.ATTRIBUTED
    assert match.row.Da_max == 135.0
    assert match.satisfied == sorted(A.CONSTRAINTS)


def test_two_valid_rows_are_ambiguous_and_neither_is_taken():
    """A tie-break is a guess wearing a justification."""
    bearing = _bearing(d=25.0, D=47.0, designation="6005")
    # Both stand off equally on each side and both clear their own chamfer:
    # 2 and 2 at r=0.3, 3.2 and 3.2 at r=0.6. Only the width would separate
    # them, and the abutment table does not carry it.
    rows = [
        _row(bore=25.0, r=0.3, da_min=27.0, Da_max=45.0, ra_max=0.3),
        _row(bore=25.0, r=0.6, da_min=28.2, Da_max=43.8, ra_max=0.6),
    ]
    match = A.attribute(bearing, rows)
    assert match.verdict == A.AMBIGUOUS
    assert match.row is None
    assert match.candidates == 2


def test_identical_rows_are_not_ambiguity():
    """Rows agreeing in every attributed value describe the same shoulder, so
    which one it came from is a distinction without a difference."""
    bearing = _bearing(d=90.0, D=140.0)
    row = _row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0)
    match = A.attribute(bearing, [row, row, row])
    assert match.verdict == A.ATTRIBUTED


def test_no_valid_row_is_a_rejection_not_a_nearest_match():
    bearing = _bearing(d=25.0, D=52.0)
    rows = [_row(bore=25.0, r=1.0, da_min=31.0, Da_max=20.0)]
    match = A.attribute(bearing, rows)
    assert match.verdict == A.REJECTED
    assert match.row is None


def test_a_bearing_from_another_bore_group_is_never_matched():
    match = A.attribute(
        _bearing(d=30.0, D=62.0), [_row(bore=25.0, r=1.0, da_min=31.0, Da_max=57.0)]
    )
    assert match.verdict == A.REJECTED


# --------------------------------------------------------------------------- #
# parsing reads columns, never positions
# --------------------------------------------------------------------------- #
def test_the_bore_heading_is_gated_by_the_verified_catalogue():
    """Without this, a chamfer value on a continuation line reads as the
    heading of its own group — which produced bores of 6.1 and 7.5 mm."""
    page = (
        "Abutment and fillet dimensions r1,2\n"
        "45 48,2 - - 55,4 0,3 47 49 56 0,3 0,015 17\n"
        "7,5 48,2 - - 55,4 0,6 48,2 52 64 0,6 0,02 16\n"
    )
    rows = A.parse_pages([(280, page)], known_bores={45.0})
    assert rows and all(
        r.bore == 45.0 for r in rows
    ), "7,5 is a chamfer, not a bore, and is not in the catalogue"


def test_a_row_without_a_usable_abutment_block_is_dropped_not_half_read():
    page = "Abutment and fillet dimensions r1,2\n45 48,2 - - 55,4 0,3 - - - -\n"
    assert A.parse_pages([(280, page)], known_bores={45.0}) == []


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #
def test_confidence_is_attributed_and_never_climbs():
    """The constraints prove a mapping is physically consistent. They do not
    prove it is the one the manufacturer printed."""
    bearing = _bearing(d=90.0, D=140.0, designation="6018")
    match = A.attribute(bearing, [_row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0)])
    record = A.provenance(bearing, match, object())
    assert record["confidence"] == Confidence.ATTRIBUTED
    assert record["confidence"] != Confidence.MEASURED
    assert record["confidence"] != Confidence.READ


def test_every_field_the_contract_requires_is_present():
    bearing = _bearing(d=90.0, D=140.0, designation="6018")
    match = A.attribute(bearing, [_row(bore=90.0, r=1.0, da_min=95.0, Da_max=135.0)])
    record = A.provenance(bearing, match, object())
    for field in (
        "designation",
        "bearing_family",
        "bore",
        "outside_diameter",
        "width",
        "da_min",
        "Da_max",
        "r_min",
        "matching_constraints",
        "confidence",
        "source_document",
        "source_pages",
    ):
        assert field in record, f"provenance is missing {field}"
    assert record["matching_constraints"], "nothing proved this mapping"
    assert record["source_pages"], "an attributed value with no page"


# --------------------------------------------------------------------------- #
# the generated dataset
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.path.exists(_DATA), reason="abutments not harvested")
class TestHarvested:
    @staticmethod
    def data() -> dict:
        with open(_DATA, encoding="utf-8") as fh:
            return json.load(fh)

    def test_every_attributed_row_satisfies_every_constraint(self):
        """Re-proved from the stored record rather than trusted."""
        for designation, row in self.data()["abutments"].items():
            bearing = {
                "designation": designation,
                "d": row["bore"],
                "D": row["outside_diameter"],
                "B": row["width"],
            }
            candidate = A.AbutmentRow(
                bore=row["bore"],
                r_min=row["r_min"],
                da_min=row["da_min"],
                Da_max=row["Da_max"],
                ra_max=row["ra_max"],
            )
            for name, check in A.CONSTRAINTS.items():
                assert (
                    check(bearing, candidate) is None
                ), f"{designation} violates {name}"

    def test_no_stored_row_claims_more_than_attributed(self):
        for designation, row in self.data()["abutments"].items():
            assert row["confidence"] == Confidence.ATTRIBUTED, designation

    def test_the_shoulder_is_geometrically_possible(self):
        """A shoulder outside the bearing, or inside its own bore, is not a
        shoulder."""
        for designation, row in self.data()["abutments"].items():
            assert (
                row["bore"] < row["da_min"] < row["Da_max"] < row["outside_diameter"]
            ), designation

    def test_unresolved_rows_are_reported_not_dropped(self):
        data = self.data()
        assert data["unresolved"], "ambiguity and rejection are outcomes"
        assert data["gate"]["ambiguous"] + data["gate"]["rejected"] == len(
            data["unresolved"]
        )
        for row in data["unresolved"]:
            assert row["verdict"] in (A.AMBIGUOUS, A.REJECTED)

    def test_the_method_is_recorded_with_the_data(self):
        data = self.data()
        assert "position" in data["method"]
        assert set(data["constraints"]) == set(A.CONSTRAINTS)

    def test_the_ground_truth_the_catalogue_states_is_reproduced(self):
        """Page 37 of the SKF catalogue works an example: a 6211 has
        r1,2 min = 1,5 mm at d = 55 mm."""
        row = self.data()["abutments"].get("6211")
        assert row, "6211 was not attributed"
        assert row["r_min"] == 1.5
        assert row["bore"] == 55.0
