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
    assert any("ISO 273" in n for n in notes)


def test_naming_a_thread_does_not_invent_a_counterbore():
    """A thread implies a clearance hole. A counterbore is a design choice.

    This asserted the opposite, and the opposite was a bug: "L bracket ... M8
    holes" acquired an ISO 7046 counterbore nobody asked for, and since
    ``cbore_d`` requires ``cbore_depth`` the interview then refused to build
    until the user answered "Counterbore depth?" about a feature they had never
    mentioned. A standards lookup must not create work.
    """
    slots, _ = interview.apply_standards({"thread": "M8"})
    assert "cbore_d" not in slots


def test_a_counterbore_that_was_asked_for_is_still_dimensioned_by_the_standard():
    slots, notes = interview.apply_standards({"thread": "M8", "cbore_depth": 9.0})
    assert slots["cbore_d"] == 15.0  # ISO 7046
    assert any("ISO 7046" in n for n in notes)


def test_a_stated_diameter_is_not_overridden_by_the_table():
    slots, _ = interview.apply_standards({"thread": "M8", "hole_d": 8.5})
    assert slots["hole_d"] == 8.5


# --------------------------------------------------------------------------- #
# reading the request: a reasoning model, and a dead one
# --------------------------------------------------------------------------- #
class _Budgeted:
    """A model that answers only when given room to think first.

    K2-Think-v2 spends the budget deriving and emits the JSON last: measured
    ~2,460 completion tokens to extract six fields, against a 2,048 default. It
    returns an empty string, which is indistinguishable from a model that read
    the request and found nothing — so a fully dimensioned plate came back with
    no slots at all and the user was asked for the numbers they had just given.
    """

    model = "reasoner"

    def __init__(self, needs: int, replies: list[str]):
        self._needs = needs
        self._replies = replies
        self.budgets: list[int] = []

    def chat(self, messages, max_tokens=None, **kw):
        self.budgets.append(max_tokens)
        body = "" if (max_tokens or 0) < self._needs else self._replies.pop(0)
        return type(
            "R",
            (),
            {
                "content": body,
                "thinking": "...",
                "tool_calls": [],
                "finish_reason": "length" if not body else "stop",
                "usage": {},
            },
        )()


def test_a_reasoning_model_that_needs_room_is_given_it():
    client = _Budgeted(
        needs=4096,
        replies=['{"family": "rect_plate"}',
                 '{"length": 100, "width": 60, "thickness": 5}'],
    )

    got = interview.read_request(client, "plate 100 x 60 x 5", max_tokens=2048)

    assert got.family == "rect_plate"
    assert got.slots == {"length": 100, "width": 60, "thickness": 5}
    assert got.complete
    # Small ask first, so a model that answers directly never pays for the big one.
    assert client.budgets[0] == 2048
    assert interview.REASONING_TOKENS in client.budgets


class _Unreachable:
    model = "gone"

    def chat(self, messages, **kw):
        return type(
            "R",
            (),
            {
                "content": "[transport error: connection refused]",
                "thinking": "",
                "tool_calls": [],
                "finish_reason": "error",
                "usage": {},
            },
        )()


def test_an_outage_is_reported_as_an_outage_not_as_an_unknown_part():
    """An empty family means two different things and the caller must be able
    to tell them apart: "nothing here builds springs" is about the request,
    "the endpoint is down" is about us, and only the second should be retried
    against another provider."""
    got = interview.read_request(_Unreachable(), "plate 100 x 60 x 5")

    assert got.family == ""
    assert got.transport_error
    assert not got.complete


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
    # UW is the upright's own width, declared even when it equals the base's so
    # the expression reads the same either way.
    assert set(payload["variables"]) == {"BL", "BW", "BT", "UH", "UT", "UW"}
    assert payload["variables"]["UW"] == payload["variables"]["BW"]


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


def test_a_slot_without_a_position_becomes_a_question():
    """'near each corner' does not fix a position, and the right place to
    discover that is the interview, not the generator.

    ``slot_edge_gap`` is optional until slots are asked for; the schema's
    ``requires`` makes it required the moment ``slot_length`` appears. Before
    that the interview declared itself complete and the generator refused after
    the fact — the wrong end of the pipeline for a question.
    """
    i = iv(
        "rect_plate",
        length=300,
        width=220,
        thickness=16,
        slot_length=40,
        slot_width=14,
    )
    assert [s.name for s in interview.missing("rect_plate", i.slots)] == [
        "slot_edge_gap"
    ]
    assert interview.next_question(i) == "How far are the slots from the plate edge?"
    with pytest.raises(ValueError, match="incomplete"):
        interview.build(i)


