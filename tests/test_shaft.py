"""The shaft generator.

The claim under test is that the shaft is *generated from* the resolved design
rather than drawn beside it: its seat is the bearing's bore by construction,
its shoulder is the bearing's attributed abutment or absent, and its profile is
parametric rather than a set of numbers computed once.
"""

from __future__ import annotations

import math

import pytest

from orion import shaft as SH
from orion.knowledge import functions as F

SHOULDERED = (
    "Support a rotating shaft carrying 4 kN at 600 rpm for 20000 "
    "hours and transmit 300 Nm of torque"
)
JOINT = (
    "Design a robotic shoulder joint: support a rotating shaft carrying "
    "1.2 kN at 600 rpm for 20000 hours and transmit 80 Nm of torque"
)


def test_the_seat_is_the_bearing_bore_by_construction():
    """A shaft drawn independently disagrees with its bearings about as often
    as someone mistypes, and the disagreement looks like a drawing."""
    from orion.skills.bearing_seat import bearing

    shaft, result = SH.from_request(SHOULDERED)
    designation = next(
        r.summary.split()[0]
        for r in result.chosen.plan.resolutions
        if r.function == F.SUPPORTS_ROTATION and r.resolved
    )
    spec = bearing(designation)
    seat = next(s for s in shaft.sections if s.kind == SH.BEARING_SEAT)
    assert seat.dia_mm == spec["d"]
    assert seat.length_mm == spec["B"]


def test_the_shoulder_is_the_attributed_abutment():
    shaft, _ = SH.from_request(SHOULDERED)
    shoulder = next(s for s in shaft.sections if s.kind == SH.SHOULDER)
    seat = next(s for s in shaft.sections if s.kind == SH.BEARING_SEAT)
    assert shoulder.dia_mm > seat.dia_mm
    assert "attributed" in shoulder.why
    assert any("attributed" in w for w in shaft.warnings)


def test_a_bearing_with_no_abutment_gets_no_invented_shoulder():
    """A shoulder invented to make the drawing look finished is the failure the
    abutment work exists to prevent."""
    shaft, _ = SH.from_request(JOINT)
    assert not [s for s in shaft.sections if s.kind == SH.SHOULDER]
    assert any("no abutment diameter on file" in w for w in shaft.warnings)
    assert any("spacer or a retaining ring" in w for w in shaft.warnings)


def test_the_keyway_matches_the_key_the_torque_sized():
    shaft, result = SH.from_request(SHOULDERED)
    key = next(
        r for r in result.chosen.plan.resolutions if r.function == F.TRANSMITS_TORQUE
    )
    keyed = next(s for s in shaft.sections if s.kind == SH.KEYED)
    feature = keyed.features[0]
    assert feature["kind"] == "keyway"
    assert feature["width_mm"] == key.provides["key_width_mm"]
    assert feature["length_mm"] == key.provides["key_length_mm"]


def test_adjacent_equal_diameters_become_one_cylinder():
    """Two identical points in the polyline is a zero-length edge — a sketch
    the kernel may reject, and a shape wrong in a way volume never reveals."""
    shaft, _ = SH.from_request(JOINT)
    assert len(shaft.sections) > len(shaft.runs())
    points = shaft.profile()
    assert len(points) == len(set(map(tuple, points)))


def test_the_profile_is_parametric_not_computed_once():
    """A literal in a profile is a number nothing can re-derive."""
    shaft, _ = SH.from_request(SHOULDERED)
    names = set(shaft.variables())
    for radius, z in shaft.profile():
        assert radius in names or radius == "0"
        assert all(
            term.strip() in names or term.strip() == "0" for term in z.split("+")
        )


def test_the_volume_expression_agrees_with_the_arithmetic():
    shaft, _ = SH.from_request(SHOULDERED)
    value = eval(
        shaft.volume_expr(), {"pi": math.pi, **shaft.variables()}  # noqa: S307
    )
    assert value == pytest.approx(shaft.volume_mm3(), rel=1e-12)


def test_the_blueprint_passes_the_static_check():
    """freeze() refuses a blueprint whose numbers reference no variable."""
    shaft, _ = SH.from_request(SHOULDERED)
    bp = SH.blueprint(shaft)
    assert bp.blueprint_hash and bp.verify_hash()
    assert set(bp.variables) == set(shaft.variables())


def test_the_widest_variable_is_the_one_the_extent_asserts():
    shaft, _ = SH.from_request(SHOULDERED)
    widest = shaft.widest()
    assert shaft.variables()[widest] * 2 == shaft.max_dia_mm


def test_no_resolved_design_means_no_shaft_rather_than_an_empty_one():
    shaft, result = SH.from_request(
        "Support a rotating shaft carrying 1.2 kN at 600 rpm and transmit "
        "90000 Nm of torque"
    )
    assert shaft.sections == []
    assert result is None
    assert any("no design was resolved" in w for w in shaft.warnings)


def test_generation_is_deterministic():
    first, _ = SH.from_request(SHOULDERED)
    second, _ = SH.from_request(SHOULDERED)
    assert first.to_dict() == second.to_dict()
