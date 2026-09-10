"""Emit the assembly's part placements for the FreeCAD-side builder.

The kinematic model lives in the main interpreter (numpy/trimesh) and the B-rep
lives in FreeCAD's, so the two talk through this JSON: the body tree, one entry
per placed part with its 4x4 world transform in millimetres, and the joint frames
needed to pose the robot.

`pose` maps joint name -> angle in radians. Poses are applied about each joint's
own axis in its own body frame, exactly as MuJoCo does, so a pose emitted here
and a pose simulated there are the same configuration.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from mjcf_model import MJCF, Model, transform

ROOT = Path(__file__).resolve().parent.parent

#: The simulator ships two configurations of the same robot. The rollers build
#: swaps the feet for skates and adds four passive wheel joints, and it is the
#: only place the rim/tire/roller_blade/ankle_*_v1 parts appear - so building it
#: too is what makes the reconstruction cover all 43 source meshes.
VARIANTS = {
    "": MJCF,
    "rollers": MJCF.parent / "robot_allcollisions_rollers.xml",
}


def axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation about `axis` (already a unit vector in the body frame)."""
    a = axis / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * (K @ K)


def world_transforms(model: Model, pose: dict[str, float] | None = None):
    """World transform per body at `pose` (radians), root fixed at the origin."""
    pose = pose or {}
    out: dict[str, np.ndarray] = {}
    for name in model.order:
        b = model.bodies[name]
        if b.parent is None:
            out[name] = np.eye(4)
            continue
        T = out[b.parent] @ b.T_parent
        if b.joint is not None:
            angle = float(pose.get(b.joint.name, 0.0))
            if angle:
                T = T @ transform(np.zeros(3), axis_rotation(b.joint.axis, angle))
        out[name] = T
    return out


def build(pose: dict[str, float] | None = None, label: str = "zero",
          variant: str = "") -> dict:
    model = Model(VARIANTS[variant])
    W = world_transforms(model, pose)
    bodies, instances = [], []
    for name in model.order:
        b = model.bodies[name]
        bodies.append({
            "name": name,
            "parent": b.parent,
            "mass_g": round(b.mass * 1000, 3),
            "com_mm": None if b.com is None else [round(float(x), 4) for x in b.com],
            "joint": None if b.joint is None else {
                "name": b.joint.name,
                "axis": [float(x) for x in b.joint.axis],
                "range_deg": None if b.joint.range is None
                else [round(math.degrees(float(x)), 3) for x in b.joint.range],
            },
        })
        for i, inst in enumerate(b.instances):
            instances.append({
                "body": name,
                "part": inst.mesh,
                "id": f"{name}__{inst.mesh}__{i}",
                "matrix": [round(float(x), 6) for x in (W[name] @ inst.T).ravel()],
            })
    return {"label": label, "variant": variant or "walker", "pose": pose or {},
            "bodies": bodies, "instances": instances,
            "total_mass_g": round(model.total_mass() * 1000, 2)}


#: A few configurations worth having as built assemblies, not just as numbers.
POSES = {
    "zero": {},
    "stand": {
        "left_hip_pitch": -0.25, "left_knee": 0.5, "left_ankle": -0.25,
        "right_hip_pitch": -0.25, "right_knee": 0.5, "right_ankle": -0.25,
    },
    "crouch": {
        "left_hip_pitch": -0.9, "left_knee": 1.5, "left_ankle": -0.6,
        "right_hip_pitch": -0.9, "right_knee": 1.5, "right_ankle": -0.6,
        "neck_pitch": 0.3, "head_pitch": -0.3,
    },
}


#: (file label, pose name, variant)
BUILDS = [(name, name, "") for name in POSES] + [("rollers", "zero", "rollers")]


def main() -> None:
    out = ROOT / "work"
    out.mkdir(exist_ok=True)
    for label, pose_name, variant in BUILDS:
        data = build(POSES[pose_name], label, variant)
        (out / f"placements_{label}.json").write_text(json.dumps(data, indent=1))
        print(f"{label:8s} variant={data['variant']:7s} bodies={len(data['bodies'])} "
              f"instances={len(data['instances'])} mass={data['total_mass_g']} g")


if __name__ == "__main__":
    main()
