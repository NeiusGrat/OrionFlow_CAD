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


def test_the_bracket_motor_interface_is_exact():
    """Bore and bolt holes are cut in the upright's own profile.

    Every attempt to machine them with a Pocket removed either nothing or a
    sliver, while the build reported success each time — the frames are not
    what you would guess (an XZ pad grows in -Y, a YZ pad in -X, and on YZ the
    builder's x runs along world Z).
    """
    import math

    payload = interview.build(
        iv(
            "l_bracket",
            base_length=160,
            base_width=100,
            base_thickness=12,
            upright_height=100,
            upright_thickness=12,
            bore_d=47.14,
            hole_d=5.5,
            bolt_square=69.6,
        )
    )
    bp = Blueprint.from_dict(payload).freeze()
    body = next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")

    envelope = 160 * 100 * 12 + 100 * 100 * 12 - 12 * 100 * 12
    cuts = (math.pi * 23.57**2 + 4 * math.pi * 2.75**2) * 12
    assert body["target_value"] == pytest.approx(envelope - cuts)


def test_counterbores_are_a_thickness_split_not_a_cut():
    """A counterbored plate is two slabs: a thin one at the face carrying the
    large holes and the rest carrying the small ones.

    Built as a blind Pocket it removed 56.65 mm3 against an expected 797.18 —
    and that 56.65 was not counterbore at all, it was the two lower circles
    clipping the top edge of the base plate. Stacked pads with holes in-profile
    are exact and have no direction to get wrong.
    """
    import math

    tall = dict(
        base_length=160,
        base_width=100,
        base_thickness=12,
        upright_height=140,
        upright_thickness=12,
        bore_d=47.14,
        hole_d=5.5,
        bolt_square=69.6,
    )
    plain = Blueprint.from_dict(interview.build(iv("l_bracket", **tall))).freeze()
    bored = Blueprint.from_dict(
        interview.build(iv("l_bracket", **tall, cbore_d=9.0, cbore_depth=5))
    ).freeze()

    def body(bp):
        return next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")[
            "target_value"
        ]

    annulus = 4 * math.pi * (4.5**2 - 2.75**2) * 5
    assert body(plain) - body(bored) == pytest.approx(annulus)


def test_corner_slots_are_exact():
    """A stadium is a rectangle between two semicircular caps, so its area is
    exact — but it is not a circle, so it cannot ride in the pad profile the
    way the bores do and needs its own through cut."""
    import math

    plate = dict(length=300, width=220, thickness=16)
    plain = Blueprint.from_dict(interview.build(iv("rect_plate", **plate))).freeze()
    slotted = Blueprint.from_dict(
        interview.build(
            iv("rect_plate", **plate, slot_length=40, slot_width=14, slot_edge_gap=20)
        )
    ).freeze()

    def body(bp):
        return next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")[
            "target_value"
        ]

    # Four stadiums, 40 overall by 14 wide, through 16.
    expected = 4 * ((40 - 14) * 14 + math.pi * 7**2) * 16
    assert body(plain) - body(slotted) == pytest.approx(expected)


def test_a_slot_without_a_position_is_refused():
    """'near each corner' does not fix a position."""
    with pytest.raises(blueprint_gen.GeneratorError, match="distance from the plate"):
        interview.build(
            iv(
                "rect_plate",
                length=300,
                width=220,
                thickness=16,
                slot_length=40,
                slot_width=14,
            )
        )


def test_a_slot_that_is_not_elongated_is_refused():
    with pytest.raises(blueprint_gen.GeneratorError, match="not elongated"):
        interview.build(
            iv(
                "rect_plate",
                length=300,
                width=220,
                thickness=16,
                slot_length=14,
                slot_width=14,
                slot_edge_gap=20,
            )
        )


