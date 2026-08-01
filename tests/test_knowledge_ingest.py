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
    bad = {"d": 25.0, "d_in": 2.0472}  # actually the D column
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
    result = gate(
        [row],
        [mm_inch_agree("d", "d_in")],
        soft=[(positive("nonexistent"), ("C_N", "C_lbf"))],
    )
    assert len(result.accepted) == 1
    kept = result.accepted[0]
    assert kept["d"] == 25.0  # geometry survived
    assert "C_N" not in kept and "C_lbf" not in kept
    assert kept["dropped"], "the drop must be recorded, not silent"


def test_the_cross_row_check_catches_a_broken_series():
    """No per-row invariant can see this: every row is individually plausible."""
    rows = [
        {"designation": "6207", "d": 35.0, "D": 72.0, "B": 17.0},
        {"designation": "6208", "d": 40.0, "D": 80.0, "B": 15.0},
        {"designation": "6209", "d": 45.0, "D": 85.0, "B": 19.0},
    ]
    broken = series_monotonic(
        rows,
        series_of=lambda r: r["designation"][:-2],
        order_of=lambda r: int(r["designation"][-2:]),
    )
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
    not os.path.exists(HARVEST), reason="bearing harvest not generated"
)


@needs_harvest
def test_harvested_bearings_still_satisfy_their_invariants():
    data = json.load(open(HARVEST, encoding="utf-8"))["bearings"]
    assert len(data) > 400
    rows = [{"designation": k, **v} for k, v in data.items()]
    for row in rows:
        assert row["d"] < row["D"], row
        assert row["B"] > 0, row
        assert designation_encodes_bore()(row) is None, row
    assert not series_monotonic(
        rows,
        series_of=lambda r: r["designation"][:-2],
        order_of=lambda r: int(r["designation"][-2:]),
    )


@needs_harvest
def test_the_values_a_published_web_table_got_wrong():
    data = json.load(open(HARVEST, encoding="utf-8"))["bearings"]
    assert data["6208"]["B"] == 18  # a web table said 15
    assert data["6205"]["C_N"] == 14800.0  # a web table said 3147 (kgf)


@pytest.mark.skipif(not os.path.exists(GLANDS), reason="gland harvest absent")
def test_gland_rows_carry_their_page_and_arrangement():
    """The handbook has several gland tables and they disagree for the same
    cord. Deduplicating on cord alone mixes a face seal with a piston seal, so
    every row must say which arrangement it is for — or say that it cannot."""
    data = json.load(open(GLANDS, encoding="utf-8"))
    for row in data["rows"]:
        assert "source_page" in row
        assert row["gland_depth_mm"] < row["cord_dia_mm"]  # squeeze exists
        assert row["applies_to"], "every row must state its arrangement"
        assert row["standard"] and row["units"] and row["confidence"]


@pytest.mark.skipif(not os.path.exists(GLANDS), reason="gland harvest absent")
def test_an_unresolved_arrangement_is_marked_not_guessed():
    """AMBIGUOUS rows carry correct numbers and an unestablished application.
    That is the part a caller would machine to, so it must not read as known."""
    from orion.knowledge.contract import Confidence

    data = json.load(open(GLANDS, encoding="utf-8"))
    for row in data["rows"]:
        if row["applies_to"] == "AMBIGUOUS":
            assert row["confidence"] == Confidence.DERIVED
            assert len(row["arrangements"]) != 1


@pytest.mark.skipif(not os.path.exists(GLANDS), reason="gland harvest absent")
def test_every_dataset_records_the_document_and_loader_version():
    """A loader bug found later needs a precise blast radius."""
    data = json.load(open(GLANDS, encoding="utf-8"))
    source = data["source"]
    for key in ("manufacturer", "document", "edition", "loader", "loader_version"):
        assert source.get(key), f"{key} missing from the dataset source"


# --------------------------------------------------------------------------- #
# the contract, exercised by a real loader
# --------------------------------------------------------------------------- #
def test_the_bearing_loader_implements_the_contract():
    from orion.knowledge.contract import ComponentLoader
    from orion.knowledge.skf_bearings import DeepGrooveBearingLoader

    loader = DeepGrooveBearingLoader()
    assert isinstance(loader, ComponentLoader)
    assert loader.family and loader.standard
    assert loader.invariants()


