"""Sim fidelity: a robot's simulation model (MJCF or URDF) against the CAD it claims to be.

Read from the sim file: bodies (tree, pose at the zero configuration, inertial),
joints (type, axis, range) and which mesh each body draws.

Mapping sim body -> CAD instances, in order:
  human      the engineer's pairing
  manifest   a provenance file shipped with the sim model (``meshes: {name: {file, body, leaf_features}}``,
             as yubi_mujoco's ``cad_manifest.json``): body -> its meshes -> the CAD part labels they were made from
  name       body name equals a CAD part name

Frames. A registration file (``cad_origin_mm``, ``cad_to_canonical_rotation``,
``cad_to_canonical_scale``, as ``cad_assembly.json``) says how CAD coordinates
map to the sim's root frame. With it, the root body's centre of mass and
inertia are compared directly. A hinged body is posed differently in the CAD
(as modelled) and in the sim (its zero), so for it the centre of mass is
compared in cylindrical coordinates about the joint axis — radius and height
along the axis do not change with the joint angle — and the angle between the
two poses is estimated and reported, not hidden. Principal moments of inertia
do not depend on pose at all. Without a registration file only mass and
principal moments are compared, and the frame-dependent checks say why they
did not run.
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


# ------------------------------------------------------------------ rotations --

def quat_to_mat(q) -> np.ndarray:
    w, x, y, z = [float(v) for v in q]
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def euler_to_mat(e, seq="xyz") -> np.ndarray:
    R = np.eye(3)
    for ax, a in zip(seq.lower(), e):
        c, s = math.cos(a), math.sin(a)
        M = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
             "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[ax]
        R = R @ np.array(M)          # intrinsic (MuJoCo lower-case eulerseq)
    return R


def axis_angle(axis, a) -> np.ndarray:
    k = np.asarray(axis, float)
    k = k / (np.linalg.norm(k) or 1.0)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K


def _f(s, n=None, default=0.0):
    if s is None:
        return [default] * (n or 0)
    v = [float(x) for x in str(s).split()]
    return v


# ------------------------------------------------------------------ MJCF / URDF --

def parse_mjcf(text: str) -> dict:
    root = ET.fromstring(text)
    comp = root.find("compiler")
    degrees = not (comp is not None and comp.get("angle", "degree") == "radian")
    seq = (comp.get("eulerseq") if comp is not None else None) or "xyz"
    ang = (lambda a: math.radians(a)) if degrees else (lambda a: a)
    meshes = {}
    for m in root.iter("mesh"):
        if m.get("file"):
            meshes[m.get("name") or Path(m.get("file")).stem] = Path(m.get("file")).name
    bodies, joints = [], []

    def rot_of(el) -> np.ndarray:
        if el.get("quat"):
            return quat_to_mat(_f(el.get("quat")))
        if el.get("euler"):
            return euler_to_mat([ang(a) for a in _f(el.get("euler"))], seq)
        if el.get("axisangle"):
            v = _f(el.get("axisangle"))
            return axis_angle(v[:3], ang(v[3]))
        return np.eye(3)

    def walk(el, parent, T_parent):
        for b in el.findall("body"):
            T = np.eye(4)
            T[:3, :3] = rot_of(b)
            T[:3, 3] = _f(b.get("pos")) if b.get("pos") else [0, 0, 0]
            Tw = T_parent @ T
            inertial = None
            ie = b.find("inertial")
            if ie is not None:
                pos = np.array(_f(ie.get("pos")) if ie.get("pos") else [0, 0, 0], float)
                if ie.get("fullinertia"):
                    xx, yy, zz, xy, xz, yz = _f(ie.get("fullinertia"))
                    I = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
                else:
                    d = _f(ie.get("diaginertia")) if ie.get("diaginertia") else [0, 0, 0]
                    R = rot_of(ie)
                    I = R @ np.diag(d) @ R.T
                inertial = {"mass": float(ie.get("mass", 0)), "com": pos.tolist(), "inertia": I.tolist()}
            name = b.get("name") or f"body{len(bodies)}"
            geoms = [g.get("mesh") for g in b.findall("geom") if g.get("mesh")]
            free = b.find("freejoint") is not None or any(j.get("type") == "free" for j in b.findall("joint"))
            bodies.append({"name": name, "parent": parent, "T_world": Tw.tolist(), "T_parent": T.tolist(),
                           "inertial": inertial, "meshes": [meshes.get(g, g) for g in geoms], "free": free,
                           "mocap": b.get("mocap") == "true"})
            for j in b.findall("joint"):
                jt = j.get("type", "hinge")
                if jt == "free":
                    continue
                rng = _f(j.get("range")) if j.get("range") else None
                if rng and jt == "hinge" and degrees:
                    rng = [math.radians(r) for r in rng]
                joints.append({"name": j.get("name") or f"{name}_joint", "type": jt, "body": name, "parent": parent,
                               "axis": _f(j.get("axis")) if j.get("axis") else [0, 0, 1],
                               "pos": _f(j.get("pos")) if j.get("pos") else [0, 0, 0], "range": rng})
            walk(b, name, Tw)

    wb = root.find("worldbody")
    if wb is not None:
        walk(wb, None, np.eye(4))
    return {"format": "mjcf", "model": root.get("model", ""), "bodies": bodies, "joints": joints}


def parse_urdf(text: str) -> dict:
    root = ET.fromstring(text)

    def origin(el):
        T = np.eye(4)
        o = el.find("origin") if el is not None else None
        if o is not None:
            T[:3, 3] = _f(o.get("xyz")) if o.get("xyz") else [0, 0, 0]
            r, p, y = _f(o.get("rpy")) if o.get("rpy") else [0, 0, 0]
            T[:3, :3] = euler_to_mat([y, p, r], "zyx")
        return T

    links = {}
    for l in root.findall("link"):
        ie = l.find("inertial")
        inertial = None
        if ie is not None:
            To = origin(ie)
            m = ie.find("mass")
            i = ie.find("inertia")
            I = np.zeros((3, 3))
            if i is not None:
                g = lambda k: float(i.get(k, 0))
                I = np.array([[g("ixx"), g("ixy"), g("ixz")], [g("ixy"), g("iyy"), g("iyz")], [g("ixz"), g("iyz"), g("izz")]])
                I = To[:3, :3] @ I @ To[:3, :3].T
            inertial = {"mass": float(m.get("value", 0)) if m is not None else 0.0, "com": To[:3, 3].tolist(), "inertia": I.tolist()}
        meshes = [Path(mm.get("filename", "")).name for mm in l.iter("mesh")]
        links[l.get("name")] = {"inertial": inertial, "meshes": meshes}
    parent_of, joints, T_child = {}, [], {}
    for j in root.findall("joint"):
        p, c = j.find("parent").get("link"), j.find("child").get("link")
        parent_of[c] = p
        T_child[c] = origin(j)
        if j.get("type") in ("revolute", "continuous", "prismatic"):
            lim = j.find("limit")
            rng = [float(lim.get("lower", 0)), float(lim.get("upper", 0))] if lim is not None and j.get("type") != "continuous" else None
            ax = j.find("axis")
            joints.append({"name": j.get("name"), "type": "hinge" if j.get("type") != "prismatic" else "slide", "body": c,
                           "parent": p, "axis": _f(ax.get("xyz")) if ax is not None and ax.get("xyz") else [1, 0, 0],
                           "pos": [0, 0, 0], "range": rng})
    bodies = []

    def world(name):
        T = np.eye(4)
        chain = []
        while name in parent_of:
            chain.append(name)
            name = parent_of[name]
        for n in reversed(chain):
            T = T @ T_child[n]
        return T
    for name, l in links.items():
        bodies.append({"name": name, "parent": parent_of.get(name), "T_world": world(name).tolist(),
                       "T_parent": T_child.get(name, np.eye(4)).tolist(), "inertial": l["inertial"],
                       "meshes": l["meshes"], "free": False, "mocap": False})
    return {"format": "urdf", "model": root.get("name", ""), "bodies": bodies, "joints": joints}


def parse_sim(name: str, data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    return parse_mjcf(text) if "<mujoco" in text[:4000].lower() else parse_urdf(text)


def pick_robot(model: dict) -> dict:
    """One robot from a scene: the first free-floating subtree that has joints (a scene may hold two hands)."""
    bodies = model["bodies"]
    kids: dict = {}
    for b in bodies:
        kids.setdefault(b["parent"], []).append(b["name"])

    def subtree(n):
        out, todo = [], [n]
        while todo:
            x = todo.pop()
            out.append(x)
            todo += kids.get(x, [])
        return out
    jointed = {j["body"] for j in model["joints"]}
    roots = [b["name"] for b in bodies if (b["free"] or b["parent"] is None) and not b["mocap"]]
    best = None
    for r in roots:
        sub = subtree(r)
        if any(x in jointed for x in sub):
            best = (r, sub)
            break
    if best is None:
        return {**model, "root": None, "copies": 0}
    r, sub = best
    same = sum(1 for r2 in roots if len([x for x in subtree(r2) if x in jointed]) == len([x for x in sub if x in jointed]))
    keep = set(sub)
    return {**model, "root": r, "copies": same, "bodies": [b for b in bodies if b["name"] in keep],
            "joints": [j for j in model["joints"] if j["body"] in keep]}


# ------------------------------------------------------------------ provenance --

def read_aux(files: list[tuple[str, bytes]]) -> tuple[dict | None, dict | None]:
    """(registration, manifest) from JSON files shipped with the sim model, if any."""
    reg = man = None
    for name, data in files:
        if not name.lower().endswith(".json"):
            continue
        try:
            d = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and "cad_origin_mm" in d and "cad_to_canonical_rotation" in d:
            reg = {"file": name, "origin_mm": d["cad_origin_mm"], "rotation": d["cad_to_canonical_rotation"],
                   "scale": d.get("cad_to_canonical_scale", 0.001), "bodies": d.get("bodies", {})}
        if isinstance(d, dict) and isinstance(d.get("meshes"), dict) and any(
                isinstance(v, dict) and "leaf_features" in v for v in d["meshes"].values()):
            man = {"file": name, "meshes": d["meshes"], "source_sha256": d.get("source_sha256")}
    return reg, man


def _key(s: str) -> str:
    return re.sub(r"[\s_\-./]+", "", s.strip().lower())


def _label_keys(s: str) -> list[str]:
    """The label as written, then without FreeCAD's 3-digit duplicate suffix ("CBSTNR2-5001" -> "CBSTNR2-5")."""
    keys = [_key(s)]
    m = re.match(r"^(.*?)(\d{3})$", s.strip())
    if m and m.group(1):
        keys.append(_key(m.group(1)))
    return keys


