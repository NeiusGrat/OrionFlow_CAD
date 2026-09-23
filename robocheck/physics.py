"""Checks on the compiled model: mass against geometry, overlap, settling.

These run on what MuJoCo actually simulates, for URDF and MJCF alike.
"""
from __future__ import annotations

import math

import mujoco
import numpy as np
import trimesh

from .findings import Report

#: Plausible bulk densities, kg/m^3. Below expanded foam or above osmium
#: means the mass or the geometry is in the wrong units, or is a placeholder.
DENSITY_MIN = 30.0
DENSITY_MAX = 22_600.0

#: Declared inertia against the inertia of the body's own geometry at the
#: same mass. A factor of ten either way is beyond any hollowing or material
#: mix; a factor near 1e6 is millimetres read as metres.
INERTIA_RATIO_WARN = 10.0

#: Contacts deeper than this at rest, between bodies that are not parent and
#: child, are parts occupying the same space.
PENETRATION_M = 1e-3

SETTLE_S = 2.0
QVEL_LIMIT = 100.0      # rad/s or m/s: nothing settling under gravity moves this fast


def _body_name(m: mujoco.MjModel, b: int) -> str:
    return mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or f"body#{b}"


def _geom_mesh(m: mujoco.MjModel, g: int) -> trimesh.Trimesh | None:
    """A geom as a mesh in its body's frame."""
    t = m.geom_type[g]
    s = m.geom_size[g]
    G = mujoco.mjtGeom
    if t == G.mjGEOM_MESH:
        mid = m.geom_dataid[g]
        va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
        mesh = trimesh.Trimesh(m.mesh_vert[va:va + vn].copy(), m.mesh_face[fa:fa + fn].copy(), process=False)
    elif t == G.mjGEOM_BOX:
        mesh = trimesh.creation.box(extents=2 * s[:3])
    elif t == G.mjGEOM_SPHERE:
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=s[0])
    elif t == G.mjGEOM_CYLINDER:
        mesh = trimesh.creation.cylinder(radius=s[0], height=2 * s[1])
    elif t == G.mjGEOM_CAPSULE:
        mesh = trimesh.creation.capsule(radius=s[0], height=2 * s[1])
    elif t == G.mjGEOM_ELLIPSOID:
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        mesh.apply_scale(s[:3])
    else:
        return None
    T = np.eye(4)
    q = m.geom_quat[g]
    R = np.zeros(9)
    mujoco.mju_quat2Mat(R, q)
    T[:3, :3] = R.reshape(3, 3)
    T[:3, 3] = m.geom_pos[g]
    mesh.apply_transform(T)
    return mesh


def _shape_geoms(m: mujoco.MjModel, b: int) -> tuple[list[int], list[int]]:
    """(geoms that describe the body's shape, all of its geoms).

    Collision geometry is often a proxy - a cylinder standing in for a hip
    casting, a sphere for a foot - so the shape is read from the visual
    geoms when the model has them, and from the collision geoms otherwise.
    """
    gs = [g for g in range(m.ngeom)
          if m.geom_bodyid[g] == b and m.geom_type[g] != mujoco.mjtGeom.mjGEOM_PLANE]
    visual = [g for g in gs if not (m.geom_contype[g] or m.geom_conaffinity[g])]
    return (visual or gs), gs


def check_mass_against_geometry(m: mujoco.MjModel, report: Report,
                                shapes: dict[str, trimesh.Trimesh] | None = None) -> None:
    """Density and inertia of every moving body, against its own geometry.

    `shapes` supplies a body's true shape when the compiled model only holds
    collision proxies (a URDF's visual meshes); otherwise the model's own
    visual geoms are used, and its collision geoms when it has no others.
    """
    shapes = shapes or {}
    checked = 0
    skipped = []
    for b in range(1, m.nbody):
        try:
            checked += _check_body(m, b, report, shapes)
        except Exception as exc:        # degenerate geometry: skip the body, not the model
            skipped.append(f"{_body_name(m, b)} ({type(exc).__name__})")
    if skipped:
        report.add("PHYS013", "info", f"{len(skipped)} bodies skipped, geometry unusable: {skipped[:5]}")
    report.stats["bodies_checked_against_geometry"] = checked


def _check_body(m: mujoco.MjModel, b: int, report: Report, shapes: dict) -> int:
    """Check one body; returns 1 if it was compared against geometry."""
    if m.body_dofnum[b] == 0 and m.body_weldid[b] == 0:
        return 0   # welded to the world: never moves, mass is irrelevant
    mass = float(m.body_mass[b])
    name = _body_name(m, b)
    shape_ids, all_ids = _shape_geoms(m, b)
    meshes = [x for x in (_geom_mesh(m, g) for g in shape_ids) if x is not None and len(x.faces)]
    every = [x for x in (_geom_mesh(m, g) for g in all_ids) if x is not None and len(x.faces)]
    if name in shapes:
        meshes = [shapes[name]]
        every = every + [shapes[name]]
    if not meshes:
        return 0
    geo = trimesh.util.concatenate(meshes)
    extent = trimesh.util.concatenate(every)
    solid = geo if geo.is_volume else geo.convex_hull
    vol = float(abs(solid.volume))
    if vol < 1e-12 or mass <= 0:
        return 0
    density = mass / vol
    if density < DENSITY_MIN or density > DENSITY_MAX:
        report.add("PHYS010", "warning",
                   f"mass {mass:.4g} kg over {vol * 1e6:.4g} cm^3 of geometry is {density:.4g} kg/m^3 "
                   f"(plausible {DENSITY_MIN:g}-{DENSITY_MAX:g})", where=f"body {name}", value=density)
    # Declared principal inertia vs the geometry's, scaled to this mass.
    solid.density = mass / vol
    I_geo = np.sort(np.linalg.eigvalsh(solid.moment_inertia))
    I_dec = np.sort(np.asarray(m.body_inertia[b], dtype=float))
    if I_geo.sum() <= 0 or I_dec.sum() <= 0:
        return 1
    ratio = I_dec.sum() / I_geo.sum()
    if ratio > INERTIA_RATIO_WARN or ratio < 1 / INERTIA_RATIO_WARN:
        hint = ""
        if 1e5 < ratio < 1e7 or 1e-7 < ratio < 1e-5:
            hint = " (a factor of ~1e6: millimetre-squared read as metre-squared?)"
        report.add("PHYS011", "warning",
                   f"declared inertia is {ratio:.3g}x what its geometry gives at this mass{hint}",
                   where=f"body {name}", value=ratio)
    # centre of mass should be inside, or near, the body's geometry
    lo, hi = extent.bounds
    pad = 0.1 * float(np.max(hi - lo))
    com = np.asarray(m.body_ipos[b])
    if np.any(com < lo - pad) or np.any(com > hi + pad):
        report.add("PHYS012", "warning", "centre of mass lies outside the body's geometry",
                   where=f"body {name}", value=com.round(4).tolist())
    return 1