def test_a_conditional_requirement_is_silent_until_its_trigger_appears():
    """A plate with no slots is not interrogated about slot positions."""
    i = iv("rect_plate", length=300, width=220, thickness=16)
    assert interview.next_question(i) is None
    assert i.complete


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


TIER2 = [
    # A chamfer whose selector also takes the straight edges of a pocket or a
    # slot: more is chamfered than any closed form describes.
    (
        "rect_plate",
        dict(
            length=300,
            width=220,
            thickness=16,
            chamfer=3,
            pocket_l=180,
            pocket_w=120,
            pocket_depth=6,
        ),
        "pocket",
    ),
    (
        "rect_plate",
        dict(
            length=300,
            width=220,
            thickness=16,
            chamfer=3,
            slot_length=40,
            slot_width=14,
            slot_edge_gap=20,
        ),
        "slot",
    ),
    # Bolt holes crossing the pocket wall share a region bounded by a circle
    # and a straight edge.
    (
        "rect_plate",
        dict(
            length=300,
            width=220,
            thickness=16,
            bore_d=90,
            hole_count=8,
            hole_d=11,
            pcd=160,
            pocket_l=180,
            pocket_w=120,
            pocket_depth=6,
        ),
        "cross the pocket wall",
    ),
    # An external fillet: each rounded corner is exact, the corner count is not.
    ("rect_plate", dict(length=300, width=220, thickness=16, fillet=8), "fillet"),
    # The servo bracket as specified — counterbores clipped by the base plate.
    (
        "l_bracket",
        dict(
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
        ),
        "circular segment",
    ),
    # Ports breaking into the passage: two perpendicular cylinders.
    (
        "manifold",
        dict(length=180, width=90, height=45, passage_d=18, port_count=6, port_d=13.2),
        "perpendicular cylinders",
    ),
]


@pytest.mark.parametrize("family,slots,reason", TIER2, ids=[t[2] for t in TIER2])
def test_geometry_without_a_closed_form_drops_a_tier_rather_than_being_refused(
    family, slots, reason
):
    """The part is right; only the prediction cannot be written.

    Tier 1 is a closed form checked at 1e-6. Where the geometry admits none —
    two perpendicular cylinders need elliptic integrals, a counterbore clipped
    by a base plate leaves a segment whose analytic area was 0.32 mm3 out — the
    volume claim becomes `body_mesh_converged`, which proves the tessellation
    converges to OCC's own volume without claiming it matches a prediction.
    Refusing these would reject buildable parts; inventing a nearly-right
    closed form is what this module exists to prevent.
    """
    payload = interview.build(iv(family, **slots))
    body = next(a for a in payload["assertions"] if a["id"] == "body")

    assert body["kind"] == "body_mesh_converged"
    assert body["tier"] == 2
    assert "target" not in body, "a mesh claim must not also assert a value"
    why = " ".join(payload["design_plan"]["no_closed_form"])
    assert reason in why, f"the reason should name {reason!r}: {why}"

    # The extents stay exact whatever happens to the volume.
    assert any(
        a["kind"] == "bbox_extent" and a["tier"] == 1 for a in payload["assertions"]
    )


def test_a_plain_part_keeps_the_stronger_claim():
    """Dropping a tier must be the exception, not a general loosening."""
    payload = interview.build(iv("rect_plate", length=300, width=220, thickness=16))
    body = next(a for a in payload["assertions"] if a["id"] == "body")
    assert body["kind"] == "body_volume" and body["tier"] == 1
    assert "no_closed_form" not in payload["design_plan"]


def test_a_corner_radius_and_an_external_fillet_are_not_both_accepted():
    """One rounds the outline in the sketch where the area is exact; the other
    rounds the same edges afterwards where it is not."""
    with pytest.raises(blueprint_gen.GeneratorError, match="Give one"):
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


# --------------------------------------------------------------------------- #
# bearing housing and manifold: nothing extracted is silently ignored
# --------------------------------------------------------------------------- #
HOUSING = dict(length=160, width=80, height=60, bore_d=52.0, seat_depth=15)
MANIFOLD = dict(length=180, width=90, height=45, passage_d=18)


def _body(payload):
    bp = Blueprint.from_dict(payload).freeze()
    return next(a for a in bp.resolve_assertions() if a["kind"] == "body_volume")[
        "target_value"
    ]


def test_a_shoulder_defines_the_bore_beneath_the_seat():
    """A shoulder is the step the bearing seats against, so it fixes the bore
    below it at seat_r - shoulder. Arithmetic, not a guess."""
    import math

    plain = _body(interview.build(iv("bearing_housing", **HOUSING)))
    stepped = _body(interview.build(iv("bearing_housing", **HOUSING, shoulder=4)))

    shaft_r = 26.0 - 4.0
    # The shaft bore runs right through; the seat then only takes the ring.
    expected = math.pi * shaft_r**2 * 60 + math.pi * (26.0**2 - shaft_r**2) * 15
    assert 160 * 80 * 60 - stepped == pytest.approx(expected)
    assert stepped < plain


