"""The orchestration layer must not move the model off its training distribution.

The whole point of EngineeringSpecification is that engineering decides the
numbers and never touches the sentence. The load-bearing test is therefore not
that the renderer produces something reasonable — it is that it reproduces a
real training prompt character for character.
"""

import json
import os

import pytest

from app.services.engineering_spec import (
    EngineeringSpecification,
    SpecError,
    looks_unfamiliar,
    known_vocabulary,
)

TRAIN = os.path.join("data", "forge", "sft_v1", "train.jsonl")


def _spec_rows(limit: int = 40):
    """Real ``spec``-view rows from the set the adapter was trained on."""
    rows = []
    with open(TRAIN, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("meta", {}).get("view") != "spec":
                continue
            blueprint = json.loads(
                rec["messages"][2]["content"].split("</think>")[1].strip()
            )
            rows.append((rec["messages"][1]["content"], blueprint))
            if len(rows) >= limit:
                break
    return rows


needs_corpus = pytest.mark.skipif(
    not os.path.exists(TRAIN), reason="training corpus not present"
)


@needs_corpus
def test_renders_byte_identical_to_training_prompts():
    rows = _spec_rows()
    assert rows, "no spec-view rows found"
    for trained_prompt, blueprint in rows:
        spec = EngineeringSpecification(
            part_class=blueprint["part_class"],
            variables=blueprint["variables"],
            # provenance must not leak into the sentence
            citations=["ISO 273", "NASA-STD-5020B 4.6.4"],
            calculations={"beam_bending": {"max_stress_mpa": 150.0}},
            constraints=["must clear the motor boss"],
            rationale={"t": "minimum wall for the chosen process"},
            material="aluminium_6061_t6",
            process="3-axis milled",
        )
        assert spec.to_prompt() == trained_prompt


@needs_corpus
def test_grounding_never_reaches_the_prompt():
    trained_prompt, blueprint = _spec_rows(1)[0]
    spec = EngineeringSpecification(
        part_class=blueprint["part_class"],
        variables=blueprint["variables"],
        citations=["ISO 2768-mK"],
        constraints=["wall >= 3 mm for die casting"],
        material="steel_4140",
    )
    rendered = spec.to_prompt()
    assert rendered == trained_prompt
    for secret in ("ISO 2768", "die casting", "steel_4140"):
        assert secret not in rendered
    # ...but it is still available to everything that is not the design turn.
    grounding = spec.grounding()
    assert "ISO 2768-mK" in grounding["citations"]
    assert grounding["material"] == "steel_4140"


def test_rejects_variable_shadowing_a_builtin():
    spec = EngineeringSpecification("mount_plate", {"max": 10.0, "t": 5.0})
    problems = spec.validate()
    assert any("shadows the built-in" in p for p in problems)
    with pytest.raises(SpecError):
        spec.to_prompt()


def test_rejects_non_finite_and_non_numeric():
    assert any(
        "inf" in p
        for p in EngineeringSpecification("plate", {"L": float("inf")}).validate()
    )
    assert any(
        "not a number" in p
        for p in EngineeringSpecification("plate", {"L": "120"}).validate()
    )
    assert any(
        "no variables" in p for p in EngineeringSpecification("plate", {}).validate()
    )


def test_integers_render_without_a_decimal_point():
    # The training set writes t=6, never t=6.0 — a changed literal is a
    # changed prompt.
    spec = EngineeringSpecification("gusset_plate", {"a": 106, "b": 56, "t": 6.0})
    assert "t=6," in spec.to_prompt() + "," or "t=6\n" in spec.to_prompt()
    assert "6.0" not in spec.to_prompt()


def test_variables_render_in_sorted_order():
    spec = EngineeringSpecification("plate", {"t": 5.0, "L": 100.0, "b": 20.0})
    line = [ln for ln in spec.to_prompt().splitlines() if ln.startswith("Variables:")][
        0
    ]
    assert line == "Variables: L=100, b=20, t=5"


def test_unfamiliar_part_class_warns_but_does_not_block():
    assert looks_unfamiliar("mount_plate") is None
    assert looks_unfamiliar("mount_plate_plus_locating_pin") is None
    warning = looks_unfamiliar("quadcopter_frame")
    assert warning and "not one of the" in warning
    # a warning is not a refusal
    spec = EngineeringSpecification("quadcopter_frame", {"L": 100.0})
    assert spec.to_prompt().startswith("Design a parametric quadcopter frame.")


@needs_corpus
def test_family_choice_is_deterministic_and_prefers_the_specific_name():
    from app.services.engineering_spec import choose_family

    assert choose_family("mount_plate")[0] == "mount_plate"
    assert choose_family("mount plate")[0] == "mount_plate"
    assert choose_family("mounting plate")[0] == "mount_plate"
    # "nema 17 mount plate" contains the family name
    assert choose_family("a NEMA 17 mount plate")[0] == "mount_plate"
    # nothing recognisable comes back as a question, not a guess
    family, alternatives = choose_family("flux capacitor")
    assert family is None and alternatives == []


@needs_corpus
def test_intent_becomes_a_specification_without_any_model():
    from orion_agent.harness.spec import SpecParser
    from app.services.engineering_spec import specification_from_intent

    message = (
        "I need an aluminium mounting plate for a NEMA 17, 112 mm long "
        "and 66 wide, 10 mm thick. Milled."
    )
    intent = SpecParser().parse(message)  # regex path, no LLM
    spec, questions = specification_from_intent(intent, part_hint=message)

    assert spec.part_class == "mount_plate"
    # stated numbers survive verbatim
    assert spec.variables["pl"] == 112.0
    assert spec.variables["pw"] == 66.0
    assert spec.variables["pt"] == 10.0
    # unstated ones are filled from the corpus and SAID to be assumed
    for name in ("hr", "mx", "my"):
        assert name in spec.variables
        assert "not stated" in spec.rationale[name]
    assert spec.rationale["pl"] == "stated by the user"
    # and it renders
    assert spec.validate() == []
    assert spec.warnings() == []
    assert "Variables: hr=" in spec.to_prompt()
    assert isinstance(questions, list)


@needs_corpus
def test_defaults_come_from_values_that_have_verified_before():
    """The medians are the reason a planner only has to improve on a working
    part rather than invent one."""
    from orion.family_schema import for_family
    from app.services.engineering_spec import specification_from_intent

    class _Intent:
        part = "wheel hub"
        dimensions: dict = {}
        counts: dict = {}
        material = ""
        manufacturing = ""
        constraints: list = []
        unresolved: list = []

    spec, _ = specification_from_intent(_Intent())
    schema = for_family("wheel_hub")
    assert set(spec.variables) == set(schema.required())
    for name, value in spec.variables.items():
        stat = schema.variables[name]
        assert stat.lo <= value <= stat.hi
    assert spec.warnings() == []


@needs_corpus
def test_unmappable_dimension_becomes_a_question():
    from app.services.engineering_spec import specification_from_intent

    class _Intent:
        part = "mount plate"
        dimensions = {"thickness": 8.0, "dim_4": 6.4}
        counts: dict = {}
        material = ""
        manufacturing = ""
        constraints: list = []
        unresolved: list = []

    spec, questions = specification_from_intent(_Intent())
    assert spec.variables["pt"] == 8.0
    assert any("dim_4" in q for q in questions)


@needs_corpus
def test_numbers_that_reached_no_variable_are_reported():
    """Defaulting is fine when the user said nothing. It is not fine when they
    gave dimensions nobody could read: every guard still holds, every variable
    is in range, and the specification looks perfect while describing a
    different part."""
    from app.services.planner import EngineeringPlanner

    result = EngineeringPlanner().plan(
        "A mount plate with a 47 degree chamfer and an 88 mm keep-out zone"
    )
    orphans = [q for q in result.questions if "reached no" in q]
    assert orphans, "unreadable dimensions were silently replaced by medians"
    assert "88" in orphans[0]


@needs_corpus
def test_a_hole_count_never_becomes_a_hole_radius():
    from app.services.engineering_spec import specification_from_intent

    class _Intent:
        part = "mount plate"
        dimensions = {"thickness": 6.0}
        counts = {"hole": 4}  # "four M5 clearance holes"
        material = ""
        manufacturing = ""
        constraints: list = []
        unresolved: list = []

    spec, _ = specification_from_intent(_Intent())
    assert spec.variables["pt"] == 6.0
    # hr is a radius; a count of four holes must not become a 4 mm radius
    assert spec.rationale["hr"].startswith("not stated")


def test_vocabulary_is_the_real_one():
    vocab = known_vocabulary()
    assert "mount_plate" in vocab["bases"]
    assert "locating_pin" in vocab["attachments"]
