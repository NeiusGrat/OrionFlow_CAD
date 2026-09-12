"""§7.4 reference-based scorers, to the CAD-Recode/cadrille convention.
Optional overlay, never the default (R2) -- these tests exercise the
scorer math directly against known geometry, not against any task."""

import pytest
from build123d import Box, Pos

from orion_harness.verify.reference import chamfer_distance, invalidity_ratio, volumetric_iou


def test_chamfer_distance_is_small_for_identical_shapes():
    # Two independent point samples of the *same* surface still have a
    # small nonzero nearest-neighbor distance (sampling noise) -- this
    # asserts that noise floor, not an exact zero.
    box = Box(10, 10, 10)
    cd = chamfer_distance(box, box, n_points=512)
    assert cd["mean"] < 0.15
    assert cd["median"] < 0.15


def test_chamfer_distance_is_much_larger_for_clearly_different_shapes():
    box = Box(10, 10, 10)
    same_shape_noise = chamfer_distance(box, box, n_points=512)["mean"]

    very_different_box = Box(10, 10, 100)  # 10x taller, same X/Y footprint
    cd = chamfer_distance(box, very_different_box, n_points=512)
    assert cd["mean"] > 5 * same_shape_noise


def test_volumetric_iou_is_one_for_identical_shapes():
    box = Box(10, 10, 10)
    assert volumetric_iou(box, box) == pytest.approx(1.0, rel=1e-6)


def test_volumetric_iou_is_zero_for_disjoint_shapes():
    a = Box(10, 10, 10)
    b = Pos(1000, 0, 0) * Box(10, 10, 10)
    assert volumetric_iou(a, b) == pytest.approx(0.0, abs=1e-9)


def test_volumetric_iou_matches_hand_computed_partial_overlap():
    # two 1000mm^3 boxes overlapping in exactly half of each -> intersection 500
    # IoU = 500 / (1000 + 1000 - 500) = 1/3
    a = Box(10, 10, 10)
    b = Pos(5, 0, 0) * Box(10, 10, 10)
    assert volumetric_iou(a, b) == pytest.approx(1 / 3, rel=1e-6)


def test_invalidity_ratio_counts_invalid_and_timeout_statuses():
    statuses = ["scored", "scored", "invalid", "invalid", "error", "timeout"]
    # countable excludes "error": scored, scored, invalid, invalid, timeout (5 total)
    # invalid-or-timeout count: 3
    assert invalidity_ratio(statuses) == pytest.approx(3 / 5)


def test_invalidity_ratio_all_scored_is_zero():
    assert invalidity_ratio(["scored", "scored"]) == 0.0


def test_invalidity_ratio_empty_after_excluding_errors_is_zero():
    assert invalidity_ratio(["error", "error"]) == 0.0