def test_a_flange_recess_adds_only_the_ring_outside_the_seat():
    import math

    without = _body(interview.build(iv("bearing_housing", **HOUSING)))
    with_recess = _body(
        interview.build(iv("bearing_housing", **HOUSING, recess_d=62.0, recess_depth=4))
    )
    assert without - with_recess == pytest.approx(math.pi * (31.0**2 - 26.0**2) * 4)


def test_manifold_mounting_holes_and_counterbores_are_exact():
    import math

    plain = _body(interview.build(iv("manifold", **MANIFOLD)))
    holed = _body(
        interview.build(iv("manifold", **MANIFOLD, hole_d=9.0, hole_edge_gap=12))
    )
    bored = _body(
        interview.build(
            iv(
                "manifold",
                **MANIFOLD,
                hole_d=9.0,
                hole_edge_gap=12,
                cbore_d=14.0,
                cbore_depth=8,
            )
        )
    )
    assert plain - holed == pytest.approx(4 * math.pi * 4.5**2 * 45)
    assert holed - bored == pytest.approx(4 * math.pi * (7.0**2 - 4.5**2) * 8)


@pytest.mark.parametrize(
    "family,base,slots,why",
    [
        ("bearing_housing", HOUSING, dict(shoulder=30), "leaves no bore"),
        (
            "bearing_housing",
            HOUSING,
            dict(recess_d=40.0, recess_depth=4),
            "no wider than",
        ),
        (
            "bearing_housing",
            HOUSING,
            dict(hole_d=11, hole_pitch_x=40, hole_pitch_y=30),
            "run into the bearing seat",
        ),
        (
            "manifold",
            MANIFOLD,
            dict(hole_d=9.0, hole_edge_gap=40),
            "run into the main passage",
        ),
    ],
)
def test_an_impossible_optional_feature_is_refused(family, base, slots, why):
    with pytest.raises(blueprint_gen.GeneratorError, match=why):
        interview.build(iv(family, **base, **slots))


# --------------------------------------------------------------------------- #
# nothing extracted is silently ignored — structurally, not by diligence
# --------------------------------------------------------------------------- #
FULL = {
    "rect_plate": dict(
        length=300, width=220, thickness=16, corner_radius=8, material="steel"
    ),
    "l_bracket": dict(
        base_length=160,
        base_width=100,
        base_thickness=12,
        upright_height=140,
        upright_thickness=12,
        upright_width=100,
        inside_fillet=10,
        slot_length=20,
        slot_width=11,
        slot_count=4,
        slot_edge_gap=20,
        bore_d=47.14,
        hole_d=5.5,
        bolt_square=69.6,
        material="6061-T6",
    ),
    "bearing_housing": dict(
        length=160,
        width=80,
        height=60,
        bore_d=52.0,
        seat_depth=15,
        shoulder=4,
        recess_d=62.0,
        recess_depth=4,
        hole_d=11,
        hole_pitch_x=120,
        hole_pitch_y=60,
        chamfer=3,
        bearing_series="6205",
        mounting_type="foot_mount",
    ),
    "manifold": dict(
        length=180,
        width=90,
        height=45,
        passage_d=18,
        hole_d=9.0,
        hole_edge_gap=12,
        cbore_d=14.0,
        cbore_depth=8,
        chamfer=4,
        material="aluminium",
    ),
}


@pytest.mark.parametrize("family", sorted(FULL))
def test_a_fully_specified_part_consumes_every_parameter(family):
    """Every geometric field builds; nothing is quietly dropped."""
    bp = Blueprint.from_dict(interview.build(iv(family, **FULL[family]))).freeze()
    assert bp.blueprint_hash


def test_a_parameter_the_builder_never_reads_is_reported():
    """The guarantee is structural, not per-field diligence.

    A builder that forgets to read `slot_length` looks exactly like a plate
    with no slots, so the requirements dict records which keys were read and
    anything untouched is named. This is what makes the promise survive a
    family written later.
    """
    with pytest.raises(blueprint_gen.GeneratorError, match="unheard_of_flange"):
        blueprint_gen.generate(
            "rect_plate",
            {"length": 100, "width": 60, "thickness": 5, "unheard_of_flange": 3},
        )


def test_informational_values_are_recorded_rather_than_consumed():
    """A material shapes nothing but must not vanish — the engineering checks
    read it, and a user who stated it should see it on the part."""
    payload = interview.build(iv("bearing_housing", **FULL["bearing_housing"]))
    assert payload["design_plan"]["stated"]["bearing_series"] == "6205"


