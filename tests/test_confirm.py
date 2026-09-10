"""Closing the loop: build what the search chose and grade it.

Everything upstream of confirmation is closed form, so a candidate says
``screened`` and never ``VERIFIED``. These cover the step that earns the
stronger word — and, as much, the step that refuses to.

Most of this runs without FreeCAD. The kernel is not a test dependency and is
absent from the API container, so every entry point has to degrade to a stated
reason rather than an exception; that behaviour is tested unconditionally. The
handful of tests that need a real build are skipped when no interpreter is
found, and say so rather than passing vacuously.
"""

import pytest

from orion import blueprint_gen as G, confirm as C, design_space as DS, \
    interview as I, provenance as P, search as S
from orion.blueprint import Blueprint

#: Prose that states every dimension, so the starting design is fully sourced
#: and the only thing that can make it unsourced later is the search itself.
STATED = ("An aluminium 6061-T6 bracket: base 80 x 60 x 10 mm, upright 70 mm "
          "tall and 10 mm thick, carrying 400 N with a safety factor of 2.")

SLOTS = {"base_length": 80.0, "base_width": 60.0, "base_thickness": 10.0,
         "upright_height": 70.0, "upright_thickness": 10.0,
         "material": "6061-T6 aluminium", "load_n": 400.0,
         "safety_factor": 2}

needs_kernel = pytest.mark.skipif(
    not C.kernel_available(),
    reason="no FreeCAD interpreter on this machine; the confirmation path "
           "needs a real kernel and must not be faked")


def _requirements(request: str = STATED, **overrides) -> dict:
    iv = I.Interview(request=request, family="l_bracket",
                     slots={**SLOTS, **overrides})
    iv.classify()
    return I.requirements(iv)


def _blueprint(requirements: dict) -> Blueprint:
    return Blueprint.from_dict(
        G.generate("l_bracket", requirements)).freeze()


# --------------------------------------------------------------------------- #
# Without a kernel
# --------------------------------------------------------------------------- #


def test_a_graph_with_no_features_is_refused_before_the_kernel_runs():
    """The failure this module exists to catch.

    Handing the compiler an unresolved Blueprint does not raise: it iterates no
    features, builds nothing, writes an empty document and exits zero. Measured
    by hand once — `built: []`, no errors, null volume — which is why an empty
    graph is refused here rather than trusted because a process succeeded.
    """
    class _Empty:
        def resolve(self):
            return {"features": [], "sketches": []}

    made = C.build(_Empty())

    assert made.ok is False
    assert "no features" in made.reason
    assert "report success" in made.reason


def test_a_template_that_cannot_resolve_is_a_reason_not_an_exception():
    class _Broken:
        def resolve(self):
            raise ValueError("bad expression")

    made = C.build(_Broken())

    assert made.ok is False
    assert "did not resolve" in made.reason


def test_a_failed_build_is_not_a_statement_about_the_design():
    made = C.Built(ok=False, reason="no FreeCAD interpreter available")
    text = " ".join(C.explain(C.Confirmation(built=made)))

    assert "Not built" in text
    assert "only about whether it could be put through a kernel" in text


def test_an_unbuilt_confirmation_has_no_verdict():
    confirmation = C.Confirmation(built=C.Built(ok=False, reason="absent"))

    assert confirmation.verdict == "unbuilt"
    assert confirmation.volume_agreement is None


def test_a_candidate_with_no_family_cannot_be_built():
    candidate = S.Candidate(params={}, evidence=DS.SCREENED, metrics={},
                            path=(), requirements={})

    with pytest.raises(C.ConfirmError, match="no family"):
        C.confirm_candidate(candidate)


# --------------------------------------------------------------------------- #
# The ledger, which does not need a kernel to test
# --------------------------------------------------------------------------- #


