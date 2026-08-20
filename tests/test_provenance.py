"""Where every number came from, and what the verdict does about it.

The failure this guards is quiet and specific. A part built from dimensions a
model supplied passes its volume assertion exactly as convincingly as one built
from dimensions the user gave — because the assertion is derived from those same
dimensions. VERIFIED was therefore literally true ("the geometry matches the
numbers") and read as something else entirely ("the numbers are right").

Three properties matter, and each has a test below:

* a stated number and an invented one classify differently
* the classification is *inside* ``blueprint_hash``, so it cannot be written
  after the measurement it is meant to qualify
* the verdict changes — a part with unaccounted dimensions is no longer VERIFIED
"""

import json

import pytest

from orion import blueprint_gen, interview
from orion import provenance as P
from orion.blueprint import Blueprint
from orion_physical_ai import verify


def _interview(request: str, slots: dict, family: str = "rect_plate"):
    iv = interview.Interview(request=request, family=family)
    iv.slots, iv.notes = interview.apply_standards(dict(slots), family)
    iv.classify()
    return iv


def _blueprint(request: str, slots: dict, family: str = "rect_plate") -> Blueprint:
    iv = _interview(request, slots, family)
    return Blueprint.from_dict(
        blueprint_gen.generate(family, interview.requirements(iv))
    ).freeze()


# --------------------------------------------------------------------------- #
# reading the request
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,request_text",
    [
        (120.0, "a plate 120 long"),  # plain
        (120.0, "a plate 12 cm long"),  # unit conversion
        (50.8, 'a 2" boss'),  # imperial
        (4.0, "four holes"),  # number word
        (10.0, "a 20 mm bore"),  # stated as a diameter, stored as a radius
        (2.5, "a 2.5 mm wall"),  # decimal
    ],
)
def test_a_number_the_request_states_is_corroborated(value, request_text):
    assert P.corroborated(value, P.literals(request_text))


@pytest.mark.parametrize(
    "value,request_text",
    [
        (37.5, "a plate 120 x 80 x 10"),
        (120.0, "a mounting plate for a stepper"),
        (11.0, "an aluminium bracket"),
    ],
)
def test_a_number_nowhere_in_the_request_is_not(value, request_text):
    assert not P.corroborated(value, P.literals(request_text))


def test_a_standard_substitution_is_credited_to_the_standard():
    """9 mm for M10 is a lookup, not a recollection, and says which table."""
    iv = _interview(
        "a plate 120 x 80 x 10 with M10 clearance holes",
        {"length": 120.0, "width": 80.0, "thickness": 10.0, "thread": "M10"},
    )
    entry = iv.provenance["hole_d"]
    assert entry["source"] == P.STANDARD
    assert "ISO 273" in entry["basis"]


def test_an_answer_the_user_typed_counts_as_stated():
    """The classification follows the conversation, not only the first message."""
    iv = interview.Interview(request="a plate", family="rect_plate")
    iv.slots = {"length": 120.0, "width": 80.0}
    iv.classify()
    assert iv.provenance["length"]["source"] == P.UNSOURCED

    interview.answer(iv, "thickness", 10.0)
    assert iv.provenance["thickness"]["source"] == P.STATED


# --------------------------------------------------------------------------- #
# carrying it onto the variables
# --------------------------------------------------------------------------- #
def test_a_renamed_variable_keeps_the_source_of_the_value_it_carries():
    """``length`` becomes ``L``, and matching on name alone laundered it.

    This is the bug the value match exists for: with only a name check, a plate
    whose length, width and thickness a model had invented reported three
    *derived* dimensions and sailed through the gate written to catch it.
    """
    bp = _blueprint(
        "a mounting plate for a NEMA 23 stepper",
        {"length": 120.0, "width": 80.0, "thickness": 10.0},
    )
    ledger = bp.design_plan["provenance"]
    assert set(ledger) == {"L", "W", "T"}
    assert all(e["source"] == P.UNSOURCED for e in ledger.values())


def test_a_stated_plate_is_fully_accounted_for():
    bp = _blueprint(
        "a plate 120 x 80 x 10",
        {"length": 120.0, "width": 80.0, "thickness": 10.0},
    )
    assert P.unsourced(bp.design_plan["provenance"]) == []
    assert P.summary(bp.design_plan["provenance"]) == {P.STATED: 3}


