"""The NEMA 17 bracket, and the EDS-to-geometry gap it exposed.

A fully specified request::

    upright face 42.3 x 42.3, Ø22 central pilot bore,
    four Ø3.5 holes on a 31 x 31 square,
    base 60 x 50 x 5 with four Ø6.5 holes 10 mm in from each corner,
    upright 5 mm thick and 50 mm tall

came back as a bracket with no base holes at all. Two causes, one root: the
family carried a single ``hole_d`` slot shared between the motor pattern on the
upright and the mounting pattern through the base. One slot cannot hold two
numbers, so the Ø6.5 was either dropped entirely or cut at the upright's Ø3.5 —
measured, both happened depending on what else the reader filled.

The rule these tests hold: **every explicit geometric requirement in the
request reaches the geometry, or is reported by name.** Nothing in between.
"""

import pytest

from orion import blueprint_gen, holes as H, interview, obligations as OB

#: The request, as the interview resolves it. The prose path is exercised
#: end-to-end by the studio bench; here the concern is that a complete EDS
#: compiles to complete geometry, which is where it was being lost.
BRACKET = dict(
    base_length=60, base_width=50, base_thickness=5,
    upright_height=50, upright_thickness=5, upright_width=42.3,
    bore_d=22, hole_d=3.5, bolt_square=31,
    base_hole_d=6.5, base_hole_edge_gap=10,
    material="Aluminium 6061-T6", process="machined",
)


@pytest.fixture(scope="module")
def bp():
    return blueprint_gen.generate("l_bracket",
                                  interview.resolve("l_bracket", BRACKET))


def _holes(bp, sketch_id):
    for s in bp["template"]["sketches"]:
        if s["id"] == sketch_id:
            return s["profile"].get("args", {}).get("holes") or []
    return []


# --------------------------------------------------------------------------- #
# Every stated dimension reaches a variable
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("var, value, what", [
    ("BL", 60.0, "base length"),
    ("BW", 50.0, "base width"),
    ("BT", 5.0, "base thickness"),
    ("UH", 50.0, "upright height"),
    ("UT", 5.0, "upright thickness"),
    ("UW", 42.3, "the 42.3 mm motor face"),
    ("bore_r", 11.0, "the 22 mm pilot bore"),
    ("hole_r", 1.75, "the 3.5 mm motor holes"),
    ("bolt_half", 15.5, "the 31 x 31 bolt square"),
    ("base_hole_r", 3.25, "the 6.5 mm base holes"),
    ("base_gap", 10.0, "10 mm in from each corner"),
])
def test_every_stated_dimension_reaches_the_blueprint(bp, var, value, what):
    assert bp["variables"][var] == pytest.approx(value), what


# --------------------------------------------------------------------------- #
# ...and reaches the geometry, at its own size
# --------------------------------------------------------------------------- #
def test_the_motor_pattern_is_four_holes_at_the_motor_size(bp):
    upright = _holes(bp, "s_upright")
    motor = [h for h in upright if h[2] == "hole_r"]
    assert len(motor) == 4
    assert bp["variables"]["hole_r"] * 2 == pytest.approx(3.5)


def test_the_base_pattern_is_four_holes_at_the_base_size(bp):
    base = _holes(bp, "s_base")
    assert len(base) == 4
    assert {h[2] for h in base} == {"base_hole_r"}
    assert bp["variables"]["base_hole_r"] * 2 == pytest.approx(6.5)


def test_the_two_patterns_do_not_share_a_diameter(bp):
    """The duplication half of the bug.

    With one shared slot the base holes came out at the upright's Ø3.5 — four
    holes of the right count, in the right places, at the wrong size, and every
    downstream check agreed because they were all derived from the same slot.
    """
    upright = {h[2] for h in _holes(bp, "s_upright")}
    base = {h[2] for h in _holes(bp, "s_base")}
    assert not (upright & base)
    assert bp["variables"]["hole_r"] != bp["variables"]["base_hole_r"]


def test_the_pilot_bore_is_present_and_central(bp):
    bore = [h for h in _holes(bp, "s_upright") if h[2] == "bore_r"]
    assert len(bore) == 1
    assert bore[0][0] == "UH/2" and bore[0][1] == "0"