def rest_state(m: mujoco.MjModel) -> tuple[mujoco.MjData, str]:
    """Data at the model's rest pose: its first keyframe if it has one."""
    d = mujoco.MjData(m)
    if m.nkey:
        mujoco.mj_resetDataKeyframe(m, d, 0)
        label = f"keyframe {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_KEY, 0) or 0}"
    else:
        label = "qpos0"
    mujoco.mj_forward(m, d)
    return d, label


def check_rest_overlap(m: mujoco.MjModel, report: Report, floor_geom: int = -1) -> None:
    d, label = rest_state(m)
    pairs: dict[tuple[str, str], float] = {}
    for i in range(d.ncon):
        c = d.contact[i]
        if floor_geom >= 0 and floor_geom in (c.geom1, c.geom2):
            continue
        if c.dist >= -PENETRATION_M:
            continue
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        key = tuple(sorted((_body_name(m, b1), _body_name(m, b2))))
        adjacent = m.body_parentid[b1] == b2 or m.body_parentid[b2] == b1
        depth = max(pairs.get(key, (0.0, False))[0], -float(c.dist))
        pairs[key] = (depth, adjacent)
    for (a, b), (depth, adjacent) in sorted(pairs.items(), key=lambda kv: -kv[1][0]):
        why = ""
        if adjacent:
            # MuJoCo filters parent-child contact, except when the parent is
            # welded to the world - the usual case for an arm's base.
            why = ("; they are parent and child, but the parent is fixed to the world so MuJoCo "
                   "does not filter the contact - exclude the pair or trim the collision geometry")
        report.add("PHYS020", "warning",
                   f"{a} and {b} interpenetrate by {depth * 1000:.1f} mm at rest ({label}){why}",
                   where=f"{a} / {b}", value=depth)
    report.stats["rest_overlaps"] = len(pairs)


def lowest_point(m: mujoco.MjModel, d: mujoco.MjData) -> float:
    """Lowest z of any geom's bounding box at the current state."""
    z = math.inf
    for g in range(m.ngeom):
        if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE:
            continue
        c, h = m.geom_aabb[g][:3], m.geom_aabb[g][3:]
        R = d.geom_xmat[g].reshape(3, 3)
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * h + c
        z = min(z, float((corners @ R.T + d.geom_xpos[g])[:, 2].min()))
    return z


def check_settle(m: mujoco.MjModel, report: Report, floating: bool) -> None:
    """Let it fall and settle; it must not diverge or fly apart."""
    d, _ = rest_state(m)
    if m.nkey and m.nu and m.key_ctrl.size:
        d.ctrl[:] = m.key_ctrl[0]
    steps = int(SETTLE_S / m.opt.timestep)
    peak = 0.0
    for i in range(steps):
        mujoco.mj_step(m, d)
        if not (np.all(np.isfinite(d.qpos)) and np.all(np.isfinite(d.qvel))):
            report.add("PHYS030", "error", f"simulation diverged (NaN/inf) after {i * m.opt.timestep:.3f} s")
            return
        peak = max(peak, float(np.abs(d.qvel).max()) if m.nv else 0.0)
    bad = int(d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number)
    if bad:
        report.add("PHYS031", "error", f"MuJoCo reported {bad} bad accelerations while settling")
    if peak > QVEL_LIMIT:
        hint = (" - the parts overlapping at rest are pushing each other apart"
                if report.stats.get("rest_overlaps") else "")
        report.add("PHYS032", "warning", f"peak joint speed {peak:.3g} while settling under gravity{hint}",
                   value=peak)
    if floating:
        # the robot's own geoms only - the floor this checker added is on the world body
        robot = m.geom_bodyid > 0
        collidable = bool(np.any((m.geom_contype[robot] | m.geom_conaffinity[robot]) != 0)) or m.npair > 0
        if not collidable:
            # Nothing on it can touch anything: it falls through any floor.
            # Menagerie's Apollo is like this - the robot file relies on
            # contact pairs its scene file adds.
            report.add("PHYS034", "warning",
                       "no geom can collide (every contype and conaffinity is 0, no contact pairs): "
                       "on its own this model cannot stand on anything")
            report.stats.update(settle_s=SETTLE_S, settle_peak_qvel=round(peak, 3))
            return
        root_z = float(d.xpos[1][2]) if m.nbody > 1 else 0.0
        if root_z < -0.5:
            report.add("PHYS033", "error", f"floating base fell through the floor (z = {root_z:.2f} m)")
    report.stats.update(settle_s=SETTLE_S, settle_peak_qvel=round(peak, 3))
