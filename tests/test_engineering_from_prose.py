"""Prose to verdict: the duty a request states, gated and converted.

The analytic tier could grade a load since the producer landed, but only if
something put one in the slots. This covers the link that does it, driven
through ``interview.read_request`` — the function the studio actually calls —
rather than through the post-step in isolation, so the whole live path runs:
identify, extract, designations, standards, duty, classify, resolve, generate,
freeze, check, grade.

The properties under test are all about what does *not* happen:

* the model's arithmetic is never used, only its judgement about which number
  is the load
* a load with no unit is not a load
* a value the request does not support is dropped and noted, never rounded in
* a material naming two alloys resolves to neither
"""

import json

import pytest

from orion import blueprint_gen as G, calc, engineering, interview
from orion.blueprint import Blueprint
from orion_physical_ai import verify

MEASURED = {"body_volume": 1.0e5, "watertight": True, "valid": True,
            "solids": 1}

#: Geometry every request below shares, so the duty is the only variable.
GEOMETRY = ("Base 80 x 60 x 8 mm, upright 70 mm tall, 8 mm thick.")


class _Model:
    """A stubbed extractor. Two calls: name the family, then fill its slots.

    The slot payload is what a *plausible* model returns, including the load
    written the way the request wrote it — unconverted. Nothing downstream is
    allowed to depend on the model having done the arithmetic.
    """

    model = "stub"

    def __init__(self, family: str, slots: dict):
        self._replies = [json.dumps({"family": family}), json.dumps(slots)]

    def chat(self, messages, max_tokens=None, **kw):
        body = self._replies.pop(0) if self._replies else "{}"
        return type("R", (), {"content": body, "thinking": "", "tool_calls": [],
                              "finish_reason": "stop", "usage": {}})()


BASE_SLOTS = {"base_length": 80, "base_width": 60, "base_thickness": 8,
              "upright_height": 70, "upright_thickness": 8}


PLATE_SLOTS = {"length": 120.0, "width": 80.0, "thickness": 10.0}


def _run(request: str, slots: dict, family: str = "l_bracket"):
    """The live path, end to end, and everything it produced along the way."""
    base = PLATE_SLOTS if family == "rect_plate" else BASE_SLOTS
    iv = interview.read_request(_Model(family, {**base, **slots}), request)
    bp = Blueprint.from_dict(
        G.generate(iv.family, interview.requirements(iv))).freeze()
    # `to_dict()` is what `blueprint_service` hands the checker.
    rows = engineering.run_checks(bp.to_dict(), bp.variables, MEASURED)
    verdict = verify.verdict_for(verify.engineering_checks(rows))
    return iv, bp, rows, verdict


# --------------------------------------------------------------------------- #
# The request this whole link exists for
# --------------------------------------------------------------------------- #

VALID = ("Design a 6061-T6 aluminium bracket that carries 50 kg, with a safety "
         "factor of at least 2 and maximum deflection of 0.5 mm. " + GEOMETRY)


def test_valid_prose_reaches_a_verdict():
    """The request this whole link exists for, all the way to a verdict.

    The duty is graded on the frame, so both members have to carry it — a
    bracket that passed when only its upright was read does not necessarily
    pass now, which is the point. The geometry here is one that does.
    """
    iv, bp, rows, verdict = _run(
        VALID,
        {"material": "6061-T6 aluminium", "load_n": 50,
         "safety_factor": 2, "max_deflection_mm": 0.5,
         "base_thickness": 16.0, "upright_thickness": 16.0},
    )

    block = bp.design_plan["engineering"]
    assert block["material"] == "aluminium_6061_t6"
    assert block["checks"][0]["expect"] == {
        "safety_factor": {"min": 2.0},
        "deflection_mm": {"max": 0.5},
    }
    assert rows[0]["passed"] is True, rows[0]["detail"]
    assert verdict == verify.VERIFIED


def test_kilograms_become_newtons_in_python_not_in_the_model():
    """The model reported 50, the way the request wrote it. 50 N would be a
    twentieth of the real load and every number after it would be wrong."""
    iv, bp, _, _ = _run(VALID, {"material": "6061-T6 aluminium", "load_n": 50,
                                "safety_factor": 2})

    assert iv.slots["load_n"] == pytest.approx(50 * 9.80665)
    assert bp.design_plan["engineering"]["checks"][0]["args"]["load_n"] == \
        pytest.approx(490.3325)


