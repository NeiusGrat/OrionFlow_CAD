"""Motion (M8): joints, and a sweep of each joint through its range on exact B-rep geometry.

A joint is an axis (a point and a unit direction, assembly frame, mm), a type
(hinge | slide), limits in joint coordinates, the joint coordinate the CAD is
posed at, and the instances that move with it. Joints come from the sim model
(its axis brought into the CAD frame by the registration) or are inferred from
the geometry (a shaft running in a bore); either way the engineer confirms one
before it is swept, because a wrong moving set or axis makes every number after
it wrong.

The sweep moves the moving set from the CAD pose to each limit in steps and, at
every step, measures against every other part:

* **free pairs** (apart at the CAD pose): exact minimum distance (BRepExtrema on
  the faces whose boxes can be that close; branch and bound over the parts, so
  a far part costs one box test). A distance of zero is a collision; its angle
  is refined by bisection.
* **riding pairs** (touching at the CAD pose through surfaces of revolution
  about the joint axis or faces square to it: a shaft in its bore, a thrust
  washer): moving the joint does not change such a contact, so they are listed,
  not tracked; their overlap is measured at both limits to prove it.
* **other touching pairs**: the overlap volume (BRepAlgoAPI_Common) at every
  step against its value at the CAD pose; growth is a collision.

Joints coupled to the swept one (a gear train: MJCF ``<equality><joint>``, URDF
``<mimic>``) move by their coupling; fasteners seated off-axis in a moving part
move with it; a fixed part those fasteners thread into is the actuator driving
the joint and is not judged (its housing and output are one solid). Every other
joint stays at the CAD pose. Nothing here is estimated.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional

import numpy as np

FAR_MM = 10.0            # clearances above this are charted as "> 10 mm"
COLLIDE_MM = 1e-4        # exact distance at or below this is contact
OVERLAP_GROW_MM3 = 0.01  # a touching pair collides when its common volume grows by more than this
REFINE_DEG = 0.05        # bisection stops at this angle (or 0.005 mm for a slide)
AXIS_TOL = 0.9995        # cos(~1.8 deg): a fit / plane belongs to the joint axis
OFFSET_TOL = 0.2         # mm


# ------------------------------------------------------------------ joints --

def _unit(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def sim_joints(graph) -> list[dict]:
    """Joints of the sim model, in the CAD frame, with the instances each moves (its body and every body below)."""
    doc = graph.sim
    if not doc or not doc.get("analysis") or not doc.get("registration"):
        return []
    reg = doc["registration"]
    R = np.asarray(reg["rotation"], float)            # CAD axes -> root axes
    s = float(reg["scale"])
    origin = np.asarray(reg["origin_mm"], float)
    bodies = {b["body"]: b for b in doc["analysis"]["bodies"]}
    children: dict[str, list[str]] = {}
    for b in bodies.values():
        children.setdefault(b["parent"], []).append(b["body"])

    def subtree(name):
        out = list(bodies[name]["instances"]) if name in bodies else []
        for c in children.get(name, []):
            out += subtree(c)
        return out

    out = []
    for j in doc["analysis"]["joints"]:
        if j["type"] not in ("hinge", "slide", "revolute", "continuous", "prismatic"):
            continue
        kind = "slide" if j["type"] in ("slide", "prismatic") else "hinge"
        axis = R.T @ np.asarray(j["axis_root"], float)
        point = R.T @ (np.asarray(j["pos_root"], float) / s) + origin
        body = bodies.get(j["body"], {})
        off = body.get("pose_offset_deg")
        # analyse() rotates the CAD by +offset onto the sim zero, so the CAD sits at q = -offset
        q_cad = -math.radians(off) if (kind == "hinge" and off is not None) else 0.0
        rng = j.get("range")
        if kind == "hinge":
            lo, hi = (rng if rng else (-math.pi, math.pi))
            unit = "rad"
        else:
            lo, hi = ((rng[0] / s, rng[1] / s) if rng else (-10.0, 10.0))      # metres -> mm
            unit = "mm"
        out.append({
            "key": f"sim:{j['name']}", "name": j["name"], "source": "sim", "kind": kind, "unit": unit,
            "axis": _unit(axis).tolist(), "point": point.tolist(), "lower": float(lo), "upper": float(hi),
            "limits_source": f"{doc['file']} joint range" if rng else "none in the sim model (continuous): ±180° swept",
            "cad_q": q_cad,
            "cad_q_source": (f"estimated from the CAD vs sim centre of mass angle about the axis ({off:+.2f}°)"
                             if off is not None else "assumed 0 (sim zero)"),
            "moving": subtree(j["body"]), "body": j["body"], "parent": j.get("parent"),
        })
    couple(out, (doc.get("robot") or {}).get("couplings", []))
    return out


def _fasteners(graph) -> set[str]:
    """Instances that carry a modelled thread in some contact: screws, not shafts."""
    out = set()
    for c in graph.contacts:
        for t in c.get("threads", []):
            out.add(c["a"] if t.get("shaft_on") == "a" else c["b"])
    return out


def inferred_joints(graph, skip_axes: list[tuple] = ()) -> list[dict]:
    """Candidate hinges from the geometry: a boss running in a bore with radial clearance, between two parts
    neither of which is a threaded fastener, not already a sim joint's axis. They must be confirmed."""
    screws = _fasteners(graph)
    inst = {i.id: i for i in graph.instances}
    pname = {p.id: p.name for p in graph.parts}
    out, seen = [], []
    for c in graph.contacts:
        if c["a"] in screws or c["b"] in screws:
            continue
        for f in c.get("fits", []):
            clr = f.get("clearance")
            if clr is None or clr < 0.005 or f["shaft_diameter"] < 2.0:
                continue
            axis, point = _unit(f["axis"]), np.asarray(f["point"], float)
            same = lambda a, p: abs(float(np.dot(a, axis))) > AXIS_TOL and \
                np.linalg.norm((p - point) - axis * np.dot(p - point, axis)) < OFFSET_TOL
            if any(same(_unit(a), np.asarray(p, float)) for a, p in list(skip_axes) + seen):
                continue
            seen.append((axis, point))
            a, b = inst[c["a"]], inst[c["b"]]
            # the moving side defaults to the smaller part (the engineer confirms or changes it)
            va = next(p.volume for p in graph.parts if p.id == a.part_id)
            vb = next(p.volume for p in graph.parts if p.id == b.part_id)
            mover, fixed = (a, b) if va <= vb else (b, a)
            out.append({
                "key": f"geo:{c['id']}:{len(out)}", "name": f"{pname[mover.part_id]} in {pname[fixed.part_id]}",
                "source": "inferred", "kind": "hinge", "unit": "rad", "axis": axis.tolist(), "point": point.tolist(),
                "lower": None, "upper": None, "limits_source": "enter the limits", "cad_q": 0.0,
                "cad_q_source": "the CAD pose is joint zero", "moving": moving_set(graph, mover.id, fixed.id, axis, point),
                "evidence": f"Ø{f['shaft_diameter']} in Ø{f['hole_diameter']}: {clr} mm diametral clearance (contact {c['id']})",
            })
    out.sort(key=lambda j: j["name"])
    return out


