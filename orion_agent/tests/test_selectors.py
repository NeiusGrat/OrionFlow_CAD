"""Offline tests for the edge-selector grammar (network-free, CI-safe).

The grammar (freecad/edge_selectors.py) is the shared language between
FeatureGraph validation (harness) and edge resolution (compiler); these tests
pin the grammar and the harness side. Geometric resolution runs only under
FreeCAD and is exercised by the integration environment.

Run with:  pytest orion_agent/tests/test_selectors.py -v
"""

import pytest

from orion_agent.harness import featuregraph as fg

grammar = fg._edge_selector_grammar()


def _plate_graph(extra_features=None):
    g = {
        "features": [
            {"id": "sk_base", "type": "Sketch"},
            {"id": "pad_base", "type": "Pad", "parameters": {"Length": 10}},
        ],
        "sketches": [
            {"id": "sk_base", "plane": "XY", "geometry": [
                {"type": "LineSegment", "sx": -40, "sy": -25, "ex": 40, "ey": -25},
                {"type": "LineSegment", "sx": 40, "sy": -25, "ex": 40, "ey": 25},
                {"type": "LineSegment", "sx": 40, "sy": 25, "ex": -40, "ey": 25},
                {"type": "LineSegment", "sx": -40, "sy": 25, "ex": -40, "ey": -25},
            ]},
        ],
        "dependencies": [
            {"source": "sk_base", "target": "pad_base", "kind": "profile"},
        ],
    }
    g["features"].extend(extra_features or [])
    return g


# --------------------------------------------------------------------------- #
# grammar
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("keyword", sorted(grammar.KEYWORDS))
def test_parse_keywords(keyword):
    assert grammar.parse(keyword) == (keyword, None)


def test_parse_is_case_and_whitespace_insensitive():
    assert grammar.parse("  Top ") == ("top", None)
    assert grammar.parse("RADIUS:5") == ("radius", 5.0)


@pytest.mark.parametrize("text,expected", [
    ("direction:x", ("direction", "x")),
    ("direction:z", ("direction", "z")),
    ("radius:2.5", ("radius", 2.5)),
    ("largest:4", ("largest", 4)),
    ("largest: 1", ("largest", 1)),
])
def test_parse_parameterized(text, expected):
    assert grammar.parse(text) == expected


def test_parse_z_dict():
    assert grammar.parse({"z": 10}) == ("z", 10.0)
    assert grammar.parse({"z": True}) is None      # bool is not a height
    assert grammar.parse({"y": 1}) is None


@pytest.mark.parametrize("bad", [
    "bogus", "largest:0", "largest:abc", "largest:-2", "radius:-1",
    "radius:x", "radius:0", "direction:w", "direction:", "", 5, None, [],
])
def test_parse_invalid(bad):
    assert grammar.parse(bad) is None


def test_keyword_constant_stays_in_sync():
    assert fg.EDGE_SELECTORS == grammar.KEYWORDS


def test_authoring_guide_documents_grammar():
    for token in ("radius:<mm>", "largest:<n>", "direction:<x|y|z>",
                  "convex", "concave", "horizontal", "circular"):
        assert token in fg.AUTHORING_GUIDE


# --------------------------------------------------------------------------- #
# FeatureGraph validation accepts / rejects
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("selector", [
    "horizontal", "circular", "straight", "convex", "concave",
    "direction:x", "radius:5", "largest:4", {"z": 10},
    "top", "bottom", "vertical", "all",
])
def test_validate_accepts_selector(selector):
    graph = _plate_graph([{"id": "fil1", "type": "Fillet",
                           "parameters": {"Radius": 2, "_Edges": selector}}])
    canonical, _ = fg.normalize(graph)
    assert fg.validate(canonical) == []


@pytest.mark.parametrize("selector", ["sideways", "largest:0", "radius:no", ""])
def test_validate_rejects_bad_selector(selector):
    graph = _plate_graph([{"id": "fil1", "type": "Fillet",
                           "parameters": {"Radius": 2, "_Edges": selector}}])
    canonical, _ = fg.normalize(graph)
    errors = fg.validate(canonical)
    assert any("_Edges" in e for e in errors)
