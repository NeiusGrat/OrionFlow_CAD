"""The read-only bridge over a finished build — what makes the geometry tools
reachable from a cloud session that has no FreeCAD in it.

The fixture is not invented. It is the record FreeCAD 1.1.3 actually produced
for ``families.make("clearance_plate", length=120, width=80, t=10, hole_r=5,
hole_dx=40)``, trimmed to the elements the assertions use, and the Blueprint is
built from that same family here rather than pasted in — so the two halves this
module joins (the sidecar and the frozen contract) describe one part, which is
the only condition under which the joining means anything.

The load-bearing assertions are about honesty, not plumbing:

* an estimated distance must come back marked as an estimate, with its method
* a write must be refused rather than half-performed
* a parameter must arrive with the expression it was derived from
"""

import pytest

from app.services import part_bridge as pb


@pytest.fixture
def record():
    """The 120 x 80 x 10 plate with two 5 mm bores at x = +/- 40."""
    return {
        "schema": "orionflow-topology-v1",
        "attribution": "element_map",
        "counts": {
            "occurrences": 1,
            "shapes": 1,
            "faces": 8,
            "edges": 18,
            "vertices": 12,
            "features": 1,
            "unattributed": 0,
        },
        "truncated": [],
        "occurrences": [
            {
                "ref": "#o1",
                "name": "Body",
                "label": "Body",
                "shape": "#o1.s1",
                "bbox": [-60.0, -40.0, 0.0, 60.0, 40.0, 10.0],
            }
        ],
        "faces": [
            _face(1, "Plane", [-0.0, -40.0, 5.0], [0.0, -1.0, -0.0],
                  [-60.0, -40.0, 0.0, 60.0, -40.0, 10.0], "@plate.f2"),
            _face(2, "Plane", [60.0, -0.0, 5.0], [1.0, -0.0, -0.0],
                  [60.0, -40.0, 0.0, 60.0, 40.0, 10.0], "@plate.f7"),
            _face(5, "Cylinder", [-40.0, -0.0, 5.0], [1.0, -0.0, 0.0],
                  [-45.0, -5.0, 0.0, -35.0, 5.0, 10.0], "@plate.f1", radius=5.0),
            _face(6, "Cylinder", [40.0, -0.0, 5.0], [1.0, -0.0, 0.0],
                  [35.0, -5.0, 0.0, 45.0, 5.0, 10.0], "@plate.f6", radius=5.0),
            _face(7, "Plane", [0.0, 0.0, 0.0], [-0.0, -0.0, -1.0],
                  [-60.0, -40.0, 0.0, 60.0, 40.0, 0.0], "@plate.f3"),
            _face(8, "Plane", [0.0, 0.0, 10.0], [0.0, 0.0, 1.0],
                  [-60.0, -40.0, 10.0, 60.0, 40.0, 10.0], "@plate.f4"),
        ],
        "edges": [
            {
                "ref": "#o1.s1.e1", "index": 1, "element": "Edge1",
                "feature": "plate", "curve": "Line", "length": 10.0,
                "center": [-60.0, -40.0, 5.0],
                "ends": [[-60.0, -40.0, 0.0], [-60.0, -40.0, 10.0]],
                "stable": "@plate.e0",
            }
        ],
        "vertices": [
            _vertex(1, [-60.0, -40.0, 0.0], "@plate.v0"),
            _vertex(2, [-60.0, -40.0, 10.0], "@plate.v1"),
            _vertex(3, [60.0, -40.0, 0.0], "@plate.v8"),
        ],
        "features": {
            "plate": {
                "type": "PartDesign::Pad",
                "label": "plate",
                "build_index": 0,
                "faces": ["#o1.s1.f%d" % i for i in (1, 2, 5, 6, 7, 8)],
                "edges": ["#o1.s1.e1"],
                "vertices": ["#o1.s1.v1", "#o1.s1.v2", "#o1.s1.v3"],
                "blueprint_feature": True,
            }
        },
    }


