"""What the dimensions are allowed to be, and whether the process holds it.

A drawing without tolerances is every dimension as a wish. Until this layer
existed every number the system produced was exact and unqualified, which means
the shop applies its own general tolerance and nobody has agreed what the part
is.
"""

import pytest

from orion import blueprint_gen, interview, tolerance as T

PLATE = dict(length=120, width=80, thickness=10)


def _plan(**extra):
    req = interview.resolve("rect_plate", {**PLATE, **extra})
    return blueprint_gen.generate("rect_plate", req)


def _rows(**extra):
    bp = _plan(**extra)
    return T.check(bp["design_plan"], bp["variables"], bp["datums"])


def _ids(rows):
    return {r["id"].split(":", 1)[1] for r in rows}


# --------------------------------------------------------------------------- #
# ISO 2768-1, which is a table and not a rule of thumb
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("nominal, cls, expected", [
    (2.0, "f", 0.05), (2.0, "m", 0.1), (2.0, "c", 0.2),
    (10.0, "f", 0.1), (10.0, "m", 0.2), (10.0, "c", 0.5), (10.0, "v", 1.0),
    (120.0, "m", 0.5),          # the band is upper-exclusive: 120 is not 30-120
    (119.9, "m", 0.3),
    (400.0, "m", 0.8),
    (3000.0, "m", 2.0),
])
def test_the_iso_2768_table_is_the_iso_2768_table(nominal, cls, expected):
    assert T.deviation(nominal, cls) == expected


def test_the_standard_has_real_gaps_and_they_are_not_zero():
    """Under 0.5 mm it does not apply, and the coarsest class starts at 3 mm."""
    assert T.deviation(0.4, "m") is None
    assert T.deviation(2.0, "v") is None
    assert T.deviation(3000.0, "f") is None


def test_a_design_that_states_no_tolerance_gets_no_rows():
    """Silence is not an invitation to guess -- the same rule as every other
    evidence layer here."""
    assert _rows(process="machined") == []
    assert T.check({}, {}, {}) == []
    assert T.check(None, None, None) == []


# --------------------------------------------------------------------------- #
# The schedule
# --------------------------------------------------------------------------- #
def test_the_schedule_resolves_every_dimension():
    rows = _rows(process="machined", tolerance_class="m")
    row = next(r for r in rows if r["id"].endswith("schedule"))
    assert row["status"] == T.PASS
    sched = row["evidence"]["schedule"]
    assert sched["L"] == 0.5      # 120 mm falls in the 120-400 band
    assert sched["W"] == 0.3      # 80 mm in 30-120
    assert sched["T"] == 0.2      # 10 mm in 6-30


def test_a_class_the_standard_does_not_define_is_refused_not_applied():
    rows = _rows(process="machined", tolerance_class="q")
    assert _ids(rows) == {"class_known"}
    assert "f (fine)" in rows[0]["detail"]


# --------------------------------------------------------------------------- #
# Achievability
# --------------------------------------------------------------------------- #
def test_a_fine_class_on_a_casting_is_flagged():
    """A 0.05 mm band on a sand casting is not a tight tolerance, it is a
    fiction, and the part is rejected against a number nobody meant."""
    rows = _rows(process="cast", tolerance_class="f")
    row = next(r for r in rows if r["id"].endswith("class_process"))
    # The tightest band this part reaches: its 10 mm thickness sits in 6-30,
    # which is +/-0.1 under class f. 0.05 would need a dimension under 6 mm.
    assert row["evidence"]["required"] == 0.1
    assert row["evidence"]["process_floor"] == 0.5


def test_a_medium_class_on_a_milled_part_is_fine():
    assert "class_process" not in _ids(_rows(process="machined",
                                             tolerance_class="m"))


def test_a_called_out_tolerance_below_the_process_floor_is_flagged():
    rows = _rows(process="cast", critical_tolerance=0.02)
    row = next(r for r in rows if r["id"].endswith("critical_process"))
    assert "rejected" in row["detail"]


def test_the_same_tolerance_reads_differently_on_a_milled_part():
    """Achievable with extra operations is not the same claim as impossible."""
    rows = _rows(process="machined", critical_tolerance=0.02)
    row = next(r for r in rows if r["id"].endswith("critical_process"))
    assert "not free" in row["detail"]


def test_an_unknown_process_makes_no_achievability_claim():
    """There is no floor to compare against, so there is nothing to say."""
    rows = _rows(process="forged", critical_tolerance=0.001)
    assert "critical_process" not in _ids(rows)


