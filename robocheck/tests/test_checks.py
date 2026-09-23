"""Each check against a model built to trip exactly it, and a clean model
that must trip nothing - a checker that flags a correct robot is noise."""
from __future__ import annotations

from pathlib import Path

import pytest

from robocheck import check_file


def box_inertia(m, x, y, z):
    return m / 12 * (y * y + z * z), m / 12 * (x * x + z * z), m / 12 * (x * x + y * y)


def link(name, size=(0.1, 0.1, 0.1), mass=1.0, xyz=(0, 0, 0), inertia=None, inertial=True):
    x, y, z = size
    ixx, iyy, izz = inertia or box_inertia(mass, x, y, z)
    inert = (f'<inertial><origin xyz="{xyz[0]} {xyz[1]} {xyz[2]}"/><mass value="{mass}"/>'
             f'<inertia ixx="{ixx}" iyy="{iyy}" izz="{izz}" ixy="0" ixz="0" iyz="0"/></inertial>') if inertial else ""
    geo = (f'<origin xyz="{xyz[0]} {xyz[1]} {xyz[2]}"/><geometry><box size="{x} {y} {z}"/></geometry>')
    return f'<link name="{name}">{inert}<collision>{geo}</collision></link>'


def joint(name, parent, child, xyz=(0, 0, 0.1), limit='<limit lower="-1" upper="1" effort="5" velocity="3"/>'):
    return (f'<joint name="{name}" type="revolute"><parent link="{parent}"/><child link="{child}"/>'
            f'<origin xyz="{xyz[0]} {xyz[1]} {xyz[2]}"/><axis xyz="0 1 0"/>{limit}</joint>')


def write(tmp_path: Path, body: str, name="r.urdf") -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def codes(report, severity=None):
    return {f.code for f in report.findings if severity is None or f.severity == severity}


# ── URDF ──────────────────────────────────────────────────────────────────

def clean_arm():
    return ('<robot name="arm">' + link("base") + link("upper", mass=0.5, xyz=(0, 0, 0.1), size=(0.05, 0.05, 0.2))
            + joint("shoulder", "base", "upper", xyz=(0, 0, 0.05)) + "</robot>")


def test_clean_urdf_has_no_errors_or_warnings(tmp_path):
    r = check_file(write(tmp_path, clean_arm()))
    assert r.loaded and r.ok
    assert not codes(r, "error") and not codes(r, "warning"), [f.message for f in r.findings]


def test_impossible_inertia_is_an_error_and_still_gets_checked(tmp_path):
    body = ('<robot name="bad">' + link("base") + link("upper", inertia=(0.001, 0.001, 0.01))
            + joint("j", "base", "upper") + "</robot>")
    r = check_file(write(tmp_path, body))
    assert "URDF033" in codes(r, "error")        # A + B < C
    assert r.loaded                               # compiled after rebalancing...
    assert "LOAD003" in codes(r)                  # ...and says so


def test_millimetre_inertia_is_flagged_with_the_unit_hint(tmp_path):
    ixx, iyy, izz = box_inertia(0.5, 0.05, 0.05, 0.2)
    body = ('<robot name="mm">' + link("base")
            + link("upper", mass=0.5, xyz=(0, 0, 0.1), size=(0.05, 0.05, 0.2),
                   inertia=(ixx * 1e6, iyy * 1e6, izz * 1e6))
            + joint("j", "base", "upper", xyz=(0, 0, 0.05)) + "</robot>")
    r = check_file(write(tmp_path, body))
    msgs = [f.message for f in r.findings if f.code == "PHYS011"]
    assert msgs and "millimetre" in msgs[0]


def test_joint_without_limit_and_empty_range(tmp_path):
    body = ('<robot name="j">' + link("base") + link("a") + link("b")
            + joint("nolimit", "base", "a", limit="")
            + joint("empty", "base", "b", xyz=(0.5, 0, 0), limit='<limit lower="1" upper="1" effort="1" velocity="1"/>')
            + "</robot>")
    r = check_file(write(tmp_path, body))
    assert {"URDF022", "URDF023"} <= codes(r, "error")


