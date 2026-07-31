"""The gate is the reason harvested data can be trusted.

Extraction proposes and an invariant disposes. These tests exercise the
disposing: that a bad row cannot enter, that a bad field does not take a good
row down with it, and that the harvested catalogues satisfy the properties they
were admitted under.
"""

import json
import os

import pytest

from orion.knowledge.ingest import (
    designation_encodes_bore,
    gate,
    mm_inch_agree,
    ordered,
    positive,
    series_monotonic,
)

HARVEST = os.path.join("orion", "knowledge", "skf_deep_groove.json")
GLANDS = os.path.join("orion", "knowledge", "parker_oring_glands.json")


# --------------------------------------------------------------------------- #
# the gate itself
# --------------------------------------------------------------------------- #
def test_a_misaligned_column_is_caught_by_its_own_checksum():
    """A dual-unit table carries its own proof that the parser did not drift."""
    good = {"d": 25.0, "d_in": 0.9843}
    bad = {"d": 25.0, "d_in": 2.0472}          # actually the D column
    result = gate([good, bad], [mm_inch_agree("d", "d_in")])
    assert len(result.accepted) == 1 and len(result.rejected) == 1
    assert "misaligned" in result.rejected[0].reason


def test_designation_must_match_its_own_bore():
    check = designation_encodes_bore()
    assert check({"designation": "6205", "d": 25.0}) is None
    assert "implies a 25 mm bore" in check({"designation": "6205", "d": 30.0})
    # 00..03 are 10/12/15/17 and exempt from the times-five rule
    assert check({"designation": "6200", "d": 10.0}) is None


def test_a_soft_failure_drops_the_field_not_the_row():
    """Facts in a table are independent: a row whose geometry checks out has
    good geometry whether or not an unrelated column extracted cleanly."""
    row = {"d": 25.0, "d_in": 0.9843, "C_N": 999.0, "C_lbf": 1.0}
    result = gate([row], [mm_inch_agree("d", "d_in")],
                  soft=[(positive("nonexistent"), ("C_N", "C_lbf"))])
    assert len(result.accepted) == 1
    kept = result.accepted[0]
    assert kept["d"] == 25.0                    # geometry survived
    assert "C_N" not in kept and "C_lbf" not in kept
    assert kept["dropped"], "the drop must be recorded, not silent"


def test_the_cross_row_check_catches_a_broken_series():
    """No per-row invariant can see this: every row is individually plausible."""
    rows = [{"designation": "6207", "d": 35.0, "D": 72.0, "B": 17.0},
            {"designation": "6208", "d": 40.0, "D": 80.0, "B": 15.0},
            {"designation": "6209", "d": 45.0, "D": 85.0, "B": 19.0}]
    broken = series_monotonic(rows,
                              series_of=lambda r: r["designation"][:-2],
                              order_of=lambda r: int(r["designation"][-2:]))
    assert any("6208" in str(r.row["designation"]) for r in broken)
    assert any("not monotonic" in r.reason for r in broken)


def test_ordering_and_positivity():
    assert ordered("d", "D")({"d": 25.0, "D": 52.0}) is None
    assert "not less than" in ordered("d", "D")({"d": 52.0, "D": 25.0})
    assert "must be positive" in positive("x")({"x": 0.0})


# --------------------------------------------------------------------------- #
# the harvested catalogues
# --------------------------------------------------------------------------- #
needs_harvest = pytest.mark.skipif(
    not os.path.exists(HARVEST), reason="bearing harvest not generated")


@needs_harvest
def test_harvested_bearings_still_satisfy_their_invariants():
    data = json.load(open(HARVEST, encoding="utf-8"))["bearings"]
    assert len(data) > 400
    rows = [{"designation": k, **v} for k, v in data.items()]
    for row in rows:
        assert row["d"] < row["D"], row
        assert row["B"] > 0, row
        assert designation_encodes_bore()(row) is None, row
    assert not series_monotonic(rows,
                                series_of=lambda r: r["designation"][:-2],
                                order_of=lambda r: int(r["designation"][-2:]))


@needs_harvest
def test_the_values_a_published_web_table_got_wrong():
    data = json.load(open(HARVEST, encoding="utf-8"))["bearings"]
    assert data["6208"]["B"] == 18          # a web table said 15
    assert data["6205"]["C_N"] == 14800.0   # a web table said 3147 (kgf)


@pytest.mark.skipif(not os.path.exists(GLANDS), reason="gland harvest absent")
def test_gland_rows_carry_their_page_so_the_application_is_traceable():
    """The handbook has several gland tables and they disagree for the same
    cord. Deduplicating on cord alone mixes a face seal with a piston seal."""
    data = json.load(open(GLANDS, encoding="utf-8"))
    for row in data["glands"]:
        assert "source_page" in row
        assert row["gland_depth_mm"] < row["cord_dia_mm"]   # squeeze exists
    assert "UNRESOLVED" in data["applies_to"], \
        "the application must not be claimed while it is unread"