def _axisymmetric(c: dict, axis: np.ndarray, point: np.ndarray) -> bool:
    """A contact a rotation about this axis leaves unchanged: fits coaxial with it, planes square to it."""
    if c.get("type") == "point" or (not c.get("fits") and not c.get("planes")):
        return False
    for f in c.get("fits", []) + c.get("coaxial_holes", []):
        a, p = _unit(f["axis"]), np.asarray(f["point"], float)
        if abs(float(np.dot(a, axis))) < AXIS_TOL:
            return False
        d = p - point
        if np.linalg.norm(d - axis * np.dot(d, axis)) > OFFSET_TOL:
            return False
    for pl in c.get("planes", []):
        if abs(float(np.dot(_unit(pl["normal"]), axis))) < AXIS_TOL:
            return False
    return True


def moving_set(graph, child: str, parent: str, axis, point) -> list[str]:
    """Instances connected to ``child`` once every contact riding on the axis is cut; the parent side stays.
    When the two sides are still joined (a bolt, a gear) only the child moves."""
    axis, point = _unit(axis), np.asarray(point, float)
    adj: dict[str, set] = {}
    for c in graph.contacts:
        if _axisymmetric(c, axis, point):
            continue
        adj.setdefault(c["a"], set()).add(c["b"])
        adj.setdefault(c["b"], set()).add(c["a"])
    seen, stack = {child}, [child]
    while stack:
        for n in adj.get(stack.pop(), ()):
            if n not in seen:
                seen.add(n)
                stack.append(n)
    if parent in seen:
        return [child]
    return sorted(seen)


