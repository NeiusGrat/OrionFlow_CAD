"""Simulation export: mass properties, URDF, and SDF from a generated mesh.

The mesh is produced in millimetres; simulators want SI. We scale a copy to
metres, assign the material density, and read mass / centre of mass / inertia
tensor straight from trimesh — no diagonal-only approximations.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape

import numpy as np
import trimesh

logger = logging.getLogger(__name__)


def mass_properties(stl_path: str, density_g_cm3: float) -> dict:
    """Mass (kg), COM (m), and full inertia tensor (kg·m², about COM)."""
    mesh = trimesh.load(stl_path)
    si = mesh.copy()
    si.apply_scale(0.001)  # mm -> m
    si.density = density_g_cm3 * 1000.0  # g/cm³ -> kg/m³

    inertia = np.asarray(si.moment_inertia, dtype=float)
    return {
        "mass_kg": float(si.mass),
        "volume_mm3": float(mesh.volume),
        "com_m": [float(v) for v in si.center_mass],
        "inertia_kg_m2": {
            "ixx": float(inertia[0, 0]),
            "iyy": float(inertia[1, 1]),
            "izz": float(inertia[2, 2]),
            "ixy": float(inertia[0, 1]),
            "ixz": float(inertia[0, 2]),
            "iyz": float(inertia[1, 2]),
        },
        "watertight": bool(mesh.is_watertight),
    }


def _joint_xml_urdf(joints: list[dict], link_name: str) -> str:
    """Render plan joints as URDF joints against a fixed world link."""
    if not joints:
        return ""
    blocks = ['  <link name="world"/>']
    for j in joints:
        name = escape(str(j.get("name", "joint")))
        jtype = j.get("type", "revolute")
        if jtype not in ("revolute", "fixed", "prismatic", "continuous"):
            jtype = "revolute"
        axis = j.get("axis") or [0, 0, 1]
        lo, hi = (j.get("limit_deg") or [-90, 90])[:2]
        limit = (
            f'    <limit lower="{np.deg2rad(float(lo)):.4f}" '
            f'upper="{np.deg2rad(float(hi)):.4f}" effort="10" velocity="1"/>\n'
            if jtype in ("revolute", "prismatic")
            else ""
        )
        blocks.append(
            f'  <joint name="{name}" type="{jtype}">\n'
            f'    <parent link="world"/>\n'
            f'    <child link="{link_name}"/>\n'
            f'    <axis xyz="{axis[0]} {axis[1]} {axis[2]}"/>\n'
            f"{limit}"
            f"  </joint>"
        )
    return "\n".join(blocks) + "\n"


def generate_urdf(
    part_name: str,
    visual_mesh: str,
    collision_mesh: str,
    props: dict,
    material_name: str = "aluminum",
    rgba: str = "0.75 0.75 0.75 1.0",
    joints: list[dict] | None = None,
) -> str:
    """Single-link URDF. Mesh filenames are relative (ship them next to the
    .urdf); scale 0.001 converts our mm meshes to URDF metres."""
    name = escape(part_name)
    com = props["com_m"]
    i = props["inertia_kg_m2"]
    joint_xml = _joint_xml_urdf(joints or [], f"{name}_link")
    return f"""<?xml version="1.0"?>
<robot name="{name}">
{joint_xml}  <link name="{name}_link">
    <visual>
      <geometry>
        <mesh filename="{escape(visual_mesh)}" scale="0.001 0.001 0.001"/>
      </geometry>
      <material name="{escape(material_name)}">
        <color rgba="{rgba}"/>
      </material>
    </visual>
    <collision>
      <geometry>
        <mesh filename="{escape(collision_mesh)}" scale="0.001 0.001 0.001"/>
      </geometry>
    </collision>
    <inertial>
      <origin xyz="{com[0]:.6f} {com[1]:.6f} {com[2]:.6f}" rpy="0 0 0"/>
      <mass value="{props['mass_kg']:.6f}"/>
      <inertia ixx="{i['ixx']:.9f}" ixy="{i['ixy']:.9f}" ixz="{i['ixz']:.9f}"
               iyy="{i['iyy']:.9f}" iyz="{i['iyz']:.9f}" izz="{i['izz']:.9f}"/>
    </inertial>
  </link>
</robot>
"""


def generate_sdf(
    part_name: str,
    visual_mesh: str,
    collision_mesh: str,
    props: dict,
    rgba: str = "0.75 0.75 0.75 1.0",
) -> str:
    """SDF 1.7 model for Gazebo / Isaac Sim. Note: SDF inertials are expressed
    in the link frame at the COM pose given below."""
    name = escape(part_name)
    com = props["com_m"]
    i = props["inertia_kg_m2"]
    return f"""<?xml version="1.0"?>
<sdf version="1.7">
  <model name="{name}">
    <static>false</static>
    <link name="{name}_link">
      <inertial>
        <pose>{com[0]:.6f} {com[1]:.6f} {com[2]:.6f} 0 0 0</pose>
        <mass>{props['mass_kg']:.6f}</mass>
        <inertia>
          <ixx>{i['ixx']:.9f}</ixx>
          <ixy>{i['ixy']:.9f}</ixy>
          <ixz>{i['ixz']:.9f}</ixz>
          <iyy>{i['iyy']:.9f}</iyy>
          <iyz>{i['iyz']:.9f}</iyz>
          <izz>{i['izz']:.9f}</izz>
        </inertia>
      </inertial>
      <visual name="visual">
        <geometry>
          <mesh>
            <uri>{escape(visual_mesh)}</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
        <material>
          <diffuse>{rgba}</diffuse>
        </material>
      </visual>
      <collision name="collision">
        <geometry>
          <mesh>
            <uri>{escape(collision_mesh)}</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
      </collision>
    </link>
  </model>
</sdf>
"""
