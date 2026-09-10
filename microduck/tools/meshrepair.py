"""Repair the Onshape-exported STLs into closed, orientable solids.

The simulator meshes are decimated exports: a handful of triangles were dropped,
leaving open boundary loops (53 edges on trunk_base, 150 on xl330, ...).
trimesh.repair.fill_holes only closes 3- and 4-vertex holes, so we walk the
directed boundary half-edges into loops ourselves and triangulate each loop in
its own best-fit plane. That is exact where it applies and never touches the
original triangulation.

MeshFix is kept only as a last resort and is rejected unless it preserves the
part: it is a "close it at any cost" tool and will happily collapse a servo body
from 15 826 mm3 to 4 109 mm3.
"""
from __future__ import annotations

import numpy as np
import trimesh
from trimesh.grouping import group_rows


def _directed_boundary_edges(mesh: trimesh.Trimesh) -> list[tuple[int, int]]:
    """Half-edges with no opposite twin, in their face's winding order."""
    faces = mesh.faces
    he = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    keys = {(int(a), int(b)) for a, b in he}
    return [(int(a), int(b)) for a, b in he if (int(b), int(a)) not in keys]


def _loops(edges: list[tuple[int, int]], verts: np.ndarray) -> list[list[int]]:
    """Chain directed boundary edges into closed loops.

    A vertex can carry several outgoing boundary edges when two holes touch at a
    corner. Picking one arbitrarily welds the two holes into a single loop whose
    triangulation then overlaps the mesh, so at a fork we take the successor that
    turns the least - the loop that hugs the same hole.
    """
    succ: dict[int, list[int]] = {}
    for a, b in edges:
        succ.setdefault(a, []).append(b)

    loops: list[list[int]] = []
    for start in list(succ):
        while succ.get(start):
            loop = [start]
            prev, cur = start, succ[start].pop(0)
            while cur != start:
                loop.append(cur)
                options = succ.get(cur)
                if not options:
                    loop = []
                    break
                if len(options) == 1:
                    nxt = options.pop(0)
                else:
                    incoming = verts[cur] - verts[prev]
                    n = np.linalg.norm(incoming)
                    incoming = incoming / n if n else incoming
                    # smallest turn = tightest hug of the same boundary
                    best = max(range(len(options)), key=lambda i: float(
                        np.dot(incoming, _unit(verts[options[i]] - verts[cur]))))
                    nxt = options.pop(best)
                prev, cur = cur, nxt
                if len(loop) > 5000:
                    loop = []
                    break
            if len(loop) >= 3:
                loops.append(loop)
    return loops


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def _fan_loop(verts: np.ndarray, loop: list[int]):
    """Close a loop with a fan from a new centroid vertex.

    Earcut works in the loop's best-fit plane, which is only right when the loop
    is close to planar; on the curved shells it produces triangles that overlap
    the existing surface and the mesh goes non-manifold instead of closed. A fan
    to the centroid is exact for any simple loop and adds one vertex.
    """
    idx = np.array(loop, dtype=np.int64)
    centre = verts[idx].mean(axis=0)
    c = len(verts)
    faces = np.array([[c, idx[i], idx[(i + 1) % len(idx)]] for i in range(len(idx))],
                     dtype=np.int64)
    return np.vstack([verts, centre]), faces[:, ::-1]


def _fill_loop(verts: np.ndarray, loop: list[int]) -> np.ndarray:
    """Triangulate one boundary loop in its best-fit plane -> (n, 3) faces."""
    idx = np.array(loop, dtype=np.int64)
    pts = verts[idx]
    if len(loop) == 3:
        return idx[None, ::-1]
    centre = pts.mean(axis=0)
    _, _, vh = np.linalg.svd(pts - centre)
    u, v = vh[0], vh[1]
    uv = np.column_stack([(pts - centre) @ u, (pts - centre) @ v])
    try:
        from mapbox_earcut import triangulate_float64
        tri = triangulate_float64(uv, np.array([len(uv)])).reshape(-1, 3)
    except Exception:
        tri = np.array([[0, i, i + 1] for i in range(1, len(loop) - 1)])
    if len(tri) == 0:
        return np.zeros((0, 3), dtype=np.int64)
    # the loop runs along the open boundary, so the patch winds the other way
    return idx[tri][:, ::-1]


