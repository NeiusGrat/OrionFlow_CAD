"""The load path report: which member sizes the part, which is along for the ride.

The useful half of a topology study. What is tested is mostly what it refuses
to say — "oversized" has to mean *carrying little stress* and never *remove
it*, because a lightly stressed member can be sized by stiffness, by a process
minimum, or by what it bolts to, and a report that conflated those would be
actively dangerous advice.
"""

import pytest

from orion import design_space as DS, interview as I, search as S, \
    utilisation as U

BRACKET = {"base_length": 80.0, "base_width": 60.0, "base_thickness": 10.0,
           "upright_height": 70.0, "upright_thickness": 10.0}

DUTY = {"material": "6061-T6 aluminium", "load_n": 400.0, "safety_factor": 2}


def _state(family: str = "l_bracket", request: str = "a bracket", **slots):
    merged = {**BRACKET, **DUTY, **slots} if family == "l_bracket" else slots
    iv = I.Interview(request=request, family=family, slots=merged)
    iv.classify()
    return DS.initial_state(family, I.requirements(iv))


# --------------------------------------------------------------------------- #
# Reading the load path
# --------------------------------------------------------------------------- #


def test_utilisation_is_stress_over_what_the_design_asked_for():
    """1.0 means "at the limit you specified", not "about to break"."""
    use = U.of_state(_state())

    assert use.required_factor == 2.0
    assert use.yield_mpa == 276.0
    assert use.allowable_mpa == pytest.approx(138.0)
    for member in use.members:
        assert member.utilisation == pytest.approx(
            member.stress_mpa / 138.0)


def test_every_frame_member_is_reported():
    use = U.of_state(_state())

    assert {m.name for m in use.members} == {"base", "upright"}


def test_a_single_member_model_still_has_a_load_path():
    """A plate reports only its peak. That is one member, not none."""
    use = U.of_state(_state(family="rect_plate", length=120.0, width=80.0,
                            thickness=10.0, **DUTY))

    assert len(use.members) == 1
    assert use.members[0].name == "section"
    assert use.members[0].utilisation > 0


def test_members_are_ordered_worst_first():
    use = U.of_state(_state(base_thickness=4.0, upright_thickness=12.0))

    uses = [m.utilisation for m in use.members]
    assert uses == sorted(uses, reverse=True)
    assert use.members[0].name == "base"


def test_a_design_with_no_duty_has_no_load_path():
    """No allowable is not a small number, it is not a number."""
    assert U.of_state(_state(family="rect_plate", length=120.0, width=80.0,
                             thickness=10.0)) is None


def test_a_check_with_no_declared_factor_yields_nothing():
    assert U.of_check({"result": {"yield_mpa": 276.0}, "expect": {}}) is None
    assert U.of_check({}) is None


# --------------------------------------------------------------------------- #
# The verdicts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("utilisation,verdict", [
    (1.30, U.OVERLOADED),
    (1.00, U.BINDING),
    (0.80, U.BINDING),
    (0.50, U.WORKING),
    (0.10, U.OVERSIZED),
])
def test_the_thresholds_are_what_they_say(utilisation, verdict):
    member = U.MemberUse(name="m", stress_mpa=utilisation * 100.0,
                         allowable_mpa=100.0, utilisation=utilisation)
    assert member.verdict == verdict


def test_an_overloaded_member_is_named_as_setting_the_design():
    use = U.of_state(_state(base_thickness=4.0, upright_thickness=12.0))
    text = " ".join(U.explain(use))

    assert use.binding.name == "base"
    assert use.binding.verdict == U.OVERLOADED
    assert "nothing gets lighter until it gets stronger" in text


def test_material_in_the_wrong_place_is_distinguished_from_too_much():
    """A 9:1 spread is not a part that needs less material; it is a part that
    needs it moved. That is the topology insight, on a parametric model."""
    use = U.of_state(_state(base_thickness=4.0, upright_thickness=12.0))
    text = " ".join(U.explain(use))

    assert use.imbalance > 8
    assert "wrong place" in text
    assert "moving it from the upright to the base" in text


def test_a_balanced_design_raises_no_imbalance_note():
    use = U.of_state(_state(base_thickness=10.0, upright_thickness=10.0))
    text = " ".join(U.explain(use))

    assert use.imbalance < 2
    assert "wrong place" not in text


