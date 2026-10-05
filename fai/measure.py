"""Measure a STEP part: the nominal sizes a drawing could be checked against.

    holes / bosses   closed cylinders (merged split halves), diameter, axis, count
    arcs             partial cylinders: fillet and corner radii
    planes           planar faces grouped by normal line and offset
    candidates       every linear value the model can show: distances between
                     parallel planes, hole-to-hole spacings, hole-to-face
                     distances, overall extents — each with the faces it uses

Each face group becomes one node of the GLB, named after the group, so the
viewer can light up exactly the geometry a characteristic was matched to.

Units: OpenCASCADE's STEP reader converts to millimetres.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

CLOSED_FRACTION = 0.83


@dataclass
class Cyl:
    id: str
    kind: str                   # hole | boss | arc
    diameter: float
    axis: list[float]
    center: list[float]
    length: float
    faces: list[int] = field(default_factory=list)


@dataclass
class Candidate:
    value: float
    how: str                    # plane_distance | hole_spacing | hole_to_face | extent
    nodes: list[str]
    axis: str = ""


@dataclass
class Measurement:
    source: str
    cylinders: list[Cyl] = field(default_factory=list)
    planes: list[dict] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    extents: list[float] = field(default_factory=list)       # bbox x, y, z
    volume_mm3: float = 0.0
    faces: int = 0
    solids: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["candidates"] = d["candidates"][:400]
        return d


def _canon(d: np.ndarray) -> np.ndarray:
    d = d / (np.linalg.norm(d) or 1.0)
    for v in d:
        if abs(v) > 1e-9:
            return d if v > 0 else -d
    return d


def read_step(path: str | Path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"{Path(path).name}: not a readable STEP file")
    r.TransferRoots()
    shape = r.OneShape()
    if shape is None or shape.IsNull():
        raise ValueError(f"{Path(path).name}: the STEP file contains no shape")
    return shape


def measure(path: str | Path, glb: str | Path | None = None) -> Measurement:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    from interface_check.features import _point_normal, faces
    from interface_check.ingest_step import signature

    shape = read_step(path)
    m = Measurement(source=Path(path).name)
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        m.solids += 1
        exp.Next()
    if m.solids == 0:
        m.warnings.append("no solid body: the file is surfaces only, sizes may be incomplete")
    if m.solids > 1:
        m.warnings.append(f"{m.solids} solids in the file: an assembly or a multi-body part; "
                          "measured as one")
    face_list = list(faces(shape))
    m.faces = len(face_list)

    cyl_groups: dict[tuple, dict] = {}
    plane_groups: dict[tuple, dict] = {}
    for k, f in enumerate(face_list):
        s = BRepAdaptor_Surface(f)
        t = s.GetType()
        if t == GeomAbs_Cylinder:
            c = s.Cylinder()
            loc, d = c.Location(), c.Axis().Direction()
            o, ax = np.array([loc.X(), loc.Y(), loc.Z()]), _canon(np.array([d.X(), d.Y(), d.Z()]))
            p, n = _point_normal(f)
            radial = p - (o + ax * np.dot(p - o, ax))
            concave = bool(np.dot(n, radial) < 0)
            umin, umax, vmin, vmax = BRepTools.UVBounds_s(f)
            foot = o - ax * np.dot(o, ax)
            key = (concave, round(2 * c.Radius(), 3), *np.round(foot, 2), *np.round(ax, 3))
            g = cyl_groups.setdefault(key, {"concave": concave, "dia": 2 * c.Radius(), "foot": foot, "axis": ax,
                                            "turn": 0.0, "a0": math.inf, "a1": -math.inf, "faces": []})
            a0, a1 = sorted((np.dot(o + ax * vmin, ax), np.dot(o + ax * vmax, ax)))
            g["turn"] += umax - umin
            g["a0"], g["a1"] = min(g["a0"], a0), max(g["a1"], a1)
            g["faces"].append(k)
        elif t == GeomAbs_Plane:
            p, n = _point_normal(f)
            line = _canon(n)
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, props)
            key = (*np.round(line, 3), round(float(np.dot(p, line)), 3))
            g = plane_groups.setdefault(key, {"normal": line, "offset": float(np.dot(p, line)), "area": 0.0,
                                              "faces": []})
            g["area"] += props.Mass()
            g["faces"].append(k)

    counters = {"hole": 0, "boss": 0, "arc": 0}
    node_of: dict[int, str] = {}
    for g in cyl_groups.values():
        closed = g["turn"] >= CLOSED_FRACTION * 2 * math.pi
        kind = ("hole" if g["concave"] else "boss") if closed else "arc"
        counters[kind] += 1
        cid = f"{kind[0]}{counters[kind]}"
        center = g["foot"] + g["axis"] * (g["a0"] + g["a1"]) / 2
        m.cylinders.append(Cyl(cid, kind, round(g["dia"], 4), np.round(g["axis"], 4).tolist(),
                               np.round(center, 4).tolist(), round(g["a1"] - g["a0"], 4), g["faces"]))
        for k in g["faces"]:
            node_of[k] = cid
    for i, g in enumerate(sorted(plane_groups.values(), key=lambda g: -g["area"])):
        pid = f"p{i + 1}"
        m.planes.append({"id": pid, "normal": np.round(g["normal"], 4).tolist(), "offset": round(g["offset"], 4),
                         "area": round(g["area"], 2), "faces": g["faces"]})
        for k in g["faces"]:
            node_of[k] = pid

    sig = signature(shape)
    m.volume_mm3 = round(sig.get("volume", 0.0), 2)
    m.extents = _extents(shape)
    m.candidates = _candidates(m)
    if glb:
        _write_glb(face_list, node_of, glb)
    return m


def _extents(shape) -> list[float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b, False)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return [round(x1 - x0, 4), round(y1 - y0, 4), round(z1 - z0, 4)]


def _candidates(m: Measurement) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set = set()

    def add(v: float, how: str, nodes: list[str], axis: str = "") -> None:
        v = round(abs(v), 4)
        key = (v, how, tuple(sorted(nodes)))
        if v > 1e-6 and key not in seen:
            seen.add(key)
            out.append(Candidate(v, how, nodes, axis))

    # parallel planes
    by_line: dict[tuple, list[dict]] = {}
    for p in m.planes:
        by_line.setdefault(tuple(np.round(p["normal"], 3)), []).append(p)
    for line, ps in by_line.items():
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                add(ps[i]["offset"] - ps[j]["offset"], "plane_distance", [ps[i]["id"], ps[j]["id"]], _axis_name(line))
    # hole/boss spacings and hole-to-face, per axis direction
    closed = [c for c in m.cylinders if c.kind in ("hole", "boss")]
    for i in range(len(closed)):
        a = closed[i]
        ca = np.array(a.center)
        for j in range(i + 1, len(closed)):
            b = closed[j]
            if abs(abs(np.dot(a.axis, b.axis)) - 1) > 1e-3:
                continue
            delta = np.array(b.center) - ca
            ax = np.array(a.axis)
            delta -= ax * np.dot(delta, ax)                      # in the plane normal to the axes
            add(float(np.linalg.norm(delta)), "hole_spacing", [a.id, b.id])
            for unit, name in ((np.array([1, 0, 0]), "X"), (np.array([0, 1, 0]), "Y"), (np.array([0, 0, 1]), "Z")):
                if abs(np.dot(unit, ax)) < 1e-6:
                    add(float(np.dot(delta, unit)), "hole_spacing", [a.id, b.id], name)
        for p in m.planes:
            n = np.array(p["normal"])
            if abs(np.dot(n, a.axis)) < 1e-6:                  # plane parallel to the hole axis
                add(float(np.dot(ca, n) - p["offset"]), "hole_to_face", [a.id, p["id"]], _axis_name(tuple(n)))
    for v, name in zip(m.extents, "XYZ"):
        add(v, "extent", [], name)
    return out


def _axis_name(line) -> str:
    v = np.abs(np.array(line, dtype=float))
    i = int(np.argmax(v))
    return "XYZ"[i] if v[i] > 0.999 else ""


def _write_glb(face_list, node_of: dict[int, str], path) -> None:
    import trimesh

    from interface_check.report import tessellate

    groups: dict[str, list] = {}
    for k, f in enumerate(face_list):
        v, t = tessellate(f, 0.1)
        if len(t):
            groups.setdefault(node_of.get(k, "body"), []).append((np.asarray(v), np.asarray(t)))
    scene = trimesh.Scene()
    for name, parts in sorted(groups.items()):
        vs, ts, base = [], [], 0
        for v, t in parts:
            vs.append(v)
            ts.append(t + base)
            base += len(v)
        mesh = trimesh.Trimesh(np.vstack(vs) / 1000.0, np.vstack(ts), process=False)
        scene.add_geometry(mesh, node_name=name, geom_name=name)
    if scene.geometry:
        Path(path).write_bytes(scene.export(file_type="glb"))
