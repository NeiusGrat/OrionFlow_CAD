"""Export the articulated MicroDuck for the web studio.

Two files, written together so they cannot disagree:

- ``microduck.glb`` - one node per MJCF body, nested exactly as the kinematic
  tree is, with one child node per placed part instance. Geometry is each
  part's chosen CAD solid as tessellated by ``fc_tessellate`` - never the
  repaired STL - so the viewer shows the same part the STEP and FCStd carry.
- ``microduck.json`` - what the viewer needs to move it and describe it: each
  body's rest transform and joint (axis, range), the named poses, the body
  masses from the MJCF inertials, and per-part CAD facts (source tier, faces,
  volume, whether it is a closed solid).

A body's frame is ``parent @ T_parent @ R(axis, q)``, the same composition
``export_placements.world_transforms`` uses for the verified CAD poses. The
viewer applies it per frame; `verify_viewer` below checks the GLB against the
placements the STEP was built from.
"""
from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
import trimesh

from export_placements import POSES, VARIANTS, axis_rotation, world_transforms
from mjcf_model import Model, transform

ROOT = Path(__file__).resolve().parent.parent
TESS = ROOT / "work" / "viewer"
OUT = ROOT / "out" / "viewer"
UI = ROOT.parent / "orionflow-ui" / "public" / "demo" / "microduck"

ONSHAPE = ("https://cad.onshape.com/documents/804927696f06d877f3f1803e/w/"
           "5b75db19292e71970de02dee/e/ef6e972847fec8d82570b35e")

#: Faceted parts are one planar face per source triangle, so their normals are
#: flat and a coarse cylinder shows every facet. Normals are averaged across
#: an edge only when the two faces meet at less than this angle: a 24-gon's
#: 15-degree steps smooth into a cylinder, a bracket's 90-degree edge stays.
CREASE_DEG = 30.0

#: What each tier means, in the words the info panel shows.
TIERS = {
    "modelled": "Hand-modelled from measurements. True CAD faces.",
    "revolved": "Rebuilt as a revolved profile. True circular edges, within 2% of the source volume.",
    "slab": "Rebuilt as extruded profiles with true circles, within 2% of the source volume.",
    "faceted": "Source mesh sewn into a closed solid. Faces are flat triangles; curves are approximated.",
}

#: Display names. Inferred from the Onshape part names in the source files;
#: the file name is shown beside it so nothing here is taken on trust.
LABELS = {
    "xl330": "Dynamixel XL330 servo",
    "np_f970": "NP-F970 battery pack",
    "pcb__raspberry_pi_zero_2_w": "Raspberry Pi Zero 2 W",
    "elec_rpi_robot_hat_pcb": "Robot HAT board",
    "seeed_bearing__configuration__22x16x4": "Bearing 22 x 16 x 4",
    "seeed_bearing__configuration_default": "Bearing (small)",
    "speaker": "Speaker",
    "lens": "Camera lens",
    "m12_lens_holder": "M12 lens holder",
    "noenoeil": "Eye",
    "top_head_shell": "Head shell, top",
    "bottom_head_shell": "Head shell, bottom",
    "left_shell": "Body shell, left",
    "right_shell": "Body shell, right",
    "face_part": "Face plate",
    "jaw": "Jaw",
    "jaw_soft": "Jaw, soft",
    "soft_mouth_top": "Mouth top, soft",
    "trunk_base": "Trunk base",
    "motor_support": "Motor support",
    "power_support": "Battery support",
    "banana_pcb_locker": "PCB locker",
    "yaw2roll": "Hip yaw-to-roll bracket",
    "hip_l": "Hip bracket",
    "upper_leg_left": "Upper leg, left",
    "upper_leg_right": "Upper leg, right",
    "upper_leg_rigidity_plate": "Upper-leg stiffening plate",
    "leg": "Lower leg",
    "ankle_left": "Ankle, left",
    "ankle_right": "Ankle, right",
    "foot_left": "Foot, left",
    "foot_right": "Foot, right",
    "sole_left": "Sole, left",
    "sole_right": "Sole, right",
    "neck": "Neck link",
    "neck_pitch": "Neck pitch bracket",
    "yaw_roll_motion": "Head yaw-roll bracket",
    "bearing_roll": "Hip roll bearing housing",
}

JOINT_LABELS = {
    "left_hip_yaw": "Left hip yaw", "left_hip_roll": "Left hip roll",
    "left_hip_pitch": "Left hip pitch", "left_knee": "Left knee", "left_ankle": "Left ankle",
    "right_hip_yaw": "Right hip yaw", "right_hip_roll": "Right hip roll",
    "right_hip_pitch": "Right hip pitch", "right_knee": "Right knee", "right_ankle": "Right ankle",
    "neck_pitch": "Neck pitch", "head_pitch": "Head pitch", "head_yaw": "Head yaw", "head_roll": "Head roll",
    "passive_LF_wheel": "Left front wheel", "passive_LR_wheel": "Left rear wheel",
    "passive_RF_wheel": "Right front wheel", "passive_RR_wheel": "Right rear wheel",
}