def test_the_gusset_fillet_adds_material():
    """The one feature here that grows the part: the concave corner is filled
    by a square of r^2 less the quarter disc it rounds away."""
    import math

    base = dict(
        base_length=160,
        base_width=100,
        base_thickness=12,
        upright_height=140,
        upright_thickness=12,
    )
    plain = _body(interview.build(iv("l_bracket", **base)))
    gusseted = _body(interview.build(iv("l_bracket", **base, inside_fillet=10)))
    assert gusseted - plain == pytest.approx((1 - math.pi / 4) * 100 * 100)


@pytest.mark.parametrize(
    "family,base,slots,why",
    [
        (
            "l_bracket",
            dict(
                base_length=160,
                base_width=100,
                base_thickness=12,
                upright_height=140,
                upright_thickness=12,
            ),
            dict(inside_fillet=200),
            "taller than",
        ),
    ],
)
def test_a_feature_the_shape_cannot_carry_is_refused(family, base, slots, why):
    with pytest.raises(blueprint_gen.GeneratorError, match=why):
        interview.build(iv(family, **base, **slots))


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


# --------------------------------------------------------------------------- #
# mounting holes need a placement
#
# "Mounting plate 120 x 80 x 6 mm with four M5 clearance holes, one 10 mm from
# each corner" built a plate with NO CYLINDRICAL FACES AT ALL and the only
# thing that noticed was the feature-fulfillment check. The count and the
# diameter were read; the corner inset had no slot, so no placement reached the
# builder, and ``rect_plate`` placed holes only when a bolt circle radius was
# present. Six of the fifty benchmark prompts failed this way.
# --------------------------------------------------------------------------- #
def test_a_hole_pattern_without_a_placement_is_a_question():
    """A count and a size do not say where the holes go."""
    gaps = [s.name for s in interview.missing(
        "rect_plate",
        {"length": 120, "width": 80, "thickness": 6,
         "hole_count": 4, "hole_d": 5},
    )]
    assert "hole_edge_gap" in gaps, (
        "a hole pattern with no placement must be asked about, not built empty"
    )


def test_either_placement_completes_a_hole_pattern():
    """A bolt circle and a corner inset are alternatives, not both required."""
    base = {"length": 120, "width": 80, "thickness": 6,
            "hole_count": 4, "hole_d": 5}
    assert not interview.missing("rect_plate", {**base, "pcd": 60})
    assert not interview.missing("rect_plate", {**base, "hole_edge_gap": 10})


def test_corner_holes_reach_the_geometry():
    """The holes are in the profile, at the stated inset from each corner."""
    from orion import blueprint_gen

    iv = interview.Interview(request="plate", family="rect_plate")
    iv.slots = {"length": 120, "width": 80, "thickness": 6,
                "hole_count": 4, "hole_d": 5.5, "hole_edge_gap": 10}
    iv.classify()
    payload = blueprint_gen.generate("rect_plate", interview.requirements(iv))

    holes = payload["template"]["sketches"][0]["profile"]["args"]["holes"]
    assert len(holes) == 4, "four corners, four holes"
    assert payload["variables"]["gap"] == 10
    assert payload["variables"]["hole_r"] == 2.75

    # And the obligation says where they are, so a later drop is catchable.
    placement = payload["design_plan"]["obligations"][0]["placement"]
    assert placement["form"] == "corners"
    assert placement["span"] == [100.0, 60.0]


def test_a_corner_pattern_that_cannot_fit_is_refused():
    """Not silently moved inward — the number is wrong and says so."""
    from orion import blueprint_gen

    iv = interview.Interview(request="plate", family="rect_plate")
    iv.slots = {"length": 40, "width": 40, "thickness": 5,
                "hole_count": 4, "hole_d": 6, "hole_edge_gap": 19}
    iv.classify()
    with pytest.raises(blueprint_gen.GeneratorError):
        blueprint_gen.generate("rect_plate", interview.requirements(iv))


# --------------------------------------------------------------------------- #
# one plate, one thickness
#
# "L bracket: 60 x 40 mm base and a 60 x 50 mm vertical wall, 4 mm thick" was
# answered with "How thick is the base plate? How thick is the vertical plate?"
# — two questions about a sentence that ends by answering them. A bracket cut
# from one plate has one thickness, and that is a fact about the family, so it
# belongs in the schema rather than in the model's reading.
# --------------------------------------------------------------------------- #
def test_one_stated_thickness_completes_a_bracket():
    assert not interview.missing("l_bracket", {
        "base_length": 60, "base_width": 40, "base_thickness": 4,
        "upright_height": 50})