def test_nine_holes_in_total_and_not_one_more(bp):
    """4 motor + 1 bore on the upright, 4 through the base."""
    assert len(_holes(bp, "s_upright")) == 5
    assert len(_holes(bp, "s_base")) == 4


# --------------------------------------------------------------------------- #
# ...and is verified after the build, not merely placed
# --------------------------------------------------------------------------- #
def test_each_pattern_carries_its_own_obligation(bp):
    """Without one of its own, the base pattern could be dropped and the part
    still verified: every other check is derived from the same requirements
    that lost it."""
    obl = {o["id"]: o for o in bp["design_plan"]["obligations"]}
    assert set(obl) >= {"pilot_bore", "bolt_square", "base_mount"}
    assert obl["bolt_square"]["count"] == 4
    assert obl["bolt_square"]["radius"] == pytest.approx(1.75)
    assert obl["base_mount"]["count"] == 4
    assert obl["base_mount"]["radius"] == pytest.approx(3.25)


def test_the_obligations_state_where_the_holes_should_be(bp):
    """Count and diameter are not enough — four holes of the right size in the
    wrong places is still the wrong part."""
    obl = {o["id"]: o for o in bp["design_plan"]["obligations"]}
    assert obl["bolt_square"]["placement"]["pitch"] == [31.0, 31.0]
    # 10 mm in from each corner of a 60 x 50 base is a 40 x 30 span.
    assert obl["base_mount"]["placement"]["pitch"] == [40.0, 30.0]


def test_dropping_the_base_pattern_loses_its_obligation_too(bp):
    """The direction that matters: obligations come from the requirements, not
    from the template, so a builder that quietly stopped cutting the base holes
    would still be held to them."""
    without = blueprint_gen.generate(
        "l_bracket", interview.resolve("l_bracket", {
            k: v for k, v in BRACKET.items()
            if k not in ("base_hole_d", "base_hole_edge_gap")}))
    assert "base_mount" not in {o["id"] for o in
                                without["design_plan"]["obligations"]}
    assert _holes(without, "s_base") == []


# --------------------------------------------------------------------------- #
# The volume claim accounts for both patterns
# --------------------------------------------------------------------------- #
def test_the_volume_claim_subtracts_both_patterns_at_their_own_size(bp):
    body = next(a for a in bp["assertions"] if a["id"] == "body")
    assert "hole_r" in body["target"] and "base_hole_r" in body["target"]
    assert body["tier"] == 1


# --------------------------------------------------------------------------- #
# Geometry that cannot exist is refused with the number that is wrong
# --------------------------------------------------------------------------- #
def test_base_holes_under_the_upright_are_refused_with_the_measurement():
    """8 mm in from the end, Ø6.5, against a 5 mm upright: the hole reaches
    4.75 mm and the upright stands on the first 5 mm."""
    with pytest.raises(blueprint_gen.GeneratorError, match="4.75 mm"):
        blueprint_gen.generate("l_bracket", interview.resolve(
            "l_bracket", {**BRACKET, "base_hole_edge_gap": 8}))


def test_corner_holes_that_meet_in_the_middle_are_refused():
    with pytest.raises(blueprint_gen.GeneratorError, match="overlap at the centre"):
        blueprint_gen.generate("l_bracket", interview.resolve(
            "l_bracket", {**BRACKET, "base_hole_edge_gap": 24}))


# --------------------------------------------------------------------------- #
# The hole-group vocabulary itself
# --------------------------------------------------------------------------- #
def test_a_group_naming_a_face_the_family_lacks_is_reported_by_name():
    """Never silently ignored. "We cannot do that" and "we did not notice" are
    different facts and used to look identical."""
    groups, unsupported = H.from_eds(
        "l_bracket", [{"face": "web", "placement": "square",
                       "diameter": 5, "pitch": 20}])
    assert groups == []
    assert "no 'web' face" in unsupported[0]["reason"]
    assert "base" in unsupported[0]["reason"] and "upright" in unsupported[0]["reason"]


def test_a_group_naming_an_unknown_placement_is_reported_by_name():
    _, unsupported = H.from_eds(
        "l_bracket", [{"face": "base", "placement": "spiral", "diameter": 5}])
    assert "not a hole placement" in unsupported[0]["reason"]


