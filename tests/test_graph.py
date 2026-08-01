"""The engineering graph, and what it is allowed to claim.

The tests that matter here are about *derivation*. A graph that can be edited
independently of the code is a graph that will disagree with it, so the checks
below are mostly of the form "this node exists because that registry says so",
and "removing the thing removes the node".
"""

from __future__ import annotations

import pytest

from orion import graph as G
from orion.knowledge import failure_modes as FM
from orion.knowledge import functions as F


# --------------------------------------------------------------------------- #
# derivation
# --------------------------------------------------------------------------- #
def test_every_function_in_the_vocabulary_is_a_node():
    g = G.graph()
    ids = {n.id for n in g.of_kind(G.FUNCTION)}
    assert set(F.FUNCTIONS) <= ids


def test_every_calculator_is_a_node():
    """Including the ones nothing cites. An unreferenced calculator is a real
    finding, not an omission — it means no function can reach it."""
    from orion import calc

    ids = {n.id for n in G.graph().of_kind(G.CALCULATION)}
    assert set(calc.CALCULATORS) <= ids


def test_a_component_edge_exists_because_the_family_declares_it():
    """Not because someone wrote it down here."""
    g = G.graph()
    key = f"{G.COMPONENT}:rolling_bearing"
    declared = {i.function for i in F.implements_for(
        "rolling_bearing", {"d": 25.0, "D": 52.0, "B": 15.0})}
    linked = {g.nodes[e.dst].id for e in g.out(key, G.IMPLEMENTS)}
    assert linked == declared


def test_the_graph_answers_which_families_serve_a_function():
    families = {n.id for n in G.components_for(F.SUPPORTS_ROTATION)}
    assert "rolling_bearing" in families
    assert F.SEALS_FLUID not in families


def test_choosing_a_component_incurs_interfaces():
    """'Pick a bearing' becomes 'pick a bearing and then you owe it a
    shoulder'. A planner that does not track these produces a part floating in
    space."""
    owed = {n.id for n, _ in G.obligations("rolling_bearing")}
    assert {"shaft_seat", "housing_seat", "shoulder"} <= owed


def test_every_edge_carries_its_justification_or_is_structural():
    """An edge with no justification is an assertion nobody can check."""
    g = G.graph()
    unjustified = [e for e in g.edges
                   if not e.why and e.kind in (G.IMPLEMENTS, G.CAN_FAIL_BY,
                                               G.SOURCED_FROM)]
    assert not unjustified, unjustified[:3]


def test_the_walk_terminates_on_a_cyclic_graph():
    """A component requires an interface validated by a standard that sources
    components. Unbounded, that is a hang rather than an answer."""
    hops = list(G.graph().walk(f"{G.COMPONENT}:rolling_bearing", depth=4))
    assert hops and len(hops) < 10000


# --------------------------------------------------------------------------- #
# a declaration nobody checks is a comment
# --------------------------------------------------------------------------- #
def test_every_skill_declares_calculators_that_exist():
    """All three declared the MCP tool spelling (calc_bearing_life_l10) rather
    than the registry's, so every one was unresolvable and nothing said so."""
    from orion import calc
    from orion.skills.base import registry

    for name in registry.names():
        for calculator in registry.get(name).graph.calculators:
            assert calculator in calc.CALCULATORS, \
                f"skill {name} declares unknown calculator {calculator}"


def test_registering_a_skill_with_a_bogus_calculator_is_refused():
    from orion.skills.base import Skill, SkillGraph, SkillError, SkillRegistry

    bare = SkillRegistry()
    with pytest.raises(SkillError, match="do not exist"):
        bare.register(Skill(name="x", description="", parameters={},
                            run=lambda: None,
                            graph=SkillGraph(calculators=["no_such_calc"])))


def test_registering_a_skill_for_an_unknown_function_is_refused():
    from orion.skills.base import Skill, SkillGraph, SkillError, SkillRegistry

    bare = SkillRegistry()
    with pytest.raises(SkillError, match="not in the vocabulary"):
        bare.register(Skill(name="x", description="", parameters={},
                            run=lambda: None,
                            graph=SkillGraph(functions=["MakesItNice"])))


# --------------------------------------------------------------------------- #
# explanation is a record, not a story
# --------------------------------------------------------------------------- #
def test_why_this_bearing_traces_back_to_the_requirement():
    from orion.reasoning import reason

    chain = reason("Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm")
    why = G.explain_selection(chain)
    spine = [hop["node"] for hop in why["spine"]]
    assert spine[0] == "Requirement"
    assert spine[1] == f"Function {F.SUPPORTS_ROTATION}"
    assert spine[2] == "Component rolling_bearing"
    assert spine[-1] == chain.step("selection").detail["_candidate"].designation
    # Every hop after the first says why it was taken.
    assert all(hop["why"] for hop in why["spine"])


def test_the_explanation_names_the_standard_and_the_dataset():
    from orion.reasoning import reason

    why = G.explain_selection(
        reason("Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm"))
    validated = " ".join(v["node"] for v in why["validated_by"])
    assert "ISO 286" in validated and "bearing_life_l10" in validated
    assert why["sourced_from"], "a component with no source cannot be audited"
    assert "loader v" in why["sourced_from"][0]["why"]