# ------------------------------------------------------------------- sweep --

class Scene:
    """The assembly's placed shapes, keyed by Model Graph instance id."""

    def __init__(self, shapes: dict[str, object]):
        from .geometry import _face_boxes

        self.shapes = shapes
        self.faces: dict[str, tuple[list, np.ndarray]] = {iid: _face_boxes(s, 0.0) for iid, s in shapes.items()}
        self.box = {iid: (b[:, :3].min(0), b[:, 3:].max(0)) for iid, (_, b) in self.faces.items() if len(b)}

    @classmethod
    def from_step(cls, step_path, graph) -> "Scene":
        from interface_check.ingest_step import read_assembly

        _parts, ic_instances, notes = read_assembly(step_path)
        if any(f.rule_id == "ASSEMBLY_STRUCTURE_MISSING" for f in notes):
            from .flat import realign
            realign(_parts, ic_instances)
        if len(ic_instances) != len(graph.instances):
            raise RuntimeError(f"the STEP now reads as {len(ic_instances)} instances, the model graph has "
                               f"{len(graph.instances)}: re-run the review")
        return cls({g.id: ic.shape for ic, g in zip(ic_instances, graph.instances)})


def _trsf(kind: str, axis: np.ndarray, point: np.ndarray, delta: float):
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    t = gp_Trsf()
    if kind == "hinge":
        t.SetRotation(gp_Ax1(gp_Pnt(*map(float, point)), gp_Dir(*map(float, axis))), float(delta))
    else:
        t.SetTranslation(gp_Vec(*map(float, axis * delta)))
    return t


def _matrix(kind: str, axis: np.ndarray, point: np.ndarray, delta: float) -> np.ndarray:
    M = np.eye(4)
    if kind == "hinge":
        from .sim import axis_angle
        R = axis_angle(axis, delta)
        M[:3, :3] = R
        M[:3, 3] = point - R @ point
    else:
        M[:3, 3] = axis * delta
    return M


def _moved_boxes(boxes: np.ndarray, M: np.ndarray) -> np.ndarray:
    """Conservative AABBs of moved boxes (all 8 corners transformed)."""
    if not len(boxes):
        return boxes
    lo, hi = boxes[:, :3], boxes[:, 3:]
    corners = np.stack([np.where(np.array(bits, bool), hi, lo) for bits in np.ndindex(2, 2, 2)], axis=1)  # n,8,3
    moved = corners @ M[:3, :3].T + M[:3, 3]
    return np.concatenate([moved.min(1), moved.max(1)], axis=1)


def _box_gap(a: tuple, b: tuple) -> float:
    d = np.maximum(0.0, np.maximum(a[0] - b[1], b[0] - a[1]))
    return float(np.linalg.norm(d))


