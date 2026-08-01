"""Which requests are diverted to the reasoning chain, and which are not.

The routing rule is one line of policy with an expensive failure on each side,
so it is tested from both. The case that forced the gate to exist is
``test_geometry_is_not_a_duty_however_it_is_worded``: a mounting plate whose
only crime was containing the word "bore" was routed to bearing selection and
came back as a housing for a 604.
"""

from __future__ import annotations

import pytest

from app.services import design_router as DR

DUTY = "Support a rotating shaft carrying 3 kN radial at 1500 rpm for 20000 hours on a 25 mm shaft"
PLATE = (
    "A 120 x 80 x 12 mm aluminium mounting plate with a 30 mm central bore "
    "and four M6 clearance holes on a 100 x 60 mm rectangular pattern."
)


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
def test_a_stated_load_routes_to_the_chain():
    route = DR.decide(DUTY)
    assert route.to_chain
    assert route.duty["radial_load_N"] == 3000.0
    # The reason is shown to the user, so it has to read like one.
    assert "3000 N" in route.why


def test_geometry_is_not_a_duty_however_it_is_worded():
    """The case this gate exists for.

    "a 30 mm central bore" is a hole. Read as a duty it sends a plate to
    bearing selection, which is how a 120x80 plate became a housing for a 604.
    """
    route = DR.decide(PLATE)
    assert route.route == DR.DIRECT
    assert "no load" in route.why
    # The extractor may still read a bore; what matters is that it does not divert.
    assert not any(route.duty.get(f) for f in DR.LOAD_FIELDS)


@pytest.mark.parametrize(
    "request_text",
    [
        "A 50 mm cube",
        "An L-bracket 80 x 60 x 5 mm with two M8 clearance holes",
        "A 120 x 80 x 12 mm plate",
        "A flange 100 mm diameter with 6 bolt holes",
        "",
    ],
)
def test_plain_geometry_reaches_the_model_unchanged(request_text):
    """No regression: everything that worked before still takes the old path."""
    assert DR.decide(request_text).route == DR.DIRECT


@pytest.mark.parametrize(
    "request_text,expected_field",
    [
        ("A bracket carrying 2 kN", "radial_load_N"),
        ("A coupling transmitting 80 Nm", "torque_Nm"),
    ],
)
def test_any_load_kind_diverts(request_text, expected_field):
    route = DR.decide(request_text)
    assert route.to_chain
    assert route.duty[expected_field]


def test_the_gate_matches_what_the_chain_will_accept():
    """Routing on a signal the chain then refuses would only produce questions.

    The chain will not select without one of these fields, so the router must
    not divert on anything weaker. Pinned against the chain's own constant so
    the two cannot drift apart silently.
    """
    from orion.reasoning import _LOAD_FIELDS

    assert set(DR.LOAD_FIELDS) == set(_LOAD_FIELDS)


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_a_complete_chain_hands_the_model_dimensions_not_prose():
    from orion.reasoning import design_prompt

    route = DR.resolve(DUTY)
    assert route.to_chain and route.chain is not None
    assert route.chain.complete

    handed = design_prompt(route.chain)
    assert handed.startswith("Build a bearing_carrier with ")
    # Every dimension decided before the model is asked for anything.
    assert "=" in handed
    # The derivation is withheld: it is the user's, and feeding it back invites
    # the model to re-open settled arithmetic.
    assert "because" not in handed.lower() and "ISO" not in handed


def test_the_direct_route_never_runs_the_chain():
    """Cost as well as correctness: geometry must not pay for catalogue search."""
    route = DR.resolve(PLATE)
    assert route.route == DR.DIRECT
    assert route.chain is None


def test_a_broken_extractor_falls_back_rather_than_failing(monkeypatch):
    """A router that can break the product when its heuristics fail is worse
    than no router."""

    def _explode(_request):
        raise RuntimeError("regex engine on fire")

    monkeypatch.setattr("orion.reasoning.read_intent", _explode)
    route = DR.decide(DUTY)
    assert route.route == DR.DIRECT
    assert "could not be read" in route.why


def test_a_broken_chain_falls_back_to_the_model(monkeypatch):
    def _explode(_request):
        raise RuntimeError("catalogue unavailable")

    monkeypatch.setattr("orion.reasoning.reason", _explode)
    route = DR.resolve(DUTY)
    assert route.route == DR.DIRECT
    assert "could not run" in route.why
