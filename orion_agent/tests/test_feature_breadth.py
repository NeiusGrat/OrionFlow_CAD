"""Offline tests for the Loft / Sweep / Mirrored / Draft vocabulary
(network-free, CI-safe). Geometric compilation is verified separately under
headless FreeCAD; these pin normalization, validation, and the guide.

Run with:  pytest orion_agent/tests/test_feature_breadth.py -v
"""

import pytest

from orion_agent.harness import featuregraph as fg


def _rect(w, h):
    x, y = w / 2.0, h / 2.0
    return [
        {"type": "LineSegment", "sx": -x, "sy": -y, "ex": x, "ey": -y},
        {"type": "LineSegment", "sx": x, "sy": -y, "ex": x, "ey": y},
        {"type": "LineSegment", "sx": x, "sy": y, "ex": -x, "ey": y},
        {"type": "LineSegment", "sx": -x, "sy": y, "ex": -x, "ey": -y},
    ]


def _loft_graph(**loft_params):
    params = {"_Sections": ["sk_top"]}
    params.update(loft_params)
    return {
        "features": [
            {"id": "sk_base", "type": "Sketch"},
            {"id": "sk_top", "type": "Sketch"},
            {"id": "loft1", "type": "Loft", "parameters": params},
        ],
        "sketches": [
            {"id": "sk_base", "plane": "XY", "geometry": _rect(80, 50)},
            {"id": "sk_top", "plane": "XY", "z": 40, "geometry": _rect(30, 20)},
        ],
        "dependencies": [{"source": "sk_base", "target": "loft1", "kind": "profile"}],
    }


def _sweep_graph():
    return {
        "features": [
            {"id": "sk_prof", "type": "Sketch"},
            {"id": "sk_path", "type": "Sketch"},
            {"id": "sweep1", "type": "Sweep", "parameters": {"_Spine": "sk_path"}},
        ],
        "sketches": [
            {"id": "sk_prof", "plane": "XY", "geometry": [
                {"type": "Circle", "cx": 0, "cy": 0, "radius": 5}]},
            {"id": "sk_path", "plane": "XZ", "geometry": [
                {"type": "LineSegment", "sx": 0, "sy": 0, "ex": 0, "ey": 30}]},
        ],
        "dependencies": [{"source": "sk_prof", "target": "sweep1", "kind": "profile"}],
    }


def _pad_graph(extra=None):
    return {
        "features": [
            {"id": "sk_base", "type": "Sketch"},
            {"id": "pad1", "type": "Pad", "parameters": {"Length": 30}},
        ] + (extra or []),
        "sketches": [{"id": "sk_base", "plane": "XY", "geometry": _rect(40, 40)}],
        "dependencies": [{"source": "sk_base", "target": "pad1", "kind": "profile"}],
    }


def _validate(graph):
    canonical, _ = fg.normalize(graph)
    return fg.validate(canonical)


# --------------------------------------------------------------------------- #
# happy paths (the exact shapes verified under headless FreeCAD)
# --------------------------------------------------------------------------- #
def test_loft_validates():
    assert _validate(_loft_graph()) == []


def test_subtractive_loft_needs_other_solid():
    g = _loft_graph(Subtractive=True)
    errs = _validate(g)
    assert any("no solid" in e for e in errs)   # a cut alone builds nothing


def test_sweep_validates_with_open_spine():
    assert _validate(_sweep_graph()) == []


def test_mirrored_validates_and_normalizes_alias():
    g = _pad_graph([{"id": "mir1", "type": "Mirrored",
                     "parameters": {"_Plane": {"role": "YZ"}}}])
    canonical, _ = fg.normalize(g)
    assert fg.validate(canonical) == []
    mir = [f for f in canonical["features"] if f["id"] == "mir1"][0]
    assert mir["parameters"]["_Plane"]["role"] == "YZ_Plane"


def test_mirrored_defaults_plane():
    g = _pad_graph([{"id": "mir1", "type": "Mirrored"}])
    canonical, notes = fg.normalize(g)
    assert fg.validate(canonical) == []
    assert any("mirror plane" in n for n in notes)


def test_draft_validates():
    g = _pad_graph([{"id": "draft1", "type": "Draft",
                     "parameters": {"Angle": 3, "_Faces": "vertical"}}])
    assert _validate(g) == []


