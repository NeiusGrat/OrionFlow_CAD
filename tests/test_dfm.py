"""Can the part be made by the process it says it is made by.

A fourth dimension of evidence, and the one that can hold while the other three
do: a milled pocket with sharp internal corners matches its frozen prediction
exactly, accounts for every number, contains every requested feature, and no
shop can cut it. An end mill is round.
"""

import pytest

from orion import blueprint_gen, dfm, interview

PLATE = dict(length=120, width=80, thickness=10,
             pocket_l=50, pocket_w=30, pocket_depth=6,
             hole_count=4, hole_d=8, hole_edge_gap=15)


def _plan(**extra):
    req = interview.resolve("rect_plate", {**PLATE, **extra})
    return blueprint_gen.generate("rect_plate", req)["design_plan"]


def _ids(rows):
    return {r["id"].split(":", 1)[1] for r in rows}


def test_a_design_that_says_nothing_gets_no_rows():
    """The property that keeps the row worth reading.

    Guessing "probably milled" would put a warning on every part in the corpus,
    and a warning that is always on is one nobody reads.
    """
    assert dfm.check(_plan()) == []
    assert dfm.check({}) == []
    assert dfm.check(None) == []


def test_a_sharp_milled_pocket_is_reported_not_refused():
    """A rotating tool cannot cut a zero-radius internal corner, so the model
    and the part disagree by construction — and the fix is a one-word answer,
    so the plate is handed back with the question rather than withheld."""
    rows = dfm.check(_plan(process="machined"))
    row = next(r for r in rows if r["id"].endswith("pocket_corner_radius"))
    assert row["status"] == dfm.WARN
    assert "1.5 mm" in row["detail"]
    assert not any(r["status"] == "fail" for r in rows)


def test_nothing_in_this_module_fails_a_part():
    """REFUSED means the geometry disagreed with its own prediction. How
    expensive a part is to cut must not borrow that word."""
    assert not hasattr(dfm, "FAIL")
    for extra in ({"process": "machined"},
                  {"process": "cast"},
                  {"process": "machined", "pocket_corner_radius": 0.4},
                  {"process": "sheet"}):
        rows = dfm.check(_plan(**extra))
        assert all(r["status"] in (dfm.PASS, dfm.WARN) for r in rows), extra


def test_a_corner_too_small_for_a_stock_cutter_is_flagged():
    rows = dfm.check(_plan(process="machined", pocket_corner_radius=0.8))
    assert "pocket_corner_tooling" in _ids(rows)


def test_a_pocket_too_deep_for_its_corner_is_flagged():
    """6 mm deep on a 0.8 mm corner is 7.5 tool diameters of reach."""
    rows = dfm.check(_plan(process="machined", pocket_corner_radius=0.8))
    row = next(r for r in rows if r["id"].endswith("pocket_depth_ratio"))
    assert row["evidence"]["ratio"] == 7.5


def test_a_workable_pocket_raises_nothing():
    rows = dfm.check(_plan(process="machined", pocket_corner_radius=3))
    assert _ids(rows) == {"makeable"}
    assert rows[0]["status"] == dfm.PASS


def test_a_cast_part_with_no_draft_cannot_leave_the_mould():
    rows = dfm.check(_plan(process="cast", pocket_corner_radius=3))
    assert "draft" in _ids(rows)


def test_casting_rules_do_not_run_on_a_milled_part():
    """And the milling rules do not run on a casting: a sharp internal corner
    is a defect for one process and free for the other."""
    milled = _ids(dfm.check(_plan(process="machined", pocket_corner_radius=3)))
    cast = _ids(dfm.check(_plan(process="cast")))
    assert "draft" not in milled
    assert "pocket_corner_radius" not in cast


def test_an_unknown_process_is_recorded_and_not_guessed_at():
    """Applying the milling rules to a process we have no rules for would be
    inventing evidence."""
    rows = dfm.check(_plan(process="forged"))
    assert _ids(rows) == {"process_known"}
    assert "forged" in rows[0]["detail"]


