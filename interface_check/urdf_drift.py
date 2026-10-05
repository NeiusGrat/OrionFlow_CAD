"""CAD vs URDF: has the simulation model drifted from the parts?

For each URDF link, the CAD mass and centre of mass of the instances it maps to
are computed and compared with its ``<inertial>``; each moving joint's axis is
compared with the bore/shaft the parent and child actually share near it.

Assumptions, stated in every report that runs this:
  * the CAD assembly is posed at the robot's zero joint position;
  * the URDF root frame is the CAD assembly origin;
  * URDF is in metres and kilograms, CAD in millimetres.

Mapping link -> CAD instances: a YAML file the user edits once
(``link: [instance path or path prefix, ...]``), else by name — a link named
after a part or a sub-assembly takes every instance under it.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .bom import norm
from .features import axis_offset
from .models import Features, Finding, Instance

MASS_REL = 0.05
COM_MM = 2.0
AXIS_DEG = 0.5
ORIGIN_MM = 1.0
JOINT_SEARCH_MM = 40.0
DEFAULT_DENSITY = 2700.0            # aluminium; flagged whenever used

DENSITY = {                         # kg/m^3
    "alumin": 2700, "6061": 2700, "7075": 2810, "5052": 2680, "steel": 7850, "stainless": 8000,
    "ss304": 8000, "ss316": 8000, "brass": 8500, "bronze": 8800, "copper": 8960, "titanium": 4430,
    "pla": 1240, "petg": 1270, "abs": 1050, "asa": 1070, "nylon": 1140, "pa12": 1010, "pa6": 1140,
    "pom": 1410, "delrin": 1410, "acetal": 1410, "carbon": 1600, "cfrp": 1600, "acrylic": 1190,
    "pmma": 1190, "polycarbonate": 1200, "pc": 1200, "tpu": 1210, "resin": 1150, "magnesium": 1800,
}

ASSUMPTIONS = [
    "URDF check: CAD assembly assumed posed at the zero joint position",
    "URDF check: URDF root frame assumed to coincide with the CAD assembly origin",
]


def density_for(material: str) -> float | None:
    m = (material or "").lower().replace(" ", "")
    for key, rho in DENSITY.items():
        if key in m:
            return float(rho)
    return None


def _floats(text, n, default=0.0):
    if not text:
        return [default] * n
    v = [float(x) for x in text.split()]
    return (v + [default] * n)[:n]


def rpy_matrix(r, p, y) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _origin(el) -> np.ndarray:
    T = np.eye(4)
    if el is not None:
        T[:3, :3] = rpy_matrix(*_floats(el.get("rpy"), 3))
        T[:3, 3] = _floats(el.get("xyz"), 3)
    return T


@dataclass
class Link:
    name: str
    mass: float | None = None
    com: np.ndarray | None = None           # metres, link frame
    meshes: list[str] = field(default_factory=list)
    frame: np.ndarray = field(default_factory=lambda: np.eye(4))   # link -> assembly, metres


@dataclass
class Joint:
    name: str
    type: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray


def parse(path: str | Path) -> tuple[dict[str, Link], list[Joint]]:
    root = ET.parse(str(path)).getroot()
    links: dict[str, Link] = {}
    for el in root.findall("link"):
        ln = Link(el.get("name", ""))
        inertial = el.find("inertial")
        if inertial is not None:
            m = inertial.find("mass")
            ln.mass = float(m.get("value")) if m is not None and m.get("value") else None
            ln.com = _origin(inertial.find("origin"))[:3, 3]
        for mesh in el.iter("mesh"):
            if mesh.get("filename"):
                ln.meshes.append(mesh.get("filename"))
        links[ln.name] = ln
    joints = []
    for el in root.findall("joint"):
        p, c = el.find("parent"), el.find("child")
        ax = el.find("axis")
        a = np.array(_floats(ax.get("xyz") if ax is not None else "1 0 0", 3))
        joints.append(Joint(el.get("name", ""), el.get("type", "fixed"), p.get("link") if p is not None else "",
                            c.get("link") if c is not None else "", _origin(el.find("origin")),
                            a / (np.linalg.norm(a) or 1.0)))
    children = {j.child for j in joints}
    by_parent: dict[str, list[Joint]] = {}
    for j in joints:
        by_parent.setdefault(j.parent, []).append(j)
    stack = [(name, np.eye(4)) for name in links if name not in children]
    while stack:
        name, T = stack.pop()
        if name in links:
            links[name].frame = T
        for j in by_parent.get(name, []):
            stack.append((j.child, T @ j.origin))
    return links, joints


def resolve_mesh(filename: str, urdf_path: Path, roots: list[Path]) -> Path | None:
    """file://, package://pkg/rel (pkg dir above the URDF or under a root), or relative."""
    if filename.startswith("file://"):
        p = Path(filename[7:])
        return p if p.exists() else None
    if filename.startswith("package://"):
        pkg, _, rel = filename[len("package://"):].partition("/")
        for parent in [urdf_path.parent, *urdf_path.parents][:6]:
            for cand in (parent / pkg / rel, parent / rel):
                if cand.exists():
                    return cand
        for root in roots:
            for d in [root, *[x for x in Path(root).rglob(pkg) if x.is_dir()][:20]]:
                if (d / rel).exists():
                    return d / rel
        return None
    for base in [urdf_path.parent, *roots]:
        p = (Path(base) / filename)
        if p.exists():
            return p
    return None


