"""URDF, MJCF, meshes and STEP from one compiled robot.

Both robot files are written from the same `CompiledLink` data, so a mass,
an inertia or a joint limit cannot differ between them. Simulator meshes are
in metres (neither file needs a scale attribute); STEP stays in millimetres,
the unit the CAD was built in.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from build123d import export_step

from .massprops import MassProps

#: MuJoCo integration step. Fine enough that the position actuators, whose
#: stiffness is integrated explicitly, stay stable on these light links.
TIMESTEP = 0.001
#: A legged robot's shins are lighter still, and it also has contact.
LEGGED_TIMESTEP = 0.0005


@dataclass
class CompiledJoint:
    name: str
    parent: str
    child: str
    origin_mm: np.ndarray       # 4x4
    axis: tuple
    lower: float
    upper: float
    effort_nm: float
    velocity_rad_s: float
    damping: float
    kp: float


@dataclass
class CompiledLink:
    name: str
    mass: MassProps
    solids: list = field(default_factory=list)          # placed, mm, link frame
    visual: str = ""                                    # mesh file name
    collision: list[str] = field(default_factory=list)  # one convex mesh per component


def _f(x: float) -> str:
    return f"{float(x):.9g}"


def _vec(v) -> str:
    return " ".join(_f(x) for x in v)


def rpy(R: np.ndarray) -> tuple[float, float, float]:
    """Rotation matrix -> URDF roll, pitch, yaw (R = Rz(y) Ry(p) Rx(r))."""
    sy = math.hypot(R[0, 0], R[1, 0])
    if sy > 1e-9:
        return (math.atan2(R[2, 1], R[2, 2]), math.atan2(-R[2, 0], sy), math.atan2(R[1, 0], R[0, 0]))
    return (math.atan2(-R[1, 2], R[1, 1]), math.atan2(-R[2, 0], sy), 0.0)


def quat(R: np.ndarray) -> tuple[float, float, float, float]:
    """Rotation matrix -> MuJoCo quaternion (w, x, y, z)."""
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = (0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s)
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
        q = [0.0] * 4
        q[0] = (R[k, j] - R[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (R[j, i] + R[i, j]) / s
        q[1 + k] = (R[k, i] + R[i, k]) / s
        q = tuple(q)
    n = math.sqrt(sum(x * x for x in q))
    q = tuple(x / n for x in q)
    return q if q[0] >= 0 else tuple(-x for x in q)


def _inertia_attrs(I: np.ndarray) -> dict[str, str]:
    return {"ixx": _f(I[0, 0]), "iyy": _f(I[1, 1]), "izz": _f(I[2, 2]),
            "ixy": _f(I[0, 1]), "ixz": _f(I[0, 2]), "iyz": _f(I[1, 2])}


def urdf(name: str, links: list[CompiledLink], joints: list[CompiledJoint]) -> str:
    out = [f'<?xml version="1.0"?>', f'<robot name="{name}">']
    for l in links:
        I = _inertia_attrs(l.mass.inertia_kg_m2)
        out += [f'  <link name="{l.name}">',
                "    <inertial>",
                f'      <origin xyz="{_vec(l.mass.com_m)}" rpy="0 0 0"/>',
                f'      <mass value="{_f(l.mass.mass_kg)}"/>',
                "      <inertia " + " ".join(f'{k}="{v}"' for k, v in I.items()) + "/>",
                "    </inertial>",
                "    <visual>",
                f'      <geometry><mesh filename="meshes/{l.visual}"/></geometry>',
                "    </visual>"]
        for c in l.collision:
            out += ["    <collision>", f'      <geometry><mesh filename="meshes/{c}"/></geometry>', "    </collision>"]
        out.append("  </link>")
    for j in joints:
        R, p = j.origin_mm[:3, :3], j.origin_mm[:3, 3] * 1e-3
        out += [f'  <joint name="{j.name}" type="revolute">',
                f'    <parent link="{j.parent}"/>',
                f'    <child link="{j.child}"/>',
                f'    <origin xyz="{_vec(p)}" rpy="{_vec(rpy(R))}"/>',
                f'    <axis xyz="{_vec(j.axis)}"/>',
                f'    <limit lower="{_f(j.lower)}" upper="{_f(j.upper)}" '
                f'effort="{_f(j.effort_nm)}" velocity="{_f(j.velocity_rad_s)}"/>',
                f'    <dynamics damping="{_f(j.damping)}" friction="0"/>',
                "  </joint>"]
    out.append("</robot>")
    return "\n".join(out) + "\n"


def mjcf(name: str, links: list[CompiledLink], joints: list[CompiledJoint], *,
         floating: bool = False, poses: dict[str, dict[str, float]] | None = None,
         root_pos_m: tuple[float, float, float] = (0.0, 0.0, 0.0), timestep: float = TIMESTEP) -> str:
    """MJCF for the robot; a floating one gets a free joint and a keyframe
    per named pose, its root placed so the pose's feet touch z = 0."""
    by_child = {j.child: j for j in joints}
    children: dict[str, list[str]] = {}
    for j in joints:
        children.setdefault(j.parent, []).append(j.child)
    by_name = {l.name: l for l in links}
    meshes = [m for l in links for m in [l.visual, *l.collision]]

    def body(lname: str, depth: int) -> list[str]:
        pad = "  " * depth
        l = by_name[lname]
        j = by_child.get(lname)
        if j is None and floating:
            head = f'{pad}<body name="{lname}" pos="{_vec(root_pos_m)}">'
        elif j is None:
            head = f'{pad}<body name="{lname}">'
        else:
            R, p = j.origin_mm[:3, :3], j.origin_mm[:3, 3] * 1e-3
            head = f'{pad}<body name="{lname}" pos="{_vec(p)}" quat="{_vec(quat(R))}">'
        I = l.mass.inertia_kg_m2
        lines = [head,
                 f'{pad}  <inertial pos="{_vec(l.mass.com_m)}" mass="{_f(l.mass.mass_kg)}" '
                 f'fullinertia="{_f(I[0,0])} {_f(I[1,1])} {_f(I[2,2])} {_f(I[0,1])} {_f(I[0,2])} {_f(I[1,2])}"/>']
        if j is None and floating:
            lines.append(f'{pad}  <freejoint name="root"/>')
        if j is not None:
            lines.append(f'{pad}  <joint name="{j.name}" type="hinge" axis="{_vec(j.axis)}" '
                         f'range="{_f(j.lower)} {_f(j.upper)}" damping="{_f(j.damping)}" '
                         f'actuatorfrcrange="{_f(-j.effort_nm)} {_f(j.effort_nm)}"/>')
        lines.append(f'{pad}  <geom class="visual" mesh="{Path(l.visual).stem}"/>')
        for c in l.collision:
            lines.append(f'{pad}  <geom class="collision" mesh="{Path(c).stem}"/>')
        for ch in children.get(lname, []):
            lines += body(ch, depth + 1)
        lines.append(f"{pad}</body>")
        return lines

    root = next(l.name for l in links if l.name not in by_child)
    out = [f'<mujoco model="{name}">',
           '  <compiler angle="radian" meshdir="meshes" autolimits="true"/>',
           f'  <option timestep="{_f(timestep)}"/>',
           "  <default>",
           '    <default class="visual"><geom type="mesh" contype="0" conaffinity="0" group="2"/></default>',
           '    <default class="collision"><geom type="mesh" group="3"/></default>',
           "  </default>",
           "  <asset>"]
    out += [f'    <mesh name="{Path(m).stem}" file="{m}"/>' for m in meshes]
    out += ["  </asset>", "  <worldbody>"]
    out += body(root, 2)
    out += ["  </worldbody>", "  <actuator>"]
    # Position servos: target 0 holds the rest pose; force capped at the
    # catalogue stall torque, the target at the joint's range.
    out += [f'    <position name="{j.name}_servo" joint="{j.name}" kp="{_f(j.kp)}" '
            f'forcerange="{_f(-j.effort_nm)} {_f(j.effort_nm)}" ctrlrange="{_f(j.lower)} {_f(j.upper)}"/>'
            for j in joints]
    out += ["  </actuator>", "  <keyframe>"]
    if poses:
        for pname, q in poses.items():
            angles = [q.get(j.name, 0.0) for j in joints]
            root = [*root_pos_m, 1.0, 0.0, 0.0, 0.0] if floating else []
            out.append(f'    <key name="{pname}" qpos="{_vec(root + angles)}" ctrl="{_vec(angles)}"/>')
    else:
        out.append(f'    <key name="home" qpos="{_vec([0.0] * len(joints))}" ctrl="{_vec([0.0] * len(joints))}"/>')
    out += ["  </keyframe>", "</mujoco>"]
    return "\n".join(out) + "\n"


_STEP_STAMP = re.compile(r"(FILE_NAME\('[^']*',')[^']*(')")


def step(path: Path, shape) -> None:
    """STEP with a fixed timestamp, so the same robot writes the same bytes."""
    export_step(shape, str(path))
    text = path.read_text(encoding="utf-8", errors="replace")
    path.write_text(_STEP_STAMP.sub(r"\g<1>1970-01-01T00:00:00\g<2>", text, count=1), encoding="utf-8")
