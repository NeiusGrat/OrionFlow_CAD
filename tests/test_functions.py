"""Searching by what a design needs, not by what a part is called.

The catalogue answers "what is a 6205". It cannot answer "what supports a
rotating shaft carrying 3 kN", which is the question an engineer actually
starts from. These tests cover the difference — and in particular that
capability and suitability stay apart, because every bearing supports rotation
and only some survive the duty.
"""

import pytest

from orion.knowledge import functions as F
from orion.knowledge import registry as R
from orion.skills import registry as skills


@pytest.fixture(autouse=True)
def loaded():
    R.reset_cache()
    F.load_all()


# --------------------------------------------------------------------------- #
def test_a_function_search_is_ranked_by_least_waste():
    """An engineer asking for 20 000 hours does not want the bearing that
    lasts 170 000 — it is heavier, needs a bigger housing and costs more to do
    the same job. Life is a gate; size is the ranking."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=3000,
                  speed_rpm=1500, life_hours=20000, bore_mm=25)
    found = F.search(duty, limit=5)
    assert found, "nothing offered for a routine duty"
    diameters = [c.evidence["outside_dia_mm"] for c in found]
    assert diameters == sorted(diameters), "not ranked smallest first"
    for c in found:
        assert c.evidence["l10_hours"] >= 20000


def test_capability_and_suitability_are_different_claims():
    """Every rolling bearing supports rotation; only some carry the load. A
    search that conflates them answers every query with the whole catalogue."""
    everything = F.Duty(function=F.SUPPORTS_ROTATION, bore_mm=25)
    demanding = F.Duty(function=F.SUPPORTS_ROTATION, bore_mm=25,
                       radial_load_N=30000, speed_rpm=3000, life_hours=50000)
    assert len(F.search(everything, limit=50)) > \
        len(F.search(demanding, limit=50))


def test_an_impossible_duty_returns_nothing_rather_than_a_best_effort():
    absurd = F.Duty(function=F.SUPPORTS_ROTATION, bore_mm=25,
                    radial_load_N=500000, speed_rpm=6000, life_hours=100000)
    assert F.search(absurd) == []


def test_choosing_a_component_creates_interface_debt():
    """A bearing does not float in space. Choosing one obliges a seat, a bore
    and a shoulder, and a planner that tracks these has a task list."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=2000,
                  speed_rpm=1000, bore_mm=25)
    kinds = {r["interface"] for r in F.search(duty)[0].requires}
    assert {"shaft_seat", "housing_seat", "shoulder"} <= kinds


def test_a_bearing_with_no_rating_is_excluded_not_assumed_adequate():
    """A missing number is not a passing one."""
    from orion.knowledge.functions_catalogue import bearing_supports_rotation

    unrated = {"d": 25.0, "D": 52.0, "B": 15.0}          # no C_N
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=3000,
                  speed_rpm=1500, life_hours=20000)
    assert bearing_supports_rotation(unrated, duty) is None


def test_glands_offer_nothing_while_their_arrangement_is_unresolved():
    """Offering a face-seal gland for a piston is a seal that fails invisibly.
    An empty result is a far better outcome than a plausible wrong one."""
    from orion.knowledge.functions_catalogue import why_no_glands

    assert F.search(F.Duty(function=F.SEALS_FLUID, cord_dia_mm=2.62)) == []
    assert "AMBIGUOUS" in why_no_glands()


# --------------------------------------------------------------------------- #
def test_a_skill_declares_what_it_rests_on():
    """A skill that cannot say which standards govern it is a black box, and
    black boxes do not compose."""
    graph = skills.get("create_bearing_seat").graph
    assert F.SUPPORTS_ROTATION in graph.functions
    assert graph.calculators and graph.standards and graph.outputs
    assert "ISO 286" in " ".join(graph.standards)
    assert graph.explain()


def test_the_planner_reaches_a_skill_by_function_not_by_name():
    assert [s.name for s in skills.for_function(F.SUPPORTS_ROTATION)] == \
        ["create_bearing_seat"]
    assert [s.name for s in skills.for_function(F.PROVIDES_CLAMP_FORCE)] == \
        ["create_bolt_pattern"]
    # a function nothing serves yet returns nothing, rather than a near miss
    assert skills.for_function(F.SEALS_FLUID) == []


def test_intent_reaches_a_buildable_part():
    """The whole chain: a duty, a component that meets it, the skill that
    serves that function, and parameters the compiler accepts."""
    from orion.family_schema import check_guards

    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=3000,
                  speed_rpm=1500, life_hours=20000, bore_mm=25,
                  max_outside_dia_mm=60)
    chosen = F.search(duty)[0]
    skill = skills.for_function(F.SUPPORTS_ROTATION)[0]
    result = skill.run(bearing_designation=chosen.designation, wall_mm=7)
    guards = check_guards(result.part_class, result.variables)
    assert guards and all(g["holds"] for g in guards)