def _face(index, surface, center, normal, bbox, stable, radius=None):
    rec = {
        "ref": "#o1.s1.f%d" % index,
        "index": index,
        "element": "Face%d" % index,
        "feature": "plate",
        "lineage": ["plate", "s_p"],
        "surface": surface,
        "center": center,
        "normal": normal,
        "bbox": bbox,
        "stable": stable,
    }
    if radius is not None:
        rec["radius"] = radius
    return rec


def _vertex(index, center, stable):
    return {
        "ref": "#o1.s1.v%d" % index,
        "index": index,
        "element": "Vertex%d" % index,
        "feature": "plate",
        "center": center,
        "stable": stable,
    }


@pytest.fixture
def part():
    from orion import families

    bp = families.make(
        "clearance_plate", length=120.0, width=80.0, t=10.0, hole_r=5.0, hole_dx=40.0
    )
    return {
        "part_class": bp.part_class,
        "blueprint": bp.to_dict(),
        "stats": {
            "volume_mm3": 94429.20367320509,
            "solids": 1,
            "valid": True,
            "watertight": True,
            "bbox_mm": [120.0, 80.0, 10.0],
        },
    }


@pytest.fixture
def bridge(record, part):
    b = pb.PartBridge(request_id="build-1", part=part)
    # Injected rather than loaded: this suite is about what the bridge does
    # with a record, not about where the record was fetched from.
    b._topology, b._topology_loaded = record, True
    return b


# --------------------------------------------------------------------------- #
# inspection
# --------------------------------------------------------------------------- #
def test_the_body_and_its_features_are_both_listed(bridge):
    names = [o["name"] for o in bridge.list_objects()["objects"]]
    assert names == ["Body", "plate"]


def test_the_body_shape_carries_the_measured_volume_and_real_counts(bridge):
    shape = bridge.inspect_topology()["shapes"][0]
    assert shape["faces"] == 8 and shape["edges"] == 18
    assert shape["cylindrical_faces"] == 2
    assert shape["surface_types"] == {"Plane": 4, "Cylinder": 2}
    assert shape["bounding_box"]["size"] == [120.0, 80.0, 10.0]
    assert shape["volume"] == pytest.approx(94429.2, rel=1e-4)


def test_one_feature_can_be_inspected_on_its_own(bridge):
    shape = bridge.inspect_topology("plate")["shapes"][0]
    assert shape["name"] == "plate"
    assert shape["cylindrical_faces"] == 2


def test_an_unknown_object_names_what_the_build_does_have(bridge):
    with pytest.raises(pb.PartBridgeError) as exc:
        bridge.inspect_topology("gusset")
    assert "Body" in str(exc.value) and "plate" in str(exc.value)


def test_a_build_with_no_topology_record_says_so_rather_than_guessing(part):
    bare = pb.PartBridge(request_id="", part=part)
    bare._topology, bare._topology_loaded = None, True
    with pytest.raises(pb.PartBridgeError) as exc:
        bare.list_objects()
    assert "no topology record" in str(exc.value)


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #
def test_a_parameter_arrives_with_the_expression_that_produced_it(bridge):
    """The number alone loses the one fact that separates derived from invented."""
    params = bridge.get_object_parameters("plate")["parameters"]
    assert params["Length"] == {"value": 10.0, "expression": "t"}


def test_a_sketch_reports_its_profile_rather_than_an_empty_dict(bridge):
    """A sketch's dimensions live in its profile builder, not its properties."""
    params = bridge.get_object_parameters("s_p")["parameters"]
    assert params["profile_builder"] == "rect_with_holes"
    assert params["plane"] == "XY"
    assert params["w"] == {"value": 120.0, "expression": "length"}
    assert params["geometry"] == {"LineSegment": 4, "Circle": 2}


def test_a_blueprint_backed_part_is_tier_a(bridge):
    assert bridge.get_model_tier()["tier"] == "A"


def test_the_featuregraph_is_the_resolved_blueprint_without_its_analysis(bridge):
    graph = bridge.extract_featuregraph()["graph"]
    assert "_analysis" not in graph
    assert [f["id"] for f in graph["features"]] == ["Body", "s_p", "plate"]


