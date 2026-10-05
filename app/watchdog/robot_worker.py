"""Robot-model worker, run as a separate process by :mod:`app.watchdog.robot`.

    python robot_worker.py check   RUN_DIR ROBOT_FILE
    python robot_worker.py compile RUN_DIR (arm|quadruped|SPEC.json)

It runs under whichever interpreter can load MuJoCo (on this machine the
system Python, not Anaconda), so it imports nothing from ``app`` — only the
standalone ``robocheck`` and ``embodiment`` packages. It writes
``RUN_DIR/report.json`` and, when the robot's visual geometry can be posed,
``RUN_DIR/model.glb`` with one node per link at the zero joint configuration.
"""
from __future__ import annotations

import json
import math
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def _rpy(r: float, p: float, y: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _origin(el) -> np.ndarray:
    T = np.eye(4)
    o = el.find("origin") if el is not None else None
    if o is not None:
        xyz = [float(v) for v in (o.get("xyz") or "0 0 0").split()]
        rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()]
        T[:3, :3] = _rpy(*rpy)
        T[:3, 3] = xyz
    return T


def _resolve(filename: str, roots: list[Path]) -> Path | None:
    rel = filename
    if rel.startswith("package://"):
        rel = rel[len("package://"):]
        candidates = [rel, rel.split("/", 1)[1] if "/" in rel else rel]
    elif rel.startswith("file://"):
        candidates = [rel[len("file://"):]]
    else:
        candidates = [rel]
    for root in roots:
        for c in candidates:
            p = (root / c)
            if p.is_file():
                return p
            hit = next(root.rglob(Path(c).name), None) if root.is_dir() else None
            if hit is not None:
                return hit
    return None


def urdf_glb(urdf_path: Path, out: Path, roots: list[Path]) -> dict:
    """Pose every link's visual geometry at zero joint angles; one GLB node per link."""
    import trimesh

    root = ET.parse(urdf_path).getroot()
    links = {lk.get("name"): lk for lk in root.findall("link")}
    children: dict[str, list] = {}
    child_names = set()
    for j in root.findall("joint"):
        parent, child = j.find("parent").get("link"), j.find("child").get("link")
        children.setdefault(parent, []).append((child, _origin(j)))
        child_names.add(child)
    world: dict[str, np.ndarray] = {}
    stack = [(n, np.eye(4)) for n in links if n not in child_names]
    while stack:
        name, T = stack.pop()
        world[name] = T
        for child, J in children.get(name, []):
            stack.append((child, T @ J))

    scene = trimesh.Scene()
    missing = []
    for name, lk in links.items():
        parts = []
        for vis in lk.findall("visual"):
            g = vis.find("geometry")
            if g is None:
                continue
            m = None
            if g.find("mesh") is not None:
                me = g.find("mesh")
                p = _resolve(me.get("filename", ""), roots)
                if p is None:
                    missing.append(me.get("filename", ""))
                    continue
                loaded = trimesh.load(p, force="mesh")
                m = loaded if isinstance(loaded, trimesh.Trimesh) else None
                if m is not None and me.get("scale"):
                    m.apply_scale([float(s) for s in me.get("scale").split()])
            elif g.find("box") is not None:
                m = trimesh.creation.box([float(s) for s in g.find("box").get("size").split()])
            elif g.find("cylinder") is not None:
                c = g.find("cylinder")
                m = trimesh.creation.cylinder(float(c.get("radius")), float(c.get("length")))
            elif g.find("sphere") is not None:
                m = trimesh.creation.icosphere(radius=float(g.find("sphere").get("radius")))
            if m is None or not len(m.faces):
                continue
            m = m.copy()
            m.apply_transform(world.get(name, np.eye(4)) @ _origin(vis))
            parts.append(m)
        if parts:
            mesh = trimesh.util.concatenate(parts)
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    if not scene.geometry:
        return {"glb": False, "missing_meshes": missing}
    out.write_bytes(scene.export(file_type="glb"))
    return {"glb": True, "links_drawn": len(scene.geometry), "missing_meshes": missing}


def do_check(run: Path, robot: Path) -> dict:
    from robocheck import check_file

    roots = [robot.parent, run / "meshes"]
    rep = check_file(robot, search_roots=roots, workdir=run / "work").to_dict()
    rep["source"] = robot.name
    out = {"mode": "check", "robocheck": {rep["format"]: rep}, "accepted": rep["ok"]}
    if rep["format"] == "urdf":
        try:
            out["view"] = urdf_glb(robot, run / "model.glb", roots)
        except Exception as e:  # noqa: BLE001 - no picture is not a failed check
            out["view"] = {"glb": False, "error": f"{type(e).__name__}: {e}"}
    else:
        out["view"] = {"glb": False, "error": "3D view is drawn from URDF; MJCF is checked but not drawn"}
    return out


def do_compile(run: Path, what: str) -> dict:
    from embodiment.compiler import compile_robot
    from embodiment.legged import QuadrupedSpec
    from embodiment.spec import ArmSpec

    if what.endswith(".json"):
        data = json.loads(Path(what).read_text(encoding="utf-8"))
        spec = QuadrupedSpec.model_validate(data) if data.get("kind") == "quadruped" else ArmSpec.model_validate(data)
    else:
        spec = QuadrupedSpec() if what == "quadruped" else ArmSpec()
    robot_dir = run / "robot"
    rep = compile_robot(spec, robot_dir)
    rep["mode"] = "compile"
    urdf = robot_dir / f"{spec.name}.urdf"
    try:
        rep["view"] = urdf_glb(urdf, run / "model.glb", [robot_dir])
    except Exception as e:  # noqa: BLE001
        rep["view"] = {"glb": False, "error": f"{type(e).__name__}: {e}"}
    return rep


def main() -> int:
    mode, run = sys.argv[1], Path(sys.argv[2])
    try:
        rep = do_check(run, Path(sys.argv[3])) if mode == "check" else do_compile(run, sys.argv[3])
        rep["status"] = "done"
    except Exception as e:  # noqa: BLE001 - the run records its own failure
        rep = {"mode": mode, "status": "error", "error": f"{type(e).__name__}: {e}",
               "trace": traceback.format_exc(limit=4)}
    (run / "report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return 0 if rep["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