def test_a_mirrored_slot_is_not_a_second_question():
    """With no thickness at all, the user is asked once, not twice."""
    gaps = [s.name for s in interview.missing("l_bracket", {
        "base_length": 60, "base_width": 40, "upright_height": 50})]
    assert gaps == ["base_thickness"]


def test_an_explicit_value_beats_the_mirror():
    """A bracket with a thicker upright is a real part and must survive."""
    filled = interview.apply_mirrors("l_bracket", {
        "base_thickness": 4, "upright_thickness": 8})
    assert filled["upright_thickness"] == 8


def test_a_mirrored_thickness_is_derived_not_stated():
    """Nobody typed it. The ledger has to say so."""
    from orion import provenance as P

    iv = interview.Interview(request="L bracket 60 x 40 base, 50 tall, 4 mm thick",
                             family="l_bracket")
    iv.slots = {"base_length": 60, "base_width": 40, "base_thickness": 4,
                "upright_height": 50}
    iv.classify()
    req = interview.requirements(iv)

    assert req["upright_thickness"] == 4
    assert req["provenance"]["upright_thickness"]["source"] == P.DERIVED
    assert "base_thickness" in req["provenance"]["upright_thickness"]["detail"]


def test_a_grid_of_holes_is_a_third_placement():
    """Nine holes at 30 mm could be 3x3 or 9x1, so the counts are asked for."""
    base = {"length": 100, "width": 100, "thickness": 3,
            "hole_count": 9, "hole_d": 6}
    gaps = [s.name for s in interview.missing("rect_plate",
                                              {**base, "hole_pitch": 30})]
    assert "hole_cols" in gaps and "hole_rows" in gaps
    assert not interview.missing("rect_plate", {
        **base, "hole_pitch": 30, "hole_cols": 3, "hole_rows": 3})


def test_grid_holes_are_parametric_in_the_pitch():
    """Baked-in constants stop being a grid the moment the spacing is edited."""
    from orion import blueprint_gen

    iv = interview.Interview(request="grid plate", family="rect_plate")
    iv.slots = {"length": 100, "width": 100, "thickness": 3, "hole_count": 9,
                "hole_d": 6, "hole_pitch": 30, "hole_cols": 3, "hole_rows": 3}
    iv.classify()
    payload = blueprint_gen.generate("rect_plate", interview.requirements(iv))

    holes = payload["template"]["sketches"][0]["profile"]["args"]["holes"]
    assert len(holes) == 9
    assert all("pitch" in h[0] and "pitch" in h[1] for h in holes)
    # The obligation states the span between outermost holes, not the spacing.
    assert payload["design_plan"]["obligations"][0]["placement"] == {
        "form": "grid", "pitch": [60.0, 60.0]}


def test_a_grid_too_big_for_the_plate_is_refused():
    from orion import blueprint_gen

    iv = interview.Interview(request="grid plate", family="rect_plate")
    iv.slots = {"length": 50, "width": 50, "thickness": 3, "hole_count": 9,
                "hole_d": 6, "hole_pitch": 30, "hole_cols": 3, "hole_rows": 3}
    iv.classify()
    with pytest.raises(blueprint_gen.GeneratorError, match="does not fit"):
        blueprint_gen.generate("rect_plate", interview.requirements(iv))


# --------------------------------------------------------------------------- #
# the disc family, and the dimension that vanished
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("slots,expected_v", [
    ({"outer_d": 20, "bore_d": 8.4, "thickness": 2},
     "(pi*R**2 - pi*bore_r**2)*T"),
    ({"outer_d": 30, "thickness": 50}, "(pi*R**2)*T"),
    ({"outer_d": 100, "bore_d": 25, "thickness": 8,
      "hole_count": 6, "hole_d": 9, "pcd": 80},
     "(pi*R**2 - pi*bore_r**2 - 6*pi*hole_r**2)*T"),
])
def test_the_disc_family_has_an_exact_closed_form(slots, expected_v):
    from orion import blueprint_gen

    iv = interview.Interview(request="disc", family="disc")
    iv.slots = dict(slots)
    iv.classify()
    payload = blueprint_gen.generate("disc", interview.requirements(iv))
    body = [a for a in payload["assertions"] if a["id"] == "body"][0]
    assert body["target"] == expected_v
    assert body["tier"] == 1, "a disc is closed-form; it must not drop a tier"


def test_a_bolt_circle_breaking_into_the_bore_is_refused():
    from orion import blueprint_gen

    iv = interview.Interview(request="flange", family="disc")
    iv.slots = {"outer_d": 100, "bore_d": 60, "thickness": 8,
                "hole_count": 6, "hole_d": 9, "pcd": 66}
    iv.classify()
    with pytest.raises(blueprint_gen.GeneratorError, match="bore"):
        blueprint_gen.generate("disc", interview.requirements(iv))