def _common_volume(a, b) -> float:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopTools import TopTools_ListOfShape

    try:
        c = BRepAlgoAPI_Common()
        args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(a)
        tools.Append(b)
        c.SetArguments(args)
        c.SetTools(tools)
        c.SetRunParallel(True)
        c.Build()
        if not c.IsDone():
            return float("nan")
        g = GProp_GProps()
        BRepGProp.VolumeProperties_s(c.Shape(), g)
        return abs(g.Mass())
    except Exception:  # noqa: BLE001
        return float("nan")


def poly(coef, x: float) -> float:
    return float(sum(c * x ** k for k, c in enumerate(coef)))


def couple(joints: list[dict], couplings: list[dict]) -> None:
    """Attach to each joint the joints that move with it (``followers``): q_follower = f(q_this).
    A coupling q1 = c0 + c1 q2 drives joint1 from joint2, and joint2 from joint1 when linear."""
    by = {j["name"]: j for j in joints}
    for j in joints:
        j["followers"] = []
    for c in couplings:
        a, b = by.get(c["joint"]), by.get(c["of"])
        if a is None or b is None:
            continue
        coef = list(c["coef"]) + [0.0] * (2 - len(c["coef"]))
        b["followers"].append({"name": a["name"], "coef": coef, "source": c["source"]})
        if all(abs(x) < 1e-12 for x in coef[2:]) and abs(coef[1]) > 1e-12:
            a["followers"].append({"name": b["name"], "coef": [-coef[0] / coef[1], 1.0 / coef[1]],
                                   "source": c["source"] + " (inverted)"})


def expand(graph, joint: dict, others: dict[str, dict] | None = None) -> dict:
    """Groups that move when this joint moves (the joint itself, then its followers), each completed with the
    fasteners it carries, and the drivers: fixed parts the carried fasteners thread into (an actuator whose output
    is bolted to the moving parts; its housing and output are one solid, so contact with it cannot be judged)."""
    others = others or {}
    groups = [{"name": joint["name"], "kind": joint["kind"], "axis": joint["axis"], "point": joint["point"],
               "cad_q": joint["cad_q"], "coef": [0.0, 1.0], "moving": list(joint["moving"]), "source": "swept joint"}]
    for f in joint.get("followers", []):
        o = others.get(f["name"])
        if o is not None:
            groups.append({"name": o["name"], "kind": o["kind"], "axis": o["axis"], "point": o["point"],
                           "cad_q": o["cad_q"], "coef": f["coef"], "moving": list(o["moving"]), "source": f["source"]})
    screws = _fasteners(graph)
    vol = {i.id: next(p.volume for p in graph.parts if p.id == i.part_id) for i in graph.instances}
    taken = {i for g in groups for i in g["moving"]}
    ignore = set(joint.get("ignore", []))
    drivers: dict[str, dict] = {}
    for g in groups:
        axis, point, mv = _unit(g["axis"]), np.asarray(g["point"], float), set(g["moving"])
        carried = []
        for c in graph.contacts:
            if (c["a"] in mv) == (c["b"] in mv):
                continue
            m, s = (c["a"], c["b"]) if c["a"] in mv else (c["b"], c["a"])
            if s in taken or s in ignore:
                continue
            off_axis = [f for f in c.get("fits", []) if not _axisymmetric({"fits": [f], "type": "x"}, axis, point)]
            if off_axis and (s in screws or vol[s] < vol[m]):
                carried.append(s)
        for s in carried:
            if s not in taken:
                g["moving"].append(s)
                taken.add(s)
        # a part locked to a moving part (a key, a set collar) that the fixed side holds only through contacts
        # riding on this axis turns with the group too; repeat until nothing more joins
        while True:
            mv = set(g["moving"])
            touch_mv: dict[str, bool] = {}
            held: set[str] = set()
            for c in graph.contacts:
                for x, y in ((c["a"], c["b"]), (c["b"], c["a"])):
                    if x in mv or x in taken or x in ignore:
                        continue
                    ax = _axisymmetric(c, axis, point)
                    if y in mv:
                        touch_mv[x] = touch_mv.get(x, False) or not ax
                    elif not ax:
                        held.add(x)
            more = [x for x, locked in touch_mv.items() if locked and x not in held]
            if not more:
                break
            for x in more:
                g["moving"].append(x)
                taken.add(x)
                carried.append(x)
        g["carried"] = carried
    for g in groups:
        mv = set(g["moving"])
        for c in graph.contacts:
            if not c.get("threads") or (c["a"] in mv) == (c["b"] in mv):
                continue
            m, s = (c["a"], c["b"]) if c["a"] in mv else (c["b"], c["a"])
            if s in taken:
                continue
            if any((t["shaft_on"] == "a") == (c["a"] == m) for t in c["threads"]) and m in g["carried"]:
                drivers.setdefault(s, {"id": s, "group": g["name"], "via": []})["via"].append(m)
    return {"groups": groups, "drivers": list(drivers.values())}


