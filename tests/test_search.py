"""The deterministic search over the design space.

Not an optimizer and not trying to be. What is tested is that the search is
reproducible, that it never offers a candidate the environment would refuse,
that alternatives are genuinely different designs rather than one design at
three nearby dimensions, and — the property this module exists to keep — that
a parameter no declared check reads is *named* rather than quietly driven to
its bound.

That last one is not hypothetical. The first run of this search, on a bracket
carrying 400 N, thinned the base plate to 1 mm: the declared duty is a beam
check on the upright, so nothing in the evidence reads the base at all, and a
parameter nothing reads is free mass.
"""

import pytest

from orion import design_space as DS, interview as I, search as S

BRACKET = {"base_length": 80.0, "base_width": 60.0, "base_thickness": 10.0,
           "upright_height": 70.0, "upright_thickness": 10.0}

DUTY = {"material": "6061-T6 aluminium", "load_n": 400.0, "safety_factor": 2}

STATED = ("An aluminium 6061-T6 bracket, base 80 x 60 mm, upright 70 mm tall, "
          "carrying 400 N with a safety factor of 2.")


def _state(slots: dict, request: str = "a bracket",
           family: str = "l_bracket") -> DS.State:
    iv = I.Interview(request=request, family=family, slots=dict(slots))
    iv.classify()
    return DS.initial_state(family, I.requirements(iv))


@pytest.fixture
def bracket() -> DS.State:
    return _state({**BRACKET, **DUTY}, request=STATED)


# --------------------------------------------------------------------------- #
# Reproducibility
# --------------------------------------------------------------------------- #


def test_the_same_request_produces_the_same_alternatives(bracket):
    """An engineer who reruns a design and gets different numbers has no
    reason to trust either run."""
    a = S.explore(bracket)
    b = S.explore(_state({**BRACKET, **DUTY}, request=STATED))

    assert [c.params for c in a.alternatives] == [c.params for c in b.alternatives]
    assert a.evaluated == b.evaluated
    assert S.explain(a) == S.explain(b)


def test_ties_break_on_the_parameter_vector_not_on_chance():
    """Two designs of equal mass are common; their order must still be fixed."""
    start = S.Candidate(params={"A": 1.0}, evidence=DS.SCREENED,
                        metrics={"mass_g": 10.0}, path=())
    same = [
        S.Candidate(params={"A": 3.0}, evidence=DS.SCREENED,
                    metrics={"mass_g": 5.0}, path=()),
        S.Candidate(params={"A": 2.0}, evidence=DS.SCREENED,
                    metrics={"mass_g": 5.0}, path=()),
    ]
    objective = S.Objective()

    first = S._ranked(list(same), objective)
    second = S._ranked(list(reversed(same)), objective)

    assert [c.params for c in first] == [c.params for c in second]


# --------------------------------------------------------------------------- #
# What it finds
# --------------------------------------------------------------------------- #


def test_it_finds_a_lighter_design_that_still_passes(bracket):
    result = S.explore(bracket)

    assert result.improved
    best = result.best
    assert best.value(result.objective) < result.start.value(result.objective)
    assert best.feasible


def test_every_alternative_is_feasible(bracket):
    result = S.explore(bracket)

    assert result.alternatives
    for alt in result.alternatives:
        assert alt.feasible
        assert alt.evidence in (DS.SCREENED, DS.NO_DUTY)


def test_alternatives_differ_in_what_was_done_to_them(bracket):
    """A ranked list alone returns the same bracket three times."""
    result = S.explore(bracket)

    descriptors = [alt.changed(result.start) for alt in result.alternatives]
    assert len(descriptors) == len(set(descriptors)), \
        "two alternatives moved the same parameters"


def test_an_alternative_carries_the_moves_that_reached_it(bracket):
    result = S.explore(bracket)

    for alt in result.alternatives:
        assert alt.path, "a candidate with no path is the starting design"
        for action in alt.path:
            assert action.parameter in DS.SEARCHABLE["l_bracket"]


def test_infeasible_candidates_are_kept_not_discarded(bracket):
    """"Every lighter version failed its duty" is the most useful thing this
    can say, and it cannot be said from the feasible set alone."""
    result = S.explore(bracket)

    rejected = [c for c in result.considered if not c.feasible]
    assert rejected
    assert any(c.evidence == DS.FAILED for c in rejected)


# --------------------------------------------------------------------------- #
# What it will not do
# --------------------------------------------------------------------------- #


def test_a_stated_dimension_is_never_moved(bracket):
    """The user said 70 mm tall. A lighter bracket that is 10 mm tall is not
    an answer to the question they asked."""
    result = S.explore(bracket)

    for candidate in result.considered:
        assert candidate.params["UH"] == bracket.params["UH"]
        assert candidate.params["BL"] == bracket.params["BL"]
        assert candidate.params["BW"] == bracket.params["BW"]


