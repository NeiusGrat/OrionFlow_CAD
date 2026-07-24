"""Phase-0 unit tests: expression engine, profiles, Tier-1 math, checker,
blueprint freeze/resolve, fault injection. Pure Python — no FreeCAD.

Run:  pytest orion/tests/ -q
"""

import math

import pytest

from orion import expr as E
from orion import profiles as P
from orion import tier1
from orion.blueprint import Blueprint, BlueprintError, perturbed
from orion.checker import check_blueprint
from orion.faults import inject_wrong_sidetype


# --------------------------------------------------------------------------- #
# expr
# --------------------------------------------------------------------------- #
def test_expr_basic():
    assert E.evaluate("reach + 2*t", {"reach": 40, "t": 3}) == 46


def test_expr_functions_and_pi():
    v = E.evaluate("pi * (d/2)**2", {"d": 10})
    assert abs(v - math.pi * 25) < 1e-12


def test_expr_rejects_attributes_and_calls():
    with pytest.raises(E.ExprError):
        E.evaluate("__import__('os').getcwd()", {})
    with pytest.raises(E.ExprError):
        E.evaluate("open('x')", {})
    with pytest.raises(E.ExprError):
        E.evaluate("x.y", {"x": 1})


def test_expr_unknown_name():
    with pytest.raises(E.ExprError):
        E.evaluate("bore + 1", {"reach": 40})


def test_expr_names():
    assert E.names("sqrt(a*a + b*b) + pi") == {"a", "b"}


# --------------------------------------------------------------------------- #
# profiles: geometry and closed form must agree (Green vs formula)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,kwargs", [
    ("circle", {"r": 7.5}),
    ("annulus", {"r_outer": 20, "r_inner": 8}),
    ("rect", {"w": 30, "h": 12}),
    ("rect_with_holes", {"w": 60, "h": 40, "holes": [(-20, 0, 4), (20, 0, 4)]}),
    ("rounded_rect", {"w": 50, "h": 30, "r": 6}),
    ("slot", {"length": 25, "r": 5}),
    ("bolt_circle", {"n": 6, "r_bc": 30, "r_hole": 3.3}),
    ("regular_polygon", {"n": 6, "r_circum": 10}),
    ("polyline", {"points": [(0, 0), (40, 0), (40, 10), (10, 10), (10, 40), (0, 40)]}),
])
def test_profile_area_matches_green(name, kwargs):
    """The builder's closed-form area must equal Green's theorem over its own
    emitted geometry — one source, two derivations, must agree to 1e-9."""
    prof = P.build(name, **kwargs)
    area, centroid, why = tier1.sketch_area(prof["geometry"])
    assert why is None, why
    assert area == pytest.approx(prof["area"], rel=1e-9)
    assert centroid[0] == pytest.approx(prof["centroid"][0], abs=1e-6)
    assert centroid[1] == pytest.approx(prof["centroid"][1], abs=1e-6)


def test_profile_rejects_impossible():
    with pytest.raises(P.ProfileError):
        P.build("annulus", r_outer=5, r_inner=9)
    with pytest.raises(P.ProfileError):
        P.build("bolt_circle", n=8, r_bc=10, r_hole=4)   # holes overlap
    with pytest.raises(P.ProfileError):
        P.build("rect_with_holes", w=20, h=20, holes=[(9, 9, 5)])  # escapes


# --------------------------------------------------------------------------- #
# tier1 extrusion — including the SideType bug signature
# --------------------------------------------------------------------------- #
def test_extrusion_one_side():
    v, why = tier1.extrusion_volume(100.0, {"Length": 5.0})
    assert why is None and v == 500.0


def test_extrusion_two_sides_needs_length2():
    """The exact half-height bug: same params minus Length2 handling."""
    full, _ = tier1.extrusion_volume(
        16.0, {"Length": 2.95, "Length2": 2.95, "SideType": "Two sides"})
    half, _ = tier1.extrusion_volume(16.0, {"Length": 2.95})
    assert full == pytest.approx(2 * half)


def test_extrusion_refuses_taper_and_upto():
    v, why = tier1.extrusion_volume(10.0, {"Length": 5, "TaperAngle": 2.0})
    assert v is None and "Tier 2" in why
    v, why = tier1.extrusion_volume(10.0, {"Length": 5, "Type": "UpToFace"})
    assert v is None


def test_revolution_pappus_annulus():
    """Full revolution of an off-axis circle = torus: V = 2*pi*R * pi*r^2."""
    prof = P.build("circle", r=3, cx=20, cy=0)
    v, why = tier1.revolution_volume(
        prof["area"], prof["centroid"], ((0.0, 0.0), (0.0, 1.0)),
        {"Angle": 360.0})
    assert why is None
    assert v == pytest.approx(2 * math.pi * 20 * math.pi * 9, rel=1e-12)


def test_revolution_refuses_centroid_on_axis():
    v, why = tier1.revolution_volume(10.0, (0.0, 0.0),
                                     ((0.0, 0.0), (0.0, 1.0)), {"Angle": 360})
    assert v is None


