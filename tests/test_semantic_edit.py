"""Turning a click into a Blueprint change, without losing the design's meaning.

The layer under test closes one specific gap: the topology layer resolves a
click to a *feature*, but ``blueprint_edit.retune`` takes *variables*, and
nothing connected the two because the connection is not stored anywhere — it has
to be read out of the template, where a parameter is an expression.

Three properties are what make this an editor rather than a number box, and each
has tests here:

* **a dimension often lives in the sketch** — a bore's radius is an argument of
  the profile it was cut with, reached through a ``profile`` dependency edge;
* **changing one number moves others, and that is the design working** — an edit
  is planned first and says exactly what else moves;
* **an expression is not invertible** — ``t * 2`` cannot be "set to 14" without
  inventing a value for ``t``, so it is refused by name.

The fixture is the part the whole pipeline was verified against: a 40x40 plate,
a through bore, a corner fillet. ``t`` deliberately drives both the pad and the
pocket, because a shared variable is the interesting case.
"""

import json

import pytest

from app.services import semantic_edit as se

BLUEPRINT = {
    "part_class": "plate",
    "variables": {"t": 10.0, "w": 40.0, "hole_r": 5.0, "fr": 2.0},
    "datums": {},
    "design_plan": {},
    "assertions": [
        {
            "id": "a_vol",
            "kind": "body_volume",
            "tier": 1,
            "target": "w*w*t - pi*hole_r**2*t",
            "tol_rel": 0.02,
        },
        {"id": "a_solid", "kind": "solids", "tier": 1, "target": "1", "tol_rel": 0.0},
    ],
    "template": {
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "base_pad", "type": "Pad", "parameters": {"Length": "t"}},
            {"id": "s1", "type": "Sketch", "parameters": {}},
            {
                "id": "bore",
                "type": "Pocket",
                "parameters": {"Length": "t", "Type": "ThroughAll"},
            },
            {
                "id": "corner_round",
                "type": "Fillet",
                "parameters": {"Radius": "fr", "_Edges": "vertical"},
            },
        ],
        "sketches": [
            {
                "id": "s0",
                "plane": "XY",
                "profile": {"builder": "rect", "args": {"w": "w", "h": "w"}},
            },
            {
                "id": "s1",
                "plane": "XY",
                "profile": {"builder": "circle", "args": {"r": "hole_r"}},
            },
        ],
        "dependencies": [
            {"kind": "profile", "source": "s0", "target": "base_pad"},
            {"kind": "profile", "source": "s1", "target": "bore"},
        ],
    },
    "blueprint_hash": "abc",
}


@pytest.fixture
def blueprint():
    return json.loads(json.dumps(BLUEPRINT))


def _named(parameters, name):
    return next(p for p in parameters if p.name == name)


# --------------------------------------------------------------------------- #
# what a click can reach
# --------------------------------------------------------------------------- #
def test_a_bores_radius_is_found_in_the_sketch_it_was_cut_with(blueprint):
    """The dimension a user means is not where the file format keeps it.

    ``Pocket`` owns a depth. The radius is an argument of the profile sketch,
    and only the ``profile`` dependency edge says which sketch belongs to which
    cut. Without following it, clicking a bore wall and asking for "radius"
    finds nothing — which was the state before this module.
    """
    parameters = se.editable(blueprint, "bore")

    radius = _named(parameters, "profile.r")
    assert radius.value == 5.0
    assert radius.site.kind == "sketch"
    assert radius.direct is True
    assert radius.variables == ["hole_r"]


def test_a_feature_also_exposes_its_own_parameters(blueprint):
    depth = _named(se.editable(blueprint, "bore"), "Length")

    assert depth.value == 10.0
    assert depth.site.kind == "feature"


def test_a_shared_dimension_says_what_it_shares_with(blueprint):
    """``t`` drives the pad and the pocket. That is the design, and it shows."""
    depth = _named(se.editable(blueprint, "bore"), "Length")

    assert depth.shared_with == ["base_pad.Length"]

    radius = _named(se.editable(blueprint, "bore"), "profile.r")
    assert radius.shared_with == []


def test_enums_and_selectors_are_not_offered_as_dimensions(blueprint):
    """``Type: ThroughAll`` and ``_Edges: vertical`` carry meaning, not a number.

    Offering them as editable would put a slider on a word.
    """
    names = [p.name for p in se.editable(blueprint, "bore")]
    assert "Type" not in names

    names = [p.name for p in se.editable(blueprint, "corner_round")]
    assert names == ["Radius"]


