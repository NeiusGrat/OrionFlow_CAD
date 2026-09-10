"""The search environment: what an l_bracket is allowed to become.

No policy is tested here because none exists. What is tested is the contract a
policy will act through — that the space it is offered is actually legal, that a move
outside it is refused rather than silently clipped, and that a parameter
somebody typed is not quietly overwritten.

The load-bearing test is :func:`test_every_allowed_value_actually_builds`. It
sweeps every value the space permits through the real builder, because the
builder is the authority on what exists and a space that disagrees with it
would send a search chasing parts that cannot be made.
"""

import numpy as np
import pytest

from orion import blueprint_gen as G, design_space as DS, interview as I

FAMILY = "l_bracket"

BASE = {"base_length": 80.0, "base_width": 60.0, "base_thickness": 8.0,
        "upright_height": 70.0, "upright_thickness": 8.0}

DUTY = {"material": "6061-T6 aluminium", "load_n": 900.0,
        "process": "machined", "safety_factor": 2}


def _requirements(slots: dict, request: str = "") -> dict:
    """Requirements with a provenance ledger, as `interview.requirements` makes.

    The request text decides what counts as stated, so a test that wants a
    parameter locked says it in prose rather than asserting on the ledger.
    """
    iv = I.Interview(request=request or "a bracket", family=FAMILY,
                     slots=dict(slots))
    iv.classify()
    return I.requirements(iv)


def _state(slots: dict, request: str = "") -> DS.State:
    return DS.initial_state(FAMILY, _requirements(slots, request))


# --------------------------------------------------------------------------- #
# Bounds and relations
# --------------------------------------------------------------------------- #


def test_a_valid_parameter_set_is_accepted():
    st = _state({**BASE, **DUTY})

    assert DS.feasible(FAMILY, st.params)
    assert DS.violations(FAMILY, st.params) == []


@pytest.mark.parametrize("param,value,relation", [
    ("UT", 200.0, "upright_fits_base"),      # thicker than the base is long
    ("BT", 90.0, "upright_clears_base"),     # base thicker than upright is tall
    ("UW", 200.0, "upright_within_base"),    # upright wider than the base
])
def test_a_broken_relation_is_reported_with_its_name(param, value, relation):
    st = _state({**BASE, **DUTY})
    broken = {**st.params, param: value}

    ids = [v.id for v in DS.violations(FAMILY, broken)]
    assert relation in ids
    assert not DS.feasible(FAMILY, broken)


def test_a_relation_the_builder_enforces_is_marked_hard():
    """"Cannot exist" and "outside our range" must not read alike."""
    st = _state({**BASE, **DUTY})
    bad = DS.violations(FAMILY, {**st.params, "UT": 200.0})

    assert bad and all(v.hard for v in bad)
    assert all(r.enforced for r in DS.relations(FAMILY))


def test_a_relation_that_cannot_be_evaluated_counts_as_broken():
    """A predicate nobody could test is not a predicate that passed."""
    assert not DS.feasible(FAMILY, {"BL": 80.0})       # everything else absent


def test_an_unknown_family_has_no_declared_space():
    """Silence reads as "nothing known to be safe", not "anything goes"."""
    assert DS.space("rect_plate", {"L": 100.0}) == {}
    assert DS.relations("rect_plate") == []
    assert DS.bounds("rect_plate", {"L": 100.0}) == []


# --------------------------------------------------------------------------- #
# The space itself
# --------------------------------------------------------------------------- #


def test_the_binding_end_names_the_bound_that_produced_it():
    # A short base makes the builder's guard tighter than the family range.
    st = _state({**BASE, "base_length": 25.0, "upright_thickness": 6.0})
    ut = DS.space(FAMILY, st.params, st.requirements)["UT"]

    assert ut.high == 25.0
    assert ut.strict_high, "UT < BL is strict; 25 is not available"
    assert "builder" in ut.high_from and "UT < BL" in ut.high_from


def test_a_process_minimum_raises_the_floor_and_says_so():
    machined = _state({**BASE, **DUTY})
    cast = _state({**BASE, **DUTY, "process": "cast"})

    m = DS.space(FAMILY, machined.params, machined.requirements)["BT"]
    c = DS.space(FAMILY, cast.params, cast.requirements)["BT"]

    assert c.low > m.low, "cast walls are thicker than milled ones"
    assert "process" in c.low_from