def test_a_stated_dimension_that_reached_no_slot_is_a_question():
    """"Tube 40 mm OD, 32 mm ID, 60 mm long" read as a SOLID BAR and verified.

    The bore was dropped by the extraction, and every downstream check agreed
    with the omission because they are all derived from the same slots.
    """
    iv = interview.Interview(request="Tube 40 mm OD, 32 mm ID, 60 mm long",
                             family="disc")
    iv.slots = {"outer_d": 40, "thickness": 60}
    assert iv.unaccounted == [32.0]
    assert not iv.complete, "a dropped dimension must not read as complete"
    assert any("32" in q for q in interview.open_questions(iv))


@pytest.mark.parametrize("request_text,slots", [
    ("Washer 20 mm OD, 8.4 mm ID, 2 mm thick",
     {"outer_d": 20, "bore_d": 8.4, "thickness": 2}),
    ("Mounting plate 120 x 80 x 6 mm with four M5 clearance holes, "
     "one 10 mm from each corner",
     {"length": 120, "width": 80, "thickness": 6, "hole_count": 4,
      "hole_d": 5.5, "hole_edge_gap": 10}),
    ("Plate 100 x 100 x 3 mm with a 3 x 3 grid of 6 mm holes spaced 30 mm apart",
     {"length": 100, "width": 100, "thickness": 3, "hole_count": 9,
      "hole_d": 6, "hole_pitch": 30, "hole_cols": 3, "hole_rows": 3}),
])
def test_a_fully_read_request_raises_no_false_question(request_text, slots):
    """A false question is a worse answer than none, so this is the guard."""
    from orion import provenance as P

    assert P.unclaimed_lengths(request_text, slots) == []


# --------------------------------------------------------------------------- #
# open-top boxes
# --------------------------------------------------------------------------- #
def test_the_shelled_box_is_a_pad_and_a_pocket_not_a_shell():
    """Thickness would re-author every face and hide the volume in the kernel."""
    from orion import blueprint_gen

    iv = interview.Interview(request="box", family="shelled_box")
    iv.slots = {"length": 80, "width": 60, "height": 30, "wall": 2.5}
    iv.classify()
    payload = blueprint_gen.generate("shelled_box", interview.requirements(iv))

    kinds = [f["type"] for f in payload["template"]["features"]]
    assert "Pocket" in kinds and "Thickness" not in kinds
    body = [a for a in payload["assertions"] if a["id"] == "body"][0]
    assert body["tier"] == 1
    assert body["target"] == "L*W*H - (L - 2*wall)*(W - 2*wall)*(H - floor_t)"


def test_the_floor_variable_does_not_shadow_the_builtin():
    """`floor` is a function in the expression language; the static check
    rejects a variable that shadows it, and then reports it unreferenced."""
    from orion import blueprint_gen
    from orion.blueprint import Blueprint

    iv = interview.Interview(request="tray", family="shelled_box")
    iv.slots = {"length": 120, "width": 80, "height": 15, "wall": 3, "floor": 3}
    iv.classify()
    payload = blueprint_gen.generate("shelled_box", interview.requirements(iv))
    assert "floor" not in payload["variables"]
    assert payload["variables"]["floor_t"] == 3
    Blueprint.from_dict(payload).freeze()  # must pass the static check


@pytest.mark.parametrize("slots,match", [
    ({"length": 40, "width": 40, "height": 25, "wall": 20}, "no cavity"),
    ({"length": 80, "width": 60, "height": 10, "wall": 2, "floor": 12},
     "no depth"),
])
def test_a_box_with_no_inside_is_refused(slots, match):
    from orion import blueprint_gen

    iv = interview.Interview(request="box", family="shelled_box")
    iv.slots = dict(slots)
    iv.classify()
    with pytest.raises(blueprint_gen.GeneratorError, match=match):
        blueprint_gen.generate("shelled_box", interview.requirements(iv))


# --------------------------------------------------------------------------- #
# the knowledge layer, on the live path
#
# "NEMA 17 motor mount plate, 6 mm thick: M3 holes on a 31 x 31 mm square bolt
# pattern" was answered with "How long should the plate be?" — about the one
# dimension a designation fixes exactly. An engineer knows the face is 42.3 mm
# and can say where they got it; so, now, can this.
# --------------------------------------------------------------------------- #
def test_a_named_motor_frame_sizes_the_plate():
    slots, notes = interview.apply_standards(
        {"motor_frame": "NEMA 17", "thickness": 6}, family="rect_plate")
    assert slots["length"] == 42.3 and slots["width"] == 42.3
    assert slots["hole_pitch"] == 31.0
    assert slots["hole_cols"] == 2 and slots["hole_rows"] == 2
    assert not interview.missing("rect_plate", slots)
    assert any("NEMA ICS 16" in n for n in notes), "a table has to say which"