# --------------------------------------------------------------------------- #
# The datum frame
# --------------------------------------------------------------------------- #
def test_a_called_out_tolerance_wants_a_complete_datum_frame():
    """A face removes three degrees of freedom, an edge two, a stop one. These
    parts declare two datums, so a position is locked in five directions and
    floating in the sixth."""
    row = next(r for r in _rows(process="machined", critical_tolerance=0.05)
               if r["id"].endswith("datum_frame"))
    assert row["evidence"]["datums"] == {"A": "bottom face z=0 (primary)",
                                         "B": "long edge (secondary)"}


def test_a_datum_that_is_not_the_one_the_part_is_dimensioned_from():
    """A part built off one face and inspected off another is measured through
    every tolerance in between."""
    row = next(r for r in _rows(process="machined", critical_tolerance=0.05,
                                datum="top face")
               if r["id"].endswith("datum_agrees"))
    assert row["evidence"]["stated"] == "top face"
    assert row["evidence"]["declared_primary"] == "bottom face z=0 (primary)"


def test_naming_the_datum_the_part_actually_uses_says_nothing():
    assert "datum_agrees" not in _ids(_rows(process="machined",
                                            critical_tolerance=0.05,
                                            datum="bottom face"))


def test_the_comparison_is_on_what_distinguishes_the_faces():
    """Matching on any shared word meant a top face agreed with a bottom face,
    because both contain the word 'face' -- so the one comparison this rule
    exists to make was the one it could not make."""
    assert T._distinguishing("top face") == {"top"}
    assert T._distinguishing("bottom face z=0 (primary)") == {"bottom", "z"}
    assert not (T._distinguishing("top face")
                & T._distinguishing("bottom face z=0 (primary)"))


# --------------------------------------------------------------------------- #
# Reading it out of the request
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, cls", [
    ("machined to ISO 2768-m", "m"),
    ("ISO 2768 f general tolerances", "f"),
    ("iso2768-c", "c"),
    ("with a medium tolerance throughout", "m"),
])
def test_the_tolerance_class_is_read_from_the_request(text, cls):
    assert interview.designations(text, {})["tolerance_class"] == cls


@pytest.mark.parametrize("text, value", [
    ("the bore is +/-0.05", 0.05),
    ("held to +/-0.02 mm", 0.02),
    ("0.1 mm tolerance on the slot", 0.1),
])
def test_a_called_out_band_is_read_from_the_request(text, value):
    assert interview.designations(text, {})["critical_tolerance"] == value


def test_a_request_with_no_tolerance_gets_none():
    out = interview.designations("a plate 100 x 50 x 5 mm", {})
    assert "tolerance_class" not in out and "critical_tolerance" not in out


# --------------------------------------------------------------------------- #
# Frozen, like every other claim
# --------------------------------------------------------------------------- #
def test_the_declaration_is_inside_the_hash():
    """A tolerance that could be changed after the part was measured would
    prove nothing, for the same reason the assertions are frozen."""
    from orion.blueprint import Blueprint

    payload = _plan(process="machined", tolerance_class="m")
    frozen = Blueprint.from_dict(payload).freeze()
    assert frozen.design_plan["tolerance"]["class"] == "m"

    other = dict(payload)
    other["design_plan"] = dict(payload["design_plan"])
    other["design_plan"]["tolerance"] = {"class": "c"}
    assert Blueprint.from_dict(other).freeze().blueprint_hash \
        != frozen.blueprint_hash


def test_nothing_here_fails_a_part():
    """REFUSED belongs to the geometry disagreeing with its own prediction. A
    tolerance nobody can hold is a conversation, not a defect in the model."""
    for extra in ({"process": "cast", "tolerance_class": "f"},
                  {"process": "cast", "critical_tolerance": 0.001},
                  {"process": "machined", "tolerance_class": "q"},
                  {"process": "machined", "critical_tolerance": 0.05,
                   "datum": "top face"}):
        assert all(r["status"] in (T.PASS, T.WARN) for r in _rows(**extra))


def test_every_rule_states_its_basis():
    for extra in ({"process": "cast", "tolerance_class": "f"},
                  {"process": "machined", "critical_tolerance": 0.02,
                   "datum": "top face"},
                  {"process": "machined", "tolerance_class": "q"}):
        for row in _rows(**extra):
            assert row["evidence"].get("basis"), row["id"]