def map_bodies(robot: dict, graph, manifest: dict | None, human: dict[str, list[str]] | None = None,
               reg: dict | None = None) -> dict[str, dict]:
    """sim body -> {instances: [...], method}. Each CAD instance goes to at most one body.

    When several CAD copies share a label (a gear in each jaw), the copy is chosen by where it is: the
    manifest gives each mesh's bounds in its body frame, and with the registration a copy's centre can be
    tested against them. Without that, the first free copy is taken and the mapping says so.
    """
    human = human or {}
    parts = {p.id: p for p in graph.parts}
    by_label: dict[str, list] = {}
    for i in graph.instances:
        by_label.setdefault(_key(parts[i.part_id].name), []).append(i.id)
    inst = {i.id: i for i in graph.instances}

    def centre_root(iid):
        i = inst[iid]
        T = np.asarray(i.transform, float)
        p = graph.part(i.part_id)
        c = (np.asarray(p.bbox.min) + np.asarray(p.bbox.max)) / 2
        return to_root(reg, T[:3, :3] @ c + T[:3, 3])

    def box_distance(pt, mesh):
        lo, hi = mesh.get("bounds_local_m", [[0, 0, 0], [0, 0, 0]])
        o = np.asarray(mesh.get("body_origin_canonical_m", [0, 0, 0]), float)
        q = pt - o
        return float(np.linalg.norm(np.maximum(0, np.maximum(np.asarray(lo) - q, q - np.asarray(hi)))))
    taken: set[str] = set()
    out: dict[str, dict] = {}
    for b in robot["bodies"]:
        if b["name"] in human:
            ids = [x for x in human[b["name"]] if x not in taken]
            taken.update(ids)
            out[b["name"]] = {"instances": ids, "method": "human", "labels": []}
    if manifest:
        by_file = {Path(v.get("file", k)).name: v for k, v in manifest["meshes"].items()}
        for b in robot["bodies"]:
            if b["name"] in out or not b["meshes"]:
                continue
            labels: list[tuple[str, dict]] = []
            for mf in b["meshes"]:
                v = by_file.get(Path(mf).name)
                if v:
                    labels += [(lf.get("label", ""), v) for lf in v.get("leaf_features", [])]
            if not labels:
                continue
            out[b["name"]] = {"instances": [], "method": "manifest", "labels": [lab for lab, _ in labels], "_want": labels}
    if manifest and reg is not None:
        # By position: every CAD copy goes to the body whose meshes contain it. Exporters mangle labels
        # (FreeCAD numbers copies of "CB2.5-15" as "CB2.5-016", "CB2.5-017", and gave eleven inserts of three
        # types labels SB-304550..SB-304558), so a label is only a tie-breaker, never the assignment.
        meshes_of = {bname: [m for _, m in rec.pop("_want")] for bname, rec in out.items() if rec["method"] == "manifest"}
        keys_of = {bname: {k for lab in out[bname]["labels"] for k in _label_keys(lab)} for bname in meshes_of}
        uniq = {bname: list({id(m): m for m in ms}.values()) for bname, ms in meshes_of.items()}
        for iid in inst:
            if iid in taken:
                continue
            c = centre_root(iid)
            pk = _key(parts[inst[iid].part_id].name)
            scored = []
            for bname, ms in uniq.items():
                d = min(box_distance(c, m) for m in ms)
                scored.append((d, 0 if pk in keys_of[bname] else 1, bname))
            scored.sort()
            if scored and scored[0][0] <= 0.003:            # inside, or within 3 mm of, one of the body's meshes
                out[scored[0][2]]["instances"].append(iid)
                taken.add(iid)
        for bname in meshes_of:
            out[bname]["method"] = "manifest+position"
    elif manifest:
        # no registration: labels only, first free copy; the mapping says it could not check positions
        for bname, rec in out.items():
            if rec["method"] != "manifest":
                continue
            for lab, _m in rec.pop("_want"):
                for k in _label_keys(lab):
                    cands = [x for x in by_label.get(k, []) if x not in taken]
                    if cands:
                        rec["instances"].append(cands[0])
                        taken.add(cands[0])
                        break
            rec.setdefault("notes", []).append("copies assigned by label only: add a registration file to check positions")
    for b in robot["bodies"]:
        if b["name"] in out:
            continue
        ids = [x for x in by_label.get(_key(b["name"]), []) if x not in taken]
        out[b["name"]] = {"instances": ids, "method": "name" if ids else "none", "labels": []}
        taken.update(ids)
    return out


