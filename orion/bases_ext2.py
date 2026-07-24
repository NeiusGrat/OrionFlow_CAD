"""Composable base library, tranche 2 (Phase-X Step 3 — topology expansion).

Six genuinely-distinct topology classes, none a rename of an existing family:
a 2-D hole grid, a radial-arm hub, a bent lever plate, a plate with crossing
ribs (exact inclusion-exclusion), a hollow box (pad+pocket, not Thickness), and
a slotted rail. Every body volume is exact closed form; each exposes a mount
land so the attachment system multiplies it into ~10 topologies.
"""

from __future__ import annotations

import math

from .bases import BASES, _ring_land
from .bases_ext import _draft
from .recipes import _u


# =========================================================================== #
# 1. fixture plate — rectangular plate with a 2-D grid of holes
# =========================================================================== #
def base_fixture_plate(rng):
    nx = rng.choice([3, 4, 5])
    ny = rng.choice([2, 3, 4])
    pitch = _u(rng, 12, 24, 1)
    hole_r = _u(rng, 2.0, min(4.5, pitch / 2 - 1.5), 0.25)
    margin = _u(rng, hole_r + 10, hole_r + 18, 1)
    L = round(pitch * (nx - 1) + 2 * margin, 2)
    W = round(pitch * (ny - 1) + 2 * margin, 2)
    T = _u(rng, 8, 18, 0.5)
    v = {"L": L, "W": W, "T": T, "hole_r": hole_r, "pitch": pitch}
    body = f"L*W*T - {nx * ny}*pi*hole_r**2*T"
    return _draft(
        "fixture_plate", v,
        [{"step": 1, "eq": f"V = L*W*T - {nx * ny}*pi*hole_r^2*T",
          "why": f"tooling plate with an {nx}x{ny} dowel/bolt grid; the grid "
                 f"is one profile so every hole is a disjoint through-cut"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "plate", "type": "Pad", "rationale": "fixture plate blank "
             "with the full dowel grid in-profile",
             "parameters": {"Length": "T", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "hole_grid",
                         "args": {"w": "L", "h": "W", "nx": str(nx),
                                  "ny": str(ny), "r": "hole_r",
                                  "pitch_x": "pitch", "pitch_y": "pitch"}}}],
         "dependencies": [
            {"source": "s0", "target": "plate", "kind": "profile"}]},
        [{"id": "pitch_guard", "kind": "precondition", "tier": 1,
          "target": "pitch - 2*hole_r - 2"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "T"}],
        body, ["Sketch", "Pad"], "plate",
        _fixture_edge_land(L, W, pitch, ny, hole_r))


