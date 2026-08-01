"""Decomposing a request into functions, and making the answers agree.

The tests that matter are about the two claims the planner makes: that the
function list is *derived* rather than guessed, and that resolutions which
cannot both be built are reported rather than reconciled by taking one.
"""

from __future__ import annotations

from orion import planner as P
from orion.knowledge import functions as F

JOINT = (
    "Design a robotic shoulder joint: support a rotating shaft carrying "
    "1.2 kN at 600 rpm for 20000 hours and transmit 80 Nm of torque"
)
SIZED = (
    "Support a rotating 30 mm shaft carrying 1.2 kN at 600 rpm and "
    "transmit 80 Nm of torque"
)


# --------------------------------------------------------------------------- #
# step 2 — decomposition
# --------------------------------------------------------------------------- #
def test_the_request_supplies_only_the_entry_point():
    d = P.decompose(JOINT)
    stated = [n.function for n in d.needs if n.origin == P.STATED]
    assert set(stated) == {F.SUPPORTS_ROTATION, F.TRANSMITS_TORQUE}


def test_the_rest_of_the_function_list_is_entailed_by_interfaces():
    """An interface something must provide is a function something must
    perform. Locating and retaining the shaft are not guesses about what a
    shoulder joint needs — they are debts the bearing incurred."""
    d = P.decompose(JOINT)
    entailed = {n.function: n for n in d.needs if n.origin == P.ENTAILED}
    assert F.LOCATES_PART in entailed
    assert F.RETAINS_AXIALLY in entailed
    assert entailed[F.RETAINS_AXIALLY].via == "shoulder"
    assert "rolling bearing requires" in entailed[F.RETAINS_AXIALLY].because


def test_every_entailed_function_names_the_interface_that_demanded_it():
    d = P.decompose(JOINT)
    for need in d.needs:
        if need.origin == P.ENTAILED:
            assert need.via, f"{need.function} appeared without an interface"
            assert P.INTERFACE_ENTAILS[need.via] == need.function


def test_decomposition_does_not_quote_a_specific_bearings_dimensions():
    """The graph's edge detail was computed against whichever row it sampled as
    representative, so it carries that bearing's bore — a specific number
    masquerading as a general fact, in the one place nothing has been chosen."""
    for need in P.decompose(JOINT).needs:
        assert "mm" not in need.because


def test_decomposition_terminates():
    """An entailed function entails its own interfaces, and a seal that needs a
    groove that needs a seal is a loop rather than a requirement."""
    d = P.decompose(JOINT, depth=8)
    assert len(d.needs) == len(set(d.functions()))


def test_a_request_naming_no_function_decomposes_to_nothing():
    assert P.decompose("make me something nice").needs == []


# --------------------------------------------------------------------------- #
# step 5 — resolution and reconciliation
# --------------------------------------------------------------------------- #
def test_the_bearing_fixes_the_shaft_the_key_is_cut_to():
    """A key sized before the bearing is a key sized to nothing."""
    plan = P.plan(SIZED)
    by_function = {r.function: r for r in plan.resolutions}
    assert by_function[F.SUPPORTS_ROTATION].resolved
    assert by_function[F.SUPPORTS_ROTATION].provides["shaft_dia_mm"] == 30.0
    key = by_function[F.TRANSMITS_TORQUE]
    assert key.resolved
    # DIN 6885 gives 8x7 for a 30 mm shaft, and the section is set by the
    # diameter rather than chosen.
    assert key.provides["key_width_mm"] == 8.0
    assert key.provides["key_height_mm"] == 7.0
    assert not plan.conflicts


def test_a_shaft_too_small_for_its_torque_is_a_conflict_not_a_footnote():
    """Resolving each function alone cannot find this: the bearing is sized by
    the radial load and never hears about the torque."""
    plan = P.plan(JOINT)
    assert plan.conflicts
    conflict = plan.conflicts[0]
    assert conflict.dimension == "shaft_dia_mm"
    assert conflict.values[F.SUPPORTS_ROTATION] == 15.0
    assert conflict.values[F.TRANSMITS_TORQUE] > 15.0
    assert not plan.complete


def test_a_disputed_dimension_is_not_reported_as_agreed():
    """Leaving the fixed value in the context would let a later stage read it
    as settled."""
    plan = P.plan(JOINT)
    assert "shaft_dia_mm" not in plan.context
    assert "housing_bore_mm" in plan.context  # that one is not disputed


def test_a_lower_bound_comfortably_met_is_agreement_not_conflict():
    """Treating 'at least' as an equality would report a conflict every time a
    shaft was generously sized."""
    plan = P.plan(
        "Support a rotating 60 mm shaft carrying 1.2 kN at 600 rpm "
        "and transmit 80 Nm of torque"
    )
    assert not plan.conflicts
    assert plan.context["shaft_dia_mm"] == 60.0


def test_a_function_with_no_resolver_is_reported_not_skipped():
    """The design still needs it, and pretending otherwise produces a subsystem
    that looks finished."""
    plan = P.plan(SIZED)
    unresolved = {r.function for r in plan.unresolved()}
    assert F.RETAINS_AXIALLY in unresolved
    assert not plan.complete
    for r in plan.unresolved():
        assert r.asks, f"{r.function} was dropped without a question"


def test_the_key_says_which_failure_mode_governs():
    """Nothing about the geometry shows which mode is critical, and sizing
    against the wrong one is how keyed joints fail in service."""
    plan = P.plan(SIZED)
    key = next(r for r in plan.resolutions if r.function == F.TRANSMITS_TORQUE)
    assert "governing" in key.summary
    assert any("shear" in c and "bearing" in c for c in key.citations)


def test_a_key_longer_than_it_can_usefully_be_says_so():
    """Past about 1.5 diameters the torque is not shared evenly along the key,
    so the linear capacity figure is optimistic."""
    plan = P.plan(JOINT)
    key = next(r for r in plan.resolutions if r.function == F.TRANSMITS_TORQUE)
    assert any("not shared evenly" in q for q in key.asks)


def test_torque_and_shaft_are_read_from_the_request():
    from orion import reasoning as R

    duty = R.read_intent(JOINT).detail["duty"]
    assert duty["torque_Nm"] == 80.0
    assert duty["radial_load_N"] == 1200.0
    assert duty["speed_rpm"] == 600.0


def test_the_plan_is_deterministic():
    first, second = P.plan(SIZED), P.plan(SIZED)
    assert first.to_dict() == second.to_dict()