def test_a_group_with_no_diameter_is_reported_rather_than_guessed():
    _, unsupported = H.from_eds(
        "l_bracket", [{"face": "base", "placement": "corners", "edge_gap": 10}])
    assert "no diameter" in unsupported[0]["reason"]


def test_a_supported_group_compiles_to_the_count_it_promised():
    groups, unsupported = H.from_eds(
        "l_bracket", [{"face": "base", "placement": "corners",
                       "diameter": 6.5, "edge_gap": 10}])
    assert unsupported == []
    assert H.count_of(groups[0]) == 4
    v = {}
    coords = H.coordinates(groups[0], H.FACES["l_bracket"]["base"], v,
                           {"BL": 60.0, "BW": 50.0})
    assert len(coords) == 4
    # Parametric, not baked into literals: a pattern frozen into numbers stops
    # re-solving the moment anyone edits the plate.
    assert all(any(c in expr for c in ("BL", "BW", "gap"))
               for row in coords for expr in row[:2])


@pytest.mark.parametrize("placement, params, expected", [
    ("square", {"pitch": 31}, 4),
    ("corners", {"edge_gap": 10}, 4),
    ("grid", {"pitch_u": 40, "pitch_v": 30}, 4),
    ("grid", {"pitch_u": 40}, 2),
    ("bolt_circle", {"pcd": 40, "count": 6}, 6),
])
def test_a_requested_pattern_produces_exactly_that_many_holes(
        placement, params, expected):
    """The count is known before any geometry exists, and it is what the
    obligation is written from."""
    g = H.Group(id="g", face="base", radius=2.0, placement=placement,
                params=params)
    assert H.count_of(g) == expected
    v = {}
    coords = H.coordinates(g, H.FACES["l_bracket"]["base"], v,
                           {"BL": 120.0, "BW": 100.0})
    assert len(coords) == expected


# --------------------------------------------------------------------------- #
# The extraction budget, which is what actually lost the dimensions
# --------------------------------------------------------------------------- #
def test_the_extraction_prompt_omits_what_is_read_deterministically():
    """Measured on this bracket against K2-Horizon at the same 8192 budget:

        29 fields -> 218.3s, finish=length, 60,758 chars of reasoning, 0 keys
        24 fields -> 106.2s, finish=stop,   12,170 chars,             12 keys

    Every optional field is something to deliberate about, and a reasoning
    model deliberates about all of them before writing anything. Five soft
    fields that are not dimensions cost five times the reasoning and the entire
    answer.
    """
    prompt = interview.extract_prompt("l_bracket")
    for name in interview.READ_DETERMINISTICALLY:
        assert f"  {name} — " not in prompt, name


def test_what_is_omitted_is_actually_recovered_from_the_text():
    """Otherwise trimming the prompt would just move the loss."""
    text = ("a CNC machined load bearing bracket for a NEMA 17, ISO 2768-m, "
            "+/-0.05 on the bore, measured from the bottom face")
    got = interview.designations(text, {})
    assert got["process"] == "machined"
    assert got["function"] == "load_bearing"
    assert got["motor_frame"] == "NEMA 17"
    assert got["tolerance_class"] == "m"
    assert got["critical_tolerance"] == 0.05
    assert got["datum"] == "bottom face"
    assert interview.READ_DETERMINISTICALLY <= set(got)


# --------------------------------------------------------------------------- #
# The same bracket with no per-face slots at all
# --------------------------------------------------------------------------- #
GROUPED = dict(
    base_length=60, base_width=50, base_thickness=5,
    upright_height=50, upright_thickness=5, upright_width=42.3, bore_d=22,
    hole_groups=[
        {"id": "motor_face", "face": "upright", "placement": "square",
         "diameter": 3.5, "pitch": 31},
        {"id": "base_mount", "face": "base", "placement": "corners",
         "diameter": 6.5, "edge_gap": 10},
    ],
)


def _grouped(slots=None):
    slots = slots or GROUPED
    req = interview.resolve("l_bracket", slots)
    req["hole_groups"] = slots["hole_groups"]
    return blueprint_gen.generate("l_bracket", req)


