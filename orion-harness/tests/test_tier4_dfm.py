"""T4 geometric DFM (§7.2): wall thickness, accessibility, exact set cover
over the 6 principal directions. Pure build123d queries, no solver."""

import pytest
from build123d import Box, Pos, Rectangle, extrude

from orion_harness.verify.context import VerifyContext
from orion_harness.verify.tier4_dfm import (
    UNREACHABLE_SETUPS,
    accessibility_gate,
    min_setups,
    setups_metric,
    wall_min_metric,
)


def _ctx(shape, **params):
    return VerifyContext(kind="ofl", payload="", shape=shape, params=params)


def test_wall_min_on_a_flat_plate_matches_its_thickness():
    plate = extrude(Rectangle(100, 50), amount=6)
    metric = wall_min_metric(_ctx(plate))
    assert metric.value == pytest.approx(6.0, abs=1e-6)
    assert metric.unit == "mm"


def test_accessibility_passes_for_a_top_pocket():
    plate = extrude(Rectangle(100, 50), amount=10)
    pocket = Pos(20, 0, 7) * Box(10, 10, 6)  # floor at z=4
    shape = plate - pocket
    gate = accessibility_gate(_ctx(shape, at=[20, 0, 4], tolerance=1.5))
    assert gate.passed
    assert gate.evidence["accessible_from"] == ["+Z"]


def test_accessibility_passes_for_a_side_pocket_from_minus_y():
    plate = extrude(Rectangle(100, 50), amount=10)
    pocket = Pos(0, -22, 3) * Box(10, 6, 10)  # floor at y=-19
    shape = plate - pocket
    gate = accessibility_gate(_ctx(shape, at=[0, -19, 3], tolerance=1.5))
    assert gate.passed
    assert gate.evidence["accessible_from"] == ["-Y"]


def test_accessibility_fails_with_no_params():
    plate = extrude(Rectangle(10, 10), amount=5)
    gate = accessibility_gate(_ctx(plate))
    assert not gate.passed


def test_accessibility_fails_for_a_45_degree_chamfered_face():
    """A face whose normal bisects two principal axes (a 45-degree
    chamfer) is more than angle_tol_deg=30 away from every one of the 6
    principal directions -- must fail for "no principal direction can
    reach this face", not "no face found"."""

    from build123d import Axis, Box, chamfer

    box = Box(40, 40, 40)
    chamfered = chamfer(box.edges().filter_by(Axis.Y), length=15)
    gate = accessibility_gate(_ctx(chamfered, at=[-12.5, 0, -12.5], tolerance=2.0))
    assert not gate.passed
    assert gate.reason == "accessibility:no principal direction can reach this face"


def test_min_setups_one_direction_for_a_single_target():
    assert min_setups([{"+Z"}]) == 1


def test_min_setups_two_directions_for_disjoint_targets():
    assert min_setups([{"+Z"}, {"-Y"}]) == 2


def test_min_setups_prefers_the_shared_direction():
    # both targets reachable from +Z (among others) -> one setup suffices
    assert min_setups([{"+Z", "+X"}, {"+Z", "-Y"}]) == 1


def test_min_setups_unreachable_target_is_flagged():
    assert min_setups([{"+Z"}, set()]) == UNREACHABLE_SETUPS


def test_min_setups_empty_target_list_is_zero():
    assert min_setups([]) == 0


def test_setups_metric_matches_min_setups_end_to_end():
    plate = extrude(Rectangle(100, 50), amount=10)
    top_pocket = Pos(20, 0, 7) * Box(10, 10, 6)
    side_pocket = Pos(0, -22, 3) * Box(10, 6, 10)
    shape = plate - top_pocket - side_pocket

    both = setups_metric(_ctx(shape, targets=[[20, 0, 4], [0, -19, 3]], tolerance=1.5))
    assert both.value == 2.0

    one = setups_metric(_ctx(shape, targets=[[20, 0, 4]], tolerance=1.5))
    assert one.value == 1.0

    none = setups_metric(_ctx(shape, targets=[], tolerance=1.5))
    assert none.value == 0.0