# ------------------------------------------------------------------ mass properties --

def instance_mass_props(graph, iid: str) -> dict | None:
    """Mass (kg), COM (mm, assembly frame) and inertia about the COM (kg mm^2, assembly frame) of one placed copy."""
    inst = next(i for i in graph.instances if i.id == iid)
    p = graph.part(inst.part_id)
    if p.mass is None or not p.volume:
        return None
    T = np.asarray(inst.transform, float)
    I_unit = np.asarray(p.inertia, float) if getattr(p, "inertia", None) else None
    com = T[:3, :3] @ np.asarray(p.com, float) + T[:3, 3]
    I = None
    if I_unit is not None:
        I = (p.mass / p.volume) * (T[:3, :3] @ I_unit @ T[:3, :3].T)      # density-1 tensor (mm^5) scaled to kg mm^2
    return {"mass": p.mass, "com": com, "inertia": I}


def aggregate(graph, ids: list[str]) -> dict:
    props, missing = [], []
    for iid in ids:
        mp = instance_mass_props(graph, iid)
        if mp is None:
            missing.append(iid)
        else:
            props.append(mp)
    if not props:
        return {"mass": 0.0, "com": None, "inertia": None, "missing": missing, "complete": False}
    M = sum(x["mass"] for x in props)
    com = sum(x["mass"] * x["com"] for x in props) / M
    I = np.zeros((3, 3))
    have_I = all(x["inertia"] is not None for x in props)
    if have_I:
        for x in props:
            d = x["com"] - com
            I += x["inertia"] + x["mass"] * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return {"mass": M, "com": com, "inertia": I if have_I else None, "missing": missing, "complete": not missing}