def test_an_unknown_feature_is_refused_by_name(blueprint):
    with pytest.raises(se.EditError) as exc:
        se.editable(blueprint, "nope")

    assert "bore" in str(exc.value)


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #
def test_a_plan_names_the_variable_behind_the_dimension(blueprint):
    plan = se.plan(blueprint, "bore", "profile.r", 7.0)

    assert (plan.variable, plan.before, plan.after) == ("hole_r", 5.0, 7.0)
    assert plan.also_moves == []


def test_a_plan_reports_everything_else_that_moves(blueprint):
    """The point of planning.

    A parametric design ties dimensions together on purpose. Changing the pad
    thickness moves the through-cut with it — the user should see that before
    committing, not infer it from the rebuilt geometry. A direct-modelling tool
    would silently break the link instead.
    """
    plan = se.plan(blueprint, "base_pad", "Length", 14.0)

    assert plan.variable == "t"
    assert [(m.path, m.before, m.after) for m in plan.also_moves] == [
        ("bore.Length", 10.0, 14.0)
    ]


def test_a_plan_reports_the_assertion_targets_that_move(blueprint):
    """A moved target is not a weakened contract.

    The check is an expression over the same variables, so it travels with the
    part it grades. Reporting it beside the geometry moves — rather than mixed
    in with them — is what stops a correct parametric edit looking like the
    guarantees were dropped.
    """
    plan = se.plan(blueprint, "bore", "profile.r", 7.0)

    moved = {m.path for m in plan.assertions_moved}
    assert moved == {"a_vol.target"}
    assert plan.contract_preserved is True


def test_a_computed_dimension_is_refused_rather_than_solved(blueprint):
    """``t * 2`` cannot be "set to 14" without inventing a value for ``t``.

    Solving numerically would build a part from a number the user never typed,
    and would move everything else ``t`` drives as a side effect. Refusing and
    naming the variable is the honest answer.
    """
    blueprint["template"]["features"][4]["parameters"]["Length"] = "t * 2"

    with pytest.raises(se.EditError) as exc:
        se.plan(blueprint, "bore", "Length", 14.0)

    assert "computed from t" in str(exc.value)
    assert "edit t instead" in str(exc.value)


def test_a_parameter_the_feature_does_not_have_lists_the_ones_it_does(blueprint):
    with pytest.raises(se.EditError) as exc:
        se.plan(blueprint, "corner_round", "Depth", 3.0)

    assert "'Radius'" in str(exc.value)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "wide"])
def test_a_non_finite_value_never_reaches_the_kernel(blueprint, bad):
    with pytest.raises(se.EditError):
        se.plan(blueprint, "corner_round", "Radius", bad)


# --------------------------------------------------------------------------- #
# impact
# --------------------------------------------------------------------------- #
def test_impact_answers_what_if_i_change_this(blueprint):
    report = se.impact(blueprint, "t")

    assert report["value"] == 10.0
    assert report["drives"] == ["base_pad.Length", "bore.Length"]
    assert report["assertions"] == ["a_vol"]


def test_impact_refuses_a_variable_the_blueprint_does_not_declare(blueprint):
    with pytest.raises(se.EditError):
        se.impact(blueprint, "nope")


# --------------------------------------------------------------------------- #
# applying
# --------------------------------------------------------------------------- #
def test_applying_changes_the_value_and_nothing_structural(blueprint):
    """Intent survives because a retune moves values, never the template.

    The assertions are expressions over those same values, so they still mean
    what they meant and the rebuilt part is graded against its own contract.
    """
    from app.services import blueprint_edit

    edited = se.apply(blueprint, se.plan(blueprint, "bore", "profile.r", 7.0))

    assert edited["variables"]["hole_r"] == 7.0
    assert blueprint_edit.template_changed(blueprint, edited) is False
    assert edited["blueprint_hash"] == ""


def test_applying_leaves_the_original_untouched(blueprint):
    """A plan is a proposal; nothing is committed until apply returns."""
    before = json.dumps(blueprint, sort_keys=True)

    se.apply(blueprint, se.plan(blueprint, "bore", "profile.r", 7.0))

    assert json.dumps(blueprint, sort_keys=True) == before


def test_an_edit_routes_through_retune_so_its_rules_still_apply(blueprint):
    """Undeclared names and non-finite values are refused in one place only.

    A second path into the variables block would be a second place for those
    rules to be forgotten.
    """
    plan = se.plan(blueprint, "bore", "profile.r", 7.0)
    blueprint["variables"].pop("hole_r")

    from app.services.blueprint_edit import EditError as RetuneError

    with pytest.raises(RetuneError):
        se.apply(blueprint, plan)