# --------------------------------------------------------------------------- #
# normalization details
# --------------------------------------------------------------------------- #
def test_sketch_z_passes_through():
    canonical, _ = fg.normalize(_loft_graph())
    top = [s for s in canonical["sketches"] if s["id"] == "sk_top"][0]
    assert top["z"] == 40.0
    base = [s for s in canonical["sketches"] if s["id"] == "sk_base"][0]
    assert "z" not in base


def test_loft_sections_not_stolen_as_inferred_profile():
    """A Pad after the loft must not grab a section sketch as its profile."""
    g = _loft_graph()
    g["features"].append({"id": "sk_boss", "type": "Sketch"})
    g["features"].append({"id": "pad_boss", "type": "Pad",
                          "parameters": {"Length": 5}})
    g["sketches"].append({"id": "sk_boss", "plane": "XY", "geometry": [
        {"type": "Circle", "cx": 0, "cy": 0, "radius": 5}]})
    canonical, _ = fg.normalize(g)
    assert fg.validate(canonical) == []
    profile_of = {d["target"]: d["source"] for d in canonical["dependencies"]
                  if d["kind"] == "profile"}
    assert profile_of["pad_boss"] == "sk_boss"      # not sk_top


# --------------------------------------------------------------------------- #
# rejections
# --------------------------------------------------------------------------- #
def test_loft_without_sections_rejected():
    g = _loft_graph()
    del g["features"][2]["parameters"]["_Sections"]
    assert any("_Sections" in e for e in _validate(g))


def test_loft_missing_section_sketch_rejected():
    g = _loft_graph(_Sections=["sk_nowhere"])
    assert any("does not exist" in e for e in _validate(g))


def test_loft_section_equal_profile_rejected():
    g = _loft_graph(_Sections=["sk_base"])
    assert any("also its profile" in e for e in _validate(g))


def test_sweep_without_spine_rejected():
    g = _sweep_graph()
    del g["features"][2]["parameters"]["_Spine"]
    assert any("_Spine" in e for e in _validate(g))


def test_disconnected_spine_rejected():
    g = _sweep_graph()
    g["sketches"][1]["geometry"].append(
        {"type": "LineSegment", "sx": 100, "sy": 100, "ex": 120, "ey": 100})
    assert any("connected chain" in e for e in _validate(g))


def test_open_profile_still_rejected_for_non_spine():
    g = _pad_graph()
    g["sketches"][0]["geometry"] = g["sketches"][0]["geometry"][:3]  # open it
    assert any("not closed" in e for e in _validate(g))


def test_draft_needs_angle_and_valid_faces():
    g1 = _pad_graph([{"id": "d1", "type": "Draft", "parameters": {}}])
    assert any("Angle" in e for e in _validate(g1))
    g2 = _pad_graph([{"id": "d1", "type": "Draft",
                      "parameters": {"Angle": 3, "_Faces": "sideways"}}])
    assert any("_Faces" in e for e in _validate(g2))


def test_draft_before_solid_rejected():
    g = {
        "features": [
            {"id": "d1", "type": "Draft", "parameters": {"Angle": 3}},
            {"id": "sk_base", "type": "Sketch"},
            {"id": "pad1", "type": "Pad", "parameters": {"Length": 30}},
        ],
        "sketches": [{"id": "sk_base", "plane": "XY", "geometry": _rect(40, 40)}],
        "dependencies": [{"source": "sk_base", "target": "pad1", "kind": "profile"}],
    }
    assert any("after a solid" in e for e in _validate(g))


def test_pattern_occurrence_check_not_applied_to_mirrored():
    g = _pad_graph([{"id": "mir1", "type": "Mirrored",
                     "parameters": {"_Plane": {"role": "XZ_Plane"}}}])
    assert not any("Occurrences" in e for e in _validate(g))


# --------------------------------------------------------------------------- #
# the model-facing guide documents the vocabulary
# --------------------------------------------------------------------------- #
def test_authoring_guide_documents_new_features():
    for token in ("Loft", "Sweep", "Mirrored", "Draft", "_Sections", "_Spine",
                  "_Plane", "_Faces", '"z"'):
        assert token in fg.AUTHORING_GUIDE
