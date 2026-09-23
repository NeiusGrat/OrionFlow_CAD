"""The embodiment compiler: spec -> solids -> physics -> URDF + MJCF -> gate.

    spec  --expand-->  links of FeatureGraph components + joints
          --compile->  exact OpenCASCADE solids   (app.compilers.build123d_compiler)
          --measure->  exact mass, CoM, inertia   (BRepGProp, per-component density)
          --mesh---->  visual mesh + one convex collision hull per component
          --export-->  URDF, MJCF, STEP per link, FeatureGraph JSON per component
          --gate---->  geometry, inertia, interference, actuator torque, robocheck

A robot is accepted only when every gate passes, and robocheck must find no
error and no warning in either file. A rejected robot is still written, with
the report saying which gate refused it, so a failure can be read rather
than guessed at.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path

import numpy as np
import trimesh
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

from robocheck import check_file
from robocheck.urdf import inertia_problem

from . import export
from .catalog import G, actuator, actuator_limits, material
from .geometry import compound, mesh_m, place, solid
from .massprops import combine, solid_props
from .spec import ArmSpec, expand

#: Two links may not share more than this volume at rest (mm^3): above
#: floating-point noise on a boolean, far below any real interference.
INTERFERENCE_MM3 = 1e-3

#: Holding stiffness of the position servos: the stiffness at which the
#: catalogue stall torque is reached 5 degrees off target.
STALL_AT_RAD = math.radians(5.0)

#: Joint-range sampling for the worst static gravity torque.
TORQUE_GRID = 25


def _density(source: tuple[str, str], shape) -> float:
    kind, key = source
    if kind == "material":
        return material(key)["density_g_cm3"] * 1000.0
    # An actuator's body is given its catalogue mass over its modelled volume.
    return (actuator(key)["mass_g"] / 1000.0) / (shape.volume * 1e-9)


def _common_volume(a, b) -> float:
    op = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
    op.Build()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return abs(props.Mass())


def _world(robot, q: dict[str, float]) -> dict[str, np.ndarray]:
    """Each link's frame in the world (mm) at joint angles q."""
    W = {robot.links[0].name: np.eye(4)}
    for j in robot.joints:
        c, s = math.cos(q.get(j.name, 0.0)), math.sin(q.get(j.name, 0.0))
        Rz = np.eye(4)
        Rz[:2, :2] = [[c, -s], [s, c]]
        W[j.child] = W[j.parent] @ j.origin @ Rz
    return W