def test_a_model_that_already_converted_lands_on_the_same_number():
    """Either reading of "50 kg" is the same statement, and Python's conversion
    is what is used in both cases."""
    _, converted, _, _ = _run(VALID, {"material": "6061-T6 aluminium",
                                      "load_n": 490.3325, "safety_factor": 2})
    _, raw, _, _ = _run(VALID, {"material": "6061-T6 aluminium",
                                "load_n": 50, "safety_factor": 2})

    a = converted.design_plan["engineering"]["checks"][0]["args"]["load_n"]
    b = raw.design_plan["engineering"]["checks"][0]["args"]["load_n"]
    assert a == b == pytest.approx(490.3325)


# --------------------------------------------------------------------------- #
# Failing the duty
# --------------------------------------------------------------------------- #


def test_an_excessive_load_is_refused():
    request = ("An aluminium 6061-T6 bracket carrying 900 kg with a safety "
               "factor of 2. " + GEOMETRY)
    _, _, rows, verdict = _run(request, {"material": "6061-T6 aluminium",
                                         "load_n": 900, "safety_factor": 2})

    assert rows[0]["result"]["safety_factor"] < 2.0
    assert rows[0]["passed"] is False
    assert verdict == verify.REFUSED


def test_a_deflection_violation_is_refused():
    request = ("An aluminium 6061-T6 bracket carrying 300 N, maximum "
               "deflection 0.01 mm. " + GEOMETRY)
    _, _, rows, verdict = _run(request, {"material": "6061-T6 aluminium",
                                         "load_n": 300,
                                         "max_deflection_mm": 0.01})

    assert rows[0]["result"]["deflection_mm"] > 0.01
    assert rows[0]["passed"] is False
    assert verdict == verify.REFUSED


# --------------------------------------------------------------------------- #
# Nothing is invented
# --------------------------------------------------------------------------- #


def test_a_missing_material_declares_no_check():
    request = "A bracket that carries 50 kg. " + GEOMETRY
    _, bp, rows, _ = _run(request, {"load_n": 50})

    assert "engineering" not in bp.design_plan
    assert rows == []


def test_an_ambiguous_material_resolves_to_neither():
    """"Steel" is 1018 and 4140, whose yield strengths differ by 285 MPa.
    Picking one would decide the answer by alphabetical accident."""
    request = "A steel bracket that carries 50 kg. " + GEOMETRY
    _, bp, rows, _ = _run(request, {"material": "steel", "load_n": 50})

    assert calc.resolve_material("steel") is None
    assert "engineering" not in bp.design_plan
    assert rows == []


def test_a_load_with_no_unit_is_not_a_load():
    """The hole `orion.duty` documents, closed for forces: a bare number in a
    dimensioned sentence must not be readable as newtons."""
    request = "A 6061-T6 aluminium bracket. " + GEOMETRY
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                  "load_n": 80})

    assert "load_n" not in iv.slots
    assert "engineering" not in bp.design_plan
    assert any("no force with a unit" in n for n in iv.notes)


def test_an_invented_load_is_rejected_and_the_stated_one_recovered():
    """Rejecting the model's figure must not also lose the user's.

    The request states one force. Dropping the load entirely because the
    extraction proposed a different number would punish the user for the
    model's error.
    """
    request = "A 6061-T6 aluminium bracket that carries 50 kg. " + GEOMETRY
    iv, bp, rows, _ = _run(request, {"material": "6061-T6 aluminium",
                                     "load_n": 7500})

    assert any("7500" in n and "not used" in n for n in iv.notes)
    assert iv.slots["load_n"] == pytest.approx(490.3325)
    assert rows[0]["result"]["load_n"] == pytest.approx(490.3325)


def test_a_dimensionless_factor_is_not_supported_by_a_dimension():
    """`provenance.corroborated` credits half and double a stated number,
    because a diameter becomes a radius. A safety factor is nobody's radius,
    and the allowance let an 8 mm thickness wave through a proposed factor
    of 4."""
    request = "A 6061-T6 aluminium bracket that carries 50 kg. " + GEOMETRY
    iv, _, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                 "load_n": 50, "safety_factor": 4})

    assert "8" in GEOMETRY               # the dimension that used to support it
    assert "safety_factor" not in iv.slots


def test_two_forces_and_no_designated_load_declares_nothing():
    """A choice this code is not entitled to make."""
    request = ("A 6061-T6 aluminium bracket rated to 200 N and 50 kg. "
               + GEOMETRY)
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium"})

    assert "load_n" not in iv.slots
    assert "engineering" not in bp.design_plan
    assert any("more than one force" in n for n in iv.notes)


def test_one_force_the_extraction_missed_is_still_read():
    """Unambiguous, so reading it is recovery rather than a guess."""
    request = "A 6061-T6 aluminium bracket that carries 50 kg. " + GEOMETRY
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium"})

    assert iv.slots["load_n"] == pytest.approx(490.3325)
    assert "engineering" in bp.design_plan