# --------------------------------------------------------------------------- #
# measurement — the honesty assertions
# --------------------------------------------------------------------------- #
def test_vertex_to_vertex_is_exact(bridge):
    result = bridge.measure({"sub": "Vertex1"}, {"sub": "Vertex3"})
    assert result["exact"] is True
    assert result["distance"] == pytest.approx(120.0)


def test_two_parallel_faces_that_overlap_give_the_exact_thickness(bridge):
    """Top and bottom of the plate: the shortest path runs along the normal."""
    result = bridge.measure({"sub": "Face7"}, {"sub": "Face8"})
    assert result["exact"] is True
    assert result["distance"] == pytest.approx(10.0)
    assert "plane-to-parallel-plane" in result["method"]


def test_two_curved_faces_are_reported_as_a_bound_not_as_a_distance(bridge):
    """Two 5 mm bores 80 mm apart: 70 mm of material, and we do not claim more.

    This is the assertion the module exists for. A centroid separation dressed
    up as a minimum distance is a number nobody would think to question.
    """
    result = bridge.measure({"sub": "Face5"}, {"sub": "Face6"})
    assert result["exact"] is False
    assert "bounding-box lower bound" in result["method"]
    assert result["lower_bound"] == pytest.approx(70.0)
    assert result["centroid_distance"] == pytest.approx(80.0)


def test_a_point_on_a_plane_it_projects_onto_is_exact(bridge):
    result = bridge.measure({"sub": "Vertex2"}, {"sub": "Face8"})
    assert result["exact"] is True
    assert result["distance"] == pytest.approx(0.0)


def test_both_selector_grammars_and_bare_element_names_resolve(bridge):
    by_element = bridge.measure({"sub": "Face7"}, {"sub": "Face8"})
    by_index = bridge.measure({"sub": "#f7"}, {"sub": "#o1.s1.f8"})
    by_stable = bridge.measure({"sub": "@plate.f3"}, {"sub": "@plate.f4"})
    assert by_element["distance"] == by_index["distance"] == by_stable["distance"]


def test_an_unresolvable_element_names_the_grammars_it_would_accept(bridge):
    with pytest.raises(pb.PartBridgeError) as exc:
        bridge.measure({"sub": "Face7"}, {"sub": "Flange"})
    assert "@bore.f0" in str(exc.value)


# --------------------------------------------------------------------------- #
# the write half
# --------------------------------------------------------------------------- #
def test_a_write_is_refused_with_its_reason(bridge):
    """A finished build has no document to edit. Half-doing it would leave an
    ungraded change in front of the user."""
    with pytest.raises(pb.PartBridgeError) as exc:
        bridge.set_parameter("plate", "Length", 12.0)
    assert "live FreeCAD document" in str(exc.value)


# --------------------------------------------------------------------------- #
# what the model actually sees
# --------------------------------------------------------------------------- #
def test_the_registry_exposes_inspection_and_withholds_mutation(bridge):
    from orion_agent.harness.tools.registry import build_part_registry

    reg = build_part_registry(bridge)
    for name in ("list_objects", "inspect_topology", "get_parameters", "measure",
                 "get_featuregraph", "get_model_tier"):
        assert reg.get(name) is not None, name
    for name in ("set_parameter", "edit_feature", "write_code", "import_shape",
                 "delete_object", "undo"):
        assert reg.get(name) is None, name


def test_an_estimated_distance_says_so_in_the_text_the_model_reads(bridge):
    """The raw dict never reaches the model — only this string does."""
    from orion_agent.harness.tools.registry import build_part_registry

    reg = build_part_registry(bridge)
    result = reg.execute("measure", {"a": {"sub": "Face5"}, "b": {"sub": "Face6"}})
    assert result.ok
    assert "NOT an exact minimum distance" in result.content
    assert "70.0" in result.content

    exact = reg.execute("measure", {"a": {"sub": "Face7"}, "b": {"sub": "Face8"}})
    assert "exact" in exact.content and "NOT an exact" not in exact.content


def test_a_bridge_is_only_offered_when_there_is_something_to_inspect(part):
    assert pb.for_part("", None) is None
    assert pb.for_part("build-1", None) is not None
    assert pb.for_part("", part) is not None
