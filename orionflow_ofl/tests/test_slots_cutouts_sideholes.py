"""Tests for the deterministic-breadth additions: Sketch.slot, Part - Part
subtraction (rectangular cutouts), and side-axis holes (Hole.along).

All volumes are checked against analytic ground truth.
"""

import math

import pytest

from orionflow_ofl import Hole, Plane, Sketch
from orionflow_ofl.internal.errors import GeometryError

REL_TOL = 1e-4


def test_slot_profile_volume():
    # Stadium: (L - W) * W rectangle + full circle of d=W, extruded 5 mm.
    length, width, thick = 40, 8, 5
    part = Sketch(Plane.XY).slot(length, width).extrude(thick)
    expected = ((length - width) * width + math.pi * (width / 2) ** 2) * thick
    assert part._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_slot_rejects_degenerate_dimensions():
    with pytest.raises(GeometryError):
        Sketch(Plane.XY).slot(8, 8)


def test_part_minus_part_rectangular_cutout():
    # 80x40x5 plate minus a centered 40x8 slot-bar cut through it.
    plate = Sketch(Plane.XY).rect(80, 40).extrude(5)
    cutter = Sketch(Plane.XY).slot(40, 8).extrude(7).translate(z=-1)
    plate -= cutter
    slot_area = (40 - 8) * 8 + math.pi * 4**2
    expected = 80 * 40 * 5 - slot_area * 5
    assert plate._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_part_minus_part_binary_form():
    base = Sketch(Plane.XY).rect(60, 60).extrude(10)
    pocket = Sketch(Plane.XY).rect(20, 20).extrude(12).translate(z=-1)
    result = base - pocket
    assert result._solid.volume == pytest.approx(
        60 * 60 * 10 - 20 * 20 * 10, rel=REL_TOL
    )
    # binary form must not mutate the base
    assert base._solid.volume == pytest.approx(60 * 60 * 10, rel=REL_TOL)


def test_part_minus_part_that_misses_raises():
    plate = Sketch(Plane.XY).rect(50, 50).extrude(5)
    cutter = Sketch(Plane.XY).rect(10, 10).extrude(5).translate(x=100)
    with pytest.raises(GeometryError, match="removed no material"):
        plate -= cutter


def test_side_hole_along_x():
    # 20x30x40 block; d=10 hole through it along X at (y=0, z=0 == block center).
    block = Sketch(Plane.XY).rect(20, 30).extrude(40).translate(z=-20)
    block -= Hole(10).along("x").at(0, 0).through()
    expected = 20 * 30 * 40 - math.pi * 5**2 * 20
    assert block._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_side_hole_along_y():
    block = Sketch(Plane.XY).rect(20, 30).extrude(40).translate(z=-20)
    block -= Hole(8).along("y").at(0, 10).through()  # (x, z) = (0, 10)
    expected = 20 * 30 * 40 - math.pi * 4**2 * 30
    assert block._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_side_hole_blind_depth_measured_from_max_face():
    # Blind hole along X, 8 mm deep, entering from the +X face.
    block = Sketch(Plane.XY).rect(20, 20).extrude(20).translate(z=-10)
    block -= Hole(6).along("x").at(0, 0).to_depth(8)
    expected = 20 * 20 * 20 - math.pi * 3**2 * 8
    assert block._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_side_hole_that_misses_raises_with_axis_context():
    block = Sketch(Plane.XY).rect(20, 20).extrude(10)
    with pytest.raises(GeometryError, match="along X"):
        block -= Hole(5).along("x").at(50, 50).through()


def test_default_z_axis_hole_unchanged():
    plate = Sketch(Plane.XY).rect(50, 50).extrude(5)
    plate -= Hole(10).at(0, 0).through()
    expected = 50 * 50 * 5 - math.pi * 5**2 * 5
    assert plate._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_invalid_axis_rejected():
    with pytest.raises(ValueError):
        Hole(5).along("w")


def test_blind_hole_from_bottom_face():
    # 20 mm tall block, 6 mm blind hole entering from the BOTTOM (z min).
    block = Sketch(Plane.XY).rect(30, 30).extrude(20)
    block -= Hole(6).at(0, 0).to_depth(5, from_face="bottom")
    expected = 30 * 30 * 20 - math.pi * 3**2 * 5
    assert block._solid.volume == pytest.approx(expected, rel=REL_TOL)
    # material was removed at the bottom: bbox unchanged, min face has the hole
    assert block._solid.bounding_box().min.Z == pytest.approx(0.0, abs=1e-6)


def test_hole_at_tolerates_extra_z_coordinate():
    plate = Sketch(Plane.XY).rect(50, 50).extrude(5)
    plate -= Hole(10).at(0, 0, 5).through()  # stray z ignored, no crash
    expected = 50 * 50 * 5 - math.pi * 5**2 * 5
    assert plate._solid.volume == pytest.approx(expected, rel=REL_TOL)


def test_hole_translate_raises_guidance():
    with pytest.raises(GeometryError, match="from_face"):
        Hole(6).translate(0, 0, 10)


def test_disjoint_union_raises_teachable_error():
    base = Sketch(Plane.XY).rect(40, 40).extrude(5)
    floater = Sketch(Plane.XY).rect(10, 10).extrude(5).translate(x=100)
    with pytest.raises(GeometryError, match="disconnected"):
        base += floater


def test_part_copy_is_independent():
    fin = Sketch(Plane.XY).rect(2, 40).extrude(15)
    clone = fin.copy().translate(x=10)
    # original stays put; the clone moved
    assert fin._solid.bounding_box().min.X == pytest.approx(-1.0, abs=1e-6)
    assert clone._solid.bounding_box().min.X == pytest.approx(9.0, abs=1e-6)
