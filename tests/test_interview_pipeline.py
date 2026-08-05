"""Interview -> Requirements -> deterministic Blueprint. No model in these tests.

The model's only job is language, and it is stubbed here: every test hands the
interview slots directly, so what is pinned is the part that must never vary —
the schema, the completeness rule, the standards lookups, and the generator.

Measured before this existed: asking a model to write the Blueprint from a
complete specification built 1 of 5. The base model failed the static check on
every complex part, and the fine-tune added features nobody requested. With the
generator in Python it is 5 of 5, verified and faithful.
"""

import pytest

from orion import blueprint_gen, interview
from orion.blueprint import Blueprint, BlueprintError


def iv(family, **slots):
    return interview.Interview(request="test", family=family, slots=slots)


# --------------------------------------------------------------------------- #
# the schema is data
# --------------------------------------------------------------------------- #
def test_the_schema_loads_and_is_versioned():
    version, families = interview.load_schema()
    assert version >= 1
    assert set(families) >= {"rect_plate", "l_bracket", "bearing_housing", "manifold"}


def test_every_family_declares_required_fields():
    for name, fam in interview.FAMILIES.items():
        assert fam.required, f"{name} has no required fields"
        for slot in fam.required + fam.optional:
            assert slot.prompt.endswith("?"), f"{name}.{slot.name} is not a question"


def test_every_family_in_the_schema_has_a_builder():
    """A family that can be asked about but not built is a dead end for a user
    who has just answered five questions."""
    assert set(interview.FAMILIES) <= set(blueprint_gen.BUILDERS)


