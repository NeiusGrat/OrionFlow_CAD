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


def test_a_family_with_no_declared_space_offers_none():
    """Silence reads as "nothing known to be safe", not "anything goes".

    `spur_gear` is the real case: module, tooth count and pressure angle are
    mesh compatibility, so none of them is a dimension to search.
    """
    assert "spur_gear" not in DS.SEARCHABLE
    assert DS.space("spur_gear", {"module": 2.0}) == {}
    assert DS.relations("spur_gear") == []
    assert DS.bounds("spur_gear", {"module": 2.0}) == []


# --------------------------------------------------------------------------- #
# The space itself
# --------------------------------------------------------------------------- #


def test_the_binding_end_names_the_bound_that_produced_it():
    # A short base makes the builder's guard tighter than the family range.
    st = _state({**BASE, "base_length": 25.0, "upright_thickness": 6.0})
    ut = DS.space(FAMILY, st.params, st.requirements)["UT"]

    # The probe stops just short of the boundary the builder refuses at, and
    # reports the builder's own sentence rather than a restatement of it.
    assert 24.99 < ut.high < 25.0
    assert not ut.holds(25.0), "UT < BL; 25 is not available"
    assert "builder" in ut.high_from
    assert "upright thickness exceeds the base length" in ut.high_from


def test_a_process_minimum_raises_the_floor_and_says_so():
    machined = _state({**BASE, **DUTY})
    cast = _state({**BASE, **DUTY, "process": "cast"})

    m = DS.space(FAMILY, machined.params, machined.requirements)["BT"]
    c = DS.space(FAMILY, cast.params, cast.requirements)["BT"]

    assert c.low > m.low, "cast walls are thicker than milled ones"
    assert "process" in c.low_from


def test_the_excluded_endpoint_is_excluded():
    st = _state({**BASE, "base_length": 25.0, "upright_thickness": 6.0})
    ut = DS.space(FAMILY, st.params, st.requirements)["UT"]

    assert not ut.holds(25.0)          # UT < BL
    assert ut.holds(24.0)
    # And the printed form must not round back to the value it excludes.
    assert str(ut) != "[1, 25]"


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
            slot = DS._REQUIREMENT_OF[FAMILY][name]
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


# --------------------------------------------------------------------------- #
# The other five families
#
# `l_bracket` is covered above in depth. These prove the same contract holds for
# every family that has a declared space, and — the load-bearing part — that the
# space each one reports is a space the builder agrees with.
# --------------------------------------------------------------------------- #

#: One buildable configuration per family, in interview slot names (diameters,
#: not radii — `interview.resolve` halves them on the way in).
CONFIGS = {
    "l_bracket": {"base_length": 80.0, "base_width": 60.0,
                  "base_thickness": 8.0, "upright_height": 70.0,
                  "upright_thickness": 8.0, "inside_fillet": 5.0},
    "rect_plate": {"length": 120.0, "width": 80.0, "thickness": 10.0,
                   "corner_radius": 8.0},
    "disc": {"outer_d": 80.0, "thickness": 10.0, "bore_d": 24.0},
    "shelled_box": {"length": 80.0, "width": 60.0, "height": 40.0,
                    "wall": 3.0, "floor": 3.0, "corner_radius": 6.0},
    "bearing_housing": {"length": 70.0, "width": 60.0, "height": 30.0,
                        "bore_d": 32.0, "seat_depth": 12.0},
    "manifold": {"length": 100.0, "width": 50.0, "height": 50.0,
                 "passage_d": 20.0},
}

FAMILIES = sorted(CONFIGS)


def _reqs(family: str, slots: dict, request: str = "") -> dict:
    iv = I.Interview(request=request or "a part", family=family,
                     slots=dict(slots))
    iv.classify()
    return I.requirements(iv)


@pytest.mark.parametrize("family", FAMILIES)
def test_every_declared_family_reports_a_space(family):
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)
    intervals = DS.space(family, st.params, req)

    assert set(intervals) == set(DS.SEARCHABLE[family])
    for name, interval in intervals.items():
        assert not interval.empty, f"{family}.{name} has no room at all"
        assert interval.holds(st.params[name]), \
            f"{family}.{name} excludes the value it currently has"


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_starts_feasible(family):
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)

    assert DS.feasible(family, st.params), DS.violations(family, st.params)


@pytest.mark.parametrize("family", FAMILIES)
def test_every_allowed_value_builds_for_every_family(family):
    """The invariant, family by family.

    Anything `space` permits, `blueprint_gen` must accept. This is what makes
    the probe worth its cost: the bounds are the builder's own, so a guard
    nobody transcribed still shapes the space.
    """
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)
    checked = 0
    for name, interval in DS.space(family, st.params, req).items():
        if interval.locked:
            continue
        slot = DS._REQUIREMENT_OF[family][name]
        for value in np.arange(0.25, 260.0, 0.5):
            value = round(float(value), 4)
            if not interval.holds(value):
                continue
            G.generate(family, {**req, slot: value})    # must not raise
            checked += 1
    assert checked > 0, "the sweep tested nothing"


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_refuses_a_move_outside_its_space(family):
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)
    name = DS.SEARCHABLE[family][0]

    obs = DS.step(st, DS.Action(name, 9999.0))

    assert obs.applied is False
    assert obs.state.params == st.params


@pytest.mark.parametrize("family", FAMILIES)
def test_every_enumerated_action_is_accepted_for_every_family(family):
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)

    for action in DS.actions(st, steps=3):
        assert DS.step(st, action).applied, \
            f"{family}: {action.parameter} -> {action.to}"


@pytest.mark.parametrize("family", FAMILIES)
def test_every_family_reports_a_volume(family):
    """The objective a search would rank on, closed form and kernel-free."""
    req = _reqs(family, CONFIGS[family])
    obs = DS.evaluate(DS.initial_state(family, req))

    assert obs.metrics["volume_mm3"] > 0


@pytest.mark.parametrize("family", FAMILIES)
def test_a_bound_names_the_builder_that_produced_it(family):
    """A probed edge carries the builder's own sentence, not a restatement.

    At least one parameter in each family is bounded by something the builder
    said; if none were, the probe would not be earning its cost.
    """
    req = _reqs(family, CONFIGS[family])
    st = DS.initial_state(family, req)
    froms = [
        f for interval in DS.space(family, st.params, req).values()
        for f in (interval.low_from, interval.high_from) if f
    ]
    assert any(f.startswith("builder:") for f in froms), \
        f"{family}: nothing is bounded by the builder"


def test_a_gear_is_not_searchable_and_says_why():
    """Mesh compatibility is not a dimension to optimise."""
    assert "spur_gear" not in DS.SEARCHABLE
    assert "module" in DS.UNSAFE_TO_SEARCH
    assert DS.space("spur_gear", {"module": 2.0, "teeth": 24}) == {}


@pytest.mark.parametrize("family", FAMILIES)
def test_a_probe_from_an_unbuildable_state_claims_nothing(family):
    """Probing outward from a state that does not build measures nothing, so
    only the declared bounds may be reported."""
    req = _reqs(family, CONFIGS[family])
    broken = {**req, DS._REQUIREMENT_OF[family][DS.SEARCHABLE[family][0]]: -5.0}

    found = DS.bounds(family, {}, broken)

    assert all(b.source != DS.BUILDER for b in found)
