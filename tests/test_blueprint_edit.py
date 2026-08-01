"""Hand edits to a frozen Blueprint.

The distinction these tests exist to pin down: retuning a declared variable
keeps the model's assertions meaningful, appending a feature does not. Getting
that backwards would let the studio show a VERIFIED badge over geometry nobody
verified, which is the one failure this whole contract exists to prevent.
"""

import pytest

from app.services import blueprint_edit as be


@pytest.fixture
def plate():
    """A minimal, valid template: a sketch, a pad, and one variable."""
    return {
        "part_class": "plate",
        "variables": {"thick": 6.0, "width": 40.0},
        "datums": {},
        "design_plan": {},
        "assertions": [],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad", "parameters": {"Length": "thick"}},
            ],
            "sketches": [
                {"id": "s0", "plane": "XY", "profile": {"builder": "rect", "args": {"w": "width", "h": "width"}}}
            ],
            "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"}],
        },
    }


class TestRetune:
    def test_sets_a_declared_variable(self, plate):
        out = be.retune(plate, {"thick": 9.5})
        assert out["variables"]["thick"] == 9.5
        assert out["variables"]["width"] == 40.0

    def test_leaves_the_original_alone(self, plate):
        be.retune(plate, {"thick": 9.5})
        assert plate["variables"]["thick"] == 6.0

    def test_refuses_a_name_the_blueprint_never_declared(self, plate):
        # Adding one here would introduce a dimension no assertion covers while
        # the report still said VERIFIED.
        with pytest.raises(be.EditError, match="no variable named"):
            be.retune(plate, {"invented": 3.0})

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "eight"])
    def test_refuses_values_that_are_not_finite_numbers(self, plate, bad):
        with pytest.raises(be.EditError):
            be.retune(plate, {"thick": bad})

    def test_clears_the_hash(self, plate):
        plate["blueprint_hash"] = "deadbeef"
        assert be.retune(plate, {"thick": 7.0})["blueprint_hash"] == ""

    def test_does_not_break_the_contract(self, plate):
        # Assertions are expressions over the variables, so they follow the
        # value rather than being invalidated by it.
        assert be.template_changed(plate, be.retune(plate, {"thick": 9.5})) is False


class TestAppendFeature:
    def test_adds_a_dressup_with_a_named_dimension(self, plate):
        out = be.append_feature(
            plate, "Fillet", parameters={"Radius": "fillet_r_1", "_Edges": "all"},
            variables={"fillet_r_1": 2.0},
        )
        assert out["variables"]["fillet_r_1"] == 2.0
        added = out["template"]["features"][-1]
        assert added["type"] == "Fillet"
        assert added["parameters"]["Radius"] == "fillet_r_1"

    def test_breaks_the_contract(self, plate):
        out = be.append_feature(
            plate, "Chamfer", parameters={"Size": "c1"}, variables={"c1": 1.0}
        )
        # The template changed, so the model's assertions no longer describe
        # what comes out of the kernel.
        assert be.template_changed(plate, out) is True

    def test_a_profile_operation_brings_its_sketch_and_dependency(self, plate):
        out = be.append_feature(
            plate, "Pocket",
            parameters={"Length": "d1", "Type": "Length"},
            variables={"d1": 4.0, "r1": 5.0},
            sketch={"builder": "circle", "plane": "XY", "args": {"r": "r1"}},
        )
        features = out["template"]["features"]
        # The sketch has to be built before the operation that consumes it.
        ids = [f["id"] for f in features]
        assert ids.index("s_manual1") < ids.index("pocket1")
        assert out["template"]["sketches"][-1]["profile"]["builder"] == "circle"
        assert {"source": "s_manual1", "target": "pocket1", "kind": "profile"} in out[
            "template"
        ]["dependencies"]

    def test_refuses_a_profile_operation_with_no_profile(self, plate):
        with pytest.raises(be.EditError, match="needs a profile"):
            be.append_feature(plate, "Pad", parameters={"Length": "d"}, variables={"d": 2.0})

    def test_refuses_a_profile_on_a_dressup(self, plate):
        with pytest.raises(be.EditError, match="does not take a profile"):
            be.append_feature(
                plate, "Fillet", parameters={"Radius": "r"}, variables={"r": 1.0},
                sketch={"builder": "circle", "args": {"r": "r"}},
            )

    def test_refuses_an_unknown_profile_builder(self, plate):
        with pytest.raises(be.EditError, match="not a profile"):
            be.append_feature(
                plate, "Pad", parameters={"Length": "d"}, variables={"d": 2.0},
                sketch={"builder": "spline_of_theseus", "args": {}},
            )

    def test_refuses_a_profile_missing_an_argument(self, plate):
        with pytest.raises(be.EditError, match="needs"):
            be.append_feature(
                plate, "Pad", parameters={"Length": "d"}, variables={"d": 2.0, "w": 5.0},
                sketch={"builder": "rect", "args": {"w": "w"}},  # no h
            )

    def test_refuses_a_variable_that_already_exists(self, plate):
        with pytest.raises(be.EditError, match="already declares"):
            be.append_feature(
                plate, "Fillet", parameters={"Radius": "thick"}, variables={"thick": 1.0}
            )

    def test_refuses_an_unusable_variable_name(self, plate):
        with pytest.raises(be.EditError, match="not a usable variable name"):
            be.append_feature(
                plate, "Fillet", parameters={"Radius": "r"}, variables={"2r!": 1.0}
            )

    def test_refuses_a_feature_the_workbench_does_not_offer(self, plate):
        with pytest.raises(be.EditError, match="cannot be added by hand"):
            be.append_feature(plate, "Wormhole", parameters={})

    def test_refuses_a_non_principal_sketch_plane(self, plate):
        with pytest.raises(be.EditError, match="principal plane"):
            be.append_feature(
                plate, "Pad", parameters={"Length": "d"}, variables={"d": 2.0, "r": 3.0},
                sketch={"builder": "circle", "plane": "XQ", "args": {"r": "r"}},
            )

    def test_ids_do_not_collide_across_repeated_edits(self, plate):
        once = be.append_feature(
            plate, "Fillet", parameters={"Radius": "a"}, variables={"a": 1.0}
        )
        twice = be.append_feature(
            once, "Fillet", parameters={"Radius": "b"}, variables={"b": 2.0}
        )
        ids = [f["id"] for f in twice["template"]["features"]]
        assert len(ids) == len(set(ids))
        assert "fillet1" in ids and "fillet2" in ids


class TestChecksSurviveTheRoundTrip:
    """An edit must still satisfy the static checker, or the kernel never runs."""

    def test_a_hand_edit_passes_the_no_literals_rule(self, plate):
        from orion.blueprint import Blueprint

        out = be.append_feature(
            plate, "Fillet", parameters={"Radius": "fillet_r_1", "_Edges": "all"},
            variables={"fillet_r_1": 2.0},
        )
        # freeze() runs check_blueprint; a bare number would raise here.
        assert Blueprint.from_dict(out).freeze().blueprint_hash

    def test_a_literal_dimension_is_still_refused(self, plate):
        from orion.blueprint import Blueprint, BlueprintError

        out = be.append_feature(plate, "Fillet", parameters={"Radius": 2.5})
        with pytest.raises(BlueprintError, match="literal"):
            Blueprint.from_dict(out).freeze()
