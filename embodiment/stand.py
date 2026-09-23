"""Does it stand? The floating robot on a floor, holding its stance.

robocheck proves a model does not blow up. This asks the question a legged
robot exists to answer: put it on the ground in its standing pose, let its
own servos hold that pose, and see whether it is still standing - trunk up,
level, in place, every foot down - after a few seconds.
"""
from __future__ import annotations

import math
from pathlib import Path

import mujoco
import numpy as np

SECONDS = 3.0
MIN_HEIGHT_FRACTION = 0.90     # trunk keeps at least 90% of its standing height
MAX_TILT_DEG = 5.0
MAX_DRIFT_M = 0.02


def stand_test(mjcf_path: Path, foot_links: list[str], pose: str) -> dict:
    spec = mujoco.MjSpec.from_file(str(mjcf_path))
    # Every contact bit: an added geom takes the model's default class.
    spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05], name="stand_floor",
                            contype=0x7FFFFFFF, conaffinity=0x7FFFFFFF)
    m = spec.compile()
    d = mujoco.MjData(m)
    mujoco.mj_resetDataKeyframe(m, d, m.key(pose).id)
    d.ctrl[:] = m.key_ctrl[m.key(pose).id]
    mujoco.mj_forward(m, d)
    root = m.body(0 + 1).id                 # the floating body carries the free joint
    z0 = float(d.xpos[root][2])
    xy0 = d.xpos[root][:2].copy()
    floor = m.geom("stand_floor").id
    min_z, finite = z0, True

    for _ in range(int(SECONDS / m.opt.timestep)):
        mujoco.mj_step(m, d)
        if not (np.all(np.isfinite(d.qpos)) and np.all(np.isfinite(d.qvel))):
            finite = False
            break
        min_z = min(min_z, float(d.xpos[root][2]))

    z = float(d.xpos[root][2])
    up = d.xmat[root].reshape(3, 3)[:, 2]
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(up[2])))))
    drift = float(np.linalg.norm(d.xpos[root][:2] - xy0))
    touching = set()
    for i in range(d.ncon):
        c = d.contact[i]
        if floor in (c.geom1, c.geom2):
            other = c.geom2 if c.geom1 == floor else c.geom1
            touching.add(m.body(m.geom_bodyid[other]).name)
    feet_down = sorted(set(foot_links) & touching)
    bad_acc = int(d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number)
    result = {
        "seconds": SECONDS,
        "start_height_m": round(z0, 6),
        "end_height_m": round(z, 6),
        "min_height_m": round(min_z, 6),
        "tilt_deg": round(tilt, 3),
        "drift_m": round(drift, 6),
        "feet_down": feet_down,
        "other_bodies_on_floor": sorted(touching - set(foot_links)),
        "finite": finite,
        "bad_accelerations": bad_acc,
    }
    result["passed"] = bool(
        finite and not bad_acc
        and z >= MIN_HEIGHT_FRACTION * z0
        and tilt <= MAX_TILT_DEG
        and drift <= MAX_DRIFT_M
        and len(feet_down) == len(foot_links)
        and not result["other_bodies_on_floor"])
    return result
