"""Plates, and the standards between their holes.

The case these tests exist for is the mounting plate that came back as a Ø120
disc with four Ø4 holes at sampled coordinates. Every assertion below is a thing
that was wrong about it: the width was ignored, the clearance hole was invented,
and the pattern was not placed.
"""

from __future__ import annotations

import pytest

from orion import prismatic as P

PLATE = (
    "A 120 x 80 x 12 mm aluminium mounting plate with a 30 mm central bore "
    "and four M6 clearance holes on a 100 x 60 mm rectangular pattern."
)


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def test_the_pattern_pitch_is_not_mistaken_for_the_plate_size():
    """Two dimension pairs in one sentence; only one of them is the plate.

    Matched by the noun that follows rather than by position — "100 x 60
    pattern" is a pitch wherever it appears in the sentence.
    """
    i = P.read_plate(PLATE)
    assert (i.length_mm, i.width_mm, i.thickness_mm) == (120.0, 80.0, 12.0)
    assert (i.pattern_x_mm, i.pattern_y_mm) == (100.0, 60.0)


def test_the_bore_and_the_thread_are_read():
    i = P.read_plate(PLATE)
    assert i.bore_dia_mm == 30.0
    assert i.thread_mm == 6.0
    assert i.hole_count == 4
    assert i.material == "aluminium"


def test_nothing_is_invented_when_nothing_is_stated():
    i = P.read_plate("A plate")
    assert i.length_mm is None and i.thickness_mm is None
    assert i.thread_mm is None


# --------------------------------------------------------------------------- #
# coverage — the router depends on this being conservative
# --------------------------------------------------------------------------- #
def test_a_named_and_sized_plate_is_claimed():
    ok, why = P.applies(PLATE)
    assert ok and "120 x 80 x 12" in why


@pytest.mark.parametrize(
    "request_text",
    [
        "A bracket",  # named, unsized
        "120 x 80 x 12",  # sized, unnamed
        "Support a rotating shaft carrying 3 kN",
        "A 50 mm cube",
        "",
    ],
)
def test_anything_short_of_both_signals_is_declined(request_text):
    """Claiming a request that is not ours costs the user a refusal they
    cannot act on. Both signals are required."""
    ok, _ = P.applies(request_text)
    assert not ok


# --------------------------------------------------------------------------- #
# specification
# --------------------------------------------------------------------------- #
def test_the_plate_that_started_this_now_specifies_correctly():
    spec = P.specify(PLATE)
    assert spec.complete, spec.asks()
    v = spec.variables

    assert v["pl"] == 120 and v["pw"] == 80 and v["pt"] == 12
    # The width reaches the specification. It was declared and then ignored.
    assert v["pw"] == 80

    # ISO 273 medium: M6 -> 6.6 mm, not the 4 mm the model produced.
    assert v["hr"] == pytest.approx(3.3)

    # 100 x 60 means +/-50 and +/-30. Placed, not sampled.
    assert v["mx"] == 50 and v["my"] == 30

    assert v["pb_r"] == 15  # 30 mm bore

    assert any("ISO 273" in c for c in spec.citations)

    # 120x80 with a 100x60 pattern leaves 6.7 mm to the edge against a 9.0 mm
    # convention. Reported, not refused — the request is buildable and the user
    # is told exactly how tight it is.
    assert any("hole to edge" in w for w in spec.warnings)


def test_every_number_names_where_it_came_from():
    spec = P.specify(PLATE)
    assert "ISO 273" in spec.rationale["hr"]
    assert "stated" in spec.rationale["pl"]


def test_material_is_recorded_but_never_claimed_as_verified():
    spec = P.specify(PLATE)
    assert any("aluminium" in w and "not verified" in w for w in spec.warnings)
    assert not any(k.startswith("mat") for k in spec.variables)


def test_the_model_is_handed_dimensions_not_prose():
    spec = P.specify(PLATE)
    handed = P.design_prompt(spec)
    assert handed.startswith("Build a mount_plate with ")
    assert "hr=3.3" in handed and "mx=50" in handed
    # The reasoning is the user's; feeding it back re-opens settled arithmetic.
    assert "ISO" not in handed and "because" not in handed.lower()


# --------------------------------------------------------------------------- #
# refusals — the load-bearing half
# --------------------------------------------------------------------------- #
def test_a_tight_edge_distance_is_reported_but_still_built():
    """A convention is not a standard, and refusing on one rejects the drawing
    already on the user's desk. The arithmetic is reported; the part is built."""
    spec = P.specify("A 100 x 60 x 10 mm plate with four M8 holes on a 84 x 44 pattern")
    assert spec.complete
    note = " ".join(spec.warnings)
    assert "hole to edge" in note and "1.5d" in note
    # Says what would clear it, and admits what kind of rule it is.
    assert "would clear it" in note and "not a standard" in note


def test_holes_that_fall_off_the_plate_are_refused():
    """Not tight — impossible. There is no part to build."""
    spec = P.specify("A 100 x 60 x 10 mm plate with four M8 holes on a 98 x 58 pattern")
    assert not spec.complete
    assert any("outside the plate" in q for q in spec.asks())


def test_holes_that_open_into_the_central_bore_are_refused():
    """Two features become one opening, so the part is not the one described."""
    spec = P.specify(
        "A 120 x 80 x 12 mm plate with a 70 mm central bore and four M6 "
        "holes on a 40 x 20 pattern"
    )
    assert not spec.complete
    assert any("open into the central bore" in q for q in spec.asks())


def test_an_untabulated_thread_is_refused_rather_than_interpolated():
    spec = P.specify(
        "A 120 x 80 x 12 mm plate with four M7 holes on a 100 x 60 pattern"
    )
    assert not spec.complete
    assert any("ISO 273" in q and "M7" in q for q in spec.asks())


def test_a_pattern_without_a_thread_size_asks_rather_than_guesses():
    spec = P.specify("A 120 x 80 x 12 mm plate with four holes on a 100 x 60 pattern")
    assert not spec.complete
    assert any("ISO 273" in q for q in spec.asks())


def test_a_feature_it_cannot_build_is_refused_by_name_not_dropped():
    """Silently ignoring a slot returns a part missing something the user
    asked for, with nothing in the output to say so."""
    spec = P.specify(
        "A 120 x 80 x 12 mm plate with two 20 x 6 mm slots and four M6 holes "
        "on a 100 x 60 pattern"
    )
    assert not spec.complete
    assert any("slots" in q for q in spec.asks())


def test_a_bore_wider_than_the_plate_is_refused():
    spec = P.specify("A 120 x 80 x 12 mm plate with a 90 mm central bore")
    assert not spec.complete
    assert any("wider than the plate" in q for q in spec.asks())


def test_a_plain_plate_with_no_holes_still_specifies():
    spec = P.specify("A 120 x 80 x 12 mm mounting plate")
    assert spec.complete
    assert spec.variables == {"pl": 120, "pw": 80, "pt": 12}