def test_a_strict_boundary_excludes_its_own_endpoint():
    st = _state({**BASE, "base_length": 25.0, "upright_thickness": 6.0})
    ut = DS.space(FAMILY, st.params, st.requirements)["UT"]

    assert not ut.holds(25.0)          # UT < BL
    assert ut.holds(24.0)
    assert str(ut).endswith(")")


def test_every_allowed_value_actually_builds():
    """The invariant the whole module rests on.

    Anything `space` permits, `blueprint_gen` must accept. A disagreement here
    sends a search after parts that cannot exist, and every such candidate
    costs a builder call to find out.
    """
    for slots in (
        {**BASE, "base_length": 25.0, "upright_height": 30.0,
         "upright_thickness": 6.0, "inside_fillet": 4.0, "process": "cast"},
        {**BASE, **DUTY},
        {**BASE, "base_length": 120.0, "base_width": 90.0,
         "base_thickness": 10.0, "upright_height": 100.0,
         "upright_thickness": 12.0, "upright_width": 70.0,
         "inside_fillet": 20.0},
    ):
        req = _requirements(slots)
        st = DS.initial_state(FAMILY, req)
        for name, interval in DS.space(FAMILY, st.params, req).items():
            if interval.locked:
                continue
            slot = DS._REQUIREMENT_OF[name]
            for value in np.arange(0.5, 200.0, 0.5):
                value = round(float(value), 4)
                if not interval.holds(value):
                    continue
                G.generate(FAMILY, {**req, slot: value})   # must not raise


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #


def test_a_legal_move_is_applied_and_re_evaluated():
    st = _state({**BASE, **DUTY, "upright_thickness": 4.0})
    before = DS.evaluate(st)

    obs = DS.step(st, DS.Action("UT", 10.0))

    assert obs.applied
    assert obs.state.params["UT"] == 10.0
    # Thicker upright, stiffer bracket, and the calculator was actually re-run.
    assert obs.metrics["safety_factor"] > before.metrics["safety_factor"]
    assert obs.metrics["mass_g"] > before.metrics["mass_g"]


def test_an_out_of_bounds_move_is_refused_not_clipped():
    """Refused and infeasible are different facts. A policy that cannot tell
    them apart learns to avoid legal moves near illegal ones."""
    st = _state({**BASE, **DUTY})

    obs = DS.step(st, DS.Action("UT", 5000.0))

    assert obs.applied is False
    assert obs.state.params == st.params, "a refused move changes nothing"
    assert "outside" in obs.notes[0]
    assert not obs.feasible


def test_a_parameter_outside_the_searchable_set_is_refused():
    st = _state({**BASE, **DUTY})

    obs = DS.step(st, DS.Action("hole_r", 3.0))

    assert obs.applied is False
    assert "not a searchable parameter" in obs.notes[0]


def test_the_interfaces_are_not_searchable_and_say_why():
    assert "hole_r" not in DS.SEARCHABLE[FAMILY]
    assert "bolt_square" not in DS.SEARCHABLE[FAMILY]
    for name in ("hole_r", "bolt_square", "bore_r"):
        assert name in DS.UNSAFE_TO_SEARCH
        assert DS.UNSAFE_TO_SEARCH[name]


def test_every_enumerated_action_is_one_the_environment_accepts():
    """`actions` must not offer a move that `step` then refuses."""
    st = _state({**BASE, **DUTY})

    proposed = DS.actions(st)
    assert proposed
    for action in proposed:
        assert DS.step(st, action).applied, f"{action.parameter}->{action.to}"


def test_a_builder_refusal_leaves_the_state_untouched():
    """The builder is the authority; a move it rejects is not applied."""
    st = _state({**BASE, **DUTY})
    obs = DS.step(st, DS.Action("UW", -5.0))

    assert obs.applied is False
    assert obs.state.params == st.params


# --------------------------------------------------------------------------- #
# What the user stated
# --------------------------------------------------------------------------- #


STATED_REQUEST = ("An aluminium 6061-T6 bracket, base 80 x 60 x 8 mm, upright "
                  "70 mm tall and 8 mm thick, carrying 900 N with a safety "
                  "factor of 2.")


def test_a_dimension_the_user_stated_is_locked():
    st = _state({**BASE, **DUTY}, request=STATED_REQUEST)
    intervals = DS.space(FAMILY, st.params, st.requirements)

    assert intervals["BL"].locked
    assert "base_length" in intervals["BL"].lock_reason
    assert DS.step(st, DS.Action("BL", 120.0)).applied is False