def test_a_stated_size_beats_the_frame_table():
    """The table fills what the request left open. Never overrides it."""
    slots, _ = interview.apply_standards(
        {"motor_frame": "NEMA 17", "thickness": 6, "length": 60, "width": 60},
        family="rect_plate")
    assert slots["length"] == 60 and slots["width"] == 60


@pytest.mark.parametrize("text,expected", [
    ("NEMA 17 motor mount plate", "NEMA 17"),
    ("nema-23 mount", "NEMA 23"),
    ("a NEMA17 bracket", "NEMA 17"),
    ("plain plate 50 x 50", None),
    ("ALTNEMA 17 thing", None),
])
def test_a_designation_is_read_from_the_text_not_sampled(text, expected):
    """It either appears or it does not; that must not depend on the model."""
    assert interview.designations(text, {}).get("motor_frame") == expected


def test_frame_derived_values_are_standard_not_unsourced():
    """Nobody typed 42.3. It is sourced, and the ledger names the standard."""
    from orion import provenance as P

    slots, notes = interview.apply_standards(
        {"motor_frame": "NEMA 17", "thickness": 6}, family="rect_plate")
    prov = P.classify("NEMA 17 motor mount plate, 6 mm thick", slots, notes=notes)
    for field in ("length", "width", "hole_pitch"):
        assert prov[field]["source"] == P.STANDARD, field
        assert "NEMA" in prov[field]["basis"]


# --------------------------------------------------------------------------- #
# an answer is not a new request
# --------------------------------------------------------------------------- #
def test_an_answer_is_joined_to_the_question_it_answers():
    from app.services.studio_agent import _carry_forward

    history = [
        {"role": "user", "content": "L bracket: 60 x 40 mm base and a "
                                    "60 x 50 mm vertical wall"},
        {"role": "assistant", "content": "How thick is the base plate?"},
    ]
    joined = _carry_forward(history, "4 mm")
    assert "L bracket" in joined and joined.endswith("4 mm")


def test_the_walk_stops_at_a_finished_build():
    """A new request must never be merged into the one before it."""
    from app.services.studio_agent import _carry_forward

    history = [
        {"role": "user", "content": "L bracket 60 x 40, 4 mm thick"},
        {"role": "assistant", "content": "Built it. Volume 12000 mm3."},
        {"role": "user", "content": "now a washer 20 mm OD"},
        {"role": "assistant", "content": "What is the bore?"},
    ]
    joined = _carry_forward(history, "8 mm")
    assert "washer" in joined
    assert "bracket" not in joined, "an answered request must not come back"


def test_no_history_is_the_message_itself():
    from app.services.studio_agent import _carry_forward

    assert _carry_forward([], "a plate 100 x 60 x 5 mm") == "a plate 100 x 60 x 5 mm"
    assert _carry_forward(None, "x") == "x"


def test_a_centre_hole_is_legal_when_there_is_no_bore():
    """Every odd x odd grid has one. A 5 x 5 speaker grille refused itself."""
    import math

    from orion import profiles as P

    out = P.build("disc_with_holes", r=35,
                  holes=[(0, 0, 2), (10, 0, 2), (-10, 0, 2)])
    assert abs(out["area"] - (math.pi * 35 * 35 - 3 * math.pi * 4)) < 1e-9


def test_a_centre_hole_inside_a_bore_is_still_refused():
    from orion import profiles as P

    with pytest.raises(P.ProfileError, match="bore"):
        P.build("disc_with_holes", r=35, r_inner=8, holes=[(0, 0, 2)])


def test_a_bare_answer_is_bound_to_the_field_that_asked_for_it():
    """Answering a question must advance the interview, not restart it.

    Measured before the fix: "6 mm" replying to "How thick should it be?" was
    joined to the request as a bare number, the extraction placed it nowhere,
    and the turn came back with *both* the same question and "the request
    mentions 6 mm and I have not used it anywhere" — the system asking about
    the number it had just asked for. The binding is in the schema, so it is
    decided in Python rather than left to the model.
    """
    from app.services.studio_agent import _carry_forward

    history = [
        {"role": "user", "content": "a mounting plate for a NEMA 17 stepper"},
        {"role": "assistant", "content": "How thick should it be?"},
    ]
    assert _carry_forward(history, "6 mm").endswith("thickness: 6 mm")


def test_an_answer_that_names_its_own_field_is_left_alone():
    """A sentence can say which dimension it means; a prefix would fight it."""
    from app.services.studio_agent import _carry_forward

    history = [{"role": "assistant", "content": "How thick should it be?"}]
    assert _carry_forward(history, "make it 6 mm thick") == "make it 6 mm thick"


