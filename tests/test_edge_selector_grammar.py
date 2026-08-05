"""The shared edge-selector grammar, and the one form that names a single edge.

``freecad/edge_selectors.py`` is loaded by absolute path in production — both
the compiler and the harness validator read it that way, because FreeCAD ships
its own lowercase ``freecad`` package that shadows a normal import. The same
trick is used here so this test exercises the file the compiler actually reads.

``near`` is the addition worth testing. Every other form names a *class* of
edges, which is right for "break every corner" and useless for a person who
clicked one edge. It is also the only form whose argument is a point, so it is
the only one that can be malformed in interesting ways.
"""

import importlib.util
import os

import pytest

_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, "freecad", "edge_selectors.py"
)
_spec = importlib.util.spec_from_file_location("_orion_repo_edge_selectors", _PATH)
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("near:30,20,10", ("near", (30.0, 20.0, 10.0))),
        ("near: 30 , 20 , 10 ", ("near", (30.0, 20.0, 10.0))),
        ("NEAR:1,-2,3.5", ("near", (1.0, -2.0, 3.5))),
        ("near:0,0,0", ("near", (0.0, 0.0, 0.0))),
    ],
)
def test_a_point_selector_parses(text, expected):
    assert sel.parse(text) == expected


@pytest.mark.parametrize(
    "text",
    ["near:", "near:1,2", "near:1,2,3,4", "near:a,b,c", "near:1,,3", "near"],
)
def test_a_malformed_point_is_rejected_rather_than_guessed(text):
    """A selector that cannot be read must not fall through to some default.

    Returning `all` for a broken `near` would chamfer every edge on the part.
    """
    assert sel.parse(text) is None


def test_the_existing_grammar_is_untouched():
    """`near` is an addition, not a replacement — the authored corpus uses these."""
    assert sel.parse("vertical") == ("vertical", None)
    assert sel.parse("largest:4") == ("largest", 4)
    assert sel.parse("radius:5") == ("radius", 5.0)
    assert sel.parse("direction:z") == ("direction", "z")
    assert sel.parse({"z": 10.0}) == ("z", 10.0)
    assert sel.parse("nonsense") is None


def test_the_help_string_mentions_every_form():
    """The message a user sees when a selector is refused must list what works."""
    for form in ("near:", "largest:", "radius:", "direction:", "vertical"):
        assert form in sel.HELP


def test_a_tolerance_is_published_for_the_compiler_to_use():
    """The compiler and the harness must agree on how far `near` may reach."""
    assert sel.NEAR_TOLERANCE_MM > 0