def test_a_dimension_the_search_chose_is_derived_and_not_unsourced():
    """Without this the loop could never close.

    A search-chosen part builds perfectly and matches every frozen assertion,
    and if its moved dimension were unclassified the ledger would correctly
    refuse to vouch for it — capping the verdict at UNSOURCED forever. It did
    not come from nowhere: it was chosen deterministically inside declared
    bounds, which is `derived`.
    """
    state = DS.initial_state("l_bracket", _requirements())
    state.unlocked = frozenset({"UW"})
    moved = DS.step(state, DS.Action("UW", 40.0))

    assert moved.applied
    entry = (moved.state.requirements["provenance"] or {})["upright_width"]
    assert entry["source"] == "derived"
    assert "chosen by search" in entry["basis"]
    assert "to 40" in entry["basis"]


def test_the_ledger_survives_into_the_frozen_blueprint():
    state = DS.initial_state("l_bracket", _requirements())
    state.unlocked = frozenset({"UW"})
    moved = DS.step(state, DS.Action("UW", 40.0))

    blueprint = _blueprint(moved.state.requirements)

    assert P.unsourced(blueprint.design_plan["provenance"]) == []
    assert blueprint.design_plan["provenance"]["UW"]["source"] == "derived"


def test_a_fully_stated_design_starts_with_a_clean_ledger():
    """The control for the test above: if the start were already unsourced,
    a clean result afterwards would prove nothing."""
    blueprint = _blueprint(_requirements())

    assert P.unsourced(blueprint.design_plan["provenance"]) == []


def test_a_dimension_nobody_stated_is_still_unsourced():
    """The gate is not weakened. Only a *search* move is derived; a number
    that arrived from nowhere else is still refused."""
    loose = _requirements(
        request="An aluminium 6061-T6 bracket carrying 400 N with a safety "
                "factor of 2.")
    blueprint = _blueprint(loose)

    assert P.unsourced(blueprint.design_plan["provenance"])


# --------------------------------------------------------------------------- #
# With a kernel
# --------------------------------------------------------------------------- #


@needs_kernel
def test_a_generated_blueprint_builds_and_matches_its_own_prediction():
    """The quantity the whole search ranks on, checked against a solid.

    A search optimising a volume expression that does not describe the built
    part is optimising a fiction, and nothing before this point could notice.
    """
    confirmation = C.confirm(_blueprint(_requirements()))

    assert confirmation.built.ok, confirmation.built.reason
    assert confirmation.built.measured["solids"] == 1
    assert confirmation.built.measured["watertight"] is True
    assert confirmation.built.measured["valid"] is True
    assert confirmation.volume_agreement < 1e-9


@needs_kernel
def test_the_search_winner_builds_and_verifies():
    """The loop, closed: prose in, a lighter part out, graded by a kernel."""
    state = DS.initial_state("l_bracket", _requirements())
    state.unlocked = frozenset({"UW", "BT", "UT"})
    result = S.explore(state)

    assert result.improved
    confirmation = C.confirm_candidate(result.best)

    assert confirmation.built.ok, confirmation.built.reason
    assert confirmation.volume_agreement < 1e-9
    assert not [r for r in confirmation.assertions if not r.get("ok", True)]
    assert confirmation.verdict == "verified"


@needs_kernel
def test_confirmation_writes_the_artifacts_a_user_would_want():
    confirmation = C.confirm(_blueprint(_requirements()))

    assert confirmation.built.ok
    for name in ("part.FCStd", "part.step", "part.stl"):
        assert name in confirmation.built.artifacts


@needs_kernel
def test_the_explanation_says_what_it_did_not_establish():
    """A green verdict must not be read as vouching for the stress analysis:
    nothing here measures a stress."""
    text = " ".join(C.explain(C.confirm(_blueprint(_requirements()))))

    assert "VERIFIED" in text
    assert "not that the stress analysis behind it was right" in text


@needs_kernel
def test_a_part_that_disagrees_with_its_prediction_is_reported():
    """Fabricated disagreement: the contract is edited after the fact, which
    is exactly what the frozen hash exists to prevent — here it is done
    deliberately to prove the comparison is live rather than decorative."""
    blueprint = _blueprint(_requirements())
    confirmation = C.confirm(blueprint)
    assert confirmation.built.ok

    # Halve the prediction and re-derive the agreement.
    confirmation.predicted_volume_mm3 = (
        confirmation.measured_volume_mm3 / 2.0)

    assert confirmation.volume_agreement == pytest.approx(1.0, rel=1e-6)