class Sweeper:
    """Poses every moving group for a driving-joint offset ``delta`` and measures the assembly there."""

    def __init__(self, scene: Scene, graph, joint: dict, plan: dict):
        from OCP.TopLoc import TopLoc_Location

        self._Loc = TopLoc_Location
        self.scene, self.joint = scene, joint
        self.groups = []
        self.group_of: dict[str, int] = {}
        for k, g in enumerate(plan["groups"]):
            ids = [i for i in g["moving"] if i in scene.shapes and i not in self.group_of]
            for i in ids:
                self.group_of[i] = k
            self.groups.append({**g, "ids": ids, "axis_v": _unit(g["axis"]), "point_v": np.asarray(g["point"], float)})
        self.moving = list(self.group_of)
        self.drivers = {d["id"] for d in plan["drivers"]} | set(joint.get("ignore", []))
        self.static = [i for i in scene.shapes if i not in self.group_of]
        q0 = joint["cad_q"]
        self.q0 = q0
        touching: dict[tuple, dict] = {}
        for c in graph.contacts:
            ga, gb = self.group_of.get(c["a"]), self.group_of.get(c["b"])
            if ga is None and gb is None or ga == gb:
                continue
            a, b = (c["a"], c["b"]) if ga is not None else (c["b"], c["a"])
            touching[(a, b)] = c
        self.touch = set(touching) | {(b, a) for a, b in touching}
        self.riding, self.tracked, self.skipped = [], [], []
        for (a, b), c in touching.items():
            ga, gb = self.group_of.get(a), self.group_of.get(b)
            if b in self.drivers or a in self.drivers:
                self.skipped.append((a, b))
            elif gb is None and _axisymmetric(c, self.groups[ga]["axis_v"], self.groups[ga]["point_v"]):
                self.riding.append((a, b))
            else:
                self.tracked.append((a, b))
        self.base_overlap = {k: _common_volume(scene.shapes[k[0]], scene.shapes[k[1]]) for k in self.tracked + self.riding}
        self._pair_list: list | None = None
        self._rates: dict[str, float] = {}
        self._cache: dict[tuple, tuple[float, float]] = {}       # pair -> (distance or lower bound, delta)

    # ---- poses
    def deltas(self, delta: float) -> list[float]:
        q = self.q0 + delta
        out = []
        for g in self.groups:
            out.append(delta if g["source"] == "swept joint" else poly(g["coef"], q) - poly(g["coef"], self.q0))
        return out

    def pose(self, delta: float) -> dict[str, tuple]:
        """iid -> (TopLoc_Location, 4x4) for every moving instance."""
        out = {}
        for g, d in zip(self.groups, self.deltas(delta)):
            loc = self._Loc(_trsf(g["kind"], g["axis_v"], g["point_v"], d))
            M = _matrix(g["kind"], g["axis_v"], g["point_v"], d)
            for i in g["ids"]:
                out[i] = (loc, M)
        return out

    def _placed(self, iid: str, P: dict):
        faces, boxes = self.scene.faces[iid]
        if iid not in P:
            return self.scene.shapes[iid], faces, boxes, self.scene.box.get(iid)
        loc, M = P[iid]
        mb = _moved_boxes(boxes, M)
        return (self.scene.shapes[iid].Moved(loc), (loc, faces), mb,
                (mb[:, :3].min(0), mb[:, 3:].max(0)) if len(mb) else None)

    def _pairs(self):
        """Every (moving, other) pair not in the same group and not touching at the CAD pose, once."""
        if self._pair_list is None:
            out = []
            for m in self.moving:
                for o in self.scene.shapes:
                    if o == m or self.group_of.get(o) == self.group_of[m] or (m, o) in self.touch or o in self.drivers:
                        continue
                    if o in self.group_of and o < m:
                        continue
                    if m in self.scene.box and o in self.scene.box:
                        out.append((m, o))
            self._pair_list = out
        return self._pair_list

    def _rate(self, iid: str) -> float:
        """How fast any point of this part can move per unit of the driving joint (mm per rad, or mm per mm)."""
        if iid not in self.group_of:
            return 0.0
        if iid not in self._rates:
            g = self.groups[self.group_of[iid]]
            gain = 1.0 if g["source"] == "swept joint" else sum(abs(c) * (k or 1) * 4.0 ** max(k - 1, 0)
                                                                 for k, c in enumerate(g["coef"]) if k)
            if g["kind"] == "hinge":
                lo, hi = self.scene.box[iid]
                corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                d = corners - g["point_v"]
                r = float(np.max(np.linalg.norm(d - np.outer(d @ g["axis_v"], g["axis_v"]), axis=1)))
                self._rates[iid] = r * gain
            else:
                self._rates[iid] = gain
        return self._rates[iid]

    def _lower_bounds(self, delta: float, P: dict) -> list[tuple]:
        """(lower bound on the distance, m, o) for every pair at this pose: the moved boxes' gap, and the last
        exact value less the most the pair can have closed since (rate x travel)."""
        boxes: dict = {}

        def box(i):
            if i not in boxes:
                boxes[i] = self._placed(i, P)[3]
            return boxes[i]
        out = []
        for m, o in self._pairs():
            lb = _box_gap(box(m), box(o))
            c = self._cache.get((m, o))
            if c is not None:
                lb = max(lb, c[0] - (self._rate(m) + self._rate(o)) * abs(delta - c[1]))
            out.append((lb, m, o))
        out.sort()
        return out

    def _exact(self, m: str, o: str, P: dict, delta: float, gap: float):
        """Exact distance of a pair if below ``gap`` (else None); every outcome tightens the cache."""
        from .geometry import _min_face_distance

        pm, po = self._placed(m, P), self._placed(o, P)
        fm = [f.Moved(pm[1][0]) for f in pm[1][1]] if isinstance(pm[1], tuple) else pm[1]
        fo = [f.Moved(po[1][0]) for f in po[1][1]] if isinstance(po[1], tuple) else po[1]
        bm = pm[2].copy()
        bm[:, :3] -= gap
        bm[:, 3:] += gap
        d, p = _min_face_distance(fm, bm, fo, po[2], gap)
        self._cache[(m, o)] = (d if d is not None else gap, delta)
        return (d, p) if d is not None and d < gap else (None, None)

    def free_min(self, delta: float, bound: float = FAR_MM, P: dict | None = None):
        """Smallest exact distance between a moved part and any part it was apart from at the CAD pose, if below
        ``bound``: pairs in order of their lower bound, stopping when no remaining pair can beat the best."""
        P = P if P is not None else self.pose(delta)
        best, pair, pt = bound, None, None
        for lb, m, o in self._lower_bounds(delta, P):
            if lb >= best:
                break
            d, p = self._exact(m, o, P, delta, best)
            if d is not None and d < best:
                best, pair, pt = d, (m, o), p
                if best <= COLLIDE_MM:
                    break
        return best, pair, pt

    def overlaps(self, delta: float, pairs=None, P: dict | None = None) -> list[dict]:
        P = P if P is not None else self.pose(delta)
        out = []
        for a, b in (self.tracked if pairs is None else pairs):
            v = _common_volume(self._placed(a, P)[0], self._placed(b, P)[0])
            v0 = self.base_overlap[(a, b)]
            out.append({"moving": a, "other": b, "volume": round(v, 4), "at_cad_pose": round(v0, 4),
                        "grows": bool(v == v and v0 == v0 and v - v0 > OVERLAP_GROW_MM3)})
        return out

    def collides(self, delta: float) -> tuple[bool, dict]:
        P = self.pose(delta)
        d, pair, pt = self.free_min(delta, bound=1e-3, P=P)
        if pair is not None and d <= COLLIDE_MM:
            return True, {"kind": "contact", "moving": pair[0], "other": pair[1], "point": pt}
        hits = [h for h in self.overlaps(delta, P=P) if h["grows"]]
        if hits:
            return True, {"kind": "overlap", **hits[0]}
        return False, {}

    def nearest(self, delta: float, k: int = 5) -> list[dict]:
        """The k parts nearest the moving set at this pose (one row per part; a moving-moving pair is one row).

        Pairs come off a heap by lower bound; each exact call looks only a little past that bound (a 10 mm window
        on gear teeth would load every face), and a pair found farther goes back with the tighter bound."""
        import heapq

        P = self.pose(delta)
        rows: dict = {}
        heap = list(self._lower_bounds(delta, P))
        heapq.heapify(heap)

        def kth():
            ds = sorted(r["distance"] for r in rows.values())
            return ds[k - 1] if len(ds) >= k else FAR_MM
        while heap:
            lb, m, o = heapq.heappop(heap)
            key = o if o not in self.group_of else (m, o)
            if lb >= kth():
                break
            if key in rows and lb >= rows[key]["distance"]:
                continue
            window = min(kth(), max(lb, 0.0) + 1.0)
            d, p = self._exact(m, o, P, delta, window)
            if d is None:
                if window < kth():
                    heapq.heappush(heap, (window, m, o))
                continue
            if key not in rows or d < rows[key]["distance"]:
                rows[key] = {"moving": m, "other": o, "distance": round(d, 4), "point": p}
        return sorted(rows.values(), key=lambda r: r["distance"])[:k]


