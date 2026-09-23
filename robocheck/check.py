"""Check one robot description file end to end."""
from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

from . import physics, urdf
from .findings import Report


def detect_format(path: Path) -> str:
    for _, el in ET.iterparse(path, events=("start",)):
        return "urdf" if el.tag == "robot" else "mjcf"
    return "mjcf"


def _compile(spec: mujoco.MjSpec) -> tuple[mujoco.MjModel | None, str]:
    try:
        return spec.compile(), ""
    except Exception as exc:  # MuJoCo raises ValueError with the compiler message
        return None, str(exc).strip().splitlines()[0][:300]


def check_file(path: str | Path, search_roots: list[str | Path] | None = None,
               workdir: str | Path | None = None) -> Report:
    path = Path(path).resolve()
    roots = [Path(r) for r in (search_roots or [])]
    fmt = detect_format(path)
    report = Report(source=str(path), format=fmt)
    tmp = None
    if workdir is None:
        tmp = tempfile.TemporaryDirectory(prefix="robocheck_")
        workdir = tmp.name
    workdir = Path(workdir)

    try:
        model = None
        if fmt == "urdf":
            root = urdf.check_raw(path, report, roots)
            if root is None:
                return report
            strip = False
            for balance in (False, True):
                copy_path = urdf.mujoco_copy(path, root, roots, workdir, report,
                                             balance_inertia=balance, strip_materials=strip)
                try:
                    spec = mujoco.MjSpec.from_file(str(copy_path))
                except Exception as exc:
                    msg = str(exc).splitlines()[0][:300]
                    if "material" not in msg.lower() or strip:
                        report.add("LOAD001", "error", f"MuJoCo could not parse it: {msg}")
                        return report
                    # MuJoCo's URDF parser is stricter about <material> than
                    # ROS's. Say so, and check the physics without them.
                    report.add("LOAD005", "warning",
                               f"MuJoCo rejects it as written ({msg}); checked with <material> removed")
                    strip = True
                    copy_path = urdf.mujoco_copy(path, root, roots, workdir, report,
                                                 balance_inertia=balance, strip_materials=True)
                    spec = mujoco.MjSpec.from_file(str(copy_path))
                model, err = _compile(spec)
                if model is not None:
                    if balance:
                        report.add("LOAD003", "info",
                                   "compiled only after MuJoCo rebalanced impossible inertias; "
                                   "the physical checks below ran on the rebalanced model")
                    break
                report.add("LOAD002", "error", f"MuJoCo rejected it: {err}")
                if "inertia" not in err.lower():
                    return report
            if model is None:
                # rejected even with MuJoCo's own inertia repair
                return report
        else:
            try:
                spec = mujoco.MjSpec.from_file(str(path))
            except Exception as exc:
                report.add("LOAD001", "error", f"MuJoCo could not parse it: {str(exc).splitlines()[0][:300]}")
                return report
            model, err = _compile(spec)
            if model is None:
                report.add("LOAD002", "error", f"MuJoCo rejected it: {err}")
                return report
        report.loaded = True

        m = model
        floating = bool(np.any(m.jnt_type == mujoco.mjtJoint.mjJNT_FREE))
        report.stats.update(
            bodies=int(m.nbody - 1), joints=int(m.njnt), dofs=int(m.nv), actuators=int(m.nu),
            geoms=int(m.ngeom), mass_kg=round(float(mujoco.mj_getTotalmass(m)), 4),
            floating_base=floating,
        )

        # joint ranges as MuJoCo compiled them (MJCF has no raw pass)
        for j in range(m.njnt):
            if m.jnt_limited[j] and m.jnt_range[j][0] >= m.jnt_range[j][1]:
                name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint#{j}"
                report.add("JNT001", "error", f"joint range is empty {m.jnt_range[j].tolist()}", where=f"joint {name}")

        shapes = urdf.visual_shapes(path, root, roots) if fmt == "urdf" else None
        physics.check_mass_against_geometry(m, report, shapes)
        physics.check_rest_overlap(m, report)

        # A floating robot needs something to land on. Add a floor at its
        # lowest point unless the model brings one.
        has_floor = any(m.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE and m.geom_bodyid[g] == 0
                        for g in range(m.ngeom))
        sim_model = m
        if floating and not has_floor:
            d, _ = physics.rest_state(m)
            z = physics.lowest_point(m, d)
            # Every contact bit set: an added geom inherits the model's
            # default class, and a model whose default is contype=0 (Cassie,
            # Apollo) would otherwise fall straight through its own floor.
            spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05],
                                    pos=[0, 0, z - 1e-4], name="robocheck_floor",
                                    contype=0x7FFFFFFF, conaffinity=0x7FFFFFFF)
            sim_model, err = _compile(spec)
            if sim_model is None:
                report.add("LOAD004", "warning", f"could not add a floor for the settle test: {err}")
                sim_model = m
                # no floor, so falling proves nothing; still check it stays finite
                floating = False
        physics.check_settle(sim_model, report, floating=floating)
        return report
    finally:
        if tmp is not None:
            tmp.cleanup()
