"""Robot spec -> links, components and joints.

A spec is a handful of numbers. `expand` turns it into the robot: every link
is a set of components, each one a FeatureGraph (the same IR the rest of
OrionFlow compiles) placed in the link's frame and tied to where its density
comes from - a material, or an actuator's catalogue mass. Joints carry their
limits from the actuator catalogue, never from the spec author.

Frames follow URDF: a link's frame sits on the joint that moves it, and the
joint turns about the link's +Z. World Z is up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

from app.domain.feature_graph import Feature, FeatureGraph, Sketch, SketchEntity

from .catalog import actuator


class ArmSpec(BaseModel):
    """A fixed-base serial arm whose joints turn about horizontal axes.

    Horizontal on purpose: gravity then loads every joint, so the actuator
    chosen has to hold the arm - a check a vertical-axis arm never exercises.
    """

    name: str = "two_link_arm"
    link_lengths_mm: list[float] = Field(default=[120.0, 100.0], min_length=1)
    link_width_mm: float = Field(24.0, gt=0)
    link_thickness_mm: float = Field(6.0, gt=0)
    bore_diameter_mm: float = Field(6.0, gt=0)
    base_footprint_mm: float = Field(70.0, gt=0)
    base_height_mm: float = Field(60.0, gt=0)
    #: Clearance between parts that move relative to each other.
    gap_mm: float = Field(2.0, gt=0)
    material: str = "pla"
    actuator: str = "mg996r_servo"
    joint_range_deg: float = Field(90.0, gt=0, le=180)
    joint_damping_nms: float = Field(0.05, ge=0)
    #: Required ratio of actuator torque to the worst static gravity torque.
    torque_safety_factor: float = Field(2.0, ge=1)


@dataclass
class Component:
    name: str
    graph: FeatureGraph
    #: 4x4, millimetres, the component's graph frame in the link frame.
    placement: np.ndarray
    #: ("material", key) or ("actuator", key)
    density_from: tuple[str, str]


@dataclass
class Link:
    name: str
    components: list[Component] = field(default_factory=list)


@dataclass
class Joint:
    name: str
    parent: str
    child: str
    #: 4x4, millimetres, the child's frame in the parent's.
    origin: np.ndarray
    lower: float
    upper: float
    actuator: str
    damping: float
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)


@dataclass
class Robot:
    name: str
    links: list[Link]
    joints: list[Joint]


# ── geometry as FeatureGraphs ──────────────────────────────────────────────

def _graph(params: dict, body: list[SketchEntity], cuts: list[SketchEntity], depth: str) -> FeatureGraph:
    sketches = [Sketch(id="body", plane="XY", entities=body)]
    features = [Feature(id="extrude", type="extrude", sketch="body", params={"depth": depth})]
    if cuts:
        sketches.append(Sketch(id="cuts", plane="XY", entities=cuts))
        features.append(Feature(id="bores", type="cut", sketch="cuts", params={"depth": depth},
                                depends_on=["extrude"]))
    return FeatureGraph(parameters=params, sketches=sketches, features=features)


def bar_graph(length: float, width: float, thickness: float, bore: float) -> FeatureGraph:
    """A flat link with a joint bore at each end, from x = 0 to x = length.

    The plate runs half a width past each bore centre so the bore has as
    much material around it as the bar is wide.
    """
    params = {"length": length, "width": width, "thickness": thickness,
              "overall": length + width, "mid": length / 2, "bore_r": bore / 2}
    body = [SketchEntity(id="plate", type="rectangle",
                         params={"width": "$overall", "height": "$width", "cx": "$mid", "cy": 0.0})]
    cuts = [SketchEntity(id="bore_0", type="circle", params={"radius": "$bore_r", "cx": 0.0, "cy": 0.0}),
            SketchEntity(id="bore_1", type="circle", params={"radius": "$bore_r", "cx": "$length", "cy": 0.0})]
    return _graph(params, body, cuts, "$thickness")


def box_graph(x: float, y: float, z: float) -> FeatureGraph:
    """A block, centred on the origin in x and y, from z = 0 to z = z."""
    params = {"x": x, "y": y, "z": z}
    body = [SketchEntity(id="block", type="rectangle", params={"width": "$x", "height": "$y"})]
    return _graph(params, body, [], "$z")


# ── transforms ─────────────────────────────────────────────────────────────

def translate(x: float, y: float, z: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = (x, y, z)
    return T


def rot_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    T = np.eye(4)
    T[1:3, 1:3] = [[c, -s], [s, c]]
    return T


def centred_box(dims: tuple[float, float, float], centre: tuple[float, float, float]) -> tuple[FeatureGraph, np.ndarray]:
    """A box graph and the placement that centres it on `centre`."""
    x, y, z = dims
    return box_graph(x, y, z), translate(centre[0], centre[1], centre[2] - z / 2)


# ── the arm ────────────────────────────────────────────────────────────────

def expand(spec: ArmSpec) -> Robot:
    """The arm as links and joints.

    Joint axes are world +Y. Links stack along the axis - each one a
    thickness plus a gap beyond its parent - and each joint's servo body sits
    on the parent link on the far side of the axis, so nothing that moves
    relative to anything else shares space at rest.
    """
    act = actuator(spec.actuator)
    sx, sz, sy = act["body_mm"]          # footprint across the axis, height, length along it
    # MG996R body_mm is [length, width, height] = [40.7, 19.7, 42.9]; the
    # output shaft runs along the 42.9 mm height, so that dimension lies
    # along the joint axis.
    w, t, g = spec.link_width_mm, spec.link_thickness_mm, spec.gap_mm
    rng = math.radians(spec.joint_range_deg)

    # Joint 1 sits so the shoulder servo rests on the base block.
    z_joint = spec.base_height_mm + sz / 2
    servo_centre_y = -(g + sy / 2)       # beyond the axis, away from link 1

    base = Link("base_link")
    block_graph, block_at = centred_box(
        (spec.base_footprint_mm, sy, spec.base_height_mm), (0.0, servo_centre_y, spec.base_height_mm / 2))
    base.components.append(Component("base_block", block_graph, block_at, ("material", spec.material)))
    servo_graph, servo_at = centred_box((sx, sy, sz), (0.0, servo_centre_y, z_joint))
    base.components.append(Component("shoulder_servo", servo_graph, servo_at, ("actuator", spec.actuator)))

    links, joints = [base], []
    parent = base.name
    # Link frames: x along the link, z along the joint axis. Rotating -90
    # degrees about x takes a link's z onto world +y and its y onto world -z.
    origin = translate(0.0, 0.0, z_joint) @ rot_x(-math.pi / 2)
    n = len(spec.link_lengths_mm)
    for i, length in enumerate(spec.link_lengths_mm, start=1):
        link = Link(f"link_{i}")
        link.components.append(Component(
            f"link_{i}_bar", bar_graph(length, w, t, spec.bore_diameter_mm), np.eye(4),
            ("material", spec.material)))
        if i < n:
            # The next joint's servo, on this link's distal end, on the side
            # of the bar away from the next link. In the link frame the
            # servo's height lies across the bar (y) and its length along
            # the axis (z).
            # box_graph extrudes z from 0 to sy, so this puts the body at
            # z in [-(g + sy), -g]: a gap short of the bar's back face.
            link.components.append(Component(
                f"joint_{i + 1}_servo", box_graph(sx, sz, sy), translate(length, 0.0, -(g + sy)),
                ("actuator", spec.actuator)))
        links.append(link)
        joints.append(Joint(f"joint_{i}", parent, link.name, origin, -rng, rng, spec.actuator,
                            spec.joint_damping_nms))
        parent = link.name
        # the next link: at this link's distal bore, one thickness and a gap
        # further along the axis
        origin = translate(length, 0.0, t + g)
    return Robot(spec.name, links, joints)