def test_an_ambiguous_value_inherits_the_weaker_source():
    """Two requirements share a value and disagree — the weaker one wins.

    Otherwise the ambiguity itself is a laundering route: put an invented
    number next to a stated one of the same size and it acquires its standing.
    """
    base = {
        "given": {"source": P.STATED, "basis": "given in the request"},
        "invented": {"source": P.UNSOURCED, "basis": "nothing accounts for it"},
    }
    out = P.extend(
        base,
        {"X": 40.0},
        "computed",
        source_values={"given": 40.0, "invented": 40.0},
    )
    assert out["X"]["source"] == P.UNSOURCED


# --------------------------------------------------------------------------- #
# the freeze
# --------------------------------------------------------------------------- #
def test_the_ledger_is_inside_the_hash():
    """Rewritable provenance would prove nothing — the same reason the
    assertions are frozen before the kernel runs."""
    bp = _blueprint(
        "a mounting plate for a stepper",
        {"length": 120.0, "width": 80.0, "thickness": 10.0},
    )
    assert bp.verify_hash()

    tampered = json.loads(json.dumps(bp.to_dict()))
    for entry in tampered["design_plan"]["provenance"].values():
        entry["source"] = P.STATED
    assert not Blueprint.from_dict(tampered).verify_hash()


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
PASSING_ROW = {
    "kind": "body_volume",
    "id": "v",
    "passed": True,
    "target": 1.0,
    "measured": 1.0,
    "rel_err": 0.0,
    "tier": 1,
}


def _report(bp: Blueprint) -> dict:
    return verify.from_assertion_rows(
        [PASSING_ROW],
        measured={"valid": True, "solids": 1},
        design_plan=bp.design_plan,
    )


def test_a_fully_sourced_part_still_verifies():
    report = _report(
        _blueprint("a plate 120 x 80 x 10",
                   {"length": 120.0, "width": 80.0, "thickness": 10.0})
    )
    assert report["verdict"] == verify.VERIFIED


def test_a_part_whose_dimensions_nobody_gave_is_not_verified():
    report = _report(
        _blueprint("a mounting plate for a stepper",
                   {"length": 120.0, "width": 80.0, "thickness": 10.0})
    )
    assert report["verdict"] == verify.UNSOURCED
    # Not a refusal: every geometry check passed and the part is real.
    assert report["failed"] == []
    row = next(c for c in report["checks"] if c["id"].startswith("provenance"))
    assert row["status"] == verify.WARN
    assert set(row["evidence"]["unsourced"]) == {"L", "W", "T"}


def test_the_ledger_travels_with_the_report():
    """A verdict of UNSOURCED with no detail is an accusation, not evidence."""
    report = _report(
        _blueprint("a mounting plate for a stepper",
                   {"length": 120.0, "width": 80.0, "thickness": 10.0})
    )
    assert set(report["provenance"]) == {"L", "W", "T"}


def test_a_geometry_failure_still_outranks_an_unsourced_dimension():
    failing = {**PASSING_ROW, "passed": False, "measured": 2.0, "rel_err": 1.0}
    bp = _blueprint("a mounting plate for a stepper",
                    {"length": 120.0, "width": 80.0, "thickness": 10.0})
    report = verify.from_assertion_rows([failing], design_plan=bp.design_plan)
    assert report["verdict"] == verify.REFUSED


def test_a_build_with_no_ledger_gets_no_row():
    """Parts built before this existed carry no opinion, and inventing one
    either way would be the assumed pass the rest of the module refuses."""
    assert verify.provenance_checks({}) == []
    assert verify.provenance_checks(None) == []


def test_a_clean_ledger_alone_does_not_make_a_part_verified():
    """Provenance says where the numbers came from, never that the geometry
    matches them. UNPROVEN has to keep meaning exactly that."""
    bp = _blueprint("a plate 120 x 80 x 10",
                    {"length": 120.0, "width": 80.0, "thickness": 10.0})
    report = verify.from_assertion_rows([], design_plan=bp.design_plan)
    assert report["verdict"] == verify.UNPROVEN


# --------------------------------------------------------------------------- #
# fixing it by hand
# --------------------------------------------------------------------------- #
def test_setting_a_dimension_by_hand_clears_its_warning():
    """Correcting an invented number has to actually clear the flag, or the
    label becomes something users learn to ignore."""
    from app.services import blueprint_edit

    bp = _blueprint("a mounting plate for a stepper",
                    {"length": 120.0, "width": 80.0, "thickness": 10.0})
    edited = blueprint_edit.retune(bp.to_dict(), {"L": 150.0, "W": 100.0, "T": 12.0})
    ledger = edited["design_plan"]["provenance"]

    assert P.unsourced(ledger) == []
    assert all(e["source"] == P.STATED for e in ledger.values())
    # And the edit is no longer the thing that was hashed.
    assert edited["blueprint_hash"] == ""
