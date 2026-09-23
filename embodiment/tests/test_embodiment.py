"""The embodiment compiler: exact where it claims to be, consistent across
its two output formats, reproducible, and able to refuse.

A gate that has never been seen to fail proves nothing, so half of these
hand the compiler a robot that must be rejected.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np
import pytest
from build123d import Box, Pos

from app.domain.feature_graph import Feature, FeatureGraph, Sketch, SketchEntity
from embodiment import ArmSpec, compile_robot
from embodiment.catalog import actuator_limits
from embodiment.compiler import _world
from embodiment.geometry import solid
from embodiment.massprops import solid_props
from embodiment.spec import expand, translate


@pytest.fixture(scope="module")
def default_build(tmp_path_factory):
    out = tmp_path_factory.mktemp("arm")
    return out, compile_robot(ArmSpec(), out)


# ── exactness ──────────────────────────────────────────────────────────────

def test_sketch_offsets_place_bores_where_asked():
    # the one compiler extension: a circle cut at (cx, cy), not at the origin
    g = FeatureGraph(
        parameters={"t": 5.0},
        sketches=[Sketch(id="b", entities=[SketchEntity(id="r", type="rectangle",
                                                        params={"width": 100.0, "height": 20.0, "cx": 50.0})]),
                  Sketch(id="c", entities=[SketchEntity(id="h", type="circle",
                                                        params={"radius": 4.0, "cx": 90.0, "cy": 0.0})])],
        features=[Feature(id="e", type="extrude", sketch="b", params={"depth": "$t"}),
                  Feature(id="x", type="cut", sketch="c", params={"depth": "$t"})])
    s = solid(g)
    bb = s.bounding_box()
    assert (bb.min.X, bb.max.X) == pytest.approx((0.0, 100.0))
    assert s.volume == pytest.approx(100 * 20 * 5 - math.pi * 16 * 5, rel=1e-9)
    # the hole is at x = 90, so the centre of mass moves left of the bar's middle
    assert solid_props(s, 1000.0).com_m[0] * 1000 < 50.0


def test_exact_mass_properties_match_the_analytic_box():
    a, b, c, rho = 100.0, 40.0, 10.0, 1240.0
    p = solid_props(Pos(300, -50, 20) * Box(a, b, c), rho)     # far from the origin on purpose
    m = a * b * c * 1e-9 * rho
    expect = m / 12 * np.array([b * b + c * c, a * a + c * c, a * a + b * b]) * 1e-6
    assert p.mass_kg == pytest.approx(m, rel=1e-12)
    assert np.allclose(p.com_m, [0.3, -0.05, 0.02])
    assert np.allclose(np.diag(p.inertia_kg_m2), expect, rtol=1e-12)   # about the CoM, not the origin


def test_servo_limits_come_from_the_datasheet():
    lim = actuator_limits("mg996r_servo")
    assert lim["effort_nm"] == pytest.approx(11 * 9.80665 / 100)            # 11 kg cm
    assert lim["velocity_rad_s"] == pytest.approx((math.pi / 3) / 0.14)      # 0.14 s / 60 deg


def test_an_actuator_without_a_speed_is_refused_not_guessed():
    with pytest.raises(KeyError, match="invented"):
        actuator_limits("nema17_stepper")


# ── the first robot ────────────────────────────────────────────────────────

def test_default_arm_is_accepted_by_every_gate(default_build):
    _, r = default_build
    assert r["accepted"], {k: g for k, g in r["gates"].items() if not g["passed"]}
    for fmt in ("urdf", "mjcf"):
        c = r["robocheck"][fmt]
        assert c["loaded"] and c["errors"] == 0 and c["warnings"] == 0, c["findings"]
        # robocheck ran for real: both moving bodies measured, and it settled
        assert c["stats"]["bodies_checked_against_geometry"] == 2
        assert c["stats"]["settle_s"] > 0


def test_urdf_and_mjcf_describe_the_same_robot(default_build):
    out, _ = default_build
    mu = mujoco.MjModel.from_xml_path(str(out / "two_link_arm.urdf"))
    mj = mujoco.MjModel.from_xml_path(str(out / "two_link_arm.xml"))
    du, dj = mujoco.MjData(mu), mujoco.MjData(mj)
    mujoco.mj_forward(mu, du)
    mujoco.mj_forward(mj, dj)
    W = _world(expand(ArmSpec()), {})
    for link in ("link_1", "link_2"):
        bu, bj = mu.body(link).id, mj.body(link).id
        assert mu.body_mass[bu] == pytest.approx(mj.body_mass[bj], rel=1e-9)
        assert np.allclose(np.sort(mu.body_inertia[bu]), np.sort(mj.body_inertia[bj]), rtol=1e-6)
        # the same centre of mass in the world, in both files and in the compiler's own kinematics
        assert np.allclose(du.xipos[bu], dj.xipos[bj], atol=1e-9)
        assert np.allclose(du.xpos[bu], W[link][:3, 3] * 1e-3, atol=1e-9)
        assert np.allclose(dj.xpos[bj], W[link][:3, 3] * 1e-3, atol=1e-9)


def test_the_build_is_reproducible(default_build, tmp_path):
    _, first = default_build
    second = compile_robot(ArmSpec(), tmp_path / "again")
    assert first["files"] == second["files"]            # every file, byte for byte


# ── refusals ───────────────────────────────────────────────────────────────

def test_an_undersized_servo_is_rejected(tmp_path):
    # SG90s cannot hold two 200 mm links out horizontally with a factor of 2
    spec = ArmSpec(name="weak_arm", link_lengths_mm=[200.0, 200.0], actuator="sg90_servo")
    r = compile_robot(spec, tmp_path / "weak")
    assert not r["accepted"]
    assert not r["gates"]["actuators"]["passed"]
    assert r["gates"]["actuators"]["joints"]["joint_1"]["margin"] < 2.0


def test_links_that_clash_at_rest_are_rejected(tmp_path):
    robot = expand(ArmSpec(name="clash"))
    # put link 2 in the same plane as link 1 instead of beside it
    robot.joints[1].origin = translate(120.0, 0.0, 0.0)
    r = compile_robot(ArmSpec(name="clash"), tmp_path / "clash", robot=robot)
    assert not r["accepted"]
    clashes = r["gates"]["interference"]["clashes"]
    assert any(set(c["links"]) == {"link_1", "link_2"} for c in clashes)


# ── a free-standing legged robot ───────────────────────────────────────────

@pytest.fixture(scope="module")
def quadruped_build(tmp_path_factory):
    from embodiment.legged import QuadrupedSpec
    out = tmp_path_factory.mktemp("quad")
    return out, compile_robot(QuadrupedSpec(), out)


def test_the_quadruped_is_accepted_and_stands(quadruped_build):
    _, r = quadruped_build
    assert r["accepted"], {k: g for k, g in r["gates"].items() if not g["passed"]}
    s = r["gates"]["stands"]
    assert s["feet_down"] == ["fl_shin", "fr_shin", "rl_shin", "rr_shin"]
    assert s["end_height_m"] >= 0.9 * s["start_height_m"] and s["tilt_deg"] < 5
    # interference was checked in the stance too, not only at q = 0
    assert r["gates"]["interference"]["poses"] == ["rest", "stand"]
    for fmt in ("urdf", "mjcf"):
        assert r["robocheck"][fmt]["errors"] == 0 and r["robocheck"][fmt]["warnings"] == 0


def test_mirrored_legs_get_mirrored_angles_and_feet_land_under_the_hips():
    # the MicroDuck lesson: no sign is written by hand, so check what the
    # derivation produced - left and right opposite, every foot under its hip
    from embodiment.legged import QuadrupedSpec, expand_quadruped
    robot = expand_quadruped(QuadrupedSpec())
    q = robot.poses["stand"]
    assert q["fl_hip"] == -q["fr_hip"] and q["fl_knee"] == -q["fr_knee"]
    W = _world(robot, q)
    for f in robot.feet:
        leg = f.link[:2]
        foot = (W[f.link] @ np.array([*f.centre_mm, 1.0]))[:3]
        assert foot[0] == pytest.approx(W[f"{leg}_thigh"][0, 3], abs=1e-9)


def test_a_robot_without_its_servos_does_not_stand(quadruped_build, tmp_path):
    import re

    from embodiment.stand import stand_test
    out, _ = quadruped_build
    xml = (out / "quadruped.xml").read_text()
    xml = re.sub(r"<actuator>.*?</actuator>", "", xml, flags=re.S)
    xml = re.sub(r' ctrl="[^"]*"', "", xml)
    limp = out / "limp.xml"
    limp.write_text(xml)
    r = stand_test(limp, ["fl_shin", "fr_shin", "rl_shin", "rr_shin"], "stand")
    assert not r["passed"]
    assert r["end_height_m"] < 0.9 * r["start_height_m"]


def test_a_quadruped_its_servos_cannot_hold_is_rejected(tmp_path):
    from embodiment.legged import QuadrupedSpec
    # a 40 mm solid torso on SG90s in a deep crouch: the knees need more than
    # half the stall torque
    spec = QuadrupedSpec(name="heavy", torso_mm=(160.0, 100.0, 40.0), actuator="sg90_servo",
                         stance_hip_deg=60.0)
    r = compile_robot(spec, tmp_path / "heavy")
    assert not r["accepted"]
    assert not r["gates"]["actuators"]["passed"]


@pytest.mark.parametrize("example", ["two_link_arm", "quadruped"])
def test_every_committed_example_rebuilds_byte_for_byte(example, tmp_path):
    import json
    from pathlib import Path

    from embodiment.legged import QuadrupedSpec
    folder = Path(__file__).resolve().parent.parent / "examples" / example
    committed = json.loads((folder / "report.json").read_text())
    data = json.loads((folder / "spec.json").read_text())
    spec = QuadrupedSpec.model_validate(data) if data.get("kind") == "quadruped" else ArmSpec.model_validate(data)
    rebuilt = compile_robot(spec, tmp_path / "rebuilt")
    assert committed["accepted"] and rebuilt["accepted"]
    assert rebuilt["files"] == committed["files"]
