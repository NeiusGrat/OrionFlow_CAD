"""The family schema must describe the corpus it was mined from.

The point of the schema is to stop a planner inventing variable names the model
never saw for a family. That is only worth anything if the schema is faithful,
so the load-bearing test is a round trip: take real verified parts, check them
against the mined schema, and expect silence.
"""

import json
import os

import pytest

from orion.family_schema import DEFAULT_DATA, check, describe, for_family, load

needs_corpus = pytest.mark.skipif(
    not os.path.exists(DEFAULT_DATA), reason="training corpus not present")


@needs_corpus
def test_every_family_has_a_stable_required_set():
    schemas = load()
    assert len(schemas) >= 50
    for name, schema in schemas.items():
        assert schema.n_samples > 0, name
        assert schema.required(), f"{name} has no always-present variable"


@needs_corpus
def test_real_corpus_parts_validate_clean_against_their_own_schema():
    """A mined schema that rejects the data it was mined from is worthless."""
    checked = 0
    with open(DEFAULT_DATA, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= 3000:
                break
            rec = json.loads(line)
            meta = rec.get("meta") or {}
            if meta.get("view") != "spec":
                continue
            try:
                blueprint = json.loads(
                    rec["messages"][2]["content"].split("</think>")[1].strip())
            except (IndexError, ValueError):
                continue
            notes = check(meta["base_family"], blueprint["variables"])
            assert not notes, f"{meta['base_family']}: {notes}"
            checked += 1
    assert checked > 200, f"only {checked} parts checked"


@needs_corpus
def test_invented_variable_names_are_caught():
    # L/W/t are plausible and wrong: mount_plate is hr, mx, my, pl, pt, pw.
    notes = check("mount_plate", {"L": 120.0, "W": 80.0, "t": 6.0})
    assert any("'L' is not a mount_plate variable" in n for n in notes)
    assert any("missing 'pl'" in n for n in notes)


@needs_corpus
def test_out_of_range_is_reported_not_rejected():
    schema = for_family("mount_plate")
    variables = {n: schema.variables[n].median for n in schema.required()}
    assert check("mount_plate", variables) == []
    variables["pt"] = 500.0
    notes = check("mount_plate", variables)
    assert len(notes) == 1 and "outside the observed range" in notes[0]


@needs_corpus
def test_composed_class_resolves_to_its_base_family():
    assert for_family("wheel_hub_plus_locating_pin").family == "wheel_hub"
    # attachment variables are composed, not authored, so they are not schema
    # violations on the base family
    schema = for_family("wheel_hub")
    variables = {n: schema.variables[n].median for n in schema.required()}
    variables.update({"att0_cx": 10.0, "att0_cy": 0.0, "att0_pr": 3.0,
                      "att0_ph": 6.0})
    assert check("wheel_hub_plus_locating_pin", variables) == []


@needs_corpus
def test_unknown_family_says_so():
    notes = check("quadcopter_frame", {"L": 100.0})
    assert notes and "no schema" in notes[0]


@needs_corpus
def test_describe_carries_variables_and_guards():
    text = describe("wheel_hub")
    assert "bore_r" in text and "hole_n" in text
    # the guards are the part a planner has to satisfy
    assert "must hold" in text and "lug_spacing" in text


@needs_corpus
def test_roles_are_mined_for_families_prose_cannot_read():
    # mount_plate is hr, mx, my, pl, pt, pw — pack_sft.prose_name falls through
    # on every one, so the role has to come from the template.
    schema = for_family("mount_plate")
    roles = {n: v.role for n, v in schema.variables.items()}
    assert roles["pt"] == "extrude depth"
    assert roles["pl"] == "length (X)"
    assert roles["pw"] == "width (Y)"
    assert roles["hr"] == "hole radius"


@needs_corpus
def test_prose_resolves_to_canonical_variables():
    from orion.family_schema import resolve

    assert resolve("mount_plate", "thickness").variable == "pt"
    assert resolve("mount_plate", "6 mm thick").variable == "pt"
    assert resolve("mount_plate", "long").variable == "pl"
    assert resolve("mount_plate", "width").variable == "pw"
    # naming the variable outright still works
    assert resolve("mount_plate", "pt").variable == "pt"
    assert resolve("mount_plate", "material") is None


@needs_corpus
def test_diameter_is_halved_into_a_radius_variable():
    """Storing a stated diameter in a radius variable is a 2x error that builds
    cleanly and verifies against its own wrong prediction."""
    from orion.family_schema import resolve, resolve_dimensions

    match = resolve("mount_plate", "hole diameter")
    assert match.variable == "hr" and match.halve
    assert match.apply(6.4) == 3.2

    canonical, unresolved = resolve_dimensions(
        "mount_plate", {"length": 112.0, "width": 66.0,
                        "thickness": 10.0, "hole diameter": 6.4})
    assert canonical == {"pl": 112.0, "pw": 66.0, "pt": 10.0, "hr": 3.2}
    assert unresolved == {}


@needs_corpus
def test_ambiguous_phrase_is_refused_not_guessed():
    from orion.family_schema import resolve

    # wheel_hub carries barrel_r, bc_r, bore_r, flange_r, hole_r — a bare
    # "radius" cannot mean one of them, so it must come back as a question.
    assert resolve("wheel_hub", "radius") is None


@needs_corpus
def test_unresolved_dimensions_are_returned_not_dropped():
    from orion.family_schema import resolve_dimensions

    canonical, unresolved = resolve_dimensions(
        "mount_plate", {"thickness": 8.0, "fillet radius": 2.0})
    assert canonical == {"pt": 8.0}
    assert unresolved == {"fillet radius": 2.0}


@needs_corpus
def test_directed_extraction_keeps_the_qualifier():
    """A generic parser reads three radii as one thing called 'radius' and
    keeps the last. Searching per variable cannot make that mistake."""
    from orion.family_schema import extract_for_family

    ask = ("I need a wheel hub. Dimensions (mm unless noted): barrel height 40, "
           "barrel radius 29, bc radius 48, bore radius 7, flange thickness 12.")
    found = extract_for_family(ask, "wheel_hub")
    assert found["barrel_h"] == 40.0
    assert found["barrel_r"] == 29.0
    assert found["bc_r"] == 48.0
    assert found["bore_r"] == 7.0
    assert found["flange_t"] == 12.0


@needs_corpus
def test_extraction_handles_value_before_and_after():
    from orion.family_schema import extract_for_family

    assert extract_for_family("a mount plate 112 mm length", "mount_plate")["pl"] == 112.0
    assert extract_for_family("mount plate, length = 112", "mount_plate")["pl"] == 112.0
    assert extract_for_family("mount plate with length of 112 mm",
                              "mount_plate")["pl"] == 112.0


@needs_corpus
def test_attachment_phrases_are_refused_not_mismatched():
    """'first feature rib height' is att0_rh. Matching it to a base variable
    that merely shares the word 'height' writes a real number into the wrong
    dimension — a part that builds and is not what was asked for."""
    from orion.family_schema import resolve

    assert resolve("box_shell", "first feature rib height") is None
    assert resolve("slotted_rail", "second feature counterbore radius") is None
    assert resolve("l_bracket", "first feature centre y") is None
    # the base family's own height still resolves
    assert resolve("box_shell", "height") is not None


@needs_corpus
def test_size_triple_is_read():
    """"100 x 60 x 5 mm" is how people write a plate and how the corpus never
    writes one — so a benchmark drawn from the corpus reported 100% fidelity
    while every dimension here was silently replaced by a median."""
    from orion.family_schema import extract_for_family

    got = extract_for_family("Rectangular plate 100 x 60 x 5 mm", "mount_plate")
    assert got == {"pl": 100.0, "pw": 60.0, "pt": 5.0}
    assert extract_for_family("plate 120 × 80 × 6", "mount_plate")["pl"] == 120.0


@needs_corpus
def test_a_feature_size_does_not_become_the_outline():
    from orion.family_schema import extract_for_family

    # the slot is 40x8; the plate is 80x40x5
    got = extract_for_family(
        "Plate 80 x 40 x 5 mm with a central slot 40 mm long and 8 mm wide",
        "mount_plate")
    assert got["pl"] == 80.0 and got["pw"] == 40.0 and got["pt"] == 5.0

    # a bolt pattern is not the part's extents
    got = extract_for_family(
        "NEMA 17 motor mount plate, 6 mm thick: M3 holes on a 31 x 31 mm "
        "square bolt pattern", "mount_plate")
    assert got.get("pl") != 31.0 and got.get("pw") != 31.0
    assert got["pt"] == 6.0

    # ...but a grid mentioned AFTER the size must not suppress the size
    got = extract_for_family(
        "Plate 100 x 100 x 3 mm with a 3 x 3 grid of 6 mm holes", "mount_plate")
    assert got["pl"] == 100.0 and got["pt"] == 3.0


@needs_corpus
def test_a_family_that_owns_a_feature_keeps_its_dimensions():
    """The sub-feature guard must not fire on families whose own variables are
    named after the feature — it cost 2.6 points of corpus fidelity when it did."""
    from orion.family_schema import extract_for_family, for_family

    schema = for_family("slotted_rail")
    assert [n for n in schema.variables if "slot" in n], \
        "expected slotted_rail to own slot variables"
    got = extract_for_family(
        "I need a slotted rail. Dimensions (mm unless noted): slot radius 7, "
        "rail height 20.", "slotted_rail")
    assert got.get("slot_r") == 7.0, \
        "the family's own slot dimension was consumed as a sub-feature"
    assert got.get("rail_h") == 20.0


@needs_corpus
def test_optional_variables_are_marked_optional():
    # bolted_flange carries an O-ring gland on some variants only.
    schema = for_family("bolted_flange")
    optional = [n for n, v in schema.variables.items() if not v.always]
    assert optional, "expected the gland variables to be optional"
    assert all(n.startswith("groove_") for n in optional)