def creased(pos: np.ndarray, idx: np.ndarray, crease_deg: float = CREASE_DEG):
    """Split vertices so normals average only across shallow edges."""
    tri = pos[idx]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])   # area-weighted
    unit = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    key = np.round(pos / 1e-4).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    corners_v = weld[idx].reshape(-1)                  # welded vertex per corner
    corners_t = np.repeat(np.arange(len(idx)), 3)
    order = np.argsort(corners_v, kind="stable")
    cos_lim = math.cos(math.radians(crease_deg))

    out_pos, out_nrm = [], []
    corner_new = np.empty(len(corners_v), dtype=np.int64)
    bounds = np.flatnonzero(np.diff(corners_v[order])) + 1
    for group in np.split(order, bounds):
        tris = corners_t[group]
        u = unit[tris]
        sim = (u @ u.T) >= cos_lim
        cache: dict[bytes, int] = {}
        for gi, c in enumerate(group):
            n = fn[tris[sim[gi]]].sum(axis=0)
            n /= max(np.linalg.norm(n), 1e-12)
            k = np.round(n, 4).tobytes()
            if k not in cache:
                cache[k] = len(out_pos)
                out_pos.append(pos[idx.reshape(-1)[c]])
                out_nrm.append(n)
            corner_new[c] = cache[k]
    return (np.asarray(out_pos, np.float32), np.asarray(out_nrm, np.float32),
            corner_new.reshape(-1, 3).astype(np.uint32))


def part_mesh(name: str, source: str) -> trimesh.Trimesh:
    d = np.load(TESS / f"{name}.npz")
    pos, nrm, idx = d["positions"], d["normals"], d["indices"]
    if source == "faceted":
        pos, nrm, idx = creased(pos.astype(np.float64), idx.astype(np.int64))
    mesh = trimesh.Trimesh(vertices=pos, faces=idx, vertex_normals=nrm, process=False)
    mesh.metadata["name"] = name
    return mesh


def colours(variant: str) -> dict[tuple[str, str], list[float]]:
    """(body, part) -> RGBA from the MJCF materials."""
    name = f"kinematics_{variant}.json" if variant else "kinematics.json"
    k = json.loads((ROOT / "source" / name).read_text())
    out = {}
    for b in k["bodies"]:
        for g in b["geoms"]:
            if g.get("mesh") and g.get("color"):
                out.setdefault((b["name"], g["mesh"][:-4]), g["color"])
                out.setdefault(("*", g["mesh"][:-4]), g["color"])
    return out


def build(variant: str = ""):
    model = Model(VARIANTS[variant])
    meta = json.loads((TESS / "parts_meta.json").read_text())
    rgba = colours(variant)
    used = Counter(i.mesh for n in model.order for i in model.bodies[n].instances)

    sc = trimesh.Scene(base_frame="microduck")
    meshes = {p: part_mesh(p, meta[p]["source"]) for p in used}
    for p, m in meshes.items():
        sc.geometry[p] = m

    bodies, instances = [], []
    for name in model.order:
        b = model.bodies[name]
        T_rest = np.eye(4) if b.parent is None else b.T_parent
        # three.js strips ":" "/" "." from node names on load, so names here
        # use only characters that survive: b_<body>, p_<instance index>.
        node = f"b_{name}"
        parent = "microduck" if b.parent is None else f"b_{b.parent}"
        sc.graph.update(frame_to=node, frame_from=parent, matrix=T_rest)
        bodies.append({
            "name": name,
            "node": node,
            "parent": b.parent,
            "rest": [float(x) for x in T_rest.reshape(-1)],        # row-major 4x4, mm
            "mass_g": round(b.mass * 1000, 2),
            "joint": None if b.joint is None else {
                "name": b.joint.name,
                "label": JOINT_LABELS.get(b.joint.name, b.joint.name),
                "axis": [float(x) for x in b.joint.axis],
                "range": [float(x) for x in b.joint.range] if b.joint.range is not None else None,
            },
        })
        for i, inst in enumerate(b.instances):
            iid = f"{name}/{inst.mesh}/{i}"
            pnode = f"p_{len(instances)}"
            sc.graph.update(frame_to=pnode, frame_from=node, matrix=inst.T,
                            geometry=inst.mesh)
            instances.append({
                "id": iid,
                "node": pnode,
                "part": inst.mesh,
                "body": name,
                "color": rgba.get((name, inst.mesh)) or rgba.get(("*", inst.mesh)) or [0.8, 0.8, 0.8, 1],
            })

    parts = {}
    for p, count in sorted(used.items()):
        m = meta[p]
        parts[p] = {
            "label": LABELS.get(p, p.replace("_", " ")),
            "file": p,
            "source": m["source"],
            "source_note": TIERS[m["source"]],
            "faces": m["faces"],
            "curved_faces": m["cylindrical_faces"],
            "triangles": int(len(meshes[p].faces)),
            "volume_mm3": m["volume_mm3"],
            "area_mm2": m["area_mm2"],
            "bbox_mm": m["bbox_mm"],
            "closed_solid": m["solids"] > 0 and m["valid"],
            "valid": m["valid"],
            "instances": count,
        }

    manifest = {
        "name": "MicroDuck" + (" on rollers" if variant == "rollers" else ""),
        "variant": variant or "legs",
        "units": "mm",
        "up": "Z",
        "source": {
            "robot": "Pollen Robotics MicroDuck (open source)",
            "onshape": ONSHAPE,
            "simulator": "huggingface.co/spaces/pollen-robotics/microduck-simulator",
            "note": ("Reference model rebuilt ahead of time from the open simulator's meshes; "
                     "not generated from a prompt."),
        },
        "joints": [b["joint"]["name"] for b in bodies if b["joint"]],
        "bodies": bodies,
        "instances": instances,
        "parts": parts,
        "poses": {k: dict(v) for k, v in POSES.items()},
        # World transform of every body at every named pose, from the same
        # function the CAD poses were built with. The web viewer's tests
        # recompute these from `rest` + joints and must land on them.
        "check": {k: {n: [round(float(x), 6) for x in T.reshape(-1)]
                      for n, T in world_transforms(model, v).items()}
                  for k, v in POSES.items()},
        "totals": {
            "parts": len(parts),
            "instances": len(instances),
            "mass_g": round(model.total_mass() * 1000, 1),
            "by_source": dict(Counter(parts[p]["source"] for p in parts)),
            "instances_by_source": dict(Counter(parts[i["part"]]["source"] for i in instances)),
            "triangles": int(sum(parts[i["part"]]["triangles"] for i in instances)),
        },
    }
    return sc, manifest, model


