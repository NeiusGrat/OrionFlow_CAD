"""Recover the placements a flattened STEP threw away.

A "save as one body" export holds every solid already moved into place, with
no assembly tree. interface_check folds identical solids into one part (so
eight bolts are one part with quantity 8) but each copy keeps an identity
transform: its position lives in its geometry. Everything downstream that
places a part by its transform — the viewer's instancing, placed features,
contact typing, duplicate detection — would then put all eight bolts where
the first one is.

This module finds, for each copy, the rigid transform that carries the
part's geometry onto the copy's: principal axes of inertia give the
candidates (four sign choices, plus a sweep about any axis of symmetry), and
a candidate is accepted only if every vertex of the part lands on a vertex
of the copy within ``TOL`` mm. A copy no candidate explains is split back
into its own part rather than guessed.
"""
from __future__ import annotations

import numpy as np

TOL = 0.01          # mm, vertex match
MAX_VERTS = 400


def _vertices(shape) -> np.ndarray:
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    pts = []
    ex = TopExp_Explorer(shape, TopAbs_VERTEX)
    while ex.More():
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(ex.Current()))
        pts.append((p.X(), p.Y(), p.Z()))
        ex.Next()
    v = np.unique(np.round(np.array(pts, float).reshape(-1, 3), 6), axis=0)
    return v


def _frame(shape):
    from interface_check.features import volume_props
    com, inertia = volume_props(shape)
    w, V = np.linalg.eigh((inertia + inertia.T) / 2)
    return np.asarray(com, float), w, V


def _rot(axis: np.ndarray, a: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def align(src, dst) -> np.ndarray | None:
    """4x4 (mm) carrying shape ``src`` onto shape ``dst``, verified on vertices; None if none fits."""
    from scipy.spatial import cKDTree

    vs, vd = _vertices(src), _vertices(dst)
    if len(vs) != len(vd) or not len(vs):
        return None
    tree = cKDTree(vd)
    sample = vs if len(vs) <= MAX_VERTS else vs[np.linspace(0, len(vs) - 1, MAX_VERTS).astype(int)]
    cs, ws, Vs = _frame(src)
    cd, wd, Vd = _frame(dst)
    scale = max(float(np.max(np.abs(ws))), 1e-12)

    def ok(R: np.ndarray) -> np.ndarray | None:
        t = cd - R @ cs
        d, _ = tree.query(sample @ R.T + t)
        if float(np.max(d)) <= TOL:
            T = np.eye(4)
            T[:3, :3], T[:3, 3] = R, t
            return T
        return None

    base = []
    for s in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)):
        R = Vd @ np.diag(s) @ Vs.T
        if np.linalg.det(R) < 0:
            R = Vd @ np.diag((-s[0], -s[1], -s[2])) @ Vs.T
        base.append(R)
    for R in base:
        T = ok(R)
        if T is not None:
            return T
    # an axis of symmetry (two equal moments) leaves the rotation about it free: sweep it
    gaps = np.abs(np.diff(wd)) / scale
    for k in np.where(gaps < 1e-3)[0]:
        axis = Vd[:, 2 if k == 0 else 0]           # the eigenvector outside the degenerate pair
        for R0 in base:
            for a in np.linspace(0, 2 * np.pi, 720, endpoint=False):
                T = ok(_rot(axis, a) @ R0)
                if T is not None:
                    return T
    return None


def _is_mirror(src, dst) -> bool:
    """True when ``dst`` is ``src`` reflected (an L/R pair): same shape, opposite handedness."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf

    m = gp_Trsf()
    m.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)))
    try:
        reflected = BRepBuilderAPI_Transform(src, m, True).Shape()
    except Exception:  # noqa: BLE001
        return False
    return align(reflected, dst) is not None


def _set_transform(inst, T: np.ndarray) -> None:
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetValues(*[float(v) for v in T[:3, :].ravel()])
    inst.transform = T
    inst.loc = TopLoc_Location(trsf)


def _merge_rotated(parts: dict, instances: list) -> int:
    """Fold parts that are rotated copies of each other into one part.

    interface_check groups identical solids by volume, area and *axis-aligned*
    envelope; a copy turned by an arbitrary angle has a different envelope and
    stays a separate part, so its quantity is miscounted. Volume and area do not
    change under rotation: parts that share them are candidates, and a merge
    happens only when the vertex alignment proves one is the other moved.
    Returns how many instances were re-placed.
    """
    def close(a, b, rel=1e-6):
        return abs(a - b) <= rel * max(abs(a), abs(b), 1e-9)

    moved = 0
    pids = list(parts)
    gone: set[str] = set()
    for i, lead in enumerate(pids):
        if lead in gone:
            continue
        sl = parts[lead].signature
        for other in pids[i + 1:]:
            if other in gone:
                continue
            so = parts[other].signature
            if not (close(sl["volume"], so["volume"]) and close(sl["area"], so["area"], 1e-5)):
                continue
            T = align(parts[lead].shape, parts[other].shape)
            if T is None:
                continue
            # other's part frame is the assembly frame (flat file): each of its instances sits at T . (own transform)
            for inst in instances:
                if inst.part_id == other:
                    _set_transform(inst, np.asarray(inst.transform, float) @ T)
                    inst.part_id = lead
                    moved += 1
            gone.add(other)
    for pid in gone:
        del parts[pid]
    return moved


def realign(parts: dict, instances: list) -> list[str]:
    """Give every merged copy in a flattened file its real transform; split copies that do not fit.

    Mutates interface_check Parts/Instances in place. Returns notes for the graph.
    """
    from interface_check.ingest_step import signature
    from interface_check.models import Part as ICPart

    notes: list[str] = []
    lead_shape = {pid: p.shape for pid, p in parts.items()}
    lead_inst = {}
    for inst in instances:
        lead_inst.setdefault(inst.part_id, inst)
    split = 0
    aligned = 0
    mirrors = 0
    for inst in instances:
        if lead_inst[inst.part_id] is inst:
            continue                                    # the part's own body: identity is right
        T = align(lead_shape[inst.part_id], inst.shape)
        if T is None:
            pid = f"{inst.part_id}_split{split + 1}"
            split += 1
            mirror = _is_mirror(lead_shape[inst.part_id], inst.shape)
            mirrors += int(mirror)
            label = f"{parts[inst.part_id].name}_mirror" if mirror else f"{parts[inst.part_id].name}_{split}"
            parts[pid] = ICPart(pid, label, inst.shape)
            parts[pid].signature = signature(inst.shape)
            inst.part_id = pid
            continue
        _set_transform(inst, T)
        aligned += 1
    merged = _merge_rotated(parts, instances)
    aligned += merged
    if aligned or split:
        notes.append(f"FLAT_PLACEMENTS_RECOVERED: {aligned} copies placed by aligning their geometry to their part "
                     f"(every vertex within {TOL} mm)" + (f"; {split} copies did not fit and became their own parts" if split else "")
                     + (f" ({mirrors} of them are mirror images)" if mirrors else ""))
    return notes
