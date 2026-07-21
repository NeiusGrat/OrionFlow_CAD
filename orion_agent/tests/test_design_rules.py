"""Design-rules layer: classification, datum, lookups and derived values.

These guard the properties a weaker model depends on being handed rather than
recalling — a wrong datum or a hallucinated yield strength produces geometry
that looks right and measures wrong.
"""

import pytest

from orion_agent.harness import design_rules as dr
from orion_agent.harness.spec import SpecParser


# --------------------------------------------------------------------------- #
# classification -> datum
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text,expected", [
    ("aluminium flange 80 OD with 6 bolt holes", "rotational"),
    ("turned shaft 20 dia 100 long", "rotational"),
    ("sheet metal bracket 2mm thick with one bend", "sheet_metal"),
    ("injection moulded enclosure 120x80x40", "housing"),
    ("L bracket to mount a motor", "bracket"),
    ("6mm plate 200 x 100 with four holes", "plate"),
])
def test_classify(text, expected):
    cls, _why = dr.classify(text)
    assert cls == expected


def test_sheet_metal_beats_plate():
    """'sheet metal plate' must not classify as a plain plate — the bend
    rules and flat-pattern datum are what make it sheet metal."""
    cls, _ = dr.classify("sheet metal plate 1.5mm with two bends")
    assert cls == "sheet_metal"


def test_rotational_datum_matches_compiler_convention():
    ctx = dr.resolve("aluminium flange, 6 bolts")
    d = ctx.datum
    assert d["sketch_plane"] == "XZ"
    assert d["axis"] == "X"
    # reconstruct.py maps an XZ sketch (u,v) -> (u, 0, v); the profile is
    # therefore (axial, radius). Drift here silently mis-builds every revolve.
    assert "radius" in d["coords"]


def test_every_class_declares_a_full_datum():
    required = {"sketch_plane", "axis", "symmetry", "coords", "origin"}
    for name, spec in dr.PART_CLASSES.items():
        assert required <= set(spec["datum"]), f"{name} datum incomplete"
        assert spec["recipe"], f"{name} has no feature recipe"


# --------------------------------------------------------------------------- #
# material / process lookup
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name,key", [
    ("6061", "al 6061-t6"), ("aluminium", "al 6061-t6"),
    ("AL 6061-T6", "al 6061-t6"), ("7075", "al 7075-t6"),
    ("stainless", "ss 304"), ("316", "ss 316"),
    ("titanium", "ti 6al-4v"), ("delrin", "delrin"), ("acetal", "delrin"),
])
def test_resolve_material(name, key):
    m = dr.resolve_material(name)
    assert m is not None and m["key"] == key


def test_material_values_are_sane():
    for key, m in dr.MATERIALS.items():
        assert 0.5 < m["density"] < 20, key
        assert 0 < m["yield"] < 2000, key
        assert 0 < m["modulus"] < 500, key


@pytest.mark.parametrize("name,key", [
    ("CNC machined", "cnc milling"), ("milled", "cnc milling"),
    ("turned on a lathe", "turning"),
    ("injection moulded", "injection moulding"),
    ("3d printed", "fdm 3d printing"), ("sheet metal", "sheet metal"),
])
def test_resolve_process(name, key):
    p = dr.resolve_process(name)
    assert p is not None and p["key"] == key


def test_process_rules_present():
    for key, p in dr.PROCESSES.items():
        assert p["rules"], f"{key} has no DFM rules"
        assert p["min_wall_mm"] > 0, key


# --------------------------------------------------------------------------- #
# formulas — value AND the expression that justifies it
# --------------------------------------------------------------------------- #

def test_bolt_circle_geometry():
    pts, expr = dr.bolt_circle(60.0, 6)
    assert len(pts) == 6
    assert pts[0] == pytest.approx((30.0, 0.0))
    for x, y in pts:                      # every hole on the circle
        assert (x * x + y * y) ** 0.5 == pytest.approx(30.0)
    assert "60" in expr


def test_bend_allowance_known_case():
    ba, expr = dr.bend_allowance(90, 2.0, 2.0, 0.44)
    assert ba == pytest.approx((3.14159265 / 2) * (2.0 + 0.88), rel=1e-4)
    assert "BA" in expr


def test_mass_from_volume_uses_real_density():
    grams, expr = dr.mass_from_volume(1000.0, "6061")   # 1 cm^3
    assert grams == pytest.approx(2.70, rel=1e-3)
    assert "rho" in expr


def test_mass_rejects_unknown_material():
    with pytest.raises(ValueError):
        dr.mass_from_volume(1000.0, "unobtainium")


# --------------------------------------------------------------------------- #
# resolve() end-to-end
# --------------------------------------------------------------------------- #

def test_resolve_flags_wall_below_process_minimum():
    ctx = dr.resolve("injection moulded ABS box",
                     manufacturing="injection moulding",
                     dimensions={"wall thickness": 0.4})
    assert any("VIOLATION" in c for c in ctx.checks)


def test_resolve_never_invents_dimensions():
    """No stated sizes -> no derived values. The layer supplies standing
    knowledge, never a guess at the user's part."""
    ctx = dr.resolve("make me a flange")
    assert ctx.derived == []
    assert ctx.part_class == "rotational"


def test_render_is_empty_without_a_class():
    assert dr.DesignContext().render() == ""


# --------------------------------------------------------------------------- #
# wiring into the spec parser (regex path = no LLM at all)
# --------------------------------------------------------------------------- #

def test_spec_carries_design_context_without_an_llm():
    spec = SpecParser(llm=None).parse(
        "Aluminium 6061 flange, 80 OD, 10 thick, 6 bolt holes on a 60 PCD, CNC machined")
    d = spec.design
    assert d["part_class"] == "rotational"
    assert d["datum"]["sketch_plane"] == "XZ"
    assert d["material"]["key"] == "al 6061-t6"
    assert d["process"]["key"] == "cnc milling"
    assert "DESIGN CONTEXT" in spec.render()


def test_designator_dimensions_are_extracted():
    """'80 OD' / '60 PCD' carry no unit; without these the formulas starve."""
    spec = SpecParser(llm=None).parse("flange 80 OD, 10 thick, 60 PCD")
    assert spec.dimensions["outer diameter"] == pytest.approx(80.0)
    assert spec.dimensions["pcd"] == pytest.approx(60.0)
    assert spec.dimensions["wall thickness"] == pytest.approx(10.0)


def test_thread_callout_is_not_read_as_a_quantity():
    """'two M6 holes' is 2 holes, not 6 — the 6 belongs to the thread."""
    spec = SpecParser(llm=None).parse("bracket with two M6 holes")
    assert spec.counts.get("holes") == 2


def test_word_quantities():
    spec = SpecParser(llm=None).parse("plate with four holes")
    assert spec.counts.get("holes") == 4


def test_design_resolution_never_breaks_the_spec():
    """A design-rules failure must degrade, not lose the parsed spec."""
    spec = SpecParser(llm=None).parse("")
    assert spec is not None
