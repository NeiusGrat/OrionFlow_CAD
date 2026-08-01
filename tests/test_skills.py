"""Skills remove low-level CAD vocabulary from the model's job.

The studio's failures of the invented-vocabulary kind — ``unknown profile
builder 'rect_wit…'``, parameters that do not exist — happen because the model
is asked to speak a dialect it half-remembers. A skill answers in engineering
terms and resolves the dialect itself, so what is tested here is: does it refuse
rather than invent, and is what it returns actually buildable.
"""

import pytest

from orion.skills import registry
from orion.skills.base import SkillError
from orion.skills.bearing_seat import bearing, catalogue, housing_fit, it7_um


# --------------------------------------------------------------------------- #
# the catalogue must be self-consistent
# --------------------------------------------------------------------------- #
def test_bearing_series_dimensions_increase_monotonically():
    """A structural invariant that catches transcription errors in the source.

    Within a series, bore, outside diameter and width all increase with the
    size code. One published table had 6208 as 40x80x15 — breaking the width
    progression between 6207 (17) and 6209 (19) — and a table that is quietly
    wrong produces a housing that does not fit the bearing it names.
    """
    data = catalogue()["bearings"]
    for series in ("62", "63"):
        entries = sorted((k, v) for k, v in data.items() if k.startswith(series))
        for (prev_k, prev), (k, cur) in zip(entries, entries[1:]):
            for dim in ("d", "D", "B"):
                assert cur[dim] >= prev[dim], (
                    f"{k} {dim}={cur[dim]} is smaller than {prev_k} "
                    f"{dim}={prev[dim]}; the series is not monotonic, which "
                    f"means a transcription error"
                )


def test_the_bearing_bore_is_the_designation():
    """For 04 and up the size code is the bore in 5 mm steps — an independent
    check on the table."""
    data = catalogue()["bearings"]
    for key, spec in data.items():
        code = int(key[2:])
        if code >= 4:
            assert spec["d"] == code * 5, f"{key} bore should be {code * 5}"


def test_it7_matches_the_standard_series():
    # ISO 286 IT7, corroborated against the published grade table.
    assert it7_um(25) == 21
    assert it7_um(40) == 25
    assert it7_um(52) == 30
    assert it7_um(100) == 35


def test_suffixes_do_not_change_the_envelope():
    """Seals and shields live inside the boundary dimensions."""
    plain = bearing("6205")
    for variant in ("6205-2RS", "6205 2Z", "6205ZZ", "6205-2RS1"):
        assert bearing(variant)["D"] == plain["D"]
        assert bearing(variant)["B"] == plain["B"]


# --------------------------------------------------------------------------- #
# refusing beats inventing
# --------------------------------------------------------------------------- #
def test_an_unknown_bearing_is_refused_with_what_is_known():
    with pytest.raises(SkillError, match="no catalogue entry"):
        bearing("6999")


def test_an_unknown_duty_is_refused():
    """Every ISO 286 duty now resolves — the fit deviations were harvested from
    the catalogue's own tables. An unrecognised duty name still refuses rather
    than falling back to a default, because the fit is only correct for the load
    case it was chosen under."""
    with pytest.raises(SkillError, match="unknown duty"):
        housing_fit(52.0, duty="whatever_seems_reasonable")


def test_an_unbuildable_bolt_pattern_is_refused_with_the_arithmetic():
    with pytest.raises(SkillError, match="apart"):
        registry.execute(
            "create_bolt_pattern",
            {"bolt_size_mm": 8, "count": 12, "bolt_circle_dia_mm": 60},
        )


def test_an_untabulated_bolt_size_is_refused():
    with pytest.raises(SkillError, match="ISO 273"):
        registry.execute(
            "create_bolt_pattern",
            {"bolt_size_mm": 7, "count": 4, "bolt_circle_dia_mm": 60},
        )


# --------------------------------------------------------------------------- #
# what comes back must actually build
# --------------------------------------------------------------------------- #
def test_a_bearing_seat_satisfies_its_family_guards():
    """A skill that returns parameters the compiler refuses has moved the
    failure, not removed it."""
    from orion.family_schema import check_guards

    result = registry.execute("create_bearing_seat", {"bearing_designation": "6205"})
    assert result.part_class == "bearing_carrier"
    guards = check_guards("bearing_carrier", result.variables)
    assert guards and all(g["holds"] for g in guards), guards


def test_the_seat_matches_the_bearing_it_names():
    result = registry.execute("create_bearing_seat", {"bearing_designation": "6205"})
    spec = bearing("6205")
    assert result.variables["rs"] == spec["D"] / 2.0  # housing bore
    assert result.variables["ds"] == spec["B"]  # full ring width
    assert result.variables["rb"] > spec["d"] / 2.0  # shaft clears
    # the shoulder must be the manufacturer's abutment, not the ring OD
    assert result.derived["shoulder_diameter_mm"] == spec["Da_max"]
    assert result.derived["shoulder_diameter_mm"] < spec["D"]


def test_every_number_carries_a_reason_and_a_standard():
    result = registry.execute("create_bearing_seat", {"bearing_designation": "6205"})
    for name in result.variables:
        assert result.rationale.get(name), f"{name} has no stated reason"
    assert any("ISO 15" in c for c in result.citations)
    assert any("ISO 286" in c for c in result.citations)


