"""URDF: checks on the file as written, and a copy MuJoCo can compile.

The raw checks run before MuJoCo sees the model on purpose. MuJoCo repairs
some defects on import (``balanceinertia`` rewrites an impossible inertia,
a link without ``<inertial>`` can be given one from its geometry), and a
checker that only looked at the compiled model would report the repaired
robot as the one in the file.
"""
from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from .findings import Report

#: Mesh formats MuJoCo reads directly. Anything else is converted to STL.
MUJOCO_MESHES = {".stl", ".obj", ".msh"}

#: Relative slack on the inertia triangle inequality (A + B >= C). Exported
#: inertias are rounded; a body that misses by a part in a thousand is a
#: rounding artefact, not an impossible body.
TRIANGLE_TOL = 1e-3


def _floats(text: str | None, n: int, default: float = 0.0) -> list[float]:
    if not text:
        return [default] * n
    vals = [float(v) for v in text.split()]
    return (vals + [default] * n)[:n]


def inertia_problem(ixx, iyy, izz, ixy, ixz, iyz) -> str | None:
    """Why no rigid body can have this inertia tensor, or None if one can."""
    I = np.array([[ixx, ixy, ixz], [ixy, iyy, iyz], [ixz, iyz, izz]], dtype=float)
    if not np.all(np.isfinite(I)):
        return "inertia is not finite"
    ev = np.sort(np.linalg.eigvalsh(I))
    scale = max(abs(ev).max(), 1e-30)
    if ev[0] <= 1e-12 * scale:
        return f"inertia is not positive definite (principal moments {ev.tolist()})"
    if ev[0] + ev[1] < ev[2] * (1 - TRIANGLE_TOL):
        return (f"principal moments {ev.round(12).tolist()} violate the triangle "
                f"inequality A + B >= C")
    return None


def resolve_mesh(filename: str, urdf_path: Path, search_roots: list[Path]) -> Path | None:
    """Turn a URDF mesh reference into a file on disk."""
    if filename.startswith("file://"):
        p = Path(filename[7:])
        return p if p.exists() else None
    if filename.startswith("package://"):
        rest = filename[len("package://"):]
        pkg, _, rel = rest.partition("/")
        # A ROS package is a directory named after it; look above the URDF
        # first, then anywhere under the given roots (a cloned repository).
        for parent in [urdf_path.parent, *urdf_path.parents]:
            cand = parent / pkg / rel
            if cand.exists():
                return cand
            if parent.name == pkg and (parent / rel).exists():
                return parent / rel
        for root in search_roots:
            for d in _dirs_named(root, pkg):
                if (d / rel).exists():
                    return d / rel
        # Some repositories ship the package contents without the package dir.
        for parent in [urdf_path.parent, *urdf_path.parents][:4]:
            if (parent / rel).exists():
                return parent / rel
        return None
    for base in [urdf_path.parent, *search_roots]:
        p = (Path(base) / filename).resolve()
        if p.exists():
            return p
    return None


_DIR_CACHE: dict[tuple[str, str], list[Path]] = {}


def _dirs_named(root: Path, name: str) -> list[Path]:
    key = (str(root), name)
    if key not in _DIR_CACHE:
        found = []
        for dirpath, dirnames, _ in os.walk(root):
            if dirpath.count(os.sep) - str(root).count(os.sep) > 5:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if name in dirnames:
                found.append(Path(dirpath) / name)
        _DIR_CACHE[key] = found
    return _DIR_CACHE[key]


