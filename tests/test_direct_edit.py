"""Applying a CAD operation to geometry the user pointed at.

This is the half of editing that `semantic_edit` deliberately cannot reach. A
retune changes a value the design already declares and the contract survives;
adding a feature changes the template, and the assertions the model authored
stop describing the part. Both are legitimate. Only one of them may claim the
old verdict, and keeping that distinction visible is what most of this file
tests.

The other thing under test is **naming**. A person clicked one edge. Every
selector in the authored grammar names a *class* — all vertical edges, every rim
of radius 5 — and an OCC index does not survive a rebuild. `near:<x>,<y>,<z>`
names the geometry itself, which is the only form that means the same thing
after the part changes.
"""

import json

import pytest

from app.services import direct_edit as de

BLOCK = {
    "part_class": "block",
    "variables": {"w": 60.0, "d": 40.0, "h": 20.0},
    "datums": {},
    "design_plan": {},
    "assertions": [
        {
            "id": "a_vol",
            "kind": "body_volume",
            "tier": 1,
            "target": "w*d*h",
            "tol_rel": 0.02,
        }
    ],
    "template": {
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "block", "type": "Pad", "parameters": {"Length": "h"}},
        ],
        "sketches": [
            {
                "id": "s0",
                "plane": "XY",
                "profile": {"builder": "rect", "args": {"w": "w", "h": "d"}},
            }
        ],
        "dependencies": [{"kind": "profile", "source": "s0", "target": "block"}],
    },
    "blueprint_hash": "abc",
}

EDGE = {
    "ref": "#o1.s1.e5",
    "index": 5,
    "stable": "@block.e0",
    "feature": "block",
    "curve": "Line",
    "center": [30.0, 20.0, 10.0],
    "ends": [[30.0, 20.0, 0.0], [30.0, 20.0, 20.0]],
}

FACE = {
    "ref": "#o1.s1.f6",
    "index": 6,
    "stable": "@block.f3",
    "feature": "block",
    "surface": "Plane",
    "area": 2400.0,
    "center": [0.0, 0.0, 20.0],
    "normal": [0.0, 0.0, 1.0],
}


@pytest.fixture
def blueprint():
    return json.loads(json.dumps(BLOCK))


# --------------------------------------------------------------------------- #
# naming the geometry
# --------------------------------------------------------------------------- #
def test_a_pick_becomes_a_selector_that_names_geometry_not_an_index():
    """`Edge5` would name a different edge after any rebuild that renumbers.

    A point does not: it is a statement about where the edge is, which is the
    same claim before and after the part changes.
    """
    assert de.selector_for(EDGE) == "near:30,20,10"


def test_the_selector_uses_the_recorded_centroid_not_the_raw_click():
    """A raycast hit is a few tenths off whatever it struck; a centroid is not.

    That difference decides whether a later rebuild still resolves to the same
    edge, so the selector is built from the topology record rather than from
    the pointer position that produced it.
    """
    element = dict(EDGE, center=[30.000001, 19.9999994, 10.0])

    assert de.selector_for(element) == "near:30,20,10"


def test_geometry_with_no_position_cannot_be_named():
    with pytest.raises(de.DirectEditError):
        de.selector_for({"ref": "#o1.s1.e5"})


# --------------------------------------------------------------------------- #
# planning an operation
# --------------------------------------------------------------------------- #
def test_a_chamfer_on_an_edge_declares_a_variable_not_a_literal(blueprint):
    """A hand-added dimension stays as parametric as a generated one.

    Writing 3.0 into the template would make the feature untunable afterwards
    and would fail the static checker's no-literals rule.
    """
    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})

    assert op.variables == {"chamfer_size": 3.0}
    assert op.parameters["Size"] == "chamfer_size"
    assert op.parameters["_Edges"] == "near:30,20,10"
    assert op.on_feature == "block"


def test_an_operation_declares_that_it_breaks_the_contract(blueprint):
    """The assertions describe the design before this feature existed."""
    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})

    assert op.as_dict()["contract_broken"] is True