def _nonmanifold_count(m: trimesh.Trimesh) -> int:
    return sum(1 for g in group_rows(m.edges_sorted, require_count=None) if len(g) > 2)


def _manifold(m: trimesh.Trimesh) -> bool:
    return _nonmanifold_count(m) == 0


def _split_pinches(loop: list[int]) -> list[list[int]]:
    """Split a boundary loop wherever it revisits a vertex.

    Two holes that meet at a single vertex come back as one loop that passes
    through it twice. Fanning that as a unit produces triangles which share an
    edge with the wrong neighbour, so the patch is non-manifold and gets thrown
    away - which is why `power_support` stayed open with 109 boundary edges.
    Cutting the loop at each repeat gives simple loops that fan cleanly.
    """
    out, stack, seen = [], [], {}
    for v in loop:
        if v in seen:
            start = seen[v]
            piece = stack[start:]
            if len(piece) >= 3:
                out.append(piece)
            for w in stack[start:]:
                seen.pop(w, None)
            del stack[start:]
        seen[v] = len(stack)
        stack.append(v)
    if len(stack) >= 3:
        out.append(stack)
    return out


def _dedup(verts: np.ndarray, faces: np.ndarray) -> trimesh.Trimesh:
    faces = faces[(faces[:, 0] != faces[:, 1]) &
                  (faces[:, 1] != faces[:, 2]) &
                  (faces[:, 0] != faces[:, 2])]
    _, uniq = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
    return trimesh.Trimesh(verts, faces[np.sort(uniq)], process=False)


def _drop_nonmanifold(m: trimesh.Trimesh) -> trimesh.Trimesh:
    """Delete the few faces that meet along a non-manifold edge.

    Two of the shells arrive with an edge shared by three triangles. Nothing
    downstream can close a mesh in that state - the boundary chains do not form
    loops - and the offending faces are a handful out of thousands, so cutting
    them out and letting the hole-filling close the gap costs nothing
    measurable and unblocks everything after it.
    """
    bad = set()
    for g in group_rows(m.edges_sorted, require_count=None):
        if len(g) > 2:
            bad.update(int(i) % len(m.faces) for i in g)
    if not bad:
        return m
    keep = np.array([i for i in range(len(m.faces)) if i not in bad], dtype=np.int64)
    return trimesh.Trimesh(m.vertices, m.faces[keep], process=False)


def repair(mesh: trimesh.Trimesh, weld_tol_mm: float = 1e-4) -> trimesh.Trimesh:
    """Weld, close every boundary loop, drop duplicate faces, fix winding."""
    v = np.asarray(mesh.vertices, dtype=float)
    key = np.round(v / weld_tol_mm).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    m = _dedup(v[first], inv.ravel()[mesh.faces])

    for _ in range(6):
        if m.is_watertight and _manifold(m):
            break
        loops = _loops(_directed_boundary_edges(m), m.vertices)
        if not loops:
            break
        patch = [p for lp in loops for p in [_fill_loop(m.vertices, lp)] if len(p)]
        if not patch:
            break
        cand = _dedup(m.vertices, np.vstack([m.faces] + patch))
        if not _manifold(cand):
            break
        m = cand

    # Loops the planar fill could not take - non-planar, or its patch would have
    # gone non-manifold - are closed with a centroid fan instead. Cutting out
    # non-manifold faces and filling have to alternate: each fill can expose a
    # new bad edge, and each cut opens a new hole, so doing either once leaves
    # a couple of dangling boundary edges that never form a loop.
    for _ in range(8):
        if m.is_watertight and _manifold(m):
            break
        if not _manifold(m):
            cleaned = _drop_nonmanifold(m)
            if len(cleaned.faces) < len(m.faces):
                m = cleaned
        loops = _loops(_directed_boundary_edges(m), m.vertices)
        if not loops:
            break
        progressed = False
        for raw_loop in loops:
            for lp in _split_pinches(raw_loop):
                verts, faces = _fan_loop(m.vertices, lp)
                cand = _dedup(verts, np.vstack([m.faces, faces]))
                # The test is whether this patch made things worse, not whether
                # the whole mesh is manifold: two of these shells arrive with a
                # non-manifold edge of their own, and demanding global
                # manifoldness rejected every fan for an unrelated reason.
                if _nonmanifold_count(cand) <= _nonmanifold_count(m):
                    m = cand
                    progressed = True
        if not progressed:
            break

    if not (m.is_watertight and _manifold(m)):
        m = _meshfix(m)

    m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    if m.is_watertight and m.volume < 0:
        m.invert()
    return m