def test_structure_errors(tmp_path):
    body = ('<robot name="s">' + link("base") + link("a") + link("orphan")
            + joint("j", "base", "a") + joint("ghost", "base", "missing") + "</robot>")
    r = check_file(write(tmp_path, body))
    assert {"URDF010", "URDF012"} <= codes(r, "error")


def test_missing_mesh_is_reported(tmp_path):
    body = ('<robot name="m"><link name="base"><visual><geometry><mesh filename="package://nope/x.stl"/>'
            '</geometry></visual></link></robot>')
    r = check_file(write(tmp_path, body))
    assert "URDF040" in codes(r, "error")


def test_siblings_overlapping_at_rest(tmp_path):
    # two children of the base occupying the same box; parent-child contact is
    # filtered by the simulator, sibling contact is not
    body = ('<robot name="o">' + link("base", size=(0.02, 0.02, 0.02))
            + link("a", mass=0.5, xyz=(0.1, 0, 0)) + link("b", mass=0.5, xyz=(0.1, 0, 0))
            + joint("ja", "base", "a", xyz=(0, 0, 0.2)) + joint("jb", "base", "b", xyz=(0, 0, 0.2)) + "</robot>")
    r = check_file(write(tmp_path, body))
    assert "PHYS020" in codes(r, "warning")


def test_child_overlapping_a_world_fixed_parent_is_explained(tmp_path):
    # the SO-101 case: MuJoCo filters parent-child contact except when the
    # parent is welded to the world, so an arm's base and shoulder collide
    body = ('<robot name="arm">' + link("base", size=(0.1, 0.1, 0.1))
            + link("shoulder", mass=0.3, size=(0.05, 0.05, 0.1))
            + joint("pan", "base", "shoulder", xyz=(0, 0, 0.02)) + "</robot>")
    r = check_file(write(tmp_path, body))
    msgs = [f.message for f in r.findings if f.code == "PHYS020"]
    assert msgs and "parent and child" in msgs[0]


# ── MJCF ──────────────────────────────────────────────────────────────────

def mjcf(body: str, option: str = "") -> str:
    return f'<mujoco><option {option}/><worldbody>{body}</worldbody></mujoco>'


def test_clean_floating_mjcf_settles(tmp_path):
    r = check_file(write(tmp_path, mjcf('<body pos="0 0 0.5"><freejoint/>'
                                        '<geom type="box" size="0.1 0.1 0.1" density="800"/></body>'), "b.xml"))
    assert r.ok and r.stats["floating_base"], [f.message for f in r.findings]
    assert not codes(r, "warning")


def test_implausible_density(tmp_path):
    r = check_file(write(tmp_path, mjcf('<body><freejoint/><geom type="box" size="0.1 0.1 0.1" mass="500"/>'
                                        '</body>'), "d.xml"))
    assert "PHYS010" in codes(r, "warning")


def test_divergence_is_an_error(tmp_path):
    # a feather on a very stiff spring at a coarse timestep: explicit
    # integration blows up. Started off its equilibrium by a keyframe, since a
    # spring at rest has nothing to integrate.
    body = ('<body><joint type="hinge" axis="0 1 0" stiffness="1e9" damping="0"/>'
            '<geom type="capsule" fromto="0 0 0 0 0 0.2" size="0.01" mass="1e-3"/></body>')
    xml = mjcf(body, 'timestep="0.01" integrator="Euler"').replace(
        "</mujoco>", '<keyframe><key qpos="0.5"/></keyframe></mujoco>')
    r = check_file(write(tmp_path, xml, "x.xml"))
    assert codes(r, "error") & {"PHYS030", "PHYS031"}, [f.message for f in r.findings]


def test_compile_error_is_reported_not_raised(tmp_path):
    r = check_file(write(tmp_path, mjcf('<body><joint type="hinge"/></body>'), "e.xml"))
    assert not r.loaded and "LOAD002" in codes(r, "error")


@pytest.mark.parametrize("bad", ["<robot><link", "<robot></robot>"])
def test_degenerate_files_do_not_crash(tmp_path, bad):
    r = check_file(write(tmp_path, bad))
    assert r.findings
