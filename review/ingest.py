"""Uploaded files -> classified, hashed sources; STEP -> Model Graph + viewer GLB.

Classification is by extension *and* content: a ``.xml`` is MJCF only if it
opens with ``<mujoco``, a ``.md`` is a BOM only if it holds a table with a
quantity column. The user can correct every classification before a run, so
this only has to be a good first guess — but it must never silently drop a
file: anything unrecognised is kept as ``other``.

Geometry is read by :func:`interface_check.ingest_step.read_assembly` (XCAF:
names, tree, placements; repairs reported as findings) and summarised here
into the graph. The GLB holds one mesh per *part* and one node per
*instance*, the node named by the instance id, so the viewer can pick and
highlight copies individually without shipping each copy's triangles.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Iterable

import numpy as np

from .schema import Bbox, Instance, ModelGraph, Part, SourceFile, Stats, TreeNode

STEP_EXT = {".step", ".stp", ".p21"}
BOM_EXT = {".csv", ".tsv", ".xlsx", ".xls"}
MESH_EXT = {".stl", ".obj", ".glb", ".gltf", ".3mf"}
_QTY = re.compile(r"\b(qty|quantity|q'?ty|pcs|count)\b", re.I)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(name: str, head: bytes) -> str:
    """Best guess at what a file is, from its name and its first bytes."""
    ext = Path(name).suffix.lower()
    text = head[:4096].decode("utf-8", "ignore")
    low = text.lower()
    if ext in STEP_EXT or text.lstrip().startswith("ISO-10303-21"):
        return "step"
    if ext == ".pdf" or head.startswith(b"%PDF"):
        return "pdf"
    if ext in (".urdf", ".xacro"):
        return "urdf"
    if ext in (".xml", ".mjcf"):
        if "<mujoco" in low:
            return "mjcf"
        if "<robot" in low:
            return "urdf"
        return "other"
    if ext in BOM_EXT:
        return "bom"
    if ext in (".md", ".txt") and "|" in text and _QTY.search(text):
        return "bom"
    if ext in MESH_EXT:
        return "mesh"
    return "other"


def expand_zip(data: bytes) -> Iterable[tuple[str, bytes]]:
    """Members of an uploaded archive, skipping folders, macOS litter and path tricks."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir() or name.startswith("__MACOSX/") or Path(name).name.startswith("."):
                continue
            safe = "/".join(p for p in Path(name).parts if p not in ("..", "/", "\\") and not p.endswith(":"))
            if safe:
                yield safe, z.read(info)


# ---------------------------------------------------------------- geometry --

def _bbox(shape) -> Bbox:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    if b.IsVoid():
        return Bbox(min=[0, 0, 0], max=[0, 0, 0])
    x0, y0, z0, x1, y1, z1 = b.Get()
    return Bbox(min=[x0, y0, z0], max=[x1, y1, z1])


def _moved_bbox(T: np.ndarray, b: Bbox) -> Bbox:
    c = np.array([[x, y, z] for x in (b.min[0], b.max[0]) for y in (b.min[1], b.max[1]) for z in (b.min[2], b.max[2])])
    m = c @ T[:3, :3].T + T[:3, 3]
    return Bbox(min=m.min(axis=0).tolist(), max=m.max(axis=0).tolist())


def _sig_hash(sig: dict) -> str:
    key = f"{sig['volume']:.1f}|{sig['area']:.1f}|" + ",".join(f"{s:.2f}" for s in sig["bbox"])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _round(v, nd=4):
    return [round(float(x), nd) for x in v]


def _tree(root_name: str, instances: list[Instance]) -> tuple[TreeNode, int, int]:
    """Nested tree from instance paths; returns (root, assembly count, max depth)."""
    root = TreeNode(key="", name=root_name)
    index = {"": root}
    depth = 0
    for inst in instances:
        parts = inst.path.split("/")
        depth = max(depth, len(parts))
        key = ""
        node = root
        for seg in parts[:-1]:
            key = f"{key}/{seg}" if key else seg
            if key not in index:
                child = TreeNode(key=key, name=seg)
                node.children.append(child)
                index[key] = child
            node = index[key]
        inst.parent = key or None
        node.children.append(TreeNode(key=inst.path, name=inst.name, instance=inst.id))
    # one top-level assembly holding everything is the usual export; make it the root
    if len(root.children) == 1 and root.children[0].instance is None:
        only = root.children[0]
        root = TreeNode(key=only.key, name=only.name, children=only.children)
    return root, len(index) - 1, depth