def load_map(path: str | Path | None) -> dict[str, list[str]]:
    if not path:
        return {}
    import yaml
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {str(k): [str(x) for x in (v or [])] for k, v in data.items()}


def map_links(links: dict[str, Link], instances: list[Instance], part_names: dict[str, str],
              mapping: dict[str, list[str]]) -> dict[str, list[Instance]]:
    out: dict[str, list[Instance]] = {name: [] for name in links}
    for inst in instances:
        if mapping:
            for link, prefixes in mapping.items():
                if any(inst.path == p or inst.path.startswith(p.rstrip("/") + "/") or inst.path.startswith(p + "#")
                       for p in prefixes):
                    out.setdefault(link, []).append(inst)
                    break
            continue
        keys = {norm(link): link for link in links}
        segs = [norm(s) for s in inst.path.split("/")] + [norm(part_names[inst.instance_id])]
        for s in reversed(segs):
            if s in keys:
                out[keys[s]].append(inst)
                break
    return out


def check(urdf_path: str | Path, instances: list[Instance], feats: dict[str, Features],
          part_names: dict[str, str], densities: dict[str, tuple[float, bool]],
          known_mass: dict[str, float], mapping_path: str | Path | None = None,
          search_roots: list[Path] | None = None) -> tuple[list[Finding], list[str], dict]:
    """``densities``: instance_id -> (kg/m^3, assumed?); ``known_mass``: instance_id -> kg."""
    urdf_path = Path(urdf_path)
    links, joints = parse(urdf_path)
    mapping = map_links(links, instances, part_names, load_map(mapping_path))
    findings: list[Finding] = []
    assumptions = list(ASSUMPTIONS)
    summary: dict = {"links": {}}

    roots = search_roots or [urdf_path.parent]
    for ln in links.values():
        for m in ln.meshes:
            if resolve_mesh(m, urdf_path, roots) is None:
                findings.append(Finding("URDF_MESH_MISSING", "medium", [], f"Link {ln.name} references mesh "
                                        f"'{m}', which is not in the upload.", parts=[ln.name], source="urdf"))

    mapped = {i.instance_id for insts in mapping.values() for i in insts}
    for inst in instances:
        if inst.instance_id not in mapped:
            findings.append(Finding("URDF_LINK_UNMAPPED", "low", [inst.path],
                                    f"{inst.name} belongs to no URDF link; its mass is missing from the simulation "
                                    "model (or add it to the link map).", parts=[part_names[inst.instance_id]],
                                    source="urdf"))
    assumed = False
    for name, ln in links.items():
        insts = mapping.get(name, [])
        if not insts:
            if ln.mass:
                findings.append(Finding("URDF_LINK_UNMAPPED", "medium", [], f"URDF link {name} "
                                        f"({ln.mass:g} kg) maps to no CAD part.", parts=[name], source="urdf"))
            continue
        m_tot, mom = 0.0, np.zeros(3)
        for i in insts:
            f = feats[i.instance_id]
            if i.instance_id in known_mass:
                m = known_mass[i.instance_id]
            else:
                rho, was_assumed = densities.get(i.instance_id, (DEFAULT_DENSITY, True))
                assumed |= was_assumed
                m = f.volume * 1e-9 * rho
            m_tot += m
            mom += m * f.com
        if m_tot <= 0:
            continue
        com_asm_mm = mom / m_tot
        T = ln.frame.copy()
        T[:3, 3] *= 1000.0
        com_link_mm = (np.linalg.inv(T) @ np.append(com_asm_mm, 1.0))[:3]
        summary["links"][name] = {"cad_mass_kg": round(m_tot, 5), "urdf_mass_kg": ln.mass,
                                  "cad_com_mm": np.round(com_link_mm, 3).tolist(),
                                  "urdf_com_mm": None if ln.com is None else np.round(ln.com * 1000, 3).tolist(),
                                  "instances": [i.path for i in insts]}
        paths = [i.path for i in insts]
        if ln.mass is not None and abs(ln.mass - m_tot) / m_tot > MASS_REL:
            findings.append(Finding(
                "URDF_MASS_DRIFT", "high", paths[:10],
                f"Link {name}: URDF mass {ln.mass:.4g} kg, CAD {m_tot:.4g} kg "
                f"({(ln.mass - m_tot) / m_tot:+.1%}).",
                measured={"urdf_mass_kg": ln.mass}, expected={"cad_mass_kg": round(m_tot, 5), "tol_rel": MASS_REL},
                parts=[name], location=list(com_asm_mm), source="urdf"))
        if ln.com is not None:
            d = float(np.linalg.norm(ln.com * 1000 - com_link_mm))
            if d > COM_MM:
                findings.append(Finding(
                    "URDF_COM_DRIFT", "medium", paths[:10],
                    f"Link {name}: URDF centre of mass is {d:.1f} mm from the CAD one.",
                    measured={"urdf_com_mm": np.round(ln.com * 1000, 3).tolist()},
                    expected={"cad_com_mm": np.round(com_link_mm, 3).tolist(), "tol_mm": COM_MM},
                    parts=[name], location=list(com_asm_mm), source="urdf"))
    if assumed:
        assumptions.append(f"URDF check: parts without a BOM material use {DEFAULT_DENSITY:g} kg/m³ (aluminium)")

    for j in joints:
        if j.type not in ("revolute", "continuous"):
            continue
        child = links.get(j.child)
        if child is None:
            continue
        origin_mm = child.frame[:3, 3] * 1000
        axis = child.frame[:3, :3] @ j.axis
        cyl = _shared_cylinder(mapping.get(j.parent, []), mapping.get(j.child, []), feats, origin_mm)
        if cyl is None:
            continue
        c_axis, c_point, what = cyl
        ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(axis, c_axis))))))
        paths = [i.path for i in mapping.get(j.parent, []) + mapping.get(j.child, [])][:10]
        if ang > AXIS_DEG:
            findings.append(Finding(
                "JOINT_AXIS_DRIFT", "high", paths,
                f"Joint {j.name}: URDF axis is {ang:.2f}° off the {what} shared by {j.parent} and {j.child}.",
                measured={"urdf_axis": np.round(axis, 4).tolist(), "angle_deg": round(ang, 3)},
                expected={"cad_axis": np.round(c_axis, 4).tolist(), "tol_deg": AXIS_DEG},
                parts=[j.name], location=list(origin_mm), source="urdf"))
        v = origin_mm - c_point
        off = float(np.linalg.norm(v - c_axis * np.dot(v, c_axis)))
        if off > ORIGIN_MM:
            findings.append(Finding(
                "JOINT_ORIGIN_DRIFT", "medium", paths,
                f"Joint {j.name}: URDF joint origin is {off:.1f} mm off the {what} axis in CAD.",
                measured={"offset_mm": round(off, 3)}, expected={"tol_mm": ORIGIN_MM},
                parts=[j.name], location=list(origin_mm), source="urdf"))
    return findings, assumptions, summary


def _shared_cylinder(parent: list[Instance], child: list[Instance], feats: dict[str, Features], near: np.ndarray):
    """The coaxial bore/shaft pair between parent and child closest to the joint origin."""
    def cyls(insts):
        for i in insts:
            f = feats[i.instance_id]
            for h in f.holes:
                yield h, "bore"
            for b in f.bosses:
                yield b, "shaft"
    best, best_d = None, JOINT_SEARCH_MM
    pc = list(cyls(parent))
    for cc, kind in cyls(child):
        if np.linalg.norm(cc.center - near) > JOINT_SEARCH_MM + cc.diameter:
            continue
        for pp, pkind in pc:
            if abs(abs(float(np.dot(pp.axis, cc.axis))) - 1) > 1e-4 or axis_offset(pp, cc.center) > 0.5:
                continue
            d = float(np.linalg.norm(cc.center - near))
            if d < best_d:
                best_d = d
                what = "bore/shaft" if {kind, pkind} == {"bore", "shaft"} else f"coaxial {kind}"
                best = (cc.axis, cc.center, f"Ø{cc.diameter:.1f} {what}")
    return best

