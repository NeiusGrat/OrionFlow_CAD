"""Selectors, lookup and picking — the consumer side of the sidecar.

The fixture is the record FreeCAD 1.1.1 actually produced for a 40x40x10 pad
with a 5 mm through bore and a 2 mm fillet on the four vertical edges, trimmed
to the faces the assertions use. Real numbers rather than invented ones, because
the picking maths is only worth testing against geometry that exists: a bore of
radius 5 about the origin is at distance 0 from (5, 0, 5) or the maths is wrong.

Two selector forms are exercised throughout, and the distinction between them is
the point of the module:

``#o1.s1.f7``   an address in one built shape; exact, and invalidated by any
                rebuild that shifts an OCC index
``@bore.f0``    a face of a named feature; survives a rebuild that does not
                change that feature
"""

import pytest

from app.services import topology as topo


@pytest.fixture
def record():
    return {
        "schema": "orionflow-topology-v1",
        "attribution": "element_map",
        "counts": {"faces": 4, "edges": 1, "vertices": 0, "unattributed": 0},
        "truncated": [],
        "occurrences": [
            {
                "ref": "#o1",
                "name": "Body",
                "shape": "#o1.s1",
                "bbox": [-20, -20, 0, 20, 20, 10],
            }
        ],
        "faces": [
            {
                "ref": "#o1.s1.f1",
                "index": 1,
                "stable": "@base_pad.f1",
                "feature": "base_pad",
                "lineage": ["corner_round", "base_pad"],
                "surface": "Plane",
                "area": 360.0,
                "center": [0.0, -20.0, 5.0],
                "normal": [0.0, -1.0, 0.0],
                "position": [0.0, -20.0, 0.0],
                "bbox": [-18.0, -20.0, 0.0, 18.0, -20.0, 10.0],
            },
            {
                "ref": "#o1.s1.f5",
                "index": 5,
                "stable": "@base_pad.f3",
                "feature": "base_pad",
                "lineage": ["corner_round", "base_pad"],
                "surface": "Plane",
                "area": 1518.03,
                "center": [0.0, 0.0, 10.0],
                "normal": [0.0, 0.0, 1.0],
                "position": [0.0, 0.0, 10.0],
                "bbox": [-20.0, -20.0, 10.0, 20.0, 20.0, 10.0],
            },
            {
                "ref": "#o1.s1.f9",
                "index": 9,
                "stable": "@corner_round.f3",
                "feature": "corner_round",
                "lineage": ["corner_round", "base_pad"],
                "surface": "Cylinder",
                "area": 31.42,
                "radius": 2.0,
                "axis": [0.0, 0.0, 1.0],
                "position": [18.0, 18.0, 0.0],
                "center": [19.41, 19.41, 5.0],
                "normal": [0.707, 0.707, 0.0],
                "bbox": [18.0, 18.0, 0.0, 20.0, 20.0, 10.0],
            },
            {
                "ref": "#o1.s1.f11",
                "index": 11,
                "stable": "@bore.f0",
                "feature": "bore",
                "lineage": ["corner_round", "bore"],
                "surface": "Cylinder",
                "area": 314.159265,
                "radius": 5.0,
                "axis": [0.0, 0.0, 1.0],
                "position": [0.0, 0.0, 10.0],
                "center": [0.0, 0.0, 5.0],
                "normal": [-1.0, 0.0, 0.0],
                "bbox": [-5.0, -5.0, 0.0, 5.0, 5.0, 10.0],
            },
        ],
        "edges": [
            {
                "ref": "#o1.s1.e1",
                "index": 1,
                "stable": "@base_pad.e3",
                "feature": "base_pad",
                "curve": "Line",
                "length": 36.0,
                "center": [0.0, -20.0, 0.0],
            },
        ],
        "vertices": [],
        "features": {
            "base_pad": {
                "type": "PartDesign::Pad",
                "build_index": 0,
                "blueprint_feature": True,
                "faces": ["#o1.s1.f1", "#o1.s1.f5"],
                "edges": ["#o1.s1.e1"],
                "vertices": [],
            },
            "bore": {
                "type": "PartDesign::Pocket",
                "build_index": 1,
                "blueprint_feature": True,
                "faces": ["#o1.s1.f11"],
                "edges": [],
                "vertices": [],
            },
            "corner_round": {
                "type": "PartDesign::Fillet",
                "build_index": 2,
                "blueprint_feature": True,
                "faces": ["#o1.s1.f9"],
                "edges": [],
                "vertices": [],
            },
        },
    }


# --------------------------------------------------------------------------- #
# the grammar
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,kind,index",
    [
        ("#o1.s1.f7", "faces", 7),
        ("#f7", "faces", 7),
        ("#o1.s1.e12", "edges", 12),
        ("#e12", "edges", 12),
        ("#o1.s1.v3", "vertices", 3),
        ("#v3", "vertices", 3),
    ],
)
def test_indexed_selectors_parse(text, kind, index):
    sel = topo.parse(text)

    assert (sel.form, sel.kind, sel.index) == ("indexed", kind, index)


def test_the_shorthand_expands_to_the_sole_occurrence_and_shape():
    """``#f7`` means the only body of a single-body part.

    Expanded on the way in so no caller has to special-case the day assemblies
    arrive — the short form keeps working and starts meaning ``o1`` explicitly.
    """
    assert str(topo.parse("#f7")) == "#o1.s1.f7"