def to_root(reg: dict, p_mm: np.ndarray) -> np.ndarray:
    """CAD mm (assembly frame) -> sim root frame (metres)."""
    R = np.asarray(reg["rotation"], float)
    return float(reg["scale"]) * (R @ (np.asarray(p_mm, float) - np.asarray(reg["origin_mm"], float)))


def principal(I: np.ndarray) -> list[float]:
    return sorted(float(x) for x in np.linalg.eigvalsh((np.asarray(I) + np.asarray(I).T) / 2))


def analyse(graph, robot: dict, mapping: dict, reg: dict | None) -> dict:
    """Per body and per joint: sim values, CAD values (where computable), and the corrected inertial."""
    bodies = {b["name"]: b for b in robot["bodies"]}
    root = robot["root"]
    T_root = np.asarray(bodies[root]["T_world"], float) if root else np.eye(4)
    inv_root = np.linalg.inv(T_root)
    joint_of = {j["body"]: j for j in robot["joints"]}
    out_bodies, out_joints = [], []
    for name, b in bodies.items():
        m = mapping.get(name, {"instances": [], "method": "none"})
        agg = aggregate(graph, m["instances"]) if m["instances"] else None
        sim = b["inertial"]
        rec = {"body": name, "parent": b["parent"], "method": m["method"], "instances": m["instances"],
               "labels": m.get("labels", []), "sim": sim, "cad": None, "missing": agg["missing"] if agg else [],
               "frame": None, "corrected": None, "notes": []}
        if agg and agg["mass"] > 0:
            cad = {"mass": round(agg["mass"], 6), "complete": agg["complete"]}
            if agg["inertia"] is not None:
                cad["principal_kg_m2"] = [round(x * 1e-6, 12) for x in principal(agg["inertia"])]
            if reg is not None and agg["com"] is not None:
                T_b = inv_root @ np.asarray(b["T_world"], float)          # body frame in root frame, sim zero pose
                com_root = to_root(reg, agg["com"])
                R_cr = np.asarray(reg["rotation"], float)                                  # CAD axes -> root axes
                I_root = R_cr @ agg["inertia"] @ R_cr.T * 1e-6 if agg["inertia"] is not None else None   # kg mm^2 -> kg m^2
                j = joint_of.get(name)
                if j is None or name == root:
                    com_b = (np.linalg.inv(T_b) @ np.append(com_root, 1))[:3]
                    I_b = T_b[:3, :3].T @ I_root @ T_b[:3, :3] if I_root is not None else None
                    rec["frame"] = "rigid"
                else:
                    # hinge: express the CAD COM about the joint axis; estimate the CAD pose angle from the COMs
                    ax_b = np.asarray(j["axis"], float)
                    ax_b = ax_b / np.linalg.norm(ax_b)
                    jp_b = np.asarray(j["pos"], float)
                    com_b0 = (np.linalg.inv(T_b) @ np.append(com_root, 1))[:3]       # CAD COM in body frame, no pose fix
                    theta = 0.0
                    if sim is not None:
                        def cyl(p):
                            d = p - jp_b
                            h = float(np.dot(d, ax_b))
                            radial = d - ax_b * h
                            return radial, h
                        rc, _ = cyl(com_b0)
                        rs, _ = cyl(np.asarray(sim["com"], float))
                        if np.linalg.norm(rc) > 1e-6 and np.linalg.norm(rs) > 1e-6:
                            theta = math.atan2(float(np.dot(np.cross(rc, rs), ax_b)), float(np.dot(rc, rs)))
                    Rfix = axis_angle(ax_b, theta)
                    com_b = jp_b + Rfix @ (com_b0 - jp_b)
                    I_b0 = T_b[:3, :3].T @ I_root @ T_b[:3, :3] if I_root is not None else None
                    I_b = Rfix @ I_b0 @ Rfix.T if I_b0 is not None else None
                    rec["frame"] = "hinge"
                    rec["pose_offset_deg"] = round(math.degrees(theta), 2)
                    rec["notes"].append(f"the CAD has this body posed {math.degrees(theta):+.1f}° about its joint from the sim zero; "
                                        "COM compared as radius and height about the axis")
                    def cylc(p):
                        d = np.asarray(p, float) - jp_b
                        h = float(np.dot(d, ax_b))
                        return float(np.linalg.norm(d - ax_b * h)), h
                    cad["cyl_m"] = [round(x, 6) for x in cylc(com_b)]
                    if sim is not None:
                        rec["sim_cyl_m"] = [round(x, 6) for x in cylc(sim["com"])]
                cad["com_m"] = [round(float(x), 7) for x in com_b]
                if I_b is not None:
                    cad["inertia_kg_m2"] = [[round(float(v), 12) for v in row] for row in I_b]
                if agg["complete"]:
                    rec["corrected"] = corrected_blocks(cad["mass"], com_b, I_b)
            rec["cad"] = cad
        out_bodies.append(rec)
    for j in robot["joints"]:
        b = bodies[j["body"]]
        T_b = inv_root @ np.asarray(b["T_world"], float)
        ax_root = T_b[:3, :3] @ np.asarray(j["axis"], float)
        out_joints.append({**j, "axis_root": (ax_root / np.linalg.norm(ax_root)).tolist(),
                           "pos_root": (T_b @ np.append(np.asarray(j["pos"], float), 1))[:3].tolist()})
    return {"bodies": out_bodies, "joints": out_joints}