def test_a_load_bearing_part_with_no_duty_says_so():
    """The verdict would otherwise read exactly like a part whose strength was
    proved. It was not; nobody stated a load."""
    rows = dfm.check(_plan(process="machined", pocket_corner_radius=3,
                           function="load bearing"))
    row = next(r for r in rows if r["id"].endswith("duty_stated"))
    assert row["status"] == dfm.WARN


def test_a_declared_duty_silences_it():
    """``orion.engineering`` ran the calculators; there is nothing to warn
    about."""
    plan = _plan(process="machined", pocket_corner_radius=3,
                 function="load bearing")
    plan["engineering"] = [{"id": "arm_stress"}]
    assert not any(r["id"].endswith("duty_stated") for r in dfm.check(plan))


def test_the_inputs_are_frozen_before_the_build():
    """The rules run after; the facts they run on are committed first, so a
    manufacturability verdict cannot be fitted to the result."""
    payload = blueprint_gen.generate(
        "rect_plate", interview.resolve("rect_plate",
                                        {**PLATE, "process": "machined"}))
    from orion.blueprint import Blueprint

    frozen = Blueprint.from_dict(payload).freeze()
    assert frozen.design_plan["manufacturing"]["process"] == "machined"
    # Inside the hash: change the declaration and it is a different design.
    other = dict(payload)
    other["design_plan"] = dict(payload["design_plan"])
    other["design_plan"]["manufacturing"] = {
        **payload["design_plan"]["manufacturing"], "process": "cast"}
    assert Blueprint.from_dict(other).freeze().blueprint_hash \
        != frozen.blueprint_hash


def test_a_part_reports_only_the_features_it_has():
    """A part with no pocket reports no pocket, not a pocket of depth zero.

    The difference is between a rule that does not apply and a rule that
    passes, and only one of them is evidence.
    """
    req = interview.resolve("rect_plate", dict(length=100, width=60,
                                               thickness=5, process="machined"))
    features = blueprint_gen.generate(
        "rect_plate", req)["design_plan"]["manufacturing"]["features"]
    assert "pocket" not in features and "holes" not in features


def test_every_rule_states_its_basis():
    """A rule of thumb that cannot say where it comes from is someone's habit."""
    for extra in ({"process": "machined"},
                  {"process": "cast"},
                  {"process": "machined", "pocket_corner_radius": 0.8},
                  {"process": "machined", "pocket_corner_radius": 3,
                   "function": "load bearing"}):
        for row in dfm.check(_plan(**extra)):
            assert row["evidence"].get("basis"), row["id"]


# --------------------------------------------------------------------------- #
# Reading the process out of the request
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, process", [
    ("a CNC machined aluminium bracket", "machined"),
    ("milled from 6061 plate", "machined"),
    ("a turned shaft collar", "machined"),
    ("a die cast housing", "cast"),
    ("an investment cast lever", "cast"),
    ("a 3D printed jig", "printed"),
    ("a sheet metal cover", "sheet"),
    ("a laser cut plate", "sheet"),
])
def test_the_process_is_read_from_the_request_not_sampled(text, process):
    """A designation in the same sense "NEMA 17" is: the word is in the request
    or it is not.

    This was left to the extraction first, and it did not work — "CNC machined
    aluminium mounting plate ... load bearing bracket" came back with ten slots
    filled and neither of these, because the extraction prompt is overwhelmingly
    about numbers and a choice from a list does not read as a stated value.
    """
    assert interview.designations(text, {})["process"] == process


@pytest.mark.parametrize("text, function", [
    ("a load bearing bracket", "load_bearing"),
    ("a structural gusset", "load_bearing"),
    ("a mounting plate", "mounting"),
    ("a clearance spacer", "clearance"),
    ("an enclosure lid", "enclosure"),
])
def test_the_function_is_read_from_the_request(text, function):
    assert interview.designations(text, {})["function"] == function


def test_a_request_that_says_neither_gets_neither():
    """Silence is not an invitation to guess: an assumed process would put a
    manufacturability warning on every part that never mentioned one."""
    out = interview.designations("a plate 100 x 50 x 5 mm", {})
    assert "process" not in out and "function" not in out


def test_a_stated_value_is_never_overwritten():
    """Anything the model did fill is left alone, as with every other
    designation."""
    out = interview.designations("a cast housing", {"process": "machined"})
    assert out["process"] == "machined"
