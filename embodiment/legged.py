"""A free-standing quadruped: torso, and four legs of thigh + shin + round foot.

Every joint is a pitch joint about the world lateral axis (Y). The legs are
mirror images: each leg's links stack outward from the torso along its own
axis, so the left axes point +Y and the right ones -Y, and the same joint
angle swings a left and a right leg in opposite directions. That is exactly
the convention that produced two wrong MicroDuck pose tables, so no sign is
written here by hand: the stance is given as physical flexion (thigh forward
by h, knee back by k) and each leg's joint sign is derived from where its
axis actually points in the world.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.domain.feature_graph import SketchEntity

from .catalog import actuator
from .spec import (Component, Foot, Joint, Link, Robot, _graph, bar_graph, box_graph,
                   translate)

LEGS = (("fl", +1, +1), ("fr", +1, -1), ("rl", -1, +1), ("rr", -1, -1))   # name, front(+x)?, left(+y)?


class QuadrupedSpec(BaseModel):
    kind: Literal["quadruped"] = "quadruped"
    name: str = "quadruped"
    torso_mm: tuple[float, float, float] = (160.0, 100.0, 8.0)   # length (x), width (y), thickness (z)
    hip_spacing_mm: float = Field(100.0, gt=0)                  # front hips to rear hips
    thigh_mm: float = Field(60.0, gt=0)
    shin_mm: float = Field(60.0, gt=0)
    link_width_mm: float = Field(20.0, gt=0)
    link_thickness_mm: float = Field(6.0, gt=0)
    bore_diameter_mm: float = Field(6.0, gt=0)
    foot_radius_mm: float = Field(12.0, gt=0)
    gap_mm: float = Field(2.0, gt=0)
    material: str = "pla"
    actuator: str = "mg996r_servo"
    joint_range_deg: float = Field(120.0, gt=0, le=180)
    joint_damping_nms: float = Field(0.05, ge=0)
    #: Stance: thigh forward of vertical by this much, knee bent back twice
    #: as far, which puts each foot directly under its hip.
    stance_hip_deg: float = Field(30.0, ge=0, lt=90)
    torque_safety_factor: float = Field(2.0, ge=1)


def shin_graph(length: float, width: float, thickness: float, bore: float, foot_r: float):
    """A shin from its knee bore to a round foot centred at x = length.

    The bar and the foot disc are one sketch, so they fuse into one solid:
    no volume, and so no mass, is counted twice.
    """
    params = {"thickness": thickness, "bar_len": length + width / 2, "bar_mid": (length - width / 2) / 2,
              "width": width, "foot_r": foot_r, "length": length, "bore_r": bore / 2}
    body = [SketchEntity(id="bar", type="rectangle",
                         params={"width": "$bar_len", "height": "$width", "cx": "$bar_mid", "cy": 0.0}),
            SketchEntity(id="foot", type="circle", params={"radius": "$foot_r", "cx": "$length", "cy": 0.0})]
    cuts = [SketchEntity(id="knee_bore", type="circle", params={"radius": "$bore_r", "cx": 0.0, "cy": 0.0})]
    return _graph(params, body, cuts, "$thickness")


def _leg_frame(left: bool) -> np.ndarray:
    """Rotation giving a leg link x = down and z = outward along its axis."""
    x = np.array([0.0, 0.0, -1.0])
    z = np.array([0.0, 1.0 if left else -1.0, 0.0])
    y = np.cross(z, x)
    R = np.eye(4)
    R[:3, :3] = np.column_stack([x, y, z])
    return R


def swing_sign(origin: np.ndarray) -> int:
    """+1 if a positive angle swings this leg forward (+x), else -1."""
    axis = origin[:3, :3] @ np.array([0.0, 0.0, 1.0])
    down = np.array([0.0, 0.0, -1.0])
    return 1 if np.dot(np.cross(axis, down), [1.0, 0.0, 0.0]) > 0 else -1


def expand_quadruped(spec: QuadrupedSpec) -> Robot:
    act = actuator(spec.actuator)
    sx, sz, sy = act["body_mm"]            # across the axis, height, along the axis (see spec.expand)
    L, W, T = spec.torso_mm
    w, t, g = spec.link_width_mm, spec.link_thickness_mm, spec.gap_mm
    rng = math.radians(spec.joint_range_deg)
    hx = spec.hip_spacing_mm / 2

    torso = Link("torso")
    torso.components.append(Component("torso_plate", box_graph(L, W, T), translate(0, 0, -T / 2),
                                      ("material", spec.material)))
    links, joints, feet = [torso], [], []
    h = math.radians(spec.stance_hip_deg)
    stand: dict[str, float] = {}

    for leg, fx, ly in LEGS:
        left = ly > 0
        # the hip servo, against the torso's side, centred on the hip joint
        torso.components.append(Component(
            f"{leg}_hip_servo", box_graph(sx, sy, sz),
            translate(fx * hx, ly * (W / 2 + sy / 2), -sz / 2), ("actuator", spec.actuator)))
        hip_origin = translate(fx * hx, ly * (W / 2 + sy + g), 0.0) @ _leg_frame(left)

        thigh = Link(f"{leg}_thigh")
        thigh.components.append(Component(f"{leg}_thigh_bar",
                                          bar_graph(spec.thigh_mm, w, t, spec.bore_diameter_mm),
                                          np.eye(4), ("material", spec.material)))
        # the knee servo, on the thigh's inboard face at its distal end
        thigh.components.append(Component(f"{leg}_knee_servo", box_graph(sx, sz, sy),
                                          translate(spec.thigh_mm, 0.0, -(g + sy)),
                                          ("actuator", spec.actuator)))
        shin = Link(f"{leg}_shin")
        shin.components.append(Component(
            f"{leg}_shin_foot",
            shin_graph(spec.shin_mm, w, t, spec.bore_diameter_mm, spec.foot_radius_mm),
            np.eye(4), ("material", spec.material)))
        links += [thigh, shin]

        knee_origin = translate(spec.thigh_mm, 0.0, t + g)
        joints.append(Joint(f"{leg}_hip", "torso", thigh.name, hip_origin, -rng, rng,
                            spec.actuator, spec.joint_damping_nms))
        joints.append(Joint(f"{leg}_knee", thigh.name, shin.name, knee_origin, -rng, rng,
                            spec.actuator, spec.joint_damping_nms))
        feet.append(Foot(shin.name, (spec.shin_mm, 0.0, t / 2), spec.foot_radius_mm))

        s = swing_sign(hip_origin)
        stand[f"{leg}_hip"] = s * h             # thigh forward by h
        stand[f"{leg}_knee"] = -s * 2 * h       # shin back by 2h relative: foot under the hip

    return Robot(spec.name, links, joints, floating=True, poses={"stand": stand}, feet=feet)