def corrected_blocks(mass: float, com, I) -> dict:
    c = " ".join(f"{float(v):.6g}" for v in com)
    out = {"mjcf": f'<inertial pos="{c}" mass="{mass:.6g}"'
                   + (f' fullinertia="{I[0][0]:.6g} {I[1][1]:.6g} {I[2][2]:.6g} {I[0][1]:.6g} {I[0][2]:.6g} {I[1][2]:.6g}"/>' if I is not None else "/>")}
    if I is not None:
        out["urdf"] = ("<inertial>\n"
                       f'  <origin xyz="{c}" rpy="0 0 0"/>\n'
                       f'  <mass value="{mass:.6g}"/>\n'
                       f'  <inertia ixx="{I[0][0]:.6g}" ixy="{I[0][1]:.6g}" ixz="{I[0][2]:.6g}" iyy="{I[1][1]:.6g}" '
                       f'iyz="{I[1][2]:.6g}" izz="{I[2][2]:.6g}"/>\n</inertial>')
    return out


def cad_axes(graph, reg: dict, parent_ids: list[str], child_ids: list[str]) -> list[dict]:
    """Coaxial cylinders shared by a parent and a child body's parts (a shaft in a bore): candidate joint axes."""
    if reg is None:
        return []
    out = []
    feats_by_part: dict = {}
    for f in graph.features:
        if f["kind"] in ("hole", "cylinder"):
            feats_by_part.setdefault(f["part_id"], []).append(f)
    inst = {i.id: i for i in graph.instances}

    def placed(ids):
        res = []
        for iid in ids:
            i = inst[iid]
            T = np.asarray(i.transform, float)
            for f in feats_by_part.get(i.part_id, []):
                c = T[:3, :3] @ np.asarray(f["center"], float) + T[:3, 3]
                a = T[:3, :3] @ np.asarray(f["axis"], float)
                res.append((f, c, a / np.linalg.norm(a)))
        return res
    P, C = placed(parent_ids), placed(child_ids)
    R = np.asarray(reg["rotation"], float)
    for fp, cp, ap in P:
        for fc, cc, ac in C:
            if abs(abs(float(np.dot(ap, ac))) - 1) > 1e-3:
                continue
            d = cc - cp
            if float(np.linalg.norm(d - ap * np.dot(d, ap))) > 0.1 or abs(fp["diameter"] - fc["diameter"]) > 0.6:
                continue
            out.append({"diameter": round(min(fp["diameter"], fc["diameter"]), 3), "axis_root": (R @ ap).tolist(),
                        "point_root": to_root(reg, cp).tolist()})
    out.sort(key=lambda x: -x["diameter"])
    return out