def verify_viewer(sc: trimesh.Scene, manifest: dict, model: Model) -> list[str]:
    """Pose the GLB's graph the way the viewer will and compare with the CAD placements."""
    problems = []
    by_name = {b["name"]: b for b in manifest["bodies"]}
    for pose_name, pose in POSES.items():
        W = world_transforms(model, pose)
        world = {}
        for name in model.order:
            b = by_name[name]
            T = np.array(b["rest"]).reshape(4, 4)
            if b["joint"]:
                T = T @ transform(np.zeros(3), axis_rotation(np.array(b["joint"]["axis"]),
                                                             pose.get(b["joint"]["name"], 0.0)))
            world[name] = T if b["parent"] is None else world[b["parent"]] @ T
            err = float(np.abs(world[name] - W[name]).max())
            if err > 1e-6:
                problems.append(f"{pose_name}: body {name} off by {err:.2e}")
    # the rest pose of the exported graph itself
    W0 = world_transforms(model, {})
    for inst in manifest["instances"]:
        T_glb, _ = sc.graph.get(inst["node"])
        body = model.bodies[inst["body"]]
        k = int(inst["id"].rsplit("/", 1)[1])
        want = W0[inst["body"]] @ body.instances[k].T
        if np.abs(T_glb - want).max() > 1e-6:
            problems.append(f"instance {inst['id']} misplaced in GLB")
    # A pose can match the CAD exactly and still be one no robot could stand
    # in: soles must stay parallel to the trunk, as they are at rest.
    feet = [n for n in model.order if n.startswith("ankle_")]
    for pose_name, pose in POSES.items():
        W = world_transforms(model, pose)
        for f in feet:
            R = W0[f][:3, :3].T @ W[f][:3, :3]
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
            if tilt > 0.5:
                problems.append(f"{pose_name}: {f} sole tilted {tilt:.1f} deg")
    for p, info in manifest["parts"].items():
        if not info["valid"]:
            problems.append(f"part {p} is not a valid shape")
    return problems


#: (file stem, MJCF variant). The rollers build swaps the feet for skates.
EXPORTS = (("microduck", ""), ("microduck_rollers", "rollers"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    UI.mkdir(parents=True, exist_ok=True)
    failed = False
    for stem, variant in EXPORTS:
        sc, manifest, model = build(variant)
        problems = verify_viewer(sc, manifest, model)
        t = manifest["totals"]
        print(f"{stem}: parts {t['parts']}  instances {t['instances']}  tris {t['triangles']}  "
              f"mass {t['mass_g']} g  by source {t['instances_by_source']}")
        if problems:
            failed = True
            for p in problems:
                print("  PROBLEM", p)
            continue
        glb = OUT / f"{stem}.glb"
        glb.write_bytes(trimesh.exchange.gltf.export_glb(sc, include_normals=True))
        (OUT / f"{stem}.json").write_text(json.dumps(manifest, indent=1))
        print(f"  verified at every pose; glb {glb.stat().st_size / 1e6:.2f} MB")
        shutil.copy2(glb, UI / glb.name)
        shutil.copy2(OUT / f"{stem}.json", UI / f"{stem}.json")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