def test_the_designation_grammar_is_a_checkable_claim():
    """A designation encodes the bore. Two conventions, and getting them
    confused calls a 3 mm bearing a 115 mm one."""
    from orion.knowledge.skf_bearings import DeepGrooveBearingLoader

    loader = DeepGrooveBearingLoader()
    assert loader.parse_designation("6205")["bore_mm"] == 25.0
    assert loader.parse_designation("6208")["bore_mm"] == 40.0
    # miniature series: bore is the LAST SINGLE digit, in mm directly
    assert loader.parse_designation("623")["bore_mm"] == 3.0
    assert loader.parse_designation("608")["bore_mm"] == 8.0
    # 00..03 are the exceptions to the times-five rule
    assert loader.parse_designation("6200")["bore_mm"] == 10.0
    # a suffix must not be absorbed into the code
    assert loader.parse_designation("6205-2RS")["designation"] == "6205"
    assert loader.parse_designation("nonsense") is None


def test_a_bearing_exposes_the_interfaces_a_design_meets_it_through():
    """Interfaces are the graph edges: nodes are components, edges are why
    they connect."""
    from orion.knowledge.skf_bearings import DeepGrooveBearingLoader

    edges = DeepGrooveBearingLoader().interfaces({"d": 25.0, "D": 52.0, "B": 15.0})
    kinds = {e.kind: e for e in edges}
    assert {"shaft_seat", "housing_seat"} <= set(kinds)
    assert kinds["shaft_seat"].nominal_mm == 25.0
    assert kinds["housing_seat"].nominal_mm == 52.0
    # a fit is only correct for the duty it was chosen under, so the condition
    # travels with the class
    assert kinds["housing_seat"].fit_class and kinds["housing_seat"].constraint


def test_confidence_reflects_how_a_row_was_established():
    from orion.knowledge.contract import Confidence
    from orion.knowledge.skf_bearings import DeepGrooveBearingLoader

    loader = DeepGrooveBearingLoader()
    # geometry cross-checked against the inch columns, ratings against N/lbf
    assert loader.confidence({"d": 25.0, "C_N": 14800.0}) == Confidence.MEASURED
    # ratings dropped by the soft gate: the geometry is still good
    assert loader.confidence({"d": 25.0}) == Confidence.READ
    # a row is only as trustworthy as its weakest ingredient
    assert (
        Confidence.weakest(Confidence.MEASURED, Confidence.ATTRIBUTED)
        == Confidence.ATTRIBUTED
    )


@needs_harvest
def test_the_bearing_dataset_is_versioned_like_the_gland_one():
    data = json.load(open(HARVEST, encoding="utf-8"))
    assert data["schema_version"] >= 2
    assert data["family"] == "deep_groove_ball_bearing"
    for key in ("manufacturer", "document", "edition", "loader_version"):
        assert data["source"].get(key), f"{key} missing"
    assert (
        data["rows"] and "bearings" in data
    ), "the legacy key must stay while callers migrate"


def test_two_families_now_share_the_contract():
    """One example does not prove an interface generalises. The O-ring loader
    is the second, and it is the one that pushed back."""
    from orion.knowledge.contract import ComponentLoader
    from orion.knowledge.parker_orings import ORingGlandLoader
    from orion.knowledge.skf_bearings import DeepGrooveBearingLoader

    for loader in (DeepGrooveBearingLoader(), ORingGlandLoader()):
        assert isinstance(loader, ComponentLoader)
        assert loader.family and loader.invariants()


def test_a_family_without_designations_is_allowed_to_say_so():
    """A gland's identity is (cord diameter, arrangement) — there is no
    designation. Fabricating one would let a caller look glands up by a key
    that does not exist. Retaining rings and keys are the same."""
    from orion.knowledge.parker_orings import ORingGlandLoader

    assert ORingGlandLoader().parse_designation("1.78") is None


def test_the_contract_enriches_every_row_it_accepts():
    """family, confidence, provenance, properties and interfaces are added by
    the pipeline, not by each loader repeating itself."""
    data = json.load(open(GLANDS, encoding="utf-8"))
    for row in data["rows"]:
        assert row["family"] == "o_ring_gland"
        assert row["confidence"] and row["provenance"]["pages"]
        assert row["properties"]["compression_pct"]
        kinds = {i["kind"] for i in row["interfaces"]}
        assert {"groove_width", "groove_depth", "cord"} <= kinds


def test_a_gland_interface_carries_the_squeeze_band_as_its_constraint():
    """Outside the band the seal either leaks or takes a compression set and
    leaks later, and neither shows in the model."""
    data = json.load(open(GLANDS, encoding="utf-8"))
    depth = next(
        i for i in data["rows"][0]["interfaces"] if i["kind"] == "groove_depth"
    )
    assert "%" in depth["constraint"] and "squeezes" in depth["constraint"]