def test_two_questions_and_one_number_is_not_guessed():
    """Inventing a binding is worse than asking again."""
    from app.services.studio_agent import _carry_forward

    history = [
        {
            "role": "assistant",
            "content": "How thick should it be?\nHow many mounting holes?",
        }
    ]
    assert _carry_forward(history, "6 mm") == "6 mm"


def test_every_schema_question_names_exactly_one_field():
    """`phrase_answer` is an exact lookup, which only holds while the prompts
    stay distinct. A phrasing reused for two different fields would silently
    bind answers to whichever family loaded first."""
    from orion import interview

    seen: dict[str, str] = {}
    for fam in interview.FAMILIES.values():
        for slot in list(fam.required) + list(fam.optional):
            key = slot.prompt.strip().lower()
            assert seen.setdefault(key, slot.name) == slot.name, key


# --------------------------------------------------------------------------- #
# a named hole must be a placed hole
# --------------------------------------------------------------------------- #
def test_a_two_bolt_pillow_block_gets_two_bolts():
    """The commonest bearing housing there is, and it built as a plain block.

    `bearing_housing` required BOTH `hole_pitch_x` and `hole_pitch_y` before it
    would place anything, but a pillow block carries two bolts either side of
    the shaft and states one pitch. The pattern was skipped silently — after the
    holes had been asked for, extracted, and sized by ISO 273 — and fulfillment
    then refused a fully specified part for containing no cylinders of radius
    4.5 mm.
    """
    req = interview.resolve("bearing_housing", {
        "length": 100, "width": 60, "height": 50, "bore_d": 42,
        "seat_depth": 12, "thread": "M8", "hole_pitch_x": 70, "hole_d": 9.0})
    bp = blueprint_gen.BUILDERS["bearing_housing"](req)

    holes = bp["template"]["sketches"][0]["profile"]["args"]["holes"]
    assert len(holes) == 2, holes
    assert {h[0] for h in holes} == {"-pitch_x", "+pitch_x"}
    assert {h[1] for h in holes} == {"0"}, "one pitch means the pair sits on an axis"
    assert bp["variables"]["pitch_x"] == 35.0
    assert "pitch_y" not in bp["variables"]
    # The volume claim has to count the holes it actually cut, not four.
    assert "2*pi*hole_r**2*H" in str(bp["assertions"])


def test_a_four_bolt_housing_is_unchanged():
    req = interview.resolve("bearing_housing", {
        "length": 120, "width": 90, "height": 50, "bore_d": 42,
        "seat_depth": 12, "hole_d": 9.0, "hole_pitch_x": 90, "hole_pitch_y": 60})
    bp = blueprint_gen.BUILDERS["bearing_housing"](req)

    holes = bp["template"]["sketches"][0]["profile"]["args"]["holes"]
    assert len(holes) == 4, holes
    assert "4*pi*hole_r**2*H" in str(bp["assertions"])


def test_a_single_pitch_that_hits_the_seat_is_refused_not_fudged():
    """Two holes on one axis sit a plain centre distance from the seat, so the
    corner-form clearance test does not apply to them."""
    req = interview.resolve("bearing_housing", {
        "length": 100, "width": 60, "height": 50, "bore_d": 42,
        "seat_depth": 12, "hole_d": 9.0, "hole_pitch_x": 44})
    with pytest.raises(blueprint_gen.GeneratorError, match="bearing seat"):
        blueprint_gen.BUILDERS["bearing_housing"](req)


@pytest.mark.parametrize("family, slots, expected", [
    ("rect_plate", dict(length=100, width=60, thickness=6), "hole_edge_gap"),
    ("disc", dict(outer_d=80, thickness=6), "pcd"),
    ("bearing_housing", dict(length=80, width=60, height=45, bore_d=42,
                             seat_depth=12), "hole_pitch_x"),
])
def test_naming_a_thread_without_a_placement_asks_where(family, slots, expected):
    """A hole named but never placed is the worst of both outcomes: the
    obligation is recorded, the builder has no coordinates so it cuts nothing,
    and fulfillment refuses a part the user was never asked a question about.
    Measured before the fix: five of six families accepted "M8 holes" with no
    placement, asked nothing, and built a solid with none."""
    s = dict(slots, thread="M8")
    s, _ = interview.apply_standards(s)
    assert expected in [g.name for g in interview.missing(family, s)]


def test_a_placed_hole_asks_nothing_further():
    """The guard must not start interrogating requests that are already whole."""
    done = dict(length=100, width=60, thickness=6,
                hole_count=4, hole_d=5.5, hole_edge_gap=10)
    assert interview.missing("rect_plate", done) == []