def test_the_bracket_builds_from_groups_with_no_hole_slots():
    """The point of the vocabulary: two patterns, two diameters, two faces, and
    not one slot named after where they go."""
    bp = _grouped()
    upright = _holes(bp, "s_upright")
    base = _holes(bp, "s_base")
    assert len(base) == 4
    assert len([h for h in upright if h[2] != "bore_r"]) == 4
    # Each group keeps its own radius variable.
    assert {h[2] for h in base} != {h[2] for h in upright if h[2] != "bore_r"}


def test_each_group_lands_on_the_face_it_named():
    """A group compiled into the wrong sketch is a hole in the wrong place, and
    the volume would still come out right."""
    bp = _grouped()
    base_r = next(iter({h[2] for h in _holes(bp, "s_base")}))
    up_r = next(iter({h[2] for h in _holes(bp, "s_upright") if h[2] != "bore_r"}))
    assert bp["variables"][base_r] == pytest.approx(3.25)
    assert bp["variables"][up_r] == pytest.approx(1.75)


def test_every_group_becomes_an_obligation_the_kernel_checks():
    bp = _grouped()
    obl = {o["id"]: o for o in bp["design_plan"]["obligations"]}
    assert {"pilot_bore", "motor_face", "base_mount"} <= set(obl)
    assert obl["motor_face"]["radius"] == pytest.approx(1.75)
    assert obl["base_mount"]["radius"] == pytest.approx(3.25)
    # Shape, not a lookalike: it carried a `diameter` where the checker reads
    # `radius`, so every group came back "no diameter was stated, so nothing
    # about it can be measured" — honest, and the exact silence these prevent.
    assert all("radius" in o and o.get("placement")
               for o in obl.values() if o["id"] != "pilot_bore")


def test_a_group_the_builder_cannot_place_is_reported_and_the_rest_still_build():
    """One bad group must not cost the user every other feature."""
    bad = dict(GROUPED)
    bad["hole_groups"] = GROUPED["hole_groups"] + [
        {"id": "web_relief", "face": "web", "placement": "square",
         "diameter": 5, "pitch": 20}]
    bp = _grouped(bad)
    assert len(_holes(bp, "s_base")) == 4
    reported = {u["feature"] for u in bp["design_plan"]["unsupported"]}
    assert "web_relief" in reported


def test_a_group_that_does_not_fit_is_reported_rather_than_raised():
    """A pattern wider than the plate is a statement about the request. Raising
    would take the whole bracket down with it."""
    bad = dict(GROUPED)
    bad["hole_groups"] = [
        {"id": "too_wide", "face": "base", "placement": "square",
         "diameter": 5, "pitch": 200}]
    bp = _grouped(bad)
    why = [u["reason"] for u in bp["design_plan"]["unsupported"]]
    assert any("wider than" in r for r in why), why
    # And it left no variables behind for a pattern that was never placed.
    assert not any(k.startswith("g1_") for k in bp["variables"])


def test_the_extraction_prompt_offers_groups_only_where_they_can_be_placed():
    """Generated from the capability registry, so the prompt and what the
    builder can actually cut cannot drift apart."""
    for family in ("rect_plate", "l_bracket"):
        prompt = interview.extract_prompt(family)
        assert "hole_groups" in prompt
        for face in H.FACES[family]:
            assert face in prompt
    # A family with no drillable faces declared is not offered the field.
    assert "hole_groups" not in interview.extract_prompt("disc")


def test_a_structured_field_is_less_to_deliberate_about_not_more():
    """Measured on a plate with three different hole patterns, same request,
    same 8192 budget:

        flat slots    31.8s   12,282 chars   {hole_edge_gap, pcd, length,
                                              width, thickness}
        hole_groups    7.3s    1,807 chars   all three patterns, complete

    The flat form asked the model to fit three patterns through one set of
    scalars and it returned an edge gap and a bolt circle with no diameters
    between them — the shape of the schema, not of the request. This test holds
    the property that made that possible: one field, and every pattern in it
    keeps its own diameter.
    """
    prompt = interview.extract_prompt("rect_plate")
    assert "OWN diameter" in prompt
    assert "two entries, never one" in prompt