def test_stable_selectors_parse_and_round_trip():
    sel = topo.parse("@bore.f0")

    assert (sel.form, sel.feature, sel.kind, sel.ordinal) == (
        "stable",
        "bore",
        "faces",
        0,
    )
    assert str(sel) == "@bore.f0"


def test_a_container_selector_names_the_shape():
    assert str(topo.parse("#o1")) == "#o1.s1"


@pytest.mark.parametrize(
    "text", ["", "f7", "#f", "#o1.f7.s1", "@bore", "@bore.x0", "#o1.s1.f", "#1f"]
)
def test_garbage_is_rejected_as_a_grammar_error(text):
    with pytest.raises(topo.SelectorError):
        topo.parse(text)


# --------------------------------------------------------------------------- #
# lookup
# --------------------------------------------------------------------------- #
def test_both_forms_reach_the_same_face(record):
    """The whole point of having two: one addresses, one survives."""
    by_index = topo.resolve(record, "#f11")
    by_name = topo.resolve(record, "@bore.f0")

    assert by_index is by_name
    assert by_index["feature"] == "bore"


def test_a_selector_this_build_has_nothing_for_returns_none(record):
    """Distinct from a grammar error, and the distinction is load-bearing.

    A stale ``#f7`` held across a rebuild is not a malformed selector — it is a
    well-formed one whose target moved, which is exactly the failure the
    ``@feature.f0`` form exists to avoid. A caller that cannot tell them apart
    reports a changed part as a client bug.
    """
    assert topo.resolve(record, "#f99") is None
    assert topo.resolve(record, "@bore.f9") is None

    with pytest.raises(topo.SelectorError):
        topo.resolve(record, "not-a-selector")


def test_feature_of_answers_the_question_a_user_is_actually_asking(record):
    assert topo.feature_of(record, "#f9") == "corner_round"
    assert topo.feature_of(record, "@bore.f0") == "bore"


def test_the_summary_drops_the_element_records(record):
    """The full sidecar is megabytes on a dense part; a client choosing what to
    render needs the tally, not the geometry."""
    summary = topo.summary(record)

    assert summary["features"]["base_pad"]["faces"] == 2
    assert summary["counts"]["faces"] == 4
    assert "lineage" not in repr(summary)


# --------------------------------------------------------------------------- #
# picking
# --------------------------------------------------------------------------- #
def test_a_point_on_a_cylinder_resolves_to_it_exactly(record):
    """The bore is radius 5 about the origin, so (5, 0, 5) is on its wall."""
    best = topo.pick(record, [5.0, 0.0, 5.0])[0]

    assert best["distance"] == 0.0
    assert best["feature"] == "bore"
    assert best["stable"] == "@bore.f0"


def test_a_point_on_a_plane_resolves_to_it_exactly(record):
    best = topo.pick(record, [0.0, 15.0, 10.0])[0]

    assert best["distance"] == 0.0
    assert best["feature"] == "base_pad"


def test_a_pick_on_a_fillet_names_the_fillet(record):
    """A 2 mm corner round, hit on its surface at 45 degrees.

    This is the interaction the whole layer exists for: a user clicks a rounded
    corner and the system says which feature put it there.
    """
    r = 2.0 / (2**0.5)
    best = topo.pick(record, [18.0 + r, 18.0 + r, 5.0])[0]

    assert best["distance"] == pytest.approx(0.0, abs=1e-6)
    assert best["feature"] == "corner_round"


def test_a_faces_extent_bounds_it_even_though_its_surface_does_not(record):
    """A plane is infinite; the face cut from it is not.

    Without the bbox filter the top face would win for any point anywhere in
    z = 10, including points a metre off the end of the part.
    """
    far_away = topo.pick(record, [500.0, 500.0, 10.0])

    assert all(c["ref"] != "#o1.s1.f5" for c in far_away)


def test_picking_returns_ranked_candidates_not_a_verdict(record):
    """A hit on a tangent seam is genuinely ambiguous at mesh resolution.

    Returning one face would invent a certainty the geometry does not have; a
    caller holding the runners-up can disambiguate with the normal it already
    has from the raycast.
    """
    candidates = topo.pick(record, [4.9, 0.0, 9.9], limit=3)

    assert len(candidates) > 1
    assert [c["distance"] for c in candidates] == sorted(
        c["distance"] for c in candidates
    )


def test_a_surface_named_either_way_is_matched(record):
    """FreeCAD reports ``Plane``; its type id is ``Part::GeomPlane``.

    Matching one spelling makes every pick silently fall back to a centroid
    distance — a wrong answer that still looks like an answer. Both are pinned
    because the first implementation here matched only the type-id form and the
    fallback hid it.
    """
    record["faces"][1]["surface"] = "Part::GeomPlane"

    best = topo.pick(record, [0.0, 15.0, 10.0])[0]

    assert best["distance"] == 0.0
    assert best["ref"] == "#o1.s1.f5"


def test_edges_can_be_picked_too(record):
    best = topo.pick(record, [0.0, -20.0, 0.0], kind="edges")[0]

    assert best["ref"] == "#o1.s1.e1"


def test_a_missing_sidecar_reads_as_absent(tmp_path):
    assert topo.load(str(tmp_path)) is None


def test_a_corrupt_sidecar_is_treated_as_missing(tmp_path):
    (tmp_path / topo.SIDECAR_NAME).write_text("{not json", encoding="utf-8")

    assert topo.load(str(tmp_path)) is None
