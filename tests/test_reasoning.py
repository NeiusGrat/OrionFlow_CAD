"""The chain from a sentence to a specification.

The tests worth having here are not that it produces a bearing. They are that it
cannot produce one from a request that never stated a load, that a number in the
output can be traced to the stage that decided it, and that the model is handed
dimensions rather than prose.
"""

from __future__ import annotations

import pytest

from orion import reasoning as R
from orion.knowledge import functions as F


# --------------------------------------------------------------------------- #
# intent
# --------------------------------------------------------------------------- #
def test_a_load_and_a_thrust_are_told_apart_by_the_nearest_word():
    """'carrying 3 kN with 2 kN thrust' has one qualifier and two figures.

    A window wide enough to catch 'thrust' from the second catches it from the
    first as well, which reads the radial load as axial and loses it entirely.
    """
    duty = R.read_intent(
        "Support a rotating shaft carrying 3 kN with 2 kN thrust"
    ).detail["duty"]
    assert duty["radial_load_N"] == 3000.0
    assert duty["axial_load_N"] == 2000.0


@pytest.mark.parametrize("request_, field_, value", [
    ("shaft at 1500 rpm", "speed_rpm", 1500.0),
    ("25 Hz spindle", "speed_rpm", 1500.0),
    ("for 20,000 hours", "life_hours", 20000.0),
    ("2 kN radial", "radial_load_N", 2000.0),
    ("450 lbf radial", "radial_load_N", pytest.approx(2001.7, abs=0.5)),
    ("a 25 mm shaft", "bore_mm", 25.0),
    ("shaft of 30 mm", "bore_mm", 30.0),
    ("0.5 deg out of line", "misalignment_deg", 0.5),
])
def test_figures_are_read_with_their_units(request_, field_, value):
    assert R.read_intent(request_).detail["duty"].get(field_) == value


def test_nothing_is_defaulted_at_the_intent_stage():
    """A figure absent from the request stays absent. A default load is a
    number the user never gave and will never think to check."""
    duty = R.read_intent("Support a rotating shaft").detail["duty"]
    assert duty == {}


def test_an_unrecognised_request_asks_rather_than_guesses():
    step = R.read_intent("make me something nice")
    assert step.asks
    assert "What must the part do" in step.asks[0]


# --------------------------------------------------------------------------- #
# the chain
# --------------------------------------------------------------------------- #
def test_a_request_without_a_load_cannot_reach_a_specification():
    """The load is divided by. Assuming zero produces the smallest bearing in
    the catalogue and nothing downstream catches it."""
    chain = R.reason("Support a rotating shaft at 1500 rpm")
    assert not chain.complete
    assert chain.stopped_at == R.REQUIREMENTS
    assert any("radial load" in q for q in chain.asks())
    with pytest.raises(ValueError):
        R.design_prompt(chain)


def test_a_full_request_reaches_buildable_variables():
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN "
                     "at 900 rpm for 10000 hours")
    assert chain.complete
    assert chain.part_class == "bearing_carrier"
    assert set(chain.variables) == {"R", "rs", "rb", "ds", "T"}
    # The seat is the bearing's outer diameter, and the bore clears the shaft.
    assert chain.variables["rb"] > 25.0 / 2
    assert chain.variables["R"] > chain.variables["rs"] > chain.variables["rb"]


def test_every_stage_is_on_the_record_in_order():
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN "
                     "at 900 rpm for 10000 hours")
    assert [s.stage for s in chain.steps] == list(R.STAGES)


def test_each_variable_names_the_reason_it_has_that_value():
    """A number with no stage behind it cannot appear in the output."""
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN "
                     "at 900 rpm for 10000 hours")
    for name in chain.variables:
        assert chain.rationale.get(name), f"{name} has no rationale"
    assert any("ISO 286" in c for c in chain.citations)
    assert any("ISO 15" in c for c in chain.citations)


def test_an_assumption_is_made_loudly_or_not_at_all():
    """Rating life has a defensible standing assumption; a radial load does
    not. The difference is that the assumed one is announced."""
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm")
    assert chain.complete
    assert any("10 000 h assumed" in w for w in chain.warnings)


def test_the_selected_type_carries_its_cost_forward():
    """A taper roller sized on life alone is a correct bearing and an
    incomplete decision: it needs an opposed partner nobody asked for."""
    chain = R.reason("Support a rotating shaft, 3 kN radial and 2 kN axial, "
                     "1500 rpm")
    assert chain.complete
    assert any("opposed" in w for w in chain.warnings)


def test_an_impossible_duty_names_the_requirement_to_renegotiate():
    chain = R.reason("Support a rotating shaft carrying 3 kN with 2 kN thrust "
                     "at 0.1 deg, 1500 rpm, 20000 hours")
    assert not chain.complete
    assert chain.stopped_at == R.SELECTION
    # The type that missed by the least, and only on one count.
    assert "taper_roller" in chain.asks()[0]
    assert "misalignment" in chain.step(R.SELECTION).basis


def test_the_model_is_given_dimensions_not_prose():
    """The register the model was fine-tuned on is a resolved parametric part.
    Feeding the reasoning back invites it to re-litigate settled arithmetic."""
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN "
                     "at 900 rpm for 10000 hours")
    prompt = R.design_prompt(chain)
    assert prompt.startswith("Build a bearing_carrier with ")
    assert "rs=" in prompt and "ISO" not in prompt and "because" not in prompt


def test_the_chain_is_deterministic():
    """Given the same request, the same specification. This is the property the
    model cannot offer and the reason the first seven stages are not it."""
    ask = "Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm"
    first, second = R.reason(ask), R.reason(ask)
    assert first.variables == second.variables
    assert first.to_dict()["steps"] == second.to_dict()["steps"]


def test_the_trace_reads_top_to_bottom():
    chain = R.reason("Support a rotating 25 mm shaft carrying 1.5 kN at 900 rpm")
    text = chain.explain()
    for stage in R.STAGES:
        assert stage.upper() in text
    assert "SPECIFICATION (bearing_carrier)" in text


def test_a_function_with_no_ingested_family_says_so_rather_than_inventing():
    """Every gland row reads AMBIGUOUS, so sealing has nothing to offer. An
    empty answer is far better than a face-seal gland fitted to a piston."""
    F.load_all()
    duty = F.Duty(function=F.SEALS_FLUID, cord_dia_mm=3.53)
    assert F.search(duty) == []