def check_raw(path: Path, report: Report, search_roots: list[Path]) -> ET.Element | None:
    """Structural, inertial and joint checks on the URDF as written."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        report.add("URDF001", "error", f"not well-formed XML: {exc}")
        return None
    if root.tag != "robot":
        report.add("URDF002", "error", f"root element is <{root.tag}>, not <robot>")
        return None

    links = {l.get("name"): l for l in root.findall("link")}
    joints = root.findall("joint")
    report.stats.update(links=len(links), joints=len(joints))

    parent_of: dict[str, str] = {}
    moving_children: set[str] = set()
    for j in joints:
        name = j.get("name", "?")
        jtype = j.get("type", "")
        p = j.find("parent")
        c = j.find("child")
        pl = p.get("link") if p is not None else None
        cl = c.get("link") if c is not None else None
        for role, l in (("parent", pl), ("child", cl)):
            if l not in links:
                report.add("URDF010", "error", f"{role} link {l!r} does not exist", where=f"joint {name}")
        if cl in parent_of:
            report.add("URDF011", "error", f"link {cl!r} has two parents ({parent_of[cl]!r}, {pl!r})",
                       where=f"joint {name}")
        if cl:
            parent_of[cl] = pl
        if jtype != "fixed" and cl:
            moving_children.add(cl)

        axis = j.find("axis")
        if jtype in ("revolute", "continuous", "prismatic"):
            xyz = _floats(axis.get("xyz") if axis is not None else "1 0 0", 3)
            n = float(np.linalg.norm(xyz))
            if n < 1e-9:
                report.add("URDF020", "error", "joint axis is zero", where=f"joint {name}")
            elif abs(n - 1) > 1e-3:
                report.add("URDF021", "info", f"joint axis is not unit length ({n:.4f}); simulators normalise it",
                           where=f"joint {name}")
        if jtype in ("revolute", "prismatic"):
            lim = j.find("limit")
            if lim is None:
                report.add("URDF022", "error", f"{jtype} joint has no <limit> (required by the URDF spec)",
                           where=f"joint {name}")
            else:
                lo = float(lim.get("lower", 0))
                hi = float(lim.get("upper", 0))
                if lo >= hi:
                    report.add("URDF023", "error", f"joint range is empty (lower {lo} >= upper {hi})",
                               where=f"joint {name}", value=[lo, hi])
                for attr in ("effort", "velocity"):
                    v = lim.get(attr)
                    if v is None or float(v) <= 0:
                        report.add("URDF024", "warning",
                                   f"{attr} limit is {'missing' if v is None else v}: a drive with no {attr} "
                                   "limit either cannot move or is unbounded, depending on the simulator",
                                   where=f"joint {name}")

    roots = [l for l in links if l not in parent_of]
    if len(roots) != 1:
        report.add("URDF012", "error", f"expected one root link, found {len(roots)}: {roots[:5]}")
    # cycles: walk up from every link
    for l in links:
        seen, cur = set(), l
        while cur in parent_of:
            if cur in seen:
                report.add("URDF013", "error", "kinematic loop", where=f"link {l}")
                break
            seen.add(cur)
            cur = parent_of[cur]

    for name, link in links.items():
        # A link on a fixed joint (or the root) is lumped into its parent by
        # every simulator; with zero mass and zero inertia it is a frame - an
        # IMU, a foot contact point - and that is legitimate. Only a link that
        # moves on its own joint must carry a valid mass and inertia.
        moving = name in moving_children
        inertial = link.find("inertial")
        if inertial is None:
            if moving:
                report.add("URDF030", "warning",
                           "moving link has no <inertial>: simulators give it a default mass or reject it",
                           where=f"link {name}")
            continue
        m_el = inertial.find("mass")
        mass = float(m_el.get("value", "nan")) if m_el is not None else float("nan")
        i_el = inertial.find("inertia")
        vals = ({k: float(i_el.get(k, 0)) for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")}
                if i_el is not None else {})
        if not moving and mass == 0 and not any(vals.values()):
            continue
        if not np.isfinite(mass) or mass <= 0:
            report.add("URDF031", "error" if moving else "warning",
                       f"mass is {mass}" + ("" if moving else " on a fixed link"),
                       where=f"link {name}", value=mass)
        if i_el is None:
            report.add("URDF032", "error" if moving else "warning", "<inertial> has no <inertia>",
                       where=f"link {name}")
            continue
        why = inertia_problem(**vals)
        if why:
            report.add("URDF033", "error" if moving else "warning",
                       why + ("" if moving else " (fixed link: lumped into its parent)"),
                       where=f"link {name}", value=vals)

    for el in root.iter("mesh"):
        fn = el.get("filename", "")
        if not resolve_mesh(fn, path, search_roots):
            report.add("URDF040", "error", f"mesh file not found: {fn}")
    return root


def _is_ascii_stl(p: Path) -> bool:
    """Binary STL is 84 + 50n bytes; an ASCII one starts with 'solid' and is not."""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            head = fh.read(84)
        if len(head) < 84:
            return True
        n = int.from_bytes(head[80:84], "little")
        return head[:5].lower() == b"solid" and size != 84 + 50 * n
    except OSError:
        return False


def _origin(el) -> np.ndarray:
    """4x4 from a URDF <origin xyz rpy>."""
    T = np.eye(4)
    if el is None:
        return T
    x, y, z = _floats(el.get("xyz"), 3)
    r, p, w = _floats(el.get("rpy"), 3)
    cr, sr, cp, sp, cw, sw = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(w), np.sin(w)
    T[:3, :3] = [[cw * cp, cw * sp * sr - sw * cr, cw * sp * cr + sw * sr],
                 [sw * cp, sw * sp * sr + cw * cr, sw * sp * cr - cw * sr],
                 [-sp, cp * sr, cp * cr]]
    T[:3, 3] = (x, y, z)
    return T


def visual_shapes(path: Path, root: ET.Element, search_roots: list[Path]) -> dict:
    """link name -> its visual geometry as one mesh in the link frame.

    MuJoCo is given the collision geometry (that is what contact uses), but a
    collision shape is often a proxy - a cylinder for a hip casting - and
    reading mass, inertia or centre of mass against a proxy reports defects
    the robot does not have. The visual meshes are the part.
    """
    import trimesh

    out = {}
    for link in root.findall("link"):
        parts = []
        for vis in link.findall("visual"):
            g = vis.find("geometry")
            if g is None:
                continue
            m = None
            if g.find("mesh") is not None:
                el = g.find("mesh")
                src = resolve_mesh(el.get("filename", ""), path, search_roots)
                if src is None:
                    continue
                try:
                    m = trimesh.load(src, force="mesh")
                except Exception:
                    continue
                sc = _floats(el.get("scale"), 3, 1.0) if el.get("scale") else [1.0, 1.0, 1.0]
                m.apply_scale(sc)
            elif g.find("box") is not None:
                m = trimesh.creation.box(extents=_floats(g.find("box").get("size"), 3))
            elif g.find("cylinder") is not None:
                c = g.find("cylinder")
                m = trimesh.creation.cylinder(radius=float(c.get("radius", 0)), height=float(c.get("length", 0)))
            elif g.find("sphere") is not None:
                m = trimesh.creation.icosphere(subdivisions=2, radius=float(g.find("sphere").get("radius", 0)))
            if m is None or not len(m.faces):
                continue
            m.apply_transform(_origin(vis.find("origin")))
            parts.append(m)
        if parts:
            out[link.get("name")] = trimesh.util.concatenate(parts)
    # MuJoCo fuses links on fixed joints into their parent, so the parent's
    # body carries their mass - and must carry their shape too.
    up = {}   # fixed-joint child -> (parent, transform of child frame in parent)
    for j in root.findall("joint"):
        p, c = j.find("parent"), j.find("child")
        if j.get("type") == "fixed" and p is not None and c is not None:
            up[c.get("link")] = (p.get("link"), _origin(j.find("origin")))
    fused = {}
    for name, shape in out.items():
        target, T, seen = name, np.eye(4), set()
        while target in up and target not in seen:     # climb to the body it fuses into
            seen.add(target)
            parent, T_pc = up[target]
            T = T_pc @ T
            target = parent
        s = shape.copy()
        s.apply_transform(T)
        fused[target] = trimesh.util.concatenate([fused[target], s]) if target in fused else s
    return fused


def mujoco_copy(path: Path, root: ET.Element, search_roots: list[Path], workdir: Path,
                report: Report, *, balance_inertia: bool, strip_materials: bool = False) -> Path:
    """Write a URDF MuJoCo can compile: absolute mesh paths, converted formats."""
    import copy

    import trimesh

    root = copy.deepcopy(root)
    meshdir = workdir / "meshes"
    meshdir.mkdir(parents=True, exist_ok=True)
    unconvertible: set[str] = set()
    ascii_stl: set[str] = set()
    for el in root.iter("mesh"):
        src = resolve_mesh(el.get("filename", ""), path, search_roots)
        if src is None:
            continue
        if src.suffix.lower() == ".stl" and _is_ascii_stl(src):
            ascii_stl.add(src.name)
        elif src.suffix.lower() in MUJOCO_MESHES:
            el.set("filename", str(src.resolve()))
            continue
        out = meshdir / (hashlib.sha1(str(src).encode()).hexdigest()[:16] + ".stl")
        if not out.exists():
            try:
                m = trimesh.load(src, force="mesh")
                if not len(m.faces):
                    raise ValueError("empty mesh")
                m.export(out, file_type="stl")      # binary STL
            except Exception:
                unconvertible.add(src.suffix.lower())
                el.set("filename", str(src) + ".unloadable")
                continue
        el.set("filename", str(out.resolve()))
    for ext in sorted(unconvertible):
        report.add("URDF041", "warning", f"could not convert {ext} meshes for MuJoCo; those geoms are dropped")
    if ascii_stl:
        report.add("URDF042", "warning",
                   f"{len(ascii_stl)} ASCII STL meshes: MuJoCo reads binary STL only (converted for checking)")
    # Drop geoms whose mesh could not be made loadable, rather than failing
    # the whole model on a visual file.
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag in ("visual", "collision"):
                mesh = child.find("geometry/mesh")
                if mesh is not None and Path(mesh.get("filename", "")).suffix.lower() not in MUJOCO_MESHES:
                    parent.remove(child)

    if strip_materials:
        # Colours only; no physics. Removed when MuJoCo's parser rejects them.
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag == "material":
                    parent.remove(child)

    mj = root.find("mujoco")
    if mj is None:
        mj = ET.SubElement(root, "mujoco")
    comp = mj.find("compiler")
    if comp is None:
        comp = ET.SubElement(mj, "compiler")
    # strippath would reduce every mesh to its basename; discardvisual keeps
    # collision geometry, which is what contact and overlap checks need.
    comp.set("strippath", "false")
    comp.set("discardvisual", "true")
    # MuJoCo's default: links on fixed joints merge into their parent. Keeping
    # them apart manufactures contacts - a bracket fixed to a thigh touching
    # the hip above it - that no MuJoCo user of this URDF would see.
    comp.set("fusestatic", "true")
    comp.set("balanceinertia", "true" if balance_inertia else "false")
    out = workdir / (path.stem + ".mj.urdf")
    ET.ElementTree(root).write(out)
    return out