# --------------------------------------------------------------------------- #
# One vocabulary, not two
# --------------------------------------------------------------------------- #
def test_a_slot_a_group_supersedes_is_not_offered_beside_it():
    """Two ways to say one thing is more to deliberate about, not less.

    Adding the structured field on top of the flat slots put the bracket back
    over the budget cliff: 277s and not one dimension extracted. The flat slots
    are still accepted by the schema — only the prompt changes — so a stored
    requirements set or an answer to a question keeps working.
    """
    prompt = interview.extract_prompt("l_bracket")
    for name in interview.SUPERSEDED_BY_GROUPS["l_bracket"]:
        assert f"  {name} \u2014 " not in prompt, name
    # Still accepted, and still builds.
    assert interview.FAMILIES["l_bracket"].slot("bolt_square") is not None
    assert blueprint_gen.generate(
        "l_bracket", interview.resolve("l_bracket", BRACKET))["variables"]


def test_a_group_satisfies_the_placement_a_flat_diameter_demands():
    """`hole_d` demands a placement, and a group is one.

    The bracket extracted cleanly into two groups, the frame table filled
    `hole_d`, and the interview then asked "Square bolt pattern spacing?" about
    a pattern that was already fully specified.
    """
    slots = {"base_length": 60, "base_width": 50, "base_thickness": 5,
             "upright_height": 50, "upright_thickness": 5, "hole_d": 3.4,
             "hole_groups": [{"id": "m", "face": "upright",
                              "placement": "square", "diameter": 3.5,
                              "pitch": 31}]}
    assert [g.name for g in interview.missing("l_bracket", slots)] == []
    del slots["hole_groups"]
    assert "bolt_square" in [g.name for g in interview.missing("l_bracket", slots)]


def test_a_standards_table_does_not_duplicate_a_group_at_a_different_number():
    """The user said 3.5; the NEMA table would say 3.4. The obligation raised
    from the table then failed against the 3.5 holes the group had correctly
    built — right geometry, verdict REFUSED."""
    slots = {"upright_width": 42.3, "motor_frame": "NEMA 17",
             "hole_groups": [{"id": "m", "face": "upright",
                              "placement": "square", "diameter": 3.5,
                              "pitch": 31}]}
    with_groups, _ = interview.apply_standards(dict(slots), "l_bracket")
    assert with_groups.get("hole_d") is None
    flat = {k: v for k, v in slots.items() if k != "hole_groups"}
    without, _ = interview.apply_standards(flat, "l_bracket")
    assert without["hole_d"] == 3.4


def test_a_group_may_name_a_thread_and_the_standard_decides():
    """"four M5 clearance holes" states a size the model must not answer from
    memory. Without this the whole pattern came back "no diameter was given for
    this hole group" while the thread sat right there in it."""
    slots = {"length": 120, "width": 80, "thickness": 6,
             "hole_groups": [{"id": "mounting", "face": "top",
                              "placement": "corners", "edge_gap": 10,
                              "thread": "M5"}]}
    out, notes = interview.apply_standards(slots, "rect_plate")
    assert out["hole_groups"][0]["diameter"] == 5.5
    assert any("ISO 273" in n for n in notes)


def test_a_stated_diameter_beats_the_thread():
    slots = {"hole_groups": [{"id": "m", "face": "top", "placement": "corners",
                              "edge_gap": 10, "thread": "M5", "diameter": 6.0}]}
    out, _ = interview.apply_standards(slots, "rect_plate")
    assert out["hole_groups"][0]["diameter"] == 6.0


def test_the_unaccounted_guard_looks_inside_a_group():
    """It scanned only scalar values, so a bracket whose patterns were fully
    specified as groups had every number in them reported as "stated in the
    request and no slot took it" — right about its own evidence, wrong about
    the part."""
    from orion import provenance as P

    request = "plate 120 x 80 x 6 with four 5.5 mm holes 10 mm from each corner"
    values = {"L": 120.0, "W": 80.0, "T": 6.0,
              "hole_groups": [{"diameter": 5.5, "edge_gap": 10}]}
    assert P.unclaimed_lengths(request, values) == []
    # ...and it still catches a number that really did reach nothing.
    assert P.unclaimed_lengths(request, {"L": 120.0, "W": 80.0, "T": 6.0}) == [5.5, 10.0]