def test_the_perimeter_chamfer_corner_correction():
    """Two prisms overlap at each corner and the sum counts it twice.

    The overlap is not a pyramid: with w down from the face and u, v in from
    the walls, both prisms hold over the integral of (c-w)^2, which is c^3/3.
    Taking it for c^3/6 predicted 9324 mm3 on this plate where the kernel
    removes 9288 — high by exactly 4*c^3/3.
    """
    plate = dict(length=300, width=220, thickness=16)
    plain = Blueprint.from_dict(interview.build(iv("rect_plate", **plate))).freeze()
    chamfered = Blueprint.from_dict(
        interview.build(iv("rect_plate", **plate, chamfer=3))
    ).freeze()

    def body(bp):
        return next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")[
            "target_value"
        ]

    c = 3
    assert body(plain) - body(chamfered) == pytest.approx(
        2 * ((300 + 220) * c**2 - 4 * c**3 / 3)
    )


@pytest.mark.parametrize(
    "extra",
    [
        dict(pocket_l=180, pocket_w=120, pocket_depth=6),
        dict(slot_length=40, slot_width=14, slot_edge_gap=20),
    ],
)
def test_a_chamfer_that_cannot_be_named_separately_is_refused(extra):
    """A pocket and a slot carry straight horizontal edges of their own; the
    selector would take them too and a chamfered slot flank has no closed form
    here. Refused rather than applied to the wrong edges."""
    with pytest.raises(
        blueprint_gen.GeneratorError, match="cannot be named separately"
    ):
        interview.build(
            iv("rect_plate", length=300, width=220, thickness=16, chamfer=3, **extra)
        )


def test_an_external_fillet_on_a_plate_is_a_corner_radius():
    """The same feature under two names. Accepting both would let a design
    declare two different radii for one corner."""
    with pytest.raises(blueprint_gen.GeneratorError, match="is a corner radius"):
        interview.build(iv("rect_plate", length=300, width=220, thickness=16, fillet=8))
    with pytest.raises(blueprint_gen.GeneratorError, match="give one"):
        interview.build(
            iv(
                "rect_plate",
                length=300,
                width=220,
                thickness=16,
                fillet=8,
                corner_radius=8,
            )
        )


def test_a_counterbore_that_would_break_into_the_base_is_refused():
    """The servo bracket as specified: bolt square 69.6 on a 100 tall upright
    puts the lower counterbores at z=10.7, under a 12 mm base plate. The void
    and the base would overlap and the volume has no closed form."""
    with pytest.raises(blueprint_gen.GeneratorError, match="break into it"):
        interview.build(
            iv(
                "l_bracket",
                base_length=160,
                base_width=100,
                base_thickness=12,
                upright_height=100,
                upright_thickness=12,
                bore_d=47.14,
                hole_d=5.5,
                bolt_square=69.6,
                cbore_d=9.0,
                cbore_depth=5,
            )
        )


@pytest.mark.parametrize(
    "slots,why",
    [
        # A counterbore with no hole to counterbore.
        (dict(cbore_d=9.0, cbore_depth=5), "needs the hole it counterbores"),
        # Deeper than the plate it is cut into.
        (
            dict(hole_d=5.5, bolt_square=69.6, cbore_d=9.0, cbore_depth=20),
            "must be less than",
        ),
        # No larger than the hole, so it is not a counterbore at all.
        (
            dict(hole_d=5.5, bolt_square=69.6, cbore_d=5.5, cbore_depth=5),
            "must exceed",
        ),
        # Wider than the plate it is drilled in.
        (dict(bore_d=120.0), "does not fit the upright"),
        # Fits the plate, but reaches down into the base: the cylinders are no
        # longer disjoint and the closed form would overstate what was removed.
        (dict(bore_d=80.0), "runs into the base"),
        # Bolt circle wider than the plate. Needs a tall upright, or the
        # runs-into-the-base guard catches it first — which it should.
        (
            dict(upright_height=200, hole_d=5.5, bolt_square=96.0),
            "wider than the upright",
        ),
        # Bolt holes breaking into the pilot bore.
        (dict(bore_d=60.0, hole_d=5.5, bolt_square=62.0), "overlap the pilot bore"),
    ],
)
def test_an_unbuildable_motor_interface_is_refused(slots, why):
    base = dict(
        base_length=160,
        base_width=100,
        base_thickness=12,
        upright_height=100,
        upright_thickness=12,
    )
    base.update(slots)
    with pytest.raises(blueprint_gen.GeneratorError, match=why):
        interview.build(iv("l_bracket", **base))


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
