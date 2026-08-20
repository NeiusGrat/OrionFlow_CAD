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
    assert route.route == DR.CHAIN
    assert route.duty["radial_load_N"] == 3000.0
    # The reason is shown to the user, so it has to read like one.
    assert "3000 N" in route.why


def test_geometry_never_reaches_the_duty_chain_however_it_is_worded():
    """The case this gate exists for.

    "a 30 mm central bore" is a hole. Read as a duty it sends a plate to
    bearing selection, which is how a 120x80 plate became a housing for a 604.
    It now goes to the prismatic branch — but the invariant under test is the
    negative one: never to the duty chain.
    """
    route = DR.decide(PLATE)
    assert route.route != DR.CHAIN
    assert route.route == DR.PRISMATIC
    # The extractor may still read a bore; what matters is that no load did.
    assert not any(route.duty.get(f) for f in DR.LOAD_FIELDS)


def test_a_sized_prismatic_part_routes_to_the_prismatic_branch():
    route = DR.decide("A 120 x 80 x 12 mm plate")
    assert route.route == DR.PRISMATIC
    assert "names a plate" in route.why


def test_a_load_wins_over_plate_shape():
    """A bracket that must survive something is a duty problem, plate-shaped or
    not. Ordering the branches the other way sizes it against nothing."""
    route = DR.decide("A 120 x 80 x 12 mm bracket carrying 2 kN")
    assert route.route == DR.CHAIN


@pytest.mark.parametrize(
    "request_text",
    [
        "A 50 mm cube",
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
    assert route.to_branch
    assert route.duty[expected_field]


def test_the_gate_never_diverts_on_a_signal_the_chain_refuses():
    """Routing on a signal the chain then refuses would only produce questions.

    The chain will not select without one of its load fields, so the router
    must not divert on anything weaker. Pinned against the chain's own constant
    so the two cannot drift apart silently.
    """
    from orion.reasoning import _LOAD_FIELDS

    assert set(DR.LOAD_FIELDS) <= set(_LOAD_FIELDS)


def test_a_stated_pressure_is_read_and_still_does_not_divert():
    """The converse does not hold, and pressure is the case that proves it.

    ``pressure_bar`` satisfies the chain's selection gate but no function in the
    chain acts on it, so a diverted pressure request stops at INTENT asking
    "what must the part do?" — worse than the part the model would have built.
    It was harmless while nothing extracted a pressure; now that ``orion.duty``
    reads one it has to be excluded explicitly.
    """
    from orion.reasoning import _LOAD_FIELDS

    assert "pressure_bar" in _LOAD_FIELDS
    assert "pressure_bar" not in DR.LOAD_FIELDS
    assert "pressure_bar" in DR.ADVISORY_FIELDS

    route = DR.decide("a manifold rated to 250 bar")
    assert route.route == DR.DIRECT


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_a_complete_chain_hands_the_model_dimensions_not_prose():
    from orion.reasoning import design_prompt

    route = DR.resolve(DUTY)
    assert route.to_branch and route.chain is not None
    assert route.chain.complete

    handed = design_prompt(route.chain)
    assert handed.startswith("Build a bearing_carrier with ")
    # Every dimension decided before the model is asked for anything.
    assert "=" in handed
    # The derivation is withheld: it is the user's, and feeding it back invites
    # the model to re-open settled arithmetic.
    assert "because" not in handed.lower() and "ISO" not in handed


def test_the_direct_route_runs_no_branch_at_all():
    """Cost as well as correctness: an unclaimed request pays for neither
    catalogue search nor plate specification."""
    route = DR.resolve("A 50 mm cube")
    assert route.route == DR.DIRECT
    assert route.chain is None and route.design_prompt == ""


def test_the_prismatic_route_hands_over_placed_dimensions():
    route = DR.resolve(PLATE)
    assert route.route == DR.PRISMATIC
    assert route.chain is not None and route.chain.complete
    # ISO 273 for M6, and the pattern placed at the stated pitch.
    assert "hr=3.3" in route.design_prompt
    assert "mx=50" in route.design_prompt and "my=30" in route.design_prompt


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