def sweep(scene: Scene, graph, joint: dict, others: dict[str, dict] | None = None, step: float | None = None,
          progress: Callable[[float, str], None] | None = None) -> dict:
    """Sweep one confirmed joint (and every joint coupled to it) from the CAD pose to each limit."""
    t0 = time.time()
    say = progress or (lambda *_: None)
    plan = expand(graph, joint, others)
    sw = Sweeper(scene, graph, joint, plan)
    hinge = joint["kind"] == "hinge"
    step = float(step or joint.get("step") or (math.radians(2.0) if hinge else 0.5))
    refine = math.radians(REFINE_DEG) if hinge else 0.005
    q0 = joint["cad_q"]
    ends_d = {"upper": joint["upper"] - q0, "lower": joint["lower"] - q0}
    total = max(1, sum(math.ceil(abs(e) / step) for e in ends_d.values()))
    done = 0
    rest = sw.free_min(0.0)
    rest_hit, rest_info = sw.collides(0.0)
    samples = [{"q": q0, "delta": 0.0, "min_distance": None if rest[1] is None else round(rest[0], 4),
                "pair": list(rest[1]) if rest[1] else None, "point": rest[2]}]
    collisions: dict[str, Optional[dict]] = {"upper": None, "lower": None}
    for side, end in ends_d.items():
        if abs(end) < 1e-12:
            continue
        if rest_hit:
            break
        sgn = 1.0 if end > 0 else -1.0
        n = math.ceil(abs(end) / step - 1e-9)
        prev = 0.0
        for k in range(1, n + 1):
            delta = sgn * min(k * step, abs(end))
            P = sw.pose(delta)
            d, pair, pt = sw.free_min(delta, P=P)
            grow = [h for h in sw.overlaps(delta, P=P) if h["grows"]] if sw.tracked else []
            rec = {"q": q0 + delta, "delta": delta, "min_distance": None if pair is None else round(d, 4),
                   "pair": list(pair) if pair else None, "point": pt}
            if grow:
                rec["overlap"] = grow
            samples.append(rec)
            done += 1
            say(done / total, f"{side}: {k}/{n}")
            if (pair is not None and d <= COLLIDE_MM) or grow:
                a, b, info = prev, delta, None
                while abs(b - a) > refine:
                    mid = (a + b) / 2
                    h, inf = sw.collides(mid)
                    if h:
                        b, info = mid, inf
                    else:
                        a = mid
                if info is None:
                    info = ({"kind": "overlap", **grow[0]} if grow else
                            {"kind": "contact", "moving": pair[0], "other": pair[1], "point": pt})
                collisions[side] = {"q": q0 + b, "delta": b, "clear_until_q": q0 + a, **info}
                break
            prev = delta
    ends = {}
    for side, end in ends_d.items():
        stop = (collisions[side]["clear_until_q"] - q0) if collisions[side] else end
        ends[side] = {"q": q0 + stop, "reached_limit": collisions[side] is None and not rest_hit,
                      "nearest": sw.nearest(stop),
                      "riding_overlap": sw.overlaps(stop, sw.riding) if sw.riding else []}
    samples.sort(key=lambda r: r["q"])
    ds = [r["min_distance"] for r in samples if r["min_distance"] is not None]
    mn = min(range(len(samples)), key=lambda i: samples[i]["min_distance"] if samples[i]["min_distance"] is not None else 1e9) if ds else None
    unit = "°" if hinge else " mm"
    return {
        "joint": {k: joint.get(k) for k in ("key", "name", "source", "kind", "unit", "axis", "point", "lower", "upper",
                                            "cad_q", "cad_q_source", "limits_source", "moving", "ignore")},
        "groups": [{k: g[k] for k in ("name", "kind", "axis", "point", "coef", "source", "carried")} | {"moving": g["ids"]}
                   for g in sw.groups],
        "drivers": plan["drivers"],
        "step": step, "samples": samples, "collisions": collisions, "ends": ends,
        "at_cad_pose": {"collides": rest_hit, **rest_info},
        "riding": [{"moving": a, "other": b, "overlap_at_cad_pose": sw.base_overlap[(a, b)]} for a, b in sw.riding],
        "tracked": [{"moving": a, "other": b, "overlap_at_cad_pose": round(sw.base_overlap[(a, b)], 4)} for a, b in sw.tracked],
        "skipped": [{"moving": a, "other": b} for a, b in sw.skipped],
        "min_clearance": None if mn is None else {"distance": samples[mn]["min_distance"], "q": samples[mn]["q"],
                                                  "pair": samples[mn]["pair"]},
        "seconds": round(time.time() - t0, 2),
        "method": (f"exact BRepExtrema minimum distance between every moved part and every part it was apart from, "
                   f"every {math.degrees(step) if hinge else step:.4g}{unit} from the CAD pose to each limit; collisions "
                   f"refined by bisection to {REFINE_DEG if hinge else 0.005}{unit}; parts touching at the CAD pose tracked "
                   "by BRepAlgoAPI_Common volume (growth > 0.01 mm³ = collision); contacts that are surfaces of revolution "
                   "about the axis listed as riding, their overlap measured at the limits; coupled joints moved by their "
                   "coupling; every other joint held at the CAD pose"),
    }