#: MeshFix is judged mainly on the bounding box, which is exact and cheap to
#: compare. On the six shells it was tried against it split the good results
#: from the destructive ones without ambiguity - 0.00, 0.00 and 0.08 mm against
#: 1.0, 34.4 and 65.3 mm. The volume band only has to catch gross collapse,
#: and it is deliberately loose because the reference for an open mesh is
#: itself an estimate.
MESHFIX_MAX_BBOX_MM = 0.1
MESHFIX_MAX_VOLUME_DRIFT = 0.10


def _meshfix(m: trimesh.Trimesh) -> trimesh.Trimesh:
    """Last resort. Rejected unless it leaves the part's size and bulk intact."""
    try:
        import pymeshfix
    except ImportError:
        return m
    fix = pymeshfix.MeshFix(np.asarray(m.vertices, dtype=float),
                            np.asarray(m.faces, dtype=np.int32))
    fix.repair(joincomp=False, remove_smallest_components=False)
    out = trimesh.Trimesh(np.asarray(fix.points), np.asarray(fix.faces),
                          process=False)
    if not (out.is_watertight and len(out.faces)):
        return m
    before, after = np.sort(m.extents), np.sort(out.extents)
    if np.max(np.abs(before - after)) > MESHFIX_MAX_BBOX_MM:
        return m
    ref = abs(m.volume) if m.is_watertight else _shell_volume(m)
    if ref > 0 and abs(abs(out.volume) - ref) / ref > MESHFIX_MAX_VOLUME_DRIFT:
        return m
    trimesh.repair.fix_normals(out)
    return out


def _shell_volume(m: trimesh.Trimesh) -> float:
    """Divergence-theorem volume; valid enough on a nearly closed shell."""
    tri = m.vertices[m.faces]
    return float(abs(np.einsum('ij,ij->i',
                               tri[:, 0],
                               np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0))


def load_mm(path) -> trimesh.Trimesh:
    """Load an STL (metres) as a repaired millimetre solid."""
    m = trimesh.load(path, process=False)
    m.apply_scale(1000.0)
    return repair(m)


if __name__ == "__main__":
    import glob
    from pathlib import Path

    ok, bad = 0, []
    print(f"{'part':40s} {'faces':>6s} {'tight':>5s} {'bod':>3s} {'vol_mm3':>10s} "
          f"{'dvol%':>7s} {'dbbox':>7s}")
    for f in sorted(glob.glob(str(Path(__file__).parent.parent / "source/meshes/*.stl"))):
        raw = trimesh.load(f, process=False)
        raw.apply_scale(1000.0)
        m = repair(raw)
        ref = _shell_volume(raw)
        dv = 100 * (abs(m.volume) - ref) / ref if ref else 0.0
        db = float(np.max(np.abs(np.sort(m.extents) - np.sort(raw.extents))))
        good = m.is_watertight and m.volume > 0 and abs(dv) < 2.0 and db < 0.05
        ok += good
        if not good:
            bad.append(Path(f).stem)
        print(f"{Path(f).stem:40s} {len(m.faces):6d} {str(m.is_watertight):>5s} "
              f"{m.body_count:3d} {m.volume:10.1f} {dv:7.2f} {db:7.3f}")
    print(f"\nfaithful solids: {ok}/43   needing another route: {bad}")