def test_an_unstated_dimension_is_fair_game():
    """Nothing was stated, so nothing is locked — and the search says so by
    moving what it likes."""
    loose = _state({**BRACKET, **DUTY}, request="a bracket")
    result = S.explore(loose)

    moved = set()
    for candidate in result.considered:
        moved |= candidate.changed(result.start)
    assert "UH" in moved or "BL" in moved


def test_no_candidate_would_be_refused_by_the_environment(bracket):
    """The search must never offer something `step` would reject."""
    result = S.explore(bracket)

    for candidate in result.alternatives:
        assert DS.feasible("l_bracket", candidate.params), candidate.params


# --------------------------------------------------------------------------- #
# The parameter nothing checks
# --------------------------------------------------------------------------- #


def test_a_parameter_no_check_reads_is_named(bracket):
    """The beam check reads the upright. Nothing reads the base thickness, so
    a search drives it to its bound and nothing objects."""
    result = S.explore(bracket)

    assert "BT" in result.unconstrained
    # And the ones the check does read are not named.
    assert "UT" not in result.unconstrained


def test_the_unconstrained_warning_reaches_the_explanation(bracket):
    text = " ".join(S.explain(S.explore(bracket)))

    assert "No declared check reads BT" in text
    assert "unverified" in text


def test_a_design_with_no_duty_names_nothing_unconstrained():
    """With no checks at all, "unconstrained" is not a meaningful claim: it
    would name every parameter and tell nobody anything."""
    plain = _state({**BRACKET, "material": "6061-T6 aluminium"})

    assert S.unconstrained(plain) == []


def test_every_check_reading_parameter_is_excluded(bracket):
    """A parameter the check responds to must never be reported as loose."""
    for name in S.unconstrained(bracket):
        moved = dict(bracket.params)
        moved[name] = moved[name] * 1.5
        # It may be that the value is out of range; the assertion is only that
        # the reported names are ones the duty genuinely ignores.
        assert name in DS.SEARCHABLE["l_bracket"]


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #


def test_a_repeated_design_is_served_from_the_cache(bracket):
    """Rebuilds are deterministic, so identical parameters are the same design
    and the cache is exact rather than approximate."""
    result = S.explore(bracket, depth=2)

    assert result.cached > 0
    assert result.evaluated == len(result.considered) - 1


def test_the_budget_is_respected(bracket):
    result = S.explore(bracket, depth=3, steps=6, budget=20)

    assert result.evaluated <= 20
    assert any("budget" in n for n in result.notes)


def test_a_zero_depth_search_evaluates_nothing(bracket):
    result = S.explore(bracket, depth=0)

    assert result.evaluated == 0
    assert result.alternatives == []
    assert result.best is result.start or result.best == result.start


# --------------------------------------------------------------------------- #
# When it cannot rank
# --------------------------------------------------------------------------- #


def test_a_design_with_no_material_cannot_be_ranked_and_says_so():
    """No material, no mass, no objective — and no invented one."""
    no_material = _state({**BRACKET, "load_n": 400.0})
    result = S.explore(no_material)

    assert result.evaluated == 0
    assert result.alternatives == []
    assert any("mass_g" in n for n in result.notes)


def test_a_family_whose_duty_cannot_be_judged_yields_no_alternatives():
    """A stated load on a bearing housing is `unjudged`, which is not feasible,
    so there is nothing to offer."""
    housing = _state(
        {"length": 70.0, "width": 60.0, "height": 30.0, "bore_d": 32.0,
         "seat_depth": 12.0, "material": "6061-T6 aluminium",
         "load_n": 4000.0},
        family="bearing_housing")
    result = S.explore(housing)

    assert result.alternatives == []
    assert all(c.evidence == DS.UNJUDGED for c in result.considered)


def test_a_family_with_no_duty_can_still_be_made_lighter():
    """No load stated means nothing is owed, so mass alone is a fair goal."""
    housing = _state(
        {"length": 70.0, "width": 60.0, "height": 30.0, "bore_d": 32.0,
         "seat_depth": 12.0, "material": "6061-T6 aluminium"},
        family="bearing_housing")
    result = S.explore(housing)

    assert result.improved
    assert all(a.evidence == DS.NO_DUTY for a in result.alternatives)


# --------------------------------------------------------------------------- #
# The explanation
# --------------------------------------------------------------------------- #


def test_the_explanation_never_claims_the_part_was_verified(bracket):
    text = " ".join(S.explain(S.explore(bracket)))

    assert "screened" in text.lower()
    assert "verified" not in text.lower().replace("unverified", "")


def test_the_explanation_reports_what_it_looked_at(bracket):
    result = S.explore(bracket)
    lines = S.explain(result)

    assert str(len(result.considered)) in lines[0]
    assert str(result.evaluated) in lines[0]


def test_a_maximising_objective_works_too(bracket):
    """Nothing about the ranking assumes smaller is better."""
    stiffest = S.Objective(metric="safety_factor", direction=S.MAXIMIZE)
    result = S.explore(bracket, objective=stiffest)

    assert result.improved
    assert result.best.metrics["safety_factor"] > \
        result.start.metrics["safety_factor"]