def test_an_unstated_safety_factor_is_not_taken_from_the_model():
    request = "A 6061-T6 aluminium bracket that carries 50 kg. " + GEOMETRY
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                  "load_n": 50, "safety_factor": 4})
    block = bp.design_plan["engineering"]

    assert "safety_factor" not in iv.slots
    # Falls back to the declared default, recorded as one.
    assert block["checks"][0]["expect"]["safety_factor"]["min"] == 1.5
    assert block["provenance"]["safety_factor"]["source"] == "default"


PLATE_PROSE = "120 x 80 x 10 mm."


def test_an_unstated_support_is_not_taken_from_the_model():
    """4x in stress. Too much to accept on a model's say-so.

    Asserted on the plate, because only a single-member model has a support
    case at all. A bracket is solved as a frame and its supports are part of
    its geometry — the base is bolted at its far end — so there is no
    cantilever-or-simply-supported question to get wrong.
    """
    request = ("A 6061-T6 aluminium plate that carries 50 kg, "
               + PLATE_PROSE)
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                  "load_n": 50,
                                  "support": "supported both ends"},
                        family="rect_plate")

    assert "support" not in iv.slots
    assert bp.design_plan["engineering"]["checks"][0]["args"]["case"] == \
        "cantilever_end"


def test_a_support_the_request_states_is_used():
    request = ("A 6061-T6 aluminium plate simply supported at both ends "
               "carrying 50 kg, " + PLATE_PROSE)
    iv, bp, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                  "load_n": 50}, family="rect_plate")

    assert iv.slots["support"] == "supported both ends"
    assert bp.design_plan["engineering"]["checks"][0]["args"]["case"] == \
        "simply_supported_centre"


def test_a_bracket_is_a_frame_and_is_not_asked_for_a_support_case():
    request = "A 6061-T6 aluminium bracket that carries 50 kg. " + GEOMETRY
    _, bp, _, _ = _run(request, {"material": "6061-T6 aluminium",
                                 "load_n": 50})

    args = bp.design_plan["engineering"]["checks"][0]["args"]
    assert "case" not in args
    assert args["base_thickness_mm"] == "=BT"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def test_provenance_survives_the_blueprint_round_trip():
    """Every input to the check, with where it came from, after freeze and
    `to_dict` — the exact sequence `blueprint_service` performs."""
    _, bp, _, _ = _run(VALID, {"material": "6061-T6 aluminium", "load_n": 50,
                               "safety_factor": 2, "max_deflection_mm": 0.5})

    prov = bp.to_dict()["design_plan"]["engineering"]["provenance"]

    # The conversion is on the record, both readings of it.
    assert prov["load_n"]["source"] == "derived"
    assert "50 kg" in prov["load_n"]["basis"]
    assert "9.80665" in prov["load_n"]["basis"]
    assert "490.3" in prov["load_n"]["basis"]
    # Stated values say so; assumed ones say that instead.
    assert prov["safety_factor"]["source"] in ("stated", "derived")
    assert prov["material"]["source"] in ("stated", "derived")
    # A frame has no support case to assume, so none is recorded. The plate
    # still records one — see test_an_unstated_support_is_not_taken_from_the_model.
    assert "support" not in prov


def test_the_duty_is_inside_the_frozen_hash():
    a = _run(VALID, {"material": "6061-T6 aluminium", "load_n": 50,
                     "safety_factor": 2})[1]
    heavier = _run(
        "A 6061-T6 aluminium bracket carrying 90 kg with a safety factor of 2. "
        + GEOMETRY,
        {"material": "6061-T6 aluminium", "load_n": 90, "safety_factor": 2})[1]

    assert a.blueprint_hash != heavier.blueprint_hash


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("phrase,newtons", [
    ("carries 50 kg", 490.3325),
    ("carries 500 N", 500.0),
    ("rated to 2.5 kN", 2500.0),
    ("takes a 200 lb load", 889.64432),
    ("holds 1.5 tonnes", 14709.975),
])
def test_every_supported_unit_converts_deterministically(phrase, newtons):
    from orion import duty

    readings = duty.force_readings(phrase)
    assert len(readings) == 1
    assert readings[0]["newtons"] == pytest.approx(newtons)


@pytest.mark.parametrize("text", [
    "a plate 120 x 80 x 10 mm",
    "a safety factor of 2",
    "0.5 mm maximum deflection",
    "a NEMA 17 mount",
])
def test_a_dimension_is_never_read_as_a_force(text):
    from orion import duty

    assert duty.force_readings(text) == []
