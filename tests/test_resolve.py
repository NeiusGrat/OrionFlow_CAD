"""The constraint resolution engine.

The contract these tests hold it to: it never returns "conflict", it never
lowers a requirement to make the arithmetic work, it never invents a preference
between designs that both satisfy the spec, and whatever it does return can be
built.
"""

from __future__ import annotations

from orion import planner as P
from orion import resolve as RS
from orion.knowledge import functions as F

JOINT = ("Design a robotic shoulder joint: support a rotating shaft carrying "
         "1.2 kN at 600 rpm for 20000 hours and transmit 80 Nm of torque")
SIZED = ("Support a rotating 30 mm shaft carrying 1.2 kN at 600 rpm and "
         "transmit 80 Nm of torque")
IMPOSSIBLE = ("Support a rotating shaft carrying 1.2 kN at 600 rpm and "
              "transmit 90000 Nm of torque")


# --------------------------------------------------------------------------- #
# the dependency graph
# --------------------------------------------------------------------------- #
def test_changing_the_shaft_invalidates_everything_downstream():
    """When the shaft moves, this is the list of things now stale, and an
    engineer reading the report is entitled to check nothing was left off."""
    stale = RS.dependents("shaft_dia_mm")
    assert {"housing_bore_mm", "key_width_mm", "key_length_mm",
            "seal_bore_mm", "retaining_groove_dia_mm"} <= set(stale)
    # Transitive: the housing bore feeds the shoulder and the fastener circle.
    assert "shoulder_dia_mm" in stale
    assert "fastener_circle_dia_mm" in stale


def test_the_dependency_walk_terminates():
    assert len(RS.dependents("shaft_dia_mm")) == len(
        set(RS.dependents("shaft_dia_mm")))


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_a_conflict_becomes_a_design():
    """The plan alone reports 'shaft wants 15, torque needs 22'. The solver is
    only useful if that becomes a bearing."""
    assert P.plan(JOINT).conflicts, "the unresolved plan should conflict"
    result = RS.resolve(JOINT)
    assert result.outcome in (RS.RESOLVED, RS.ALTERNATIVES)
    assert result.chosen is not None
    assert not result.chosen.plan.conflicts


def test_the_propagation_records_what_forced_each_change():
    result = RS.resolve(JOINT)
    assert result.revisions
    revision = result.revisions[0]
    assert revision.variable == "shaft_dia_mm"
    assert revision.was == 15.0 and revision.now >= 22.0
    assert "TransmitsTorque" in revision.because
    assert "housing_bore_mm" in revision.invalidates


def test_the_solver_only_ever_raises():
    """A design satisfying a weakened spec is not a solution to the stated
    problem, it is a different problem."""
    result = RS.resolve(JOINT)
    for revision in result.revisions:
        assert revision.was is None or revision.now > revision.was


def test_the_resolved_design_still_carries_the_stated_duty():
    """Re-selecting must not quietly drop the requirement that forced it."""
    result = RS.resolve(JOINT)
    key = next(r for r in result.chosen.plan.resolutions
               if r.function == F.TRANSMITS_TORQUE)
    assert key.resolved
    assert "against 80 required" in key.summary
    bearing = next(r for r in result.chosen.plan.resolutions
                   if r.function == F.SUPPORTS_ROTATION)
    assert bearing.resolved


def test_an_already_consistent_request_resolves_without_revising_anything():
    result = RS.resolve(SIZED)
    assert result.revisions == []
    assert result.rounds == 0
    assert result.chosen is not None


# --------------------------------------------------------------------------- #
# alternatives
# --------------------------------------------------------------------------- #
def test_several_valid_designs_are_ranked_rather_than_chosen_between():
    """Choosing between a lighter design and a cheaper one is the engineer's
    call, not the solver's."""
    result = RS.resolve(JOINT)
    assert result.outcome == RS.ALTERNATIVES
    assert result.alternatives
    for alt in result.alternatives:
        assert not alt.plan.conflicts
        assert alt.metrics


def test_the_chosen_design_is_the_smallest_that_works():
    result = RS.resolve(JOINT)
    chosen = result.chosen.metrics["outside_dia_mm"]
    assert all(a.metrics["outside_dia_mm"] >= chosen
               for a in result.alternatives)


def test_ties_on_envelope_go_to_the_smaller_shaft():
    """Two designs can share a housing bore and differ by 5 mm of shaft — the
    shaft is material and inertia the housing metric never sees."""
    result = RS.resolve(JOINT)
    same = {}
    for alt in result.alternatives:
        same.setdefault(alt.metrics["outside_dia_mm"], []).append(
            alt.metrics["shaft_dia_mm"])
    for _envelope, shafts in same.items():
        assert shafts == sorted(shafts)


def test_alternatives_are_distinct_designs_not_variations():
    result = RS.resolve(JOINT)
    shafts = [a.metrics["shaft_dia_mm"] for a in result.alternatives]
    assert len(shafts) == len(set(shafts))


# --------------------------------------------------------------------------- #
# unsatisfiable
# --------------------------------------------------------------------------- #
def test_an_impossible_duty_is_never_reported_as_a_design():
    """90 000 Nm has no key on any shaft in DIN 6885. Reporting the rest of the
    design as resolved around that hole is the worst kind of wrong:
    complete-looking."""
    result = RS.resolve(IMPOSSIBLE)
    assert result.outcome == RS.UNSATISFIABLE
    assert result.chosen is None
    assert "TransmitsTorque" in result.explanation


def test_unsatisfiable_names_the_smallest_change_that_would_help():
    result = RS.resolve(IMPOSSIBLE)
    assert result.smallest_change
    assert any(word in result.smallest_change
               for word in ("larger", "spline", "keys"))


def test_a_missing_resolver_is_not_an_unsatisfiable_duty():
    """A function nobody has implemented and one whose resolver looked and
    found nothing mean opposite things."""
    result = RS.resolve(SIZED)
    unresolved = result.chosen.plan.unresolved()
    assert unresolved, "LocatesPart and friends have no resolver yet"
    assert all(not r.attempted for r in unresolved)
    assert result.outcome != RS.UNSATISFIABLE


# --------------------------------------------------------------------------- #
# verification and reporting
# --------------------------------------------------------------------------- #
def test_the_resolved_design_is_verified_like_any_blueprint():
    """A resolution that cannot be built is not a resolution."""
    result = RS.resolve(JOINT)
    assert result.verification["buildable"] is True
    assert result.verification["preconditions"] == "hold"
    assert result.verification["part_class"] == "bearing_carrier"


def test_never_only_a_conflict():
    """Always a design, ranked alternatives, or an engineering explanation."""
    for request in (JOINT, SIZED, IMPOSSIBLE):
        result = RS.resolve(request)
        assert result.outcome in (RS.RESOLVED, RS.ALTERNATIVES,
                                  RS.UNSATISFIABLE)
        assert result.explanation
        if result.outcome == RS.UNSATISFIABLE:
            assert result.smallest_change
        else:
            assert result.chosen is not None


def test_the_report_reads_top_to_bottom():
    text = RS.resolve(JOINT).explain()
    for heading in ("PROPAGATION", "RESOLVED DESIGN", "ALTERNATIVES",
                    "EXPLANATION", "VERIFICATION"):
        assert heading in text
    assert "shaft_dia_mm: 15 -> 22" in text


def test_resolution_is_deterministic():
    """No model is consulted anywhere in this."""
    first, second = RS.resolve(JOINT), RS.resolve(JOINT)
    assert first.to_dict() == second.to_dict()