def build_graph(step_path: str | Path, revision_id: str, files: list[SourceFile] | None = None,
                glb_path: str | Path | None = None, progress=None, analyse: bool = True) -> ModelGraph:
    """Read a STEP assembly into a Model Graph (features and contacts too when ``analyse``),
    and optionally write the viewer GLB."""
    from interface_check.ingest_step import read_assembly, signature
    from interface_check.features import extract, faces, volume_props

    step_path = Path(step_path)
    say = progress or (lambda *_: None)
    say("parse", "reading STEP (XCAF)")
    ic_parts, ic_instances, notes = read_assembly(step_path)
    extra_notes: list[str] = []
    if any(f.rule_id == "ASSEMBLY_STRUCTURE_MISSING" for f in notes):
        from .flat import realign
        extra_notes = realign(ic_parts, ic_instances)

    pid_of: dict[str, str] = {}
    parts: list[Part] = []
    for n, (key, p) in enumerate(sorted(ic_parts.items(), key=lambda kv: kv[1].name.lower()), start=1):
        pid = f"p{n:03d}"
        pid_of[key] = pid
        sig = p.signature or signature(p.shape)
        try:
            com, _ = volume_props(p.shape)
        except Exception:  # noqa: BLE001 - a broken solid still gets a row
            com = np.zeros(3)
        parts.append(Part(
            id=pid, name=p.name or pid, hash=_sig_hash(sig), volume=round(sig["volume"], 3),
            area=round(sig["area"], 3), bbox=_bbox(p.shape), com=_round(com), valid=p.valid,
            problems=list(p.problems), face_count=sum(1 for _ in faces(p.shape))))

    by_pid = {p.id: p for p in parts}
    instances: list[Instance] = []
    for n, inst in enumerate(ic_instances, start=1):
        pid = pid_of[inst.part_id]
        T = np.asarray(inst.transform, dtype=float)
        instances.append(Instance(
            id=f"i{n:04d}", part_id=pid, path=inst.path, name=inst.name,
            transform=[_round(r, 6) for r in T.tolist()], bbox=_moved_bbox(T, by_pid[pid].bbox)))

    root_name = step_path.stem
    tree, n_asm, depth = _tree(root_name, instances)
    flat = any(f.rule_id == "ASSEMBLY_STRUCTURE_MISSING" for f in notes)
    source = next((f for f in (files or []) if f.name == step_path.name), None) or SourceFile(
        name=step_path.name, kind="step", sha256=sha256_file(step_path), size=step_path.stat().st_size)

    graph = ModelGraph(
        revision_id=revision_id, source=source, files=files or [source],
        stats=Stats(parts=len(parts), instances=len(instances), assemblies=n_asm, max_depth=depth, flat=flat),
        parts=parts, instances=instances, tree=tree,
        ingest_notes=[f"{f.rule_id}: {f.message}" for f in notes] + extra_notes)

    if analyse:
        from .geometry import contacts, part_features

        say("features", f"holes, cylinders and patterns on {len(parts)} parts")
        ic_feats = {}
        for key, p in ic_parts.items():
            f = extract(p.shape)
            ic_feats[key] = f
            pf = part_features(pid_of[key], p.shape, f)
            graph.features.extend(pf.features)
            part = by_pid[pid_of[key]]
            part.features = [x["id"] for x in pf.features]
            part.plane_count = pf.plane_count
            if f.is_mesh:
                part.geometry_type = "MESH"
        say("contacts", f"touching pairs among {len(instances)} instances")
        iid_of = {ic.instance_id: g.id for ic, g in zip(ic_instances, instances)}
        placed = {ic.instance_id: ic_feats[ic.part_id].moved(np.asarray(ic.transform, float), ic.loc)
                  for ic in ic_instances}
        cstats: dict = {}
        near: list = []
        graph.contacts = contacts(ic_instances, placed, iid_of, cstats, near=near)
        graph.clearances = near
        graph.stats.contacts = len(graph.contacts)
        graph.stats.features = len(graph.features)

    if glb_path is not None:
        say("mesh", "tessellating parts for the viewer")
        tris = write_glb({pid_of[k]: p.shape for k, p in ic_parts.items()}, instances, glb_path, by_pid)
        graph.stats.triangles = sum(tris.values())
        for p in parts:
            p.triangle_count = tris.get(p.id, 0)
    return graph


def _tolerance(b: Bbox) -> float:
    diag = float(np.linalg.norm(np.subtract(b.max, b.min)))
    return min(0.5, max(0.02, diag * 0.002))


def write_glb(shapes: dict, instances: list[Instance], path: str | Path, parts: dict[str, Part]) -> dict[str, int]:
    """One mesh per part (part coordinates), one node per instance named by its id. Metres, Y-up untouched."""
    import trimesh
    from interface_check.report import tessellate

    scene = trimesh.Scene()
    meshes: dict[str, trimesh.Trimesh] = {}
    tri_count: dict[str, int] = {}
    for pid, shape in shapes.items():
        v, t = tessellate(shape, _tolerance(parts[pid].bbox))
        if not len(t):
            continue
        meshes[pid] = trimesh.Trimesh(np.asarray(v) / 1000.0, np.asarray(t), process=False)
        tri_count[pid] = len(t)
    for inst in instances:
        mesh = meshes.get(inst.part_id)
        if mesh is None:
            continue
        T = np.array(inst.transform, dtype=float)
        T[:3, 3] /= 1000.0
        if inst.part_id in scene.geometry:
            scene.graph.update(frame_from=scene.graph.base_frame, frame_to=inst.id, matrix=T,
                               geometry=inst.part_id)
        else:
            scene.add_geometry(mesh, geom_name=inst.part_id, node_name=inst.id, transform=T)
    if not scene.geometry:
        raise ValueError("nothing could be tessellated for the 3D view")
    Path(path).write_bytes(scene.export(file_type="glb"))
    return tri_count
