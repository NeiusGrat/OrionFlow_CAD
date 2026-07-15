"""Tests for Sketch.polygon and Part.rotate / .translate / .at.

These are the three APIs the LLM reached for in 7 of 11 baseline bench
failures — each test pins the exact usage pattern observed in the wild.
"""

import math

import pytest

from orionflow_ofl import Axis, Hole, Plane, Sketch


def _bbox(part):
    bb = part._solid.bounding_box()
    return (
        (bb.min.X, bb.min.Y, bb.min.Z),
        (bb.max.X, bb.max.Y, bb.max.Z),
    )


def test_polygon_vertices_not_recentered():
    """Vertices are used exactly as given — a right triangle in the +X+Y quadrant."""
    part = Sketch(Plane.XY).polygon([(0, 0), (40, 0), (0, 40)]).extrude(5)
    (min_pt, max_pt) = _bbox(part)
    assert min_pt == pytest.approx((0, 0, 0), abs=1e-6)
    assert max_pt == pytest.approx((40, 40, 5), abs=1e-6)
    assert part._solid.volume == pytest.approx(0.5 * 40 * 40 * 5)


def test_polygon_hexagon_volume():
    """Hex standoff profile: circumradius-10 hexagon, analytic area check."""
    r = 10
    verts = [
        (r * math.cos(math.radians(60 * i)), r * math.sin(math.radians(60 * i)))
        for i in range(6)
    ]
    part = Sketch(Plane.XY).polygon(verts).extrude(12)
    hex_area = 3 * math.sqrt(3) / 2 * r**2
    assert part._solid.volume == pytest.approx(hex_area * 12, rel=1e-6)


def test_polygon_requires_three_vertices():
    from orionflow_ofl.internal.errors import GeometryError

    with pytest.raises(GeometryError, match="at least 3"):
        Sketch(Plane.XY).polygon([(0, 0), (10, 0)])


def test_translate_moves_part():
    part = Sketch(Plane.XY).rect(10, 10).extrude(2).translate(5, -3, 20)
    (min_pt, max_pt) = _bbox(part)
    assert min_pt == pytest.approx((0, -8, 20), abs=1e-6)
    assert max_pt == pytest.approx((10, 2, 22), abs=1e-6)


def test_at_is_translate_alias():
    part = Sketch(Plane.XY).circle(10).extrude(4).at(15, 0)
    (min_pt, max_pt) = _bbox(part)
    assert min_pt[0] == pytest.approx(10, abs=1e-6)
    assert max_pt[0] == pytest.approx(20, abs=1e-6)


def test_rotate_string_axis_stands_plate_up():
    """The L-bracket pattern: rotate 90 about Y turns length into height."""
    wall = Sketch(Plane.XY).rect(40, 30).extrude(4).rotate(90, axis="y")
    (min_pt, max_pt) = _bbox(wall)
    assert max_pt[2] - min_pt[2] == pytest.approx(40, abs=1e-6)  # 40 now on Z
    assert max_pt[0] - min_pt[0] == pytest.approx(4, abs=1e-6)  # t now on X


def test_rotate_accepts_axis_object():
    """LLM sometimes writes axis=Axis.Z — Axis is re-exported for that."""
    part = Sketch(Plane.XY).rect(20, 10).extrude(2).rotate(90, axis=Axis.Z)
    (min_pt, max_pt) = _bbox(part)
    assert max_pt[0] - min_pt[0] == pytest.approx(10, abs=1e-6)
    assert max_pt[1] - min_pt[1] == pytest.approx(20, abs=1e-6)


def test_rotate_rejects_unknown_axis():
    part = Sketch(Plane.XY).rect(10, 10).extrude(2)
    with pytest.raises(ValueError, match="Unknown axis"):
        part.rotate(90, axis="w")


def test_l_bracket_union_and_hole():
    """Full observed failure pattern: rotate + translate + union + hole cut."""
    base = Sketch(Plane.XY).rect(50, 30).extrude(4)
    wall = Sketch(Plane.XY).rect(40, 30).extrude(4)
    wall.rotate(90, axis="y").translate(-25, 0, 20)
    part = base + wall
    part -= Hole(5).at(13, 0).through()

    (min_pt, max_pt) = _bbox(part)
    assert max_pt[0] - min_pt[0] == pytest.approx(50, abs=1e-6)
    assert max_pt[2] - min_pt[2] == pytest.approx(40, abs=1e-6)
    analytic = 50 * 30 * 4 + 4 * 30 * 36 - math.pi * 2.5**2 * 4
    assert part._solid.volume == pytest.approx(analytic, rel=1e-6)