def test_ring_dressups_and_prismatoid():
    v, _ = tier1.chamfer_ring_volume(10.0, 1.0)
    assert v == pytest.approx(0.5 * 2 * math.pi * (10 - 1 / 3))
    v, _ = tier1.fillet_ring_volume(10.0, 2.0)
    a = 4 * (1 - math.pi / 4)
    e = 2 * (10 - 3 * math.pi) / (12 - 3 * math.pi)
    assert v == pytest.approx(a * 2 * math.pi * (10 - e))
    # cone frustum r1=10 -> r2=4, h=9 via prismatoid == exact frustum formula
    a1, a2 = math.pi * 100, math.pi * 16
    am = math.pi * 49  # mid radius (10+4)/2 = 7
    v, _ = tier1.prismatoid_volume(a1, am, a2, 9.0)
    exact = math.pi * 9 / 3 * (100 + 16 + 40)
    assert v == pytest.approx(exact, rel=1e-12)


# --------------------------------------------------------------------------- #
# blueprint + checker
# --------------------------------------------------------------------------- #
def _cap_blueprint(**overrides):
    d = {
        "part_class": "test_cap",
        "variables": {"od": 40.0, "height": 8.0, "bore": 10.0},
        "datums": {"A": "bottom face, z=0", "axis": "Z"},
        "design_plan": {"intent": "unit-test cap"},
        "assertions": [
            {"id": "vol", "kind": "body_volume", "tier": 1,
             "target": "pi*((od/2)**2 - (bore/2)**2) * height",
             "tol_rel": 1e-6},
        ],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s0", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad",
                 "parameters": {"Length": "height", "Type": "Length",
                                "Reversed": False}},
            ],
            "sketches": [
                {"id": "s0", "plane": "XY",
                 "profile": {"builder": "annulus",
                             "args": {"r_outer": "od/2", "r_inner": "bore/2"}}},
            ],
            "dependencies": [
                {"source": "s0", "target": "pad", "kind": "profile"},
            ],
        },
    }
    d.update(overrides)
    return Blueprint(**d)


def test_blueprint_freeze_resolve_roundtrip():
    bp = _cap_blueprint().freeze()
    assert bp.blueprint_hash and bp.verify_hash()
    g = bp.resolve()
    a = g["_analysis"]["s0"]
    assert a["area"] == pytest.approx(math.pi * (400 - 25))
    assert g["features"][2]["parameters"]["Length"] == 8.0
    tgt = bp.resolve_assertions()[0]["target_value"]
    assert tgt == pytest.approx(a["area"] * 8.0)


def test_blueprint_hash_is_tamper_evident():
    bp = _cap_blueprint().freeze()
    tampered = Blueprint(**{**bp.__dict__,
                            "variables": {**bp.variables, "od": 41.0}})
    assert not tampered.verify_hash()


def test_checker_rejects_magic_numbers():
    bp = _cap_blueprint()
    bp.template["features"][2]["parameters"]["Length"] = 8.0  # bare literal
    problems = check_blueprint(bp)
    assert any("bare numeric literal" in p for p in problems)
    with pytest.raises(BlueprintError):
        bp.freeze()


def test_checker_rejects_raw_sketch_geometry():
    bp = _cap_blueprint()
    bp.template["sketches"][0] = {"id": "s0", "plane": "XY",
                                  "geometry": [{"type": "Circle", "cx": 0,
                                                "cy": 0, "radius": 20}]}
    problems = check_blueprint(bp)
    assert any("profile builder" in p for p in problems)


def test_checker_rejects_unused_variable():
    bp = _cap_blueprint(variables={"od": 40.0, "height": 8.0, "bore": 10.0,
                                   "orphan": 5.0})
    problems = check_blueprint(bp)
    assert any("unused variable" in p for p in problems)


def test_perturbed_differential_blueprint():
    bp = _cap_blueprint().freeze()
    bp2 = perturbed(bp, "height", 0.08)
    assert bp2.blueprint_hash != bp.blueprint_hash
    t1 = bp.resolve_assertions()[0]["target_value"]
    t2 = bp2.resolve_assertions()[0]["target_value"]
    assert t2 == pytest.approx(t1 * 8.08 / 8.0)


# --------------------------------------------------------------------------- #
# fault injection
# --------------------------------------------------------------------------- #
def test_wrong_sidetype_injection_halves_prediction():
    graph = {"features": [{"id": "pad", "type": "Pad",
                           "parameters": {"Length": 2.95, "Length2": 2.95,
                                          "SideType": "Two sides"}}]}
    out = inject_wrong_sidetype(graph)
    assert out is not None
    mutated, meta = out
    assert meta["fault"] == "wrong_sidetype"
    # clean graph predicts full height, mutated predicts half
    clean, _ = tier1.extrusion_volume(
        16.0, graph["features"][0]["parameters"])
    faulted, _ = tier1.extrusion_volume(
        16.0, mutated["features"][0]["parameters"])
    assert faulted == pytest.approx(clean / 2)
    # and the original graph was not modified in place
    assert graph["features"][0]["parameters"]["SideType"] == "Two sides"