def test_one_member_has_no_imbalance_to_report():
    use = U.of_state(_state(family="rect_plate", length=120.0, width=80.0,
                            thickness=10.0, **DUTY))
    assert use.imbalance is None


# --------------------------------------------------------------------------- #
# What it refuses to say
# --------------------------------------------------------------------------- #


def test_oversized_is_never_an_instruction_to_remove_material():
    """The single most dangerous thing this report could imply."""
    text = " ".join(U.explain(U.of_state(_state())))

    assert "not an instruction" in text
    assert "sized by stiffness" in text or "process minimum" in text


def test_a_stiffness_driven_design_says_so_before_anything_else():
    """Deflection at 89% and stress at 18%: thinning the low-stress member
    makes the binding constraint worse. Acting on the stress number alone
    would be exactly wrong."""
    use = U.of_state(_state(max_deflection_mm=0.5))
    text = " ".join(U.explain(use))

    assert use.stiffness_driven
    assert "sized by stiffness, not strength" in text
    assert "makes the binding constraint worse" in text


def test_a_strength_driven_design_is_not_called_stiffness_driven():
    use = U.of_state(_state(base_thickness=4.0, upright_thickness=12.0,
                            max_deflection_mm=50.0))

    assert use.deflection_use is not None
    assert not use.stiffness_driven


def test_a_design_with_no_deflection_limit_claims_no_deflection_use():
    """Inventing a limit to divide by would manufacture a constraint nobody
    asked for."""
    use = U.of_state(_state())

    assert use.deflection_use is None
    assert not use.stiffness_driven


def test_the_stress_basis_travels_onto_the_report():
    """Nominal section, no concentration. Every figure inherits it."""
    text = " ".join(U.explain(U.of_state(_state())))

    assert "nominal section" in text
    assert "inherits" in text


def test_nothing_to_report_says_so_rather_than_returning_zeroes():
    assert "No load path to report" in " ".join(U.explain(None))
    assert "No load path to report" in " ".join(U.explain(U.Utilisation()))


# --------------------------------------------------------------------------- #
# Before and after
# --------------------------------------------------------------------------- #


def test_compare_reports_what_moved():
    before = U.of_state(_state(upright_thickness=10.0))
    after = U.of_state(_state(upright_thickness=5.0))

    lines = " ".join(U.compare(before, after))
    assert "upright" in lines
    assert "of allowable" in lines


def test_compare_is_silent_when_nothing_changed():
    use = U.of_state(_state())
    assert U.compare(use, use) == []


def test_compare_needs_both_sides():
    assert U.compare(None, U.of_state(_state())) == []
    assert U.compare(U.of_state(_state()), None) == []


def test_a_search_report_covers_start_end_and_what_changed():
    stated = ("An aluminium 6061-T6 bracket, base 80 x 60 mm, upright 70 mm "
              "tall, carrying 400 N with a safety factor of 2.")
    result = S.explore(_state(request=stated))
    lines = U.report(result)
    text = " ".join(lines)

    assert "Load path at the starting design" in text
    assert "After the search" in text
    assert "What the search changed" in text
    # Mass alone does not say whether a design got better; utilisation does.
    assert "% of allowable" in text


def test_a_search_that_found_nothing_says_the_load_path_stands():
    """A fully locked design has nowhere to go."""
    stated = ("An aluminium 6061-T6 bracket, base 80 x 60 x 10 mm, upright "
              "70 mm tall and 10 mm thick, carrying 400 N with a safety "
              "factor of 2.")
    result = S.explore(_state(request=stated), depth=1)
    text = " ".join(U.report(result))

    if result.best is None or not result.best.path:
        assert "load path stands" in text


def test_the_report_names_parameters_no_check_reads():
    """A parameter nothing reads has no utilisation at all, which is a
    different statement from a low one."""
    plate = _state(family="rect_plate", length=120.0, width=80.0,
                   thickness=10.0, corner_radius=8.0, **DUTY)
    result = S.explore(plate)
    text = " ".join(U.report(result))

    assert "cr" in result.unconstrained
    assert "no utilisation can be given" in text