def test_a_blocked_chain_explains_nothing_and_asks_instead():
    """The explanation cannot invent a selection the chain never made."""
    from orion.reasoning import reason

    why = G.explain_selection(reason("Support a rotating shaft at 1500 rpm"))
    assert not why.get("spine")
    assert why["asks"]
    assert "stopped at requirements" in why["answer"]


# --------------------------------------------------------------------------- #
# failure modes
# --------------------------------------------------------------------------- #
def _bearing(designation: str) -> dict:
    from orion.knowledge.registry import rows_for_family

    return next(r for r in rows_for_family("rolling_bearing")
                if r["designation"] == designation)


def test_a_failure_mode_assesses_this_part_at_this_duty():
    """'A bearing can fail by fatigue' is true of every bearing ever made and
    changes no decision."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=1500,
                  speed_rpm=1500, life_hours=20000)
    found = {a.mode: a for a in FM.assess("rolling_bearing", _bearing("6205"),
                                          duty)}
    # 6205 gives 10 673 h against 20 000 asked for.
    assert found["fatigue"].verdict == FM.AT_RISK
    assert found["fatigue"].margin < 1.0
    assert "ISO 281" in found["fatigue"].basis


def test_the_static_check_is_not_the_life_check():
    """A bearing that survives a million revolutions can be ruined by one shock
    while stationary, and rating life says nothing about it."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=9000,
                  speed_rpm=1500, life_hours=1)
    found = {a.mode: a for a in FM.assess("rolling_bearing", _bearing("6205"),
                                          duty)}
    # C0 = 7 800 N, so 9 000 N standing still indents the raceway.
    assert found["static_overload"].verdict == FM.AT_RISK
    assert "ISO 76" in found["static_overload"].basis


def test_too_little_load_is_a_failure_mode_too():
    """Below the minimum the elements skid instead of rolling, and every life
    calculation says the bearing is barely working."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=50,
                  speed_rpm=1500)
    found = {a.mode: a for a in FM.assess("rolling_bearing", _bearing("6205"),
                                          duty)}
    assert found["skidding"].verdict == FM.AT_RISK
    assert found["fatigue"].verdict == FM.OK       # the point: life is fine


def test_the_required_viscosity_is_computed_even_though_the_verdict_is_not():
    """We do not know the oil or the temperature, but the requirement follows
    from size and speed alone and is the number needed to choose a grade."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=1500,
                  speed_rpm=1500)
    found = {a.mode: a for a in FM.assess("rolling_bearing", _bearing("6205"),
                                          duty)}
    lube = found["lubrication_starvation"]
    assert lube.verdict == FM.UNKNOWN
    assert "19 mm2/s" in lube.finding        # 4500 * 1500^-0.5 * 38.5^-0.5
    assert "operating temperature" in lube.needs


def test_a_mode_that_cannot_be_computed_is_named_rather_than_dropped():
    """The modes you cannot compute are the ones that kill bearings."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=1500,
                  speed_rpm=1500)
    found = {a.mode: a for a in FM.assess("rolling_bearing", _bearing("6205"),
                                          duty)}
    for mode in ("contamination", "false_brinelling", "electrical_erosion"):
        assert found[mode].verdict == FM.UNKNOWN
        assert found[mode].needs


def test_risks_are_ordered_by_what_needs_attention():
    """A report that leads with a healthy fatigue life buries the static factor
    of 0.8 underneath it."""
    duty = F.Duty(function=F.SUPPORTS_ROTATION, radial_load_N=9000,
                  speed_rpm=1500, life_hours=1)
    verdicts = [a.verdict for a in FM.assess("rolling_bearing",
                                             _bearing("6205"), duty)]
    rank = {FM.AT_RISK: 0, FM.MARGINAL: 1, FM.UNKNOWN: 2, FM.OK: 3}
    assert verdicts == sorted(verdicts, key=lambda v: rank[v])


def test_a_selection_carries_its_failure_modes():
    from orion.reasoning import reason

    chain = reason("Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm")
    assert chain.risks
    assert {a.mode for a in chain.risks} == {m.id for m in FM.MODES}
    assert "failure modes" in chain.explain()


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
def test_coverage_counts_capability_not_files():
    """600 bearings that all serve one function is narrower than three families
    that serve five."""
    c = G.coverage()
    assert c["functions"]["total"] == len(F.FUNCTIONS)
    assert F.SUPPORTS_ROTATION in c["functions"]["complete"]
    # SealsFluid is selectable in principle but no skill builds a gland.
    assert F.SEALS_FLUID in c["functions"]["partial"]
    assert c["components"]["rows"] > 600


def test_coverage_reports_the_gaps_rather_than_hiding_them():
    c = G.coverage()
    assert c["calculators"]["orphaned"], \
        "a calculator no function can reach is the roadmap, not an omission"
    assert set(c["calculators"]["reachable_from_a_function"]) \
        & {"bearing_life_l10"}
    assert G.report().count("--  ") == len(c["functions"]["absent"])
