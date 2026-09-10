"""Export the assembled robot as GLB, and as a URDF driven by our own parts.

The GLB is the quick visual check that the placements are right - a limb rotated
about the wrong axis is obvious in a viewer and invisible in a transform table.

The URDF is emitted from the same recovered model, so the articulated robot and
the CAD assembly cannot drift apart: both read the body tree, the joint axes and
the joint limits out of mjcf_model.
"""
from __future__ import annotations

import math
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

from export_placements import BUILDS, POSES, VARIANTS, world_transforms
from mjcf_model import Model

ROOT = Path(__file__).resolve().parent.parent
REPAIRED = ROOT / "work" / "repaired"
OUT = ROOT / "out"


def scene(model: Model, pose: dict[str, float] | None = None) -> trimesh.Scene:
    W = world_transforms(model, pose)
    sc = trimesh.Scene()
    cache: dict[str, trimesh.Trimesh] = {}
    for name in model.order:
        body = model.bodies[name]
        for i, inst in enumerate(body.instances):
            if inst.mesh not in cache:
                cache[inst.mesh] = trimesh.load(REPAIRED / f"{inst.mesh}.stl")
            sc.add_geometry(cache[inst.mesh], node_name=f"{name}__{inst.mesh}__{i}",
                            geom_name=inst.mesh, transform=W[name] @ inst.T)
    return sc


def export_glb(label: str = "zero", pose_name: str = "zero",
               variant: str = "") -> Path:
    model = Model(VARIANTS[variant])
    sc = scene(model, POSES[pose_name])
    path = OUT / f"microduck_{label}.glb"
    path.write_bytes(trimesh.exchange.gltf.export_glb(sc))
    return path


def _xyz(v) -> str:
    return " ".join(f"{float(x):.9g}" for x in v)


def _rpy(R: np.ndarray) -> tuple[float, float, float]:
    """Rotation matrix -> URDF roll/pitch/yaw (fixed XYZ)."""
    sy = math.hypot(R[0, 0], R[1, 0])
    if sy > 1e-9:
        return (math.atan2(R[2, 1], R[2, 2]), math.atan2(-R[2, 0], sy),
                math.atan2(R[1, 0], R[0, 0]))
    return (math.atan2(-R[1, 2], R[1, 1]), math.atan2(-R[2, 0], sy), 0.0)


def export_urdf(mesh_dir: str = "meshes") -> Path:
    """URDF in metres, with one link per MJCF body and our parts as its visuals."""
    model = Model()
    robot = ET.Element("robot", name="microduck")
    ET.SubElement(robot, "material", name="shell").append(
        ET.Element("color", rgba="0.93 0.90 0.83 1"))

    for name in model.order:
        b = model.bodies[name]
        link = ET.SubElement(robot, "link", name=name)

        inertial = ET.SubElement(link, "inertial")
        com = (b.com if b.com is not None else np.zeros(3)) / 1000.0
        ET.SubElement(inertial, "origin", xyz=_xyz(com), rpy="0 0 0")
        ET.SubElement(inertial, "mass", value=f"{b.mass:.9g}")
        # the MJCF carries only diagonal-equivalent inertias per body; a solid
        # box about the com is a better default than an arbitrary unit tensor
        ET.SubElement(inertial, "inertia", ixx="1e-5", ixy="0", ixz="0",
                      iyy="1e-5", iyz="0", izz="1e-5")

        for inst in b.instances:
            for tag in ("visual", "collision"):
                el = ET.SubElement(link, tag)
                r, p, y = _rpy(inst.T[:3, :3])
                ET.SubElement(el, "origin", xyz=_xyz(inst.T[:3, 3] / 1000.0),
                              rpy=f"{r:.9g} {p:.9g} {y:.9g}")
                geom = ET.SubElement(el, "geometry")
                ET.SubElement(geom, "mesh",
                              filename=f"{mesh_dir}/{inst.mesh}.stl",
                              scale="0.001 0.001 0.001")
                if tag == "visual":
                    ET.SubElement(el, "material", name="shell")

    for name in model.order:
        b = model.bodies[name]
        if b.parent is None or b.joint is None:
            continue
        j = ET.SubElement(robot, "joint", name=b.joint.name, type="revolute")
        ET.SubElement(j, "parent", link=b.parent)
        ET.SubElement(j, "child", link=name)
        r, p, y = _rpy(b.T_parent[:3, :3])
        ET.SubElement(j, "origin", xyz=_xyz(b.T_parent[:3, 3] / 1000.0),
                      rpy=f"{r:.9g} {p:.9g} {y:.9g}")
        ET.SubElement(j, "axis", xyz=_xyz(b.joint.axis))
        lo, hi = (b.joint.range if b.joint.range is not None else (-math.pi, math.pi))
        ET.SubElement(j, "limit", lower=f"{lo:.9g}", upper=f"{hi:.9g}",
                      effort="0.96", velocity="10")

    path = OUT / "microduck.urdf"
    ET.indent(robot, space="  ")
    path.write_bytes(ET.tostring(robot, encoding="utf-8", xml_declaration=True))
    return path


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for label, pose_name, variant in BUILDS:
        p = export_glb(label, pose_name, variant)
        print(f"{p.name:28s} {p.stat().st_size / 1024 / 1024:6.2f} MB")
    u = export_urdf()
    model = Model()
    print(f"{u.name:28s} {u.stat().st_size / 1024:6.1f} kB  "
          f"links={len(model.bodies)} joints={len(model.joints)}")


if __name__ == "__main__":
    main()