def test_a_variable_name_that_is_taken_is_not_reused(blueprint):
    """Two chamfers must not share one dimension by accident."""
    blueprint["variables"]["chamfer_size"] = 1.0

    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})

    assert "chamfer_size2" in op.variables
    assert blueprint["variables"]["chamfer_size"] == 1.0


def test_an_edge_operation_refuses_a_face_and_the_other_way_round(blueprint):
    with pytest.raises(de.DirectEditError) as exc:
        de.plan(blueprint, "Chamfer", FACE, {"Size": 3.0})
    assert "edge" in str(exc.value)

    with pytest.raises(de.DirectEditError) as exc:
        de.plan(blueprint, "Draft", EDGE, {"Angle": 2.0})
    assert "face" in str(exc.value)


def test_thickness_is_given_the_tip_to_hollow(blueprint):
    """Fillet, Chamfer and Draft fall back to the tip; Thickness does not.

    Without an explicit base it reports "missing thickness base" and builds
    nothing, so the base is named rather than left to a fallback that is absent.
    """
    op = de.plan(blueprint, "Thickness", FACE, {"Value": 2.0})

    assert op.parameters["_Base"] == {"object": "block"}
    assert op.parameters["_Faces"] == "near:0,0,20"


def test_hollowing_a_part_with_no_solid_is_refused(blueprint):
    blueprint["template"]["features"] = [
        {"id": "Body", "type": "Body", "parameters": {}}
    ]

    with pytest.raises(de.DirectEditError):
        de.plan(blueprint, "Thickness", FACE, {"Value": 2.0})


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #
def test_an_operation_that_is_not_wired_up_says_why(blueprint):
    """A tool that appears to work and produces nothing is worse than one that
    admits it is not built."""
    with pytest.raises(de.DirectEditError) as exc:
        de.plan(blueprint, "Pocket", FACE, {})

    assert "profile" in str(exc.value)


def test_an_operation_that_does_not_exist_is_refused_by_name(blueprint):
    with pytest.raises(de.DirectEditError) as exc:
        de.plan(blueprint, "Unfold", EDGE, {"Size": 1.0})

    assert "Unfold" in str(exc.value)


def test_a_missing_dimension_is_refused(blueprint):
    with pytest.raises(de.DirectEditError) as exc:
        de.plan(blueprint, "Chamfer", EDGE, {})

    assert "distance" in str(exc.value).lower()


@pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan"), "wide"])
def test_a_dimension_that_cannot_build_never_reaches_the_kernel(blueprint, bad):
    with pytest.raises(de.DirectEditError):
        de.plan(blueprint, "Chamfer", EDGE, {"Size": bad})


def test_a_draft_angle_outside_its_range_is_refused(blueprint):
    with pytest.raises(de.DirectEditError):
        de.plan(blueprint, "Draft", FACE, {"Angle": 80.0})


# --------------------------------------------------------------------------- #
# applying
# --------------------------------------------------------------------------- #
def test_applying_appends_the_feature_and_leaves_the_original_alone(blueprint):
    before = json.dumps(blueprint, sort_keys=True)

    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})
    edited = de.apply(blueprint, op)

    assert json.dumps(blueprint, sort_keys=True) == before
    kinds = [f["type"] for f in edited["template"]["features"]]
    assert kinds[-1] == "Chamfer"
    assert edited["variables"]["chamfer_size"] == 3.0
    assert edited["blueprint_hash"] == ""


def test_the_template_really_did_change(blueprint):
    """The claim `contract_broken` makes, checked rather than asserted."""
    from app.services import blueprint_edit

    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})
    edited = de.apply(blueprint, op)

    assert blueprint_edit.template_changed(blueprint, edited) is True


# --------------------------------------------------------------------------- #
# a build that produced a solid is not a build that applied the operation
# --------------------------------------------------------------------------- #
def _bundle(built=(), errors=(), unsupported=()):
    return {
        "success": True,
        "build_log": {
            "build_report": {
                "built": [{"id": i} for i in built],
                "recompute_errors": list(errors),
                "unsupported": list(unsupported),
            }
        },
    }