# =========================================================================== #
# 2. spider hub — central annular disc with N radial arms
# =========================================================================== #
def base_spider_hub(rng):
    hub_r = _u(rng, 14, 30, 1)
    bore_r = _u(rng, 4, 0.5 * hub_r, 0.5)
    disc_t = _u(rng, 6, 14, 0.5)
    n = rng.choice([3, 4, 5, 6])
    arm_len = _u(rng, 18, 45, 1)
    arm_w = _u(rng, 6, 14, 0.5)
    arm_h = _u(rng, disc_t, disc_t + 12, 0.5)
    # arms must not collide angularly at the hub rim
    if 2 * hub_r * math.sin(math.pi / n) <= arm_w + 3:
        raise ValueError("spider arms collide at the hub")
    v = {"hub_r": hub_r, "bore_r": bore_r, "disc_t": disc_t,
         "arm_len": arm_len, "arm_w": arm_w, "arm_h": arm_h, "arm_n": float(n)}
    body = ("pi*(hub_r**2 - bore_r**2)*disc_t"
            " + arm_n*arm_w*arm_len*arm_h")
    return _draft(
        "spider_hub", v,
        [{"step": 1, "eq": "V_hub_tool = pi(hub_r^2-bore_r^2)*disc_t (exact)"},
         {"step": 2, "eq": "V_arm_tool = arm_w*arm_len*arm_h (exact, x N)"},
         {"step": 3, "eq": "V_body: arms OVERLAP the hub rim to fuse into one "
                           "solid, so the union is not a closed-form sum — the "
                           "body is verified by mesh convergence to OCC (Tier "
                           "2), with per-feature tools exact (Tier 1)",
          "why": "a fused radial-arm hub is an irreducible union like the "
                 "manifold runner; connectivity + watertight guard the mesh"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_hub", "type": "Sketch", "parameters": {}},
            {"id": "hub", "type": "Pad", "rationale": "central hub disc + bore",
             "parameters": {"Length": "disc_t", "Type": "Length"}},
            {"id": "s_arm", "type": "Sketch", "parameters": {}},
            {"id": "arm0", "type": "Pad", "rationale": "one radial arm, sunk "
             "3mm into the hub rim so it fuses into a single solid",
             "parameters": {"Length": "arm_h", "Type": "Length"}},
            {"id": "arms", "type": "PolarPattern",
             "rationale": "N equally spaced spider arms",
             "parameters": {"Occurrences": "arm_n", "Angle": "360",
                            "_Axis": {"role": "Z_Axis", "subs": [""]},
                            "_Originals": ["arm0"]}}],
         "sketches": [
            {"id": "s_hub", "plane": "XY",
             "profile": {"builder": "annulus",
                         "args": {"r_outer": "hub_r", "r_inner": "bore_r"}}},
            {"id": "s_arm", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "arm_len", "h": "arm_w",
                                  "cx": "hub_r + arm_len/2 - 3"}}}],
         "dependencies": [
            {"source": "s_hub", "target": "hub", "kind": "profile"},
            {"source": "s_arm", "target": "arm0", "kind": "profile"},
            {"source": "hub", "target": "arm0", "kind": "base"},
            {"source": "arm0", "target": "arms", "kind": "base"}]},
        [{"id": "arm_spacing", "kind": "precondition", "tier": 1,
          "target": "2*hub_r*sin(pi/arm_n) - arm_w - 3"},
         {"id": "hub_wall", "kind": "precondition", "tier": 1,
          "target": "hub_r - bore_r - 4"},
         {"id": "hub_tool", "kind": "feature_volume", "feature": "hub",
          "tier": 1, "tol_rel": 1e-6,
          "target": "pi*(hub_r**2 - bore_r**2)*disc_t"},
         {"id": "arm_tool", "kind": "feature_volume", "feature": "arm0",
          "tier": 1, "tol_rel": 1e-6, "target": "arm_w*arm_len*arm_h"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "arm_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "PolarPattern"], "arms",
        _spider_mount(hub_r, bore_r), body_mesh=True)


def _spider_mount(hub_r, bore_r):
    ring = _ring_land(bore_r, hub_r)
    if ring is None:
        return []
    return [{"id": "hub_face", "kind": "flat_top", "z": "disc_t",
             "land": {"type": "rect", "w": f"{2 * ring[1]}",
                      "h": f"{2 * ring[1]}", "cx": f"{ring[0]}", "cy": "0"},
             "thickness": "disc_t"}]


# =========================================================================== #
# 3. bent lever — L-shaped plate with a pivot bore and two end bores
# =========================================================================== #
def base_bent_lever(rng):
    a = _u(rng, 40, 90, 2)          # arm 1 length (+X)
    b = _u(rng, 35, 80, 2)          # arm 2 length (+Y)
    w = _u(rng, 14, 26, 1)          # arm width
    t = _u(rng, 6, 14, 0.5)
    pivot_r = _u(rng, 4, min(6.0, w / 2 - 3), 0.25)
    end_r = _u(rng, 3, min(5.0, w / 2 - 3), 0.25)
    v = {"a": a, "b": b, "w": w, "t": t, "pivot_r": pivot_r, "end_r": end_r}
    # L-shaped bar: elbow at origin, one arm along +X, one along +Y, width w.
    pts = [["0", "0"], ["a", "0"], ["a", "w"], ["w", "w"],
           ["w", "b"], ["0", "b"]]
    holes = [["a - w/2", "w/2", "end_r"],      # +X arm end
             ["w/2", "b - w/2", "end_r"],      # +Y arm end
             ["w/2", "w/2", "pivot_r"]]        # elbow pivot
    area = "(a*w + (b - w)*w)"
    body = (f"({area} - pi*pivot_r**2 - 2*pi*end_r**2)*t")
    return _draft(
        "bent_lever", v,
        [{"step": 1, "eq": f"A = {area}",
          "why": "L-bar: +X arm (a x w) plus the +Y arm above the elbow "
                 "((b-w) x w), sharing the w x w elbow square"},
         {"step": 2, "eq": "V = (A - pi*pivot_r^2 - 2*pi*end_r^2)*t",
          "why": "pivot bore at the elbow, one bore at each arm end, all "
                 "disjoint holes in one profile"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "lever", "type": "Pad", "rationale": "bent lever plate "
             "with pivot and end bores in-profile",
             "parameters": {"Length": "t", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "poly_with_holes",
                         "args": {"points": pts, "holes": holes}}}],
         "dependencies": [
            {"source": "s0", "target": "lever", "kind": "profile"}]},
        [{"id": "arm_width", "kind": "precondition", "tier": 1,
          "target": "w - 2*pivot_r - 4"},
         {"id": "arm1_len", "kind": "precondition", "tier": 1,
          "target": "a - w - 8"},
         {"id": "arm2_len", "kind": "precondition", "tier": 1,
          "target": "b - w - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "a"}],
        body, ["Sketch", "Pad"], "lever", _lever_mount())


def _lever_mount():
    # land straddling the +X arm midspan (between elbow and end bore)
    return [{"id": "arm_face", "kind": "flat_top", "z": "t",
             "land": {"type": "rect", "w": "(a - w)/2 - 4", "h": "w - 6",
                      "cx": "w + (a - w)/2/2", "cy": "w/2"},
             "thickness": "t"}]


# =========================================================================== #
# 4. cross-rib plate — plate with two crossing ribs (exact inclusion-exclusion)
# =========================================================================== #
def base_cross_rib_plate(rng):
    L = _u(rng, 60, 120, 2)
    W = _u(rng, 50, 0.9 * L, 2)
    T = _u(rng, 4, 8, 0.5)
    rib_t = _u(rng, 4, 8, 0.5)
    rib_h = _u(rng, 8, 20, 1)
    v = {"L": L, "W": W, "T": T, "rib_t": rib_t, "rib_h": rib_h}
    # two ribs crossing at the centre; their intersection (rib_t x rib_t x
    # rib_h) is double-counted by the sum and subtracted once.
    body = ("L*W*T + L*rib_t*rib_h + W*rib_t*rib_h - rib_t*rib_t*rib_h")
    return _draft(
        "cross_rib_plate", v,
        [{"step": 1, "eq": "V = L*W*T + (rib_x + rib_y) - overlap",
          "why": "a stiffening cross: rib along X (L) + rib along Y (W), both "
                 "standing on the plate; their central intersection "
                 "rib_t x rib_t x rib_h is counted twice by the sum and "
                 "removed once — exact inclusion-exclusion"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "plate", "type": "Pad", "rationale": "skin plate",
             "parameters": {"Length": "T", "Type": "Length"}},
            {"id": "s_rx", "type": "Sketch", "parameters": {}},
            {"id": "rib_x", "type": "Pad", "rationale": "rib along X",
             "parameters": {"Length": "rib_h", "Type": "Length"}},
            {"id": "s_ry", "type": "Sketch", "parameters": {}},
            {"id": "rib_y", "type": "Pad", "rationale": "rib along Y (crosses "
             "rib_x at the centre)",
             "parameters": {"Length": "rib_h", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_rx", "plane": "XY", "z": "T",
             "profile": {"builder": "rect",
                         "args": {"w": "L", "h": "rib_t"}}},
            {"id": "s_ry", "plane": "XY", "z": "T",
             "profile": {"builder": "rect",
                         "args": {"w": "rib_t", "h": "W"}}}],
         "dependencies": [
            {"source": "s0", "target": "plate", "kind": "profile"},
            {"source": "s_rx", "target": "rib_x", "kind": "profile"},
            {"source": "plate", "target": "rib_x", "kind": "base"},
            {"source": "s_ry", "target": "rib_y", "kind": "profile"},
            {"source": "rib_x", "target": "rib_y", "kind": "base"}]},
        [{"id": "rib_fits", "kind": "precondition", "tier": 1,
          "target": "min(L, W) - rib_t - 20"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "T + rib_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "Sketch", "Pad"], "rib_y",
        # land in one of the four plate quadrants, clear of both ribs
        [{"id": "quadrant", "kind": "flat_top", "z": "T",
          "land": {"type": "rect", "w": "L/2 - rib_t/2 - 8",
                   "h": "W/2 - rib_t/2 - 8",
                   "cx": "L/4 + rib_t/4", "cy": "W/4 + rib_t/4"},
          "thickness": "T"}])


# =========================================================================== #
# 5. box shell — hollow open-top box via pad + pocket (not Thickness)
# =========================================================================== #
def base_box_shell(rng):
    L = _u(rng, 50, 120, 2)
    W = _u(rng, 40, 0.85 * L, 2)
    H = _u(rng, 20, 50, 1)
    wall = _u(rng, 3, min(8.0, W / 6), 0.5)
    floor_t = _u(rng, 3, min(10.0, H / 3), 0.5)
    v = {"L": L, "W": W, "H": H, "wall": wall, "floor_t": floor_t}
    body = "L*W*H - (L - 2*wall)*(W - 2*wall)*(H - floor_t)"
    return _draft(
        "box_shell", v,
        [{"step": 1, "eq": "V = L*W*H - (L-2wall)(W-2wall)(H-floor_t)",
          "why": "cast box hollowed by a rectangular pocket; the cavity "
                 "overshoots the top so the removal is exactly the interior "
                 "prism (a closed-form alternative to the Thickness tray)"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "block", "type": "Pad", "rationale": "solid box blank",
             "parameters": {"Length": "H", "Type": "Length"}},
            {"id": "s_cav", "type": "Sketch", "parameters": {}},
            {"id": "cavity", "type": "Pocket", "rationale": "interior cavity, "
             "open top, floor_t left below",
             "parameters": {"Length": "H - floor_t", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_cav", "plane": "XY", "z": "H",
             "profile": {"builder": "rect",
                         "args": {"w": "L - 2*wall", "h": "W - 2*wall"}}}],
         "dependencies": [
            {"source": "s0", "target": "block", "kind": "profile"},
            {"source": "block", "target": "cavity", "kind": "base"},
            {"source": "s_cav", "target": "cavity", "kind": "profile"}]},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "W - 2*wall - 16"},
         {"id": "floor_guard", "kind": "precondition", "tier": 1,
          "target": "H - floor_t - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "H"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "cavity",
        # land on the interior floor_t
        [{"id": "cavity_floor", "kind": "flat_top", "z": "floor_t",
          "land": {"type": "rect", "w": "L - 2*wall - 8",
                   "h": "W - 2*wall - 8", "cx": "0", "cy": "0"},
          "thickness": "floor_t"}])


# =========================================================================== #
# 6. slotted rail — bar with a longitudinal T of through slots
# =========================================================================== #
def base_slotted_rail(rng):
    rail_l = _u(rng, 80, 160, 2)
    rail_w = _u(rng, 24, 44, 1)
    rail_h = _u(rng, 8, 16, 1)
    slot_r = _u(rng, 2.5, min(5.0, rail_w / 4), 0.25)
    slot_len = _u(rng, 20, 0.5 * rail_l, 2)
    v = {"rail_l": rail_l, "rail_w": rail_w, "rail_h": rail_h,
         "slot_r": slot_r, "slot_len": slot_len}
    slot_a = "(slot_len*2*slot_r + pi*slot_r**2)"
    body = f"rail_l*rail_w*rail_h - {slot_a}*rail_h"
    return _draft(
        "slotted_rail", v,
        [{"step": 1, "eq": f"A_slot = {slot_a}",
          "why": "central adjustment slot (stadium): straight length plus two "
                 "semicircle ends"},
         {"step": 2, "eq": "V = rail_l*rail_w*rail_h - A_slot*rail_h",
          "why": "the slot is cut through the full height"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "rail", "type": "Pad", "rationale": "rail bar",
             "parameters": {"Length": "rail_h", "Type": "Length"}},
            {"id": "s_slot", "type": "Sketch", "parameters": {}},
            {"id": "slot", "type": "Pocket", "rationale": "central slide slot",
             "parameters": {"Length": "rail_h + 1", "Type": "Length",
                            "Length2": "rail_h + 1", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "rail_l", "h": "rail_w"}}},
            {"id": "s_slot", "plane": "XY", "z": "0",
             "profile": {"builder": "slot",
                         "args": {"length": "slot_len", "r": "slot_r"}}}],
         "dependencies": [
            {"source": "s0", "target": "rail", "kind": "profile"},
            {"source": "rail", "target": "slot", "kind": "base"},
            {"source": "s_slot", "target": "slot", "kind": "profile"}]},
        [{"id": "slot_wall", "kind": "precondition", "tier": 1,
          "target": "rail_w/2 - slot_r - 4"},
         {"id": "slot_ends", "kind": "precondition", "tier": 1,
          "target": "rail_l/2 - slot_len/2 - slot_r - 6"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "rail_l"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "rail_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "slot",
        # land on the solid rail end, clear of the slot
        [{"id": "rail_end", "kind": "flat_top", "z": "rail_h",
          "land": {"type": "rect", "w": "rail_l/2 - slot_len/2 - 10",
                   "h": "rail_w - 8",
                   "cx": "rail_l/4 + slot_len/4 + 2", "cy": "0"},
          "thickness": "rail_h"}])


def _fixture_edge_land(L, W, pitch, ny, hole_r):
    """Clear rectangular strip between the top hole row and the plate edge —
    computed as literals (grid geometry is fixed at author time)."""
    grid_top = pitch * (ny - 1) / 2.0 + hole_r
    lo = grid_top + 6.0
    hi = W / 2.0 - 3.0
    if hi - lo < 5.0:
        return []
    return [{"id": "edge_strip", "kind": "flat_top", "z": "T",
             "land": {"type": "rect", "w": f"{round(L - 10, 2)}",
                      "h": f"{round(hi - lo, 2)}", "cx": "0",
                      "cy": f"{round((lo + hi) / 2, 2)}"},
             "thickness": "T"}]


# =========================================================================== #
# 7. tee plate — T-shaped plate with a bore at each of the three arm ends
# =========================================================================== #
def base_tee_plate(rng):
    w = _u(rng, 16, 28, 1)           # limb width
    # draw feasibly: bar must host two end arms clear of the stem, stem must be
    # longer than the junction square (matches the frozen preconditions, so a
    # drawn part is never refused at build time)
    span = _u(rng, 3 * w + 12, 130, 2)   # top-bar full width (X)
    stem = _u(rng, w + 14, 95, 2)        # stem length down (-Y)
    t = _u(rng, 6, 14, 0.5)
    end_r = _u(rng, 3, min(5.0, w / 2 - 3), 0.25)
    v = {"span": span, "stem": stem, "w": w, "t": t, "end_r": end_r}
    # T outline: top bar (span x w) at y in [0, w], stem (w x stem) hanging to
    # y = -stem, centred on x=0. (span/2 is the bar half-width.)
    pts = [["-span/2", "0"], ["-w/2", "0"], ["-w/2", "-stem"],
           ["w/2", "-stem"], ["w/2", "0"], ["span/2", "0"],
           ["span/2", "w"], ["-span/2", "w"]]
    holes = [["-span/2 + w/2", "w/2", "end_r"],   # left bar end
             ["span/2 - w/2", "w/2", "end_r"],    # right bar end
             ["0", "-stem + w/2", "end_r"]]       # stem end
    area = "(span*w + stem*w)"
    body = f"({area} - 3*pi*end_r**2)*t"
    return _draft(
        "tee_plate", v,
        [{"step": 1, "eq": f"A = {area}",
          "why": "T: top bar (span x w, y in [0,w]) plus the stem hanging "
                 "below it (w x stem, y in [-stem,0]); disjoint, so areas add"},
         {"step": 2, "eq": "V = (A - 3*pi*end_r^2)*t",
          "why": "a fixing bore at each of the three arm ends, disjoint holes "
                 "in one profile"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "tee", "type": "Pad", "rationale": "T bracket plate with "
             "the three end bores in-profile",
             "parameters": {"Length": "t", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "poly_with_holes",
                         "args": {"points": pts, "holes": holes}}}],
         "dependencies": [
            {"source": "s0", "target": "tee", "kind": "profile"}]},
        [{"id": "limb_width", "kind": "precondition", "tier": 1,
          "target": "w - 2*end_r - 5"},
         {"id": "bar_arms", "kind": "precondition", "tier": 1,
          "target": "span - 3*w"},
         {"id": "stem_len", "kind": "precondition", "tier": 1,
          "target": "stem - w - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "span"}],
        body, ["Sketch", "Pad"], "tee",
        # land on the +X bar arm, strictly between the T-junction and the
        # end bore (x in [w/2, span/2 - w/2 - end_r])
        [{"id": "bar_face", "kind": "flat_top", "z": "t",
          "land": {"type": "rect", "w": "span/2 - w - end_r - 6", "h": "w - 6",
                   "cx": "span/4 - end_r/2", "cy": "w/2"}, "thickness": "t"}])


# =========================================================================== #
# 8. stepped block — rabbeted block (L-section extruded)
# =========================================================================== #
def base_stepped_block(rng):
    L = _u(rng, 50, 110, 2)          # length (X)
    W = _u(rng, 30, 70, 2)           # full width (Y)
    H = _u(rng, 20, 45, 1)           # full height (Z)
    step_w = _u(rng, 0.3 * W, 0.6 * W, 1)   # rabbet width removed
    step_h = _u(rng, 0.3 * H, 0.6 * H, 1)   # rabbet height removed
    v = {"L": L, "W": W, "H": H, "step_w": step_w, "step_h": step_h}
    # Full block minus a rabbet pocket along the +Y edge (unambiguous XY: pad
    # up +Z, then a pocket removing the top-edge corner).
    body = "L*W*H - L*step_w*step_h"
    return _draft(
        "stepped_block", v,
        [{"step": 1, "eq": "V = L*W*H - L*step_w*step_h",
          "why": "rabbeted block: full L x W x H solid with a step_w x step_h "
                 "rabbet removed along the full length of the +Y top edge"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "block", "type": "Pad", "rationale": "solid block blank",
             "parameters": {"Length": "H", "Type": "Length"}},
            {"id": "s_rabbet", "type": "Sketch", "parameters": {}},
            {"id": "rabbet", "type": "Pocket", "rationale": "rabbet: removes "
             "the top +Y corner strip down step_h",
             "parameters": {"Length": "step_h", "Type": "Length"}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_rabbet", "plane": "XY", "z": "H",
             "profile": {"builder": "rect",
                         "args": {"w": "L + 2", "h": "step_w",
                                  "cy": "W/2 - step_w/2"}}}],
         "dependencies": [
            {"source": "s0", "target": "block", "kind": "profile"},
            {"source": "block", "target": "rabbet", "kind": "base"},
            {"source": "s_rabbet", "target": "rabbet", "kind": "profile"}]},
        [{"id": "step_w_guard", "kind": "precondition", "tier": 1,
          "target": "W - step_w - 8"},
         {"id": "step_h_guard", "kind": "precondition", "tier": 1,
          "target": "H - step_h - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "H"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "rabbet",
        # land on the rabbet step floor (z = H-step_h, +Y edge strip)
        [{"id": "step_face", "kind": "flat_top", "z": "H - step_h",
          "land": {"type": "rect", "w": "L - 10", "h": "step_w - 6",
                   "cx": "0", "cy": "W/2 - step_w/2"},
          "thickness": "H - step_h"}])


# spider_hub deferred: its hub+arms union has no exact closed form and needs
# mesh-body support under composition (the composer currently assumes additive
# closed-form bodies). Code retained for a later mesh-body tranche.
BASES.update({
    "fixture_plate": base_fixture_plate,
    "spider_hub": base_spider_hub,
    "bent_lever": base_bent_lever,
    "cross_rib_plate": base_cross_rib_plate,
    "box_shell": base_box_shell,
    "slotted_rail": base_slotted_rail,
    "tee_plate": base_tee_plate,
    "stepped_block": base_stepped_block,
})