def test_a_malformed_schema_raises_rather_than_degrading(tmp_path):
    """Silently loading no required fields would stop the interview asking
    anything at all — an invisible failure."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nfamilies: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no families"):
        interview.load_schema(str(bad))


# --------------------------------------------------------------------------- #
# completeness and refusal
# --------------------------------------------------------------------------- #
def test_a_missing_required_field_becomes_a_question():
    i = iv("rect_plate", length=100, width=60)
    assert [s.name for s in interview.missing("rect_plate", i.slots)] == ["thickness"]
    assert interview.next_question(i) == "How thick should it be?"


def test_optional_fields_are_never_asked_for():
    i = iv("rect_plate", length=100, width=60, thickness=5)
    assert interview.next_question(i) is None
    assert i.complete


def test_requirements_refuses_an_incomplete_interview():
    with pytest.raises(ValueError, match="incomplete"):
        interview.requirements(iv("rect_plate", length=100))


def test_a_later_answer_replaces_an_earlier_one():
    """Merging both is how an assistant produces a part satisfying neither."""
    i = iv("rect_plate", length=100, width=60, thickness=5)
    interview.answer(i, "thickness", 8)
    assert i.slots["thickness"] == 8


# --------------------------------------------------------------------------- #
# Python owns the conversions
# --------------------------------------------------------------------------- #
def test_diameters_become_radii():
    req = interview.resolve("rect_plate", {"bore_d": 90.0, "length": 300})
    assert req["bore_r"] == 45.0 and "bore_d" not in req
    assert req["length"] == 300


def test_a_thread_designation_is_looked_up_not_recalled():
    slots, notes = interview.apply_standards({"thread": "M8"})
    assert slots["hole_d"] == 9.0  # ISO 273 medium
    assert slots["cbore_d"] == 15.0  # ISO 7046
    assert any("ISO 273" in n for n in notes)


def test_a_stated_diameter_is_not_overridden_by_the_table():
    slots, _ = interview.apply_standards({"thread": "M8", "hole_d": 8.5})
    assert slots["hole_d"] == 8.5


def test_requirements_records_the_schema_version():
    req = interview.requirements(iv("rect_plate", length=100, width=60, thickness=5))
    assert req["schema_version"] == interview.SCHEMA_VERSION
    assert req["family"] == "rect_plate"


# --------------------------------------------------------------------------- #
# the generator
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "family,slots",
    [
        ("rect_plate", {"length": 100, "width": 60, "thickness": 5}),
        (
            "l_bracket",
            {
                "base_length": 160,
                "base_width": 100,
                "base_thickness": 12,
                "upright_height": 100,
                "upright_thickness": 12,
            },
        ),
        (
            "bearing_housing",
            {
                "length": 160,
                "width": 80,
                "height": 60,
                "bore_d": 52.0,
                "seat_depth": 15,
            },
        ),
        ("manifold", {"length": 180, "width": 90, "height": 45, "passage_d": 18}),
    ],
)
def test_every_family_generates_a_blueprint_that_freezes(family, slots):
    """The static check is the gate the model kept failing: no bare numbers, no
    unused variables, every dependency resolving."""
    bp = Blueprint.from_dict(interview.build(iv(family, **slots))).freeze()
    assert bp.blueprint_hash


def test_the_generator_adds_nothing_that_was_not_asked_for():
    """The fine-tune, given this exact specification, returned
    `l_bracket_plus_counterbore_set_vent_slot` with 26 variables."""
    payload = interview.build(
        iv(
            "l_bracket",
            base_length=160,
            base_width=100,
            base_thickness=12,
            upright_height=100,
            upright_thickness=12,
        )
    )
    assert payload["part_class"] == "l_bracket"
    assert set(payload["variables"]) == {"BL", "BW", "BT", "UH", "UT"}


def test_the_closed_form_matches_the_geometry_for_a_plain_plate():
    payload = interview.build(iv("rect_plate", length=100, width=60, thickness=5))
    bp = Blueprint.from_dict(payload).freeze()
    body = next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")
    assert body["target_value"] == pytest.approx(30000.0)


def test_a_pocket_over_a_through_hole_is_not_counted_twice():
    """Observed: a 300x220x16 plate came back 38170.35 mm3 heavier than
    predicted — exactly pi*45^2*6, the central bore under the pocket floor.
    The pocket removes nothing there; that material left with the hole."""
    payload = interview.build(
        iv(
            "rect_plate",
            length=300,
            width=220,
            thickness=16,
            bore_d=90.0,
            pocket_l=180,
            pocket_w=120,
            pocket_depth=6,
        )
    )
    bp = Blueprint.from_dict(payload).freeze()
    body = next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")

    import math

    plate = 300 * 220 * 16
    bore = math.pi * 45**2 * 16
    pocket = 180 * 120 * 6 - math.pi * 45**2 * 6  # credit the overlap back
    assert body["target_value"] == pytest.approx(plate - bore - pocket)


def test_a_hole_straddling_the_pocket_wall_is_refused_not_approximated():
    with pytest.raises(blueprint_gen.GeneratorError, match="straddles"):
        interview.build(
            iv(
                "rect_plate",
                length=300,
                width=220,
                thickness=16,
                bore_d=190.0,
                pocket_l=180,
                pocket_w=120,
                pocket_depth=6,
            )
        )


# --------------------------------------------------------------------------- #
# geometry that cannot exist is refused before a kernel runs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "family,slots,why",
    [
        (
            "rect_plate",
            {"length": 100, "width": 60, "thickness": 5, "bore_d": 200.0},
            "does not fit",
        ),
        (
            "bearing_housing",
            {
                "length": 160,
                "width": 80,
                "height": 60,
                "bore_d": 52.0,
                "seat_depth": 70,
            },
            "less than height",
        ),
        (
            "bearing_housing",
            {
                "length": 160,
                "width": 40,
                "height": 60,
                "bore_d": 52.0,
                "seat_depth": 15,
            },
            "does not fit",
        ),
        (
            "l_bracket",
            {
                "base_length": 10,
                "base_width": 100,
                "base_thickness": 12,
                "upright_height": 100,
                "upright_thickness": 12,
            },
            "exceeds the base length",
        ),
        (
            "manifold",
            {"length": 180, "width": 90, "height": 45, "passage_d": 100.0},
            "does not fit",
        ),
        (
            "rect_plate",
            {
                "length": 100,
                "width": 60,
                "thickness": 5,
                "pocket_l": 80,
                "pocket_w": 40,
                "pocket_depth": 9,
            },
            "less than thickness",
        ),
    ],
)
def test_impossible_geometry_is_refused(family, slots, why):
    with pytest.raises(blueprint_gen.GeneratorError, match=why):
        interview.build(iv(family, **slots))


def test_a_negative_dimension_is_refused():
    with pytest.raises(blueprint_gen.GeneratorError, match="must be positive"):
        interview.build(iv("rect_plate", length=100, width=-60, thickness=5))


def test_an_unknown_family_names_what_is_available():
    with pytest.raises(blueprint_gen.GeneratorError, match="no deterministic builder"):
        blueprint_gen.generate("impeller", {"length": 1})


# --------------------------------------------------------------------------- #
# the corpus path is untouched
# --------------------------------------------------------------------------- #
def test_generation_is_deterministic():
    """Same requirements, same Blueprint, same hash — every time.

    A generator that varied would make the contract meaningless: two users
    asking for the same part would get two different frozen claims about it.
    """
    slots = dict(length=100, width=60, thickness=5)
    first = Blueprint.from_dict(interview.build(iv("rect_plate", **slots)))
    second = Blueprint.from_dict(interview.build(iv("rect_plate", **slots)))
    assert first.freeze().blueprint_hash == second.freeze().blueprint_hash


def test_changing_a_dimension_changes_the_contract():
    """The hash covers the numbers, so a different plate cannot present the
    same frozen claim."""
    a = Blueprint.from_dict(
        interview.build(iv("rect_plate", length=100, width=60, thickness=5))
    ).freeze()
    b = Blueprint.from_dict(
        interview.build(iv("rect_plate", length=101, width=60, thickness=5))
    ).freeze()
    assert a.blueprint_hash != b.blueprint_hash


def test_the_generated_blueprint_passes_the_same_static_check_as_an_authored_one():
    """No special path. What the generator emits is checked by the checker that
    graded the 42k corpus — which is why a generator bug surfaces as a refused
    freeze rather than as wrong geometry."""
    payload = interview.build(iv("rect_plate", length=100, width=60, thickness=5))
    payload["variables"]["unused_extra"] = 12.0
    with pytest.raises(BlueprintError, match="unused variable"):
        Blueprint.from_dict(payload).freeze()
