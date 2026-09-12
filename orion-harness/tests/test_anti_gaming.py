"""§12 anti-gaming gates, each exercised against the exploit it exists to
catch."""

from build123d import Rectangle, extrude

from orion_harness.rl.anti_gaming import (
    count_features,
    degenerate_geometry_gate,
    feature_count_gate,
    is_exact_copy,
    parameter_at_bound,
)

OFL_SOURCE = """
from orionflow_ofl import *
part = Sketch(Plane.XY).rect(10, 10).extrude(5)
part -= Hole(2).at(0, 0).through()
part.fillet(1)
"""


def test_degenerate_geometry_gate_passes_a_normal_block():
    shape = extrude(Rectangle(40, 40), amount=10)
    gate = degenerate_geometry_gate(shape)
    assert gate.passed


def test_degenerate_geometry_gate_catches_near_zero_volume():
    sliver = extrude(Rectangle(0.01, 0.01), amount=0.01)
    gate = degenerate_geometry_gate(sliver, min_volume_mm3=1.0)
    assert not gate.passed
    assert "volume" in gate.reason


def test_degenerate_geometry_gate_catches_an_unreasonably_thin_wall():
    sliver = extrude(Rectangle(40, 40), amount=0.001)
    gate = degenerate_geometry_gate(sliver, min_volume_mm3=1e-6, min_wall_mm=0.1)
    assert not gate.passed
    assert "wall_min" in gate.reason


def test_parameter_at_bound_detects_min_and_max():
    assert parameter_at_bound(5.0, (5.0, 50.0))
    assert parameter_at_bound(50.0, (5.0, 50.0))
    assert not parameter_at_bound(27.5, (5.0, 50.0))


def test_parameter_at_bound_degenerate_domain():
    assert parameter_at_bound(3.0, (3.0, 3.0))
    assert not parameter_at_bound(4.0, (3.0, 3.0))


def test_is_exact_copy_catches_whitespace_normalized_match():
    exemplar = "part = Sketch(Plane.XY).rect(10, 10).extrude(5)"
    payload_with_extra_whitespace = "part = Sketch(Plane.XY).rect(10, 10).extrude(5)   \n"
    assert is_exact_copy(payload_with_extra_whitespace, [exemplar])


def test_is_exact_copy_does_not_flag_a_genuinely_different_submission():
    exemplar = "part = Sketch(Plane.XY).rect(10, 10).extrude(5)"
    different = "part = Sketch(Plane.XY).circle(10).extrude(5)"
    assert not is_exact_copy(different, [exemplar])


def test_count_features_counts_known_builder_calls():
    assert count_features(OFL_SOURCE) == 4  # Sketch, extrude, Hole, fillet


def test_feature_count_gate_caps_absurd_feature_counts():
    many_holes_source = "from orionflow_ofl import *\npart = Sketch(Plane.XY).rect(100, 100).extrude(5)\n"
    many_holes_source += "\n".join(f"part -= Hole(1).at({i}, 0).through()" for i in range(500))
    gate = feature_count_gate(many_holes_source, max_features=50)
    assert not gate.passed
    assert gate.evidence["n_features"] > 50


def test_feature_count_gate_passes_a_normal_submission():
    gate = feature_count_gate(OFL_SOURCE, max_features=50)
    assert gate.passed