def _gravity_torques(robot, props: dict, q: dict[str, float]) -> dict[str, float]:
    """Static torque each joint must hold against gravity at pose q (N m)."""
    W = _world(robot, q)
    names = [l.name for l in robot.links]
    out = {}
    for j in robot.joints:
        axis = W[j.child][:3, :3] @ np.array(j.axis)
        p = W[j.child][:3, 3] * 1e-3
        tau = 0.0
        for lname in names[names.index(j.child):]:           # a serial chain: everything distal
            com = (W[lname][:3, :3] @ props[lname].com_m) + W[lname][:3, 3] * 1e-3
            F = np.array([0.0, 0.0, -props[lname].mass_kg * G])
            tau += float(np.dot(axis, np.cross(com - p, F)))
        out[j.name] = tau
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_robot(spec: ArmSpec, out_dir: str | Path, robot=None) -> dict:
    """Build, measure, export and gate one robot.

    `robot` overrides the spec's expansion - how the tests hand the gates a
    robot the spec language cannot express, such as one whose links clash.
    """
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "meshes").mkdir(parents=True)
    (out / "cad").mkdir()
    robot = robot or expand(spec)
    gates: dict[str, dict] = {}

    # 1. exact solids ------------------------------------------------------
    placed: dict[str, list] = {}
    for link in robot.links:
        placed[link.name] = []
        for c in link.components:
            s = place(solid(c.graph), c.placement)
            placed[link.name].append((c, s))
            (out / "cad" / f"{c.name}.featuregraph.json").write_text(
                json.dumps({"link": link.name, "density_from": list(c.density_from),
                            "placement_mm": c.placement.round(9).tolist(),
                            "graph": c.graph.model_dump()}, indent=1, sort_keys=True))
    gates["geometry"] = {"passed": True, "components": sum(len(v) for v in placed.values())}

    # 2. exact mass properties ------------------------------------------------
    props, links_c = {}, []
    inertia_fail = []
    for link in robot.links:
        parts = [solid_props(s, _density(c.density_from, s)) for c, s in placed[link.name]]
        mp = combine(parts)
        props[link.name] = mp
        I = mp.inertia_kg_m2
        why = inertia_problem(I[0, 0], I[1, 1], I[2, 2], I[0, 1], I[0, 2], I[1, 2])
        if mp.mass_kg <= 0 or why:
            inertia_fail.append(f"{link.name}: {why or 'non-positive mass'}")
        cl = export.CompiledLink(link.name, mp, [s for _, s in placed[link.name]])
        cl.visual = f"{link.name}_visual.stl"
        trimesh.util.concatenate([mesh_m(s) for _, s in placed[link.name]]).export(out / "meshes" / cl.visual)
        for c, s in placed[link.name]:
            hull = mesh_m(s).convex_hull
            name = f"{link.name}_{c.name}_collision.stl"
            hull.export(out / "meshes" / name)
            cl.collision.append(name)
        export.step(out / "cad" / f"{link.name}.step", compound(cl.solids))
        links_c.append(cl)
    gates["inertia"] = {"passed": not inertia_fail, "problems": inertia_fail}

    # 3. interference at rest, on the exact solids -----------------------------
    W0 = _world(robot, {})
    world_solids = {l.name: [place(s, W0[l.name]) for _, s in placed[l.name]] for l in robot.links}
    clashes = []
    for a, b in itertools.combinations(world_solids, 2):
        v = sum(_common_volume(x, y) for x in world_solids[a] for y in world_solids[b])
        if v > INTERFERENCE_MM3:
            clashes.append({"links": [a, b], "common_mm3": round(v, 4)})
    gates["interference"] = {"passed": not clashes, "clashes": clashes}

    # 4. actuators against gravity, over the whole joint range -------------------
    joints_c, torque = [], {}
    grids = [np.linspace(j.lower, j.upper, TORQUE_GRID) for j in robot.joints]
    worst = {j.name: 0.0 for j in robot.joints}
    for qs in itertools.product(*grids):
        tau = _gravity_torques(robot, props, dict(zip([j.name for j in robot.joints], qs)))
        for k, v in tau.items():
            worst[k] = max(worst[k], abs(v))
    for j in robot.joints:
        lim = actuator_limits(j.actuator)
        need = worst[j.name] * spec.torque_safety_factor
        torque[j.name] = {"worst_static_gravity_nm": round(worst[j.name], 6),
                          "stall_torque_nm": round(lim["effort_nm"], 6),
                          "margin": round(lim["effort_nm"] / worst[j.name], 3) if worst[j.name] else None,
                          "required_factor": spec.torque_safety_factor,
                          "passed": lim["effort_nm"] >= need, "source": lim["source"]}
        joints_c.append(export.CompiledJoint(
            j.name, j.parent, j.child, j.origin, j.axis, j.lower, j.upper,
            lim["effort_nm"], lim["velocity_rad_s"], j.damping, kp=lim["effort_nm"] / STALL_AT_RAD))
    gates["actuators"] = {"passed": all(t["passed"] for t in torque.values()), "joints": torque}

    # 5. write both robot files, then robocheck both -----------------------------
    (out / f"{spec.name}.urdf").write_text(export.urdf(spec.name, links_c, joints_c))
    (out / f"{spec.name}.xml").write_text(export.mjcf(spec.name, links_c, joints_c))
    checks = {}
    for fmt, fname in (("urdf", f"{spec.name}.urdf"), ("mjcf", f"{spec.name}.xml")):
        r = check_file(out / fname).to_dict()
        r["source"] = fname                                   # relative: the report travels with the files
        checks[fmt] = r
    clean = all(c["loaded"] and c["errors"] == 0 and c["warnings"] == 0 for c in checks.values())
    gates["robocheck"] = {"passed": clean,
                          "summary": {k: {"loaded": v["loaded"], "errors": v["errors"], "warnings": v["warnings"]}
                                      for k, v in checks.items()}}

    accepted = all(g["passed"] for g in gates.values())
    (out / "spec.json").write_text(spec.model_dump_json(indent=1))
    report = {
        "robot": spec.name,
        "accepted": accepted,
        "gates": gates,
        "links": {n: {"mass_kg": round(p.mass_kg, 9), "com_m": p.com_m.round(9).tolist(),
                      "inertia_kg_m2": p.inertia_kg_m2.round(12).tolist()} for n, p in props.items()},
        "total_mass_kg": round(sum(p.mass_kg for p in props.values()), 9),
        "robocheck": checks,
    }
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "report.json")
    report["files"] = {str(p.relative_to(out)).replace("\\", "/"): _sha(p) for p in files}
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    return report