def test_a_dressup_that_failed_to_recompute_is_reported(blueprint):
    """The bug this was written for.

    A Draft that fails leaves the previous geometry standing, so the build
    succeeds, the volume is unchanged and every assertion still passes. Both a
    Draft and a Thickness were observed returning `success: true, verdict:
    verified` while doing nothing at all — the kernel had said exactly what went
    wrong and the route discarded it.
    """
    bundle = _bundle(
        built=["block"],
        errors=[{"id": "draft1", "error": "invalid after recompute"}],
    )

    assert de.build_failure(bundle, "draft1") == "invalid after recompute"


def test_a_cascading_failure_names_its_own_reason(blueprint):
    """Thickness reported "missing thickness base" because the Draft before it
    never built. Each failure keeps its own message rather than the first."""
    bundle = _bundle(
        built=["block"],
        errors=[
            {"id": "draft1", "error": "invalid after recompute"},
            {"id": "thickness1", "error": "missing thickness base"},
        ],
    )

    assert de.build_failure(bundle, "thickness1") == "missing thickness base"


def test_an_operation_the_compiler_does_not_support_is_reported(blueprint):
    bundle = _bundle(built=["block"], unsupported=[{"id": "x1", "type": "Loft"}])

    assert "Loft" in (de.build_failure(bundle, "x1") or "")


def test_a_feature_missing_from_the_built_list_is_not_silently_accepted():
    """Absence is a failure too. A compiler that skips a feature without
    logging an error must not read as success."""
    bundle = _bundle(built=["block", "chamfer1"])

    assert de.build_failure(bundle, "fillet1") is not None
    assert de.build_failure(bundle, "chamfer1") is None


def test_a_build_that_produced_nothing_is_left_to_the_bundles_own_error():
    """Only claim a per-feature failure when the build otherwise succeeded —
    otherwise the user gets two different explanations for one problem."""
    assert de.build_failure(_bundle(), "chamfer1") is None
    assert de.build_failure({}, "chamfer1") is None
    assert de.build_failure(_bundle(built=["block"]), None) is None


def test_the_added_feature_can_be_identified_for_that_check(blueprint):
    """`append_feature` generates the id internally, so it has to be recovered
    from the edited template before anything can ask whether it built."""
    op = de.plan(blueprint, "Chamfer", EDGE, {"Size": 3.0})
    edited = de.apply(blueprint, op)

    assert de.added_feature_id(edited) == "chamfer1"


# --------------------------------------------------------------------------- #
# operation-specific wiring
# --------------------------------------------------------------------------- #
def test_a_draft_pivots_about_the_far_face_not_itself(blueprint):
    """The compiler defaults a draft's neutral plane to "bottom". Drafting the
    bottom face then asks it to pivot about itself, which OCC rejects — the
    exact silent no-op above. The neutral plane is chosen opposite the pick.
    """
    top = dict(FACE, normal=[0.0, 0.0, 1.0])
    bottom = dict(FACE, normal=[0.0, 0.0, -1.0], center=[0.0, 0.0, 0.0])

    assert (
        de.plan(blueprint, "Draft", top, {"Angle": 3.0}).parameters["_NeutralPlane"]
        == "bottom"
    )
    assert (
        de.plan(blueprint, "Draft", bottom, {"Angle": 3.0}).parameters["_NeutralPlane"]
        == "top"
    )


def test_a_wall_drafts_about_the_bottom(blueprint):
    """Mould-release convention, and what the compiler would have chosen."""
    wall = dict(FACE, normal=[1.0, 0.0, 0.0], center=[30.0, 0.0, 10.0])

    op = de.plan(blueprint, "Draft", wall, {"Angle": 3.0})

    assert op.parameters["_NeutralPlane"] == "bottom"


def test_the_catalogue_reports_what_is_planned_and_why():
    """A missing tool reads as an oversight; one that names what it needs is a
    roadmap the user can plan around."""
    cat = de.catalogue()

    kinds = {o["kind"] for o in cat["operations"]}
    assert {"Chamfer", "Fillet", "Draft", "Thickness"} <= kinds
    assert all(o["target"] in ("edge", "face") for o in cat["operations"])
    assert all(p["reason"] for p in cat["planned"])
