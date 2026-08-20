"""Typed duty extraction, and the gate that keeps it honest.

The split this file pins: a model may read a sentence, and only Python decides
what to believe. So the tests come in two halves — what the gate accepts (every
ordinary way of writing a load, which the regular expressions could not read)
and what it refuses (anything nobody wrote down, which is the failure that would
divert a plain geometry request into an interrogation about a load).

No model is called anywhere here. ``gate`` takes what a model *would* have
proposed, which is the whole of what needs guarding.
"""

import pytest

from orion import duty as D


# --------------------------------------------------------------------------- #
# what the patterns could not read
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "request_text,proposed,expected",
    [
        # mass stated as a load, converted and rounded by the model
        ("a bracket that must hold 50 kg", {"radial_load_N": 490.3},
         {"radial_load_N": 490.3}),
        # the unit spelled out and the number in words
        ("a shaft carrying a load of three kilonewtons", {"radial_load_N": 3000.0},
         {"radial_load_N": 3000.0}),
        # imperial force
        ("a bracket taking a 200 lb side load", {"radial_load_N": 889.6},
         {"radial_load_N": 889.6}),
        # speed written out
        ("a pulley driven at 1750 revolutions per minute", {"speed_rpm": 1750.0},
         {"speed_rpm": 1750.0}),
        # frequency, converted
        ("a spindle running at 25 Hz", {"speed_rpm": 1500.0}, {"speed_rpm": 1500.0}),
        # the field the router branched on and nothing ever produced
        ("a manifold rated to 250 bar", {"pressure_bar": 250.0},
         {"pressure_bar": 250.0}),
        ("a valve body for 250 psi", {"pressure_bar": 17.24},
         {"pressure_bar": 17.24}),
        # life in years
        ("a bearing for five years of service", {"life_hours": 43800.0},
         {"life_hours": 43800.0}),
        # imperial torque
        ("a coupling rated 120 lbf-ft", {"torque_Nm": 162.7}, {"torque_Nm": 162.7}),
    ],
)
def test_a_duty_the_request_states_is_kept(request_text, proposed, expected):
    assert D.gate(request_text, proposed).fields == expected


def test_a_rounded_conversion_still_counts():
    """50 kg is 490.3325 N and a model will write 490.3.

    ``provenance``'s 1e-6 is right for a dimension, where the Blueprint holds
    the number the user typed. Here the model has done arithmetic, so the
    tolerance has to admit its rounding — and 1% is nowhere near enough to
    confuse two different loads.
    """
    assert D.gate("hold 50 kg", {"radial_load_N": 490.3}).fields
    assert D.gate("hold 50 kg", {"radial_load_N": 490.3325}).fields
    assert not D.gate("hold 50 kg", {"radial_load_N": 600.0}).fields


# --------------------------------------------------------------------------- #
# what nobody wrote down
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "request_text,proposed",
    [
        ("a mounting plate for a NEMA 23 stepper", {"radial_load_N": 500.0}),
        ("a bearing housing, medium duty", {"radial_load_N": 2000.0}),
        ("a bracket", {"torque_Nm": 40.0}),
        ("a housing for a 6205 bearing", {"speed_rpm": 3000.0}),
    ],
)
def test_an_invented_duty_is_refused_and_recorded(request_text, proposed):
    """The failure the router most fears: a duty that was never stated diverts
    a geometry request into questions about a load nobody mentioned."""
    result = D.gate(request_text, proposed)
    assert result.fields == {}
    assert result.rejected == proposed
    assert result.notes and "no number in the request supports it" in result.notes[0]


def test_a_length_cannot_support_a_force():
    """"a 30 mm bore housing" states 30, and 30 newtons is not among the things
    it states. Without the unit tag the numeral would corroborate anything."""
    assert D.gate("a 30 mm bore housing", {"radial_load_N": 30.0}).fields == {}
    # …but it does support the dimension it actually is.
    assert D.gate("a 30 mm bore housing", {"bore_mm": 30.0}).fields == {"bore_mm": 30.0}


def test_a_field_outside_the_schema_is_dropped():
    assert D.gate("a plate", {"colour": 7, "vibes": 3}).fields == {}


def test_a_non_numeric_or_negative_value_is_dropped():
    assert D.gate("hold 50 kg", {"radial_load_N": "quite a lot"}).fields == {}
    assert D.gate("hold 50 kg", {"radial_load_N": -490.3}).fields == {}


# --------------------------------------------------------------------------- #
# merging with the patterns
# --------------------------------------------------------------------------- #
def test_the_pattern_reading_wins_where_it_fired():
    """It matched a unit token literally present in the request, which is
    stronger evidence than an interpretation of the same sentence — and keeping
    it authoritative is what makes this change carry no regression risk."""
    duty, notes = D.merge(
        {"radial_load_N": 3000.0},
        D.Duty(fields={"radial_load_N": 2950.0}),
    )
    assert duty["radial_load_N"] == 3000.0
    assert any("Kept the first" in n for n in notes)


def test_the_model_only_fills_what_the_patterns_left_empty():
    duty, notes = D.merge(
        {"speed_rpm": 1500.0},
        D.Duty(fields={"radial_load_N": 490.3}),
    )
    assert duty == {"speed_rpm": 1500.0, "radial_load_N": 490.3}
    assert any("radial_load_N=490.3" in n for n in notes)


def test_an_agreeing_second_reading_adds_no_noise():
    duty, notes = D.merge(
        {"radial_load_N": 3000.0}, D.Duty(fields={"radial_load_N": 3000.0})
    )
    assert duty == {"radial_load_N": 3000.0}
    assert notes == []


# --------------------------------------------------------------------------- #
# the chain has to receive it
# --------------------------------------------------------------------------- #
def test_the_chain_uses_a_duty_it_could_not_have_read_itself():
    """Diverting on a reading the chain cannot reproduce would be worse than
    not diverting: it would stop and ask for the load just given."""
    from orion import reasoning as R

    text = "a bearing housing that must hold 50 kg at 1500 rpm"
    assert not R.reason(text).complete

    chain = R.reason(text, duty={"radial_load_N": 490.3, "speed_rpm": 1500.0})
    assert chain.complete
    assert chain.part_class


def test_an_empty_duty_changes_nothing():
    from orion import reasoning as R

    text = "a bearing housing carrying 3 kN radial at 1500 rpm"
    assert R.reason(text, duty={}).to_dict() == R.reason(text).to_dict()


# --------------------------------------------------------------------------- #
# the prompt is generated from the schema
# --------------------------------------------------------------------------- #
def test_every_field_is_named_in_the_prompt():
    """A model asked to guess your schema is not extracting, it is solving a
    riddle — the same finding that shaped ``interview.extract_prompt``."""
    prompt = D.extract_prompt()
    for f in D.FIELDS:
        assert f.name in prompt
        assert f.unit in prompt


def test_the_reader_reports_an_outage_rather_than_an_empty_duty():
    """An unreachable endpoint reads as "no duty stated", which would silently
    route every request to the model."""

    class _Dead:
        def chat(self, *_a, **_k):
            raise ConnectionError("endpoint refused the connection")

    result = D.read(_Dead(), "a bracket that must hold 50 kg")
    assert result.transport_error
    assert result.fields == {}