def test_a_lock_can_be_lifted_only_deliberately():
    """A fully dimensioned request locks everything, so "make it lighter" would
    have nothing to act on. The grant is explicit and it is recorded."""
    st = _state({**BASE, **DUTY}, request=STATED_REQUEST)
    assert DS.step(st, DS.Action("BT", 6.0)).applied is False

    st.unlocked = frozenset({"BT"})
    obs = DS.step(st, DS.Action("BT", 6.0))

    assert obs.applied
    assert obs.state.unlocked == frozenset({"BT"}), "the grant survives a step"
    # Everything else stays locked.
    assert DS.step(st, DS.Action("BL", 120.0)).applied is False


def test_a_parameter_the_user_left_open_is_searchable():
    st = _state({**BASE, **DUTY}, request=STATED_REQUEST)
    intervals = DS.space(FAMILY, st.params, st.requirements)

    # No fillet was mentioned, so it is ours to choose.
    assert not intervals["in_r"].locked


# --------------------------------------------------------------------------- #
# Flowing into the existing calculator
# --------------------------------------------------------------------------- #


def test_candidate_parameters_reach_the_engineering_calculator():
    """The point of the whole environment: a candidate is graded by the same
    analytic tier a built part is."""
    st = _state({**BASE, **DUTY, "upright_thickness": 4.0})
    obs = DS.evaluate(st)

    assert obs.checks and obs.checks[0]["calc"] == "beam_bending"
    assert obs.metrics["max_stress_mpa"] > 0
    assert obs.metrics["deflection_mm"] > 0
    # The section graded is the one the candidate has.
    assert obs.checks[0]["result"]["height_mm"] == st.params["UT"] == 4.0


def test_a_candidate_that_fails_its_duty_is_not_feasible():
    thin = _state({**BASE, **DUTY, "upright_thickness": 4.0})
    obs = DS.evaluate(thin)

    assert obs.checks[0]["passed"] is False
    assert obs.feasible is False, "the relations hold but the duty does not"


def test_a_search_can_move_a_failing_candidate_to_a_passing_one():
    """End to end, without a policy: the environment supports the move that
    fixes the part."""
    st = _state({**BASE, **DUTY, "upright_thickness": 4.0})
    assert DS.evaluate(st).feasible is False

    obs = DS.step(st, DS.Action("UT", 9.0))

    assert obs.applied and obs.feasible
    assert obs.checks[0]["passed"] is True


def test_a_state_with_no_declared_duty_has_no_checks():
    """No load stated, so nothing to grade — and no invented pass."""
    st = _state(BASE)
    obs = DS.evaluate(st)

    assert obs.checks == []
    assert "mass_g" not in obs.metrics, "no material, so no honest mass"
    assert obs.metrics["volume_mm3"] > 0


def test_mass_comes_from_the_closed_form_the_blueprint_grades_itself_on():
    st = _state({**BASE, **DUTY})
    obs = DS.evaluate(st)

    from orion import calc, expr as E
    payload = G.generate(FAMILY, st.requirements)
    target = next(a["target"] for a in payload["assertions"]
                  if a["kind"] == "body_volume")
    expected = float(E.evaluate(target, st.params))

    assert obs.metrics["volume_mm3"] == pytest.approx(expected)
    assert obs.metrics["mass_g"] == pytest.approx(
        calc.mass_properties(expected, "aluminium_6061_t6")["mass_g"])


# --------------------------------------------------------------------------- #
# The existing pipeline is undisturbed
# --------------------------------------------------------------------------- #


def test_blueprint_generation_is_unaffected():
    """Nothing in this module is on the build path."""
    plain = G.generate(FAMILY, _requirements(BASE))
    assert plain["variables"]["BL"] == 80.0
    assert "engineering" not in plain["design_plan"]

    with_duty = G.generate(FAMILY, _requirements({**BASE, **DUTY}))
    assert with_duty["design_plan"]["engineering"]["material"] == \
        "aluminium_6061_t6"


def test_evaluating_a_state_never_mutates_it():
    st = _state({**BASE, **DUTY})
    before = dict(st.params)

    DS.evaluate(st)
    DS.step(st, DS.Action("UT", 12.0))
    DS.actions(st)

    assert st.params == before