def test_a_seat_that_cannot_fit_is_refused_not_shrunk():
    with pytest.raises(SkillError, match="does not fit"):
        registry.execute(
            "create_bearing_seat",
            {"bearing_designation": "6210", "wall_mm": 0.5, "floor_mm": 0.5},
        )


def test_out_of_corpus_values_warn_without_failing():
    """A 15 mm-wide seat is legal and has no precedent in the corpus. Saying so
    is different from refusing it."""
    result = registry.execute("create_bearing_seat", {"bearing_designation": "6205"})
    assert any("outside the range" in w for w in result.warnings)


def test_derived_values_a_bearing_actually_needs():
    result = registry.execute(
        "create_bolt_pattern", {"bolt_size_mm": 8, "count": 6, "bolt_circle_dia_mm": 80}
    )
    assert result.derived["clearance_hole_mm"] == 9.0  # ISO 273 medium
    assert result.derived["hole_pitch_mm"] == pytest.approx(40.0, abs=0.1)
    assert result.derived["min_outer_diameter_mm"] > 80.0


# --------------------------------------------------------------------------- #
# the gated catalogue, wired in
# --------------------------------------------------------------------------- #
def test_the_harvested_catalogue_is_the_authority_for_envelopes():
    """658 rows that passed the invariant gate, against 22 typed by hand."""
    from orion.skills.bearing_seat import harvested

    gated = harvested()
    assert len(gated) > 400, "the harvested catalogue is missing or truncated"
    # the catalogue's own numbers, cross-checked against SKF's mm/inch columns
    assert gated["6205"]["d"] == 25 and gated["6205"]["D"] == 52
    assert gated["6205"]["B"] == 15
    # the value a published web table got wrong
    assert gated["6208"]["B"] == 18


def test_load_ratings_reach_the_life_calculator():
    """A seat carries C so sizing life needs no second lookup."""
    from orion import calc

    result = registry.execute("create_bearing_seat", {"bearing_designation": "6205"})
    c_dyn = result.derived["dynamic_load_rating_C_N"]
    assert c_dyn == 14800.0
    life = calc.bearing_life_l10(c_dyn, 2000.0, 1500.0)
    assert life["l10_hours"] > 0


def test_a_bearing_known_only_to_the_harvest_still_resolves():
    result = registry.execute(
        "create_bearing_seat",
        {"bearing_designation": "6310", "wall_mm": 8, "floor_mm": 6},
    )
    assert result.variables["rs"] == 55.0  # 110 mm OD
    assert result.variables["ds"] == 27.0  # 27 mm wide


def test_a_missing_shoulder_is_reported_not_invented():
    """Both routes to a shoulder need either Da max or r_min. With neither,
    a plausible number would be a bearing that fails early for an invisible
    reason."""
    from orion.skills.bearing_seat import bearing, create_bearing_seat

    spec = bearing("6410")
    if spec.get("Da_max") is None and spec.get("r_min") is None:
        result = create_bearing_seat("6410", wall_mm=10, floor_mm=8)
        assert result.derived["shoulder_diameter_mm"] is None
        assert any("cannot be sized" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
# ISO 286 seat fits, harvested from the catalogue's own tables
# --------------------------------------------------------------------------- #
def test_every_bearing_duty_now_resolves():
    """Only the floating-outer-ring case existed before the fit tables were
    harvested; a class with no numbers behind it cannot be machined to."""
    from orion.skills.bearing_seat import DUTIES

    assert len(DUTIES) >= 6
    for duty in DUTIES:
        result = registry.execute(
            "create_bearing_seat", {"bearing_designation": "6205", "duty": duty}
        )
        assert result.derived["housing_bore_mm"]


def test_the_deviations_are_the_iso_286_values():
    from orion.skills.bearing_seat import deviations

    # spot values, independently known
    assert deviations("housing", "H7", 25.0) == (0.0, 21.0)
    assert deviations("housing", "K7", 25.0) == (-15.0, 6.0)
    assert deviations("housing", "P7", 25.0) == (-35.0, -14.0)
    assert deviations("shaft", "k5", 25.0) == (2.0, 11.0)
    assert deviations("shaft", "m6", 25.0) == (8.0, 21.0)


def test_clearance_and_interference_go_the_right_way():
    """H7 never cuts below nominal; the interference classes always do. If a
    parse flipped a sign this is where it shows."""
    from orion.skills.bearing_seat import housing_fit

    clearance = housing_fit(52.0, "stationary_outer")
    assert clearance["min_mm"] >= 52.0

    for duty in ("rotating_outer", "rotating_outer_heavy", "rotating_outer_thin_wall"):
        press = housing_fit(52.0, duty)
        assert press["max_mm"] <= 52.0, duty
        assert press["min_mm"] < clearance["min_mm"]


def test_an_h_class_upper_deviation_equals_its_it_grade():
    """The definitional check the gate admitted these rows under, re-asserted
    against the shipped file."""
    from orion.knowledge.skf_fits import it_value
    from orion.skills.bearing_seat import seat_fits

    checked = 0
    for cls, bands in seat_fits().get("housing", {}).items():
        if not cls.startswith("H"):
            continue
        for over, incl, low, high in bands:
            assert low == 0, f"{cls} lower deviation must be zero"
            expected = it_value(int(cls[1:]), over, incl)
            if expected is not None:
                assert abs(high - expected) < 0.5, (cls, over, incl)
                checked += 1
    assert checked > 20, "too few H-class bands to be a meaningful check"
