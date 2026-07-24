"""Composable base library, tranche 4 (Phase-X Step 3 — final priority set).

The remaining priority families: control_arm_mount, suspension_knuckle,
pump_housing, structural_node (union-body / mesh where irreducible) and
pillow_block (exact). Applies the confirmed plane-coordinate mappings up front:
XZ sketch cx->world X, cy->world Z; z=0 bottom cuts use a top-down one-sided
pocket to avoid the asymmetric-two-sided-leg trap.
"""

from __future__ import annotations

import math


from .bases import BASES, _disc_land, _ring_land
from .bases_ext import _draft
from .recipes import _u


# =========================================================================== #
# 1. control-arm mount — base plate with two bushing bosses + through bores (EX)
# =========================================================================== #
def base_control_arm_mount(rng):
    base_l = _u(rng, 60, 120, 2)
    base_w = _u(rng, 30, 55, 2)
    base_t = _u(rng, 8, 16, 1)
    boss_r = _u(rng, 7, 12, 0.5)
    boss_h = _u(rng, 8, 20, 1)
    bore_r = _u(rng, 3, boss_r - 3, 0.5)
    dx = _u(rng, boss_r + 6, base_l / 2 - boss_r - 4, 1)
    v = {"base_l": base_l, "base_w": base_w, "base_t": base_t,
         "boss_r": boss_r, "boss_h": boss_h, "bore_r": bore_r, "dx": dx}
    body = ("base_l*base_w*base_t + 2*pi*boss_r**2*boss_h"
            " - 2*pi*bore_r**2*(boss_h + base_t)")
    return _draft(
        "control_arm_mount", v,
        [{"step": 1, "eq": "V = base + 2 bushing bosses - 2 through bores",
          "why": "two coaxial bushing bosses on a base, each bored through the "
                 "boss and the base beneath it; bosses disjoint so exact"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_base", "type": "Sketch", "parameters": {}},
            {"id": "base", "type": "Pad", "rationale": "mounting base",
             "parameters": {"Length": "base_t", "Type": "Length"}},
            {"id": "s_bA", "type": "Sketch", "parameters": {}},
            {"id": "bossA", "type": "Pad", "rationale": "+X bushing boss",
             "parameters": {"Length": "boss_h", "Type": "Length"}},
            {"id": "s_bB", "type": "Sketch", "parameters": {}},
            {"id": "bossB", "type": "Pad", "rationale": "-X bushing boss",
             "parameters": {"Length": "boss_h", "Type": "Length"}},
            {"id": "s_bore", "type": "Sketch", "parameters": {}},
            {"id": "bores", "type": "Pocket", "rationale": "bushing bores, "
             "drilled down through boss + base",
             "parameters": {"Length": "boss_h + base_t + 2", "Type": "Length"}}],
         "sketches": [
            {"id": "s_base", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "base_l", "h": "base_w"}}},
            {"id": "s_bA", "plane": "XY", "z": "base_t",
             "profile": {"builder": "circle",
                         "args": {"r": "boss_r", "cx": "dx"}}},
            {"id": "s_bB", "plane": "XY", "z": "base_t",
             "profile": {"builder": "circle",
                         "args": {"r": "boss_r", "cx": "-dx"}}},
            {"id": "s_bore", "plane": "XY", "z": "base_t + boss_h",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "2", "r_bc": "dx", "r_hole": "bore_r"}}}],
         "dependencies": [
            {"source": "s_base", "target": "base", "kind": "profile"},
            {"source": "s_bA", "target": "bossA", "kind": "profile"},
            {"source": "base", "target": "bossA", "kind": "base"},
            {"source": "s_bB", "target": "bossB", "kind": "profile"},
            {"source": "bossA", "target": "bossB", "kind": "base"},
            {"source": "s_bore", "target": "bores", "kind": "profile"},
            {"source": "bossB", "target": "bores", "kind": "base"}]},
        [{"id": "boss_wall", "kind": "precondition", "tier": 1,
          "target": "boss_r - bore_r - 2.5"},
         {"id": "boss_fit", "kind": "precondition", "tier": 1,
          "target": "base_l/2 - dx - boss_r - 2"},
         {"id": "boss_on_base", "kind": "precondition", "tier": 1,
          "target": "base_w/2 - boss_r - 3"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "base_l"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "base_t + boss_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "Sketch", "Pad",
               "Sketch", "Pocket"], "bores",
        # land on the base top, between the two bosses
        [{"id": "base_mid", "kind": "flat_top", "z": "base_t",
          "land": {"type": "rect", "w": "2*dx - 2*boss_r - 6", "h": "base_w - 8",
                   "cx": "0", "cy": "0"}, "thickness": "base_t"}])


# =========================================================================== #
# 2. suspension knuckle — hub with two perpendicular arms + end bores (MESH)
# =========================================================================== #
def base_suspension_knuckle(rng):
    hub_r = _u(rng, 16, 28, 1)
    bore_r = _u(rng, 6, hub_r - 5, 0.5)
    hub_h = _u(rng, 12, 24, 1)
    armx_len = _u(rng, 24, 50, 1)
    army_len = _u(rng, 20, 45, 1)
    arm_w = _u(rng, 12, 18, 1)
    arm_h = _u(rng, 8, hub_h, 1)
    # end_r ceiling is set by arm_bore_fit (arm_w/2 - end_r - 3 > 0); floor 2.5
    # and min arm_w 12 keep the range from ever inverting -> no wasted refusals.
    end_r = _u(rng, 2.5, arm_w / 2 - 3.5, 0.25)
    v = {"hub_r": hub_r, "bore_r": bore_r, "hub_h": hub_h,
         "armx_len": armx_len, "army_len": army_len, "arm_w": arm_w,
         "arm_h": arm_h, "end_r": end_r}
    # hub (bearing bore) + a strut arm (+X) + a steering arm (+Y); the arms
    # overlap the hub rim to fuse, and each carries an end bore -> the fused
    # body is an irreducible union (mesh), tools exact.
    body = ("pi*(hub_r**2 - bore_r**2)*hub_h"
            " + arm_w*armx_len*arm_h + arm_w*army_len*arm_h")
    return _draft(
        "suspension_knuckle", v,
        [{"step": 1, "eq": "hub tool = pi(hub_r^2-bore_r^2)*hub_h (exact)"},
         {"step": 2, "eq": "arm tools = arm_w*len*arm_h each (exact)"},
         {"step": 3, "eq": "V_body: two arms fused to the hub at 90 deg, each "
                           "with a ball-joint end bore -> irreducible union, "
                           "mesh-verified; tools Tier-1"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_hub", "type": "Sketch", "parameters": {}},
            {"id": "hub", "type": "Pad", "rationale": "bearing hub",
             "parameters": {"Length": "hub_h", "Type": "Length"}},
            {"id": "s_ax", "type": "Sketch", "parameters": {}},
            {"id": "armx", "type": "Pad", "rationale": "strut arm (+X), root "
             "sunk into the hub",
             "parameters": {"Length": "arm_h", "Type": "Length"}},
            {"id": "s_ay", "type": "Sketch", "parameters": {}},
            {"id": "army", "type": "Pad", "rationale": "steering arm (+Y)",
             "parameters": {"Length": "arm_h", "Type": "Length"}},
            {"id": "s_boreX", "type": "Sketch", "parameters": {}},
            {"id": "boreX", "type": "Pocket", "rationale": "strut-arm end bore, "
             "drilled from the top",
             "parameters": {"Length": "arm_h + 2", "Type": "Length"}},
            {"id": "s_boreY", "type": "Sketch", "parameters": {}},
            {"id": "bores", "type": "Pocket", "rationale": "steering-arm end "
             "bore",
             "parameters": {"Length": "arm_h + 2", "Type": "Length"}}],
         "sketches": [
            {"id": "s_hub", "plane": "XY",
             "profile": {"builder": "annulus",
                         "args": {"r_outer": "hub_r", "r_inner": "bore_r"}}},
            {"id": "s_ax", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "armx_len", "h": "arm_w",
                                  "cx": "hub_r + armx_len/2 - 3"}}},
            {"id": "s_ay", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "arm_w", "h": "army_len",
                                  "cy": "hub_r + army_len/2 - 3"}}},
            {"id": "s_boreX", "plane": "XY", "z": "arm_h",
             "profile": {"builder": "circle",
                         "args": {"r": "end_r", "cx": "hub_r + armx_len - 6"}}},
            {"id": "s_boreY", "plane": "XY", "z": "arm_h",
             "profile": {"builder": "circle",
                         "args": {"r": "end_r", "cy": "hub_r + army_len - 6"}}}],
         "dependencies": [
            {"source": "s_hub", "target": "hub", "kind": "profile"},
            {"source": "s_ax", "target": "armx", "kind": "profile"},
            {"source": "hub", "target": "armx", "kind": "base"},
            {"source": "s_ay", "target": "army", "kind": "profile"},
            {"source": "armx", "target": "army", "kind": "base"},
            {"source": "s_boreX", "target": "boreX", "kind": "profile"},
            {"source": "army", "target": "boreX", "kind": "base"},
            {"source": "s_boreY", "target": "bores", "kind": "profile"},
            {"source": "boreX", "target": "bores", "kind": "base"}]},
        [{"id": "hub_wall", "kind": "precondition", "tier": 1,
          "target": "hub_r - bore_r - 4"},
         {"id": "arm_bore_fit", "kind": "precondition", "tier": 1,
          "target": "arm_w/2 - end_r - 3"},
         {"id": "hub_tool", "kind": "feature_volume", "feature": "hub",
          "tier": 1, "tol_rel": 1e-6,
          "target": "pi*(hub_r**2 - bore_r**2)*hub_h"},
         {"id": "armx_tool", "kind": "feature_volume", "feature": "armx",
          "tier": 1, "tol_rel": 1e-6, "target": "arm_w*armx_len*arm_h"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "hub_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "Sketch", "Pad",
               "Sketch", "Pocket", "Sketch", "Pocket"], "bores",
        _knuckle_mount(hub_r, bore_r), body_mesh=True)


def _knuckle_mount(hub_r, bore_r):
    ring = _ring_land(bore_r, hub_r)
    return [] if ring is None else [
        {"id": "hub_top", "kind": "flat_top", "z": "hub_h",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"}, "thickness": "hub_h"}]


# =========================================================================== #
# 3. pump housing — cylindrical chamber cup on an overlapping base slab (MESH)
# =========================================================================== #
def base_pump_housing(rng):
    R = _u(rng, 24, 45, 1)
    wall = _u(rng, 4, 8, 0.5)
    H = _u(rng, 30, 60, 1)
    floor_t = _u(rng, 4, 9, 0.5)
    slab_l = _u(rng, 2 * R + 20, 2 * R + 50, 2)
    slab_w = _u(rng, 2 * R + 6, 2 * R + 20, 2)
    slab_t = _u(rng, 6, 12, 0.5)
    s = _disc_land(R - wall)
    if s is None:
        raise ValueError("pump bore too small for a land")
    v = {"R": R, "wall": wall, "H": H, "floor_t": floor_t,
         "slab_l": slab_l, "slab_w": slab_w, "slab_t": slab_t}
    chamber = ("pi*R**2*floor_t + pi*(R**2 - (R - wall)**2)*(H - floor_t)")
    return _draft(
        "pump_housing", v,
        [{"step": 1, "eq": f"chamber tool = {chamber} (exact)"},
         {"step": 2, "eq": "slab tool = slab_l*slab_w*slab_t (exact)"},
         {"step": 3, "eq": "V_body: the chamber cup sits on and overlaps a "
                           "mounting slab -> cylinder+box union, mesh-verified"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_slab", "type": "Sketch", "parameters": {}},
            {"id": "slab", "type": "Pad", "rationale": "mounting foot slab",
             "parameters": {"Length": "slab_t", "Type": "Length"}},
            {"id": "s_cham", "type": "Sketch", "parameters": {}},
            {"id": "chamber", "type": "Revolution", "rationale": "pump chamber "
             "cup, base sunk into the slab so it fuses",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_cham",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}}],
         "sketches": [
            {"id": "s_slab", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "slab_l", "h": "slab_w"}}},
            {"id": "s_cham", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["0", "slab_t - 3"], ["R", "slab_t - 3"],
                 ["R", "slab_t - 3 + H"], ["R - wall", "slab_t - 3 + H"],
                 ["R - wall", "slab_t - 3 + floor_t"],
                 ["0", "slab_t - 3 + floor_t"]]}}}],
         "dependencies": [
            {"source": "s_slab", "target": "slab", "kind": "profile"},
            {"source": "slab", "target": "chamber", "kind": "base"},
            {"source": "s_cham", "target": "chamber", "kind": "profile"}]},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "R - wall - 8"},
         {"id": "slab_clear", "kind": "precondition", "tier": 1,
          "target": "slab_w/2 - R - 2"},
         {"id": "chamber_tool", "kind": "feature_volume", "feature": "chamber",
          "tier": 1, "tol_rel": 1e-6, "target": chamber},
         {"id": "slab_tool", "kind": "feature_volume", "feature": "slab",
          "tier": 1, "tol_rel": 1e-6, "target": "slab_l*slab_w*slab_t"},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "slab_l"}],
        body_expr=chamber,
        seq=["Sketch", "Pad", "Sketch", "Revolution"], last_solid="chamber",
        # land on the exposed slab strip beyond the chamber rim; the strip runs
        # from x=R to x=slab_l/2, so width = slab_l/2 - R (less margin), centred
        # at its midpoint. A wider land would push attachments past slab_l and
        # break len_extent.
        mounts=[{"id": "slab_end", "kind": "flat_top", "z": "slab_t",
                 "land": {"type": "rect", "w": "slab_l/2 - R - 4",
                          "h": "slab_w - 8",
                          "cx": "R/2 + slab_l/4",
                          "cy": "0"}, "thickness": "slab_t"}],
        body_mesh=True)


# =========================================================================== #
# 4. structural node — hub with three arms and tip bores (MESH)
# =========================================================================== #
def base_structural_node(rng):
    hub_r = _u(rng, 12, 22, 1)
    bore_r = _u(rng, 4, hub_r - 5, 0.5)
    hub_h = _u(rng, 10, 20, 1)
    arm_len = _u(rng, 22, 48, 1)
    arm_w = _u(rng, 12, 16, 1)
    arm_h = _u(rng, 8, hub_h, 1)
    # end_r ceiling is set by tip_fit (arm_w/2 - end_r - 3 > 0); floor 2.5 with
    # min arm_w 12 keeps the range non-inverting.
    end_r = _u(rng, 2.5, arm_w / 2 - 3.5, 0.25)
    if 2 * (hub_r + arm_len / 2) * math.sin(math.pi / 3) <= arm_w + 5:
        raise ValueError("structural node arms collide at 120 deg")
    v = {"hub_r": hub_r, "bore_r": bore_r, "hub_h": hub_h,
         "arm_len": arm_len, "arm_w": arm_w, "arm_h": arm_h, "end_r": end_r}
    body = ("pi*(hub_r**2 - bore_r**2)*hub_h + 3*arm_w*arm_len*arm_h")
    return _draft(
        "structural_node", v,
        [{"step": 1, "eq": "hub tool + 3 arm tools (all exact)"},
         {"step": 2, "eq": "V_body: three fused arms at 120 deg, each with a "
                           "bolt bore at its tip -> space-frame node, an "
                           "irreducible union verified by mesh"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_hub", "type": "Sketch", "parameters": {}},
            {"id": "hub", "type": "Pad", "rationale": "node hub + bore",
             "parameters": {"Length": "hub_h", "Type": "Length"}},
            {"id": "s_arm", "type": "Sketch", "parameters": {}},
            {"id": "arm0", "type": "Pad", "rationale": "one arm, root fused "
             "into the hub",
             "parameters": {"Length": "arm_h", "Type": "Length"}},
            {"id": "arms", "type": "PolarPattern", "rationale": "3 arms 120 deg",
             "parameters": {"Occurrences": "3", "Angle": "360",
                            "_Axis": {"role": "Z_Axis", "subs": [""]},
                            "_Originals": ["arm0"]}},
            {"id": "s_bore", "type": "Sketch", "parameters": {}},
            {"id": "bore0", "type": "Pocket", "rationale": "tip bore on arm0",
             "parameters": {"Length": "arm_h + 2", "Type": "Length"}},
            {"id": "bores", "type": "PolarPattern", "rationale": "3 tip bores",
             "parameters": {"Occurrences": "3", "Angle": "360",
                            "_Axis": {"role": "Z_Axis", "subs": [""]},
                            "_Originals": ["bore0"]}}],
         "sketches": [
            {"id": "s_hub", "plane": "XY",
             "profile": {"builder": "annulus",
                         "args": {"r_outer": "hub_r", "r_inner": "bore_r"}}},
            {"id": "s_arm", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "arm_len", "h": "arm_w",
                                  "cx": "hub_r + arm_len/2 - 3"}}},
            {"id": "s_bore", "plane": "XY", "z": "arm_h",
             "profile": {"builder": "circle",
                         "args": {"r": "end_r",
                                  "cx": "hub_r + arm_len - 6"}}}],
         "dependencies": [
            {"source": "s_hub", "target": "hub", "kind": "profile"},
            {"source": "s_arm", "target": "arm0", "kind": "profile"},
            {"source": "hub", "target": "arm0", "kind": "base"},
            {"source": "arm0", "target": "arms", "kind": "base"},
            {"source": "s_bore", "target": "bore0", "kind": "profile"},
            {"source": "arms", "target": "bore0", "kind": "base"},
            {"source": "bore0", "target": "bores", "kind": "base"}]},
        [{"id": "hub_wall", "kind": "precondition", "tier": 1,
          "target": "hub_r - bore_r - 4"},
         {"id": "arm_spacing", "kind": "precondition", "tier": 1,
          "target": "2*(hub_r + arm_len/2)*sin(pi/3) - arm_w - 4"},
         {"id": "tip_fit", "kind": "precondition", "tier": 1,
          "target": "arm_w/2 - end_r - 3"},
         {"id": "hub_tool", "kind": "feature_volume", "feature": "hub",
          "tier": 1, "tol_rel": 1e-6,
          "target": "pi*(hub_r**2 - bore_r**2)*hub_h"},
         {"id": "arm_tool", "kind": "feature_volume", "feature": "arm0",
          "tier": 1, "tol_rel": 1e-6, "target": "arm_w*arm_len*arm_h"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "hub_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "PolarPattern",
               "Sketch", "Pocket", "PolarPattern"], "bores",
        _knuckle_mount(hub_r, bore_r), body_mesh=True)


# =========================================================================== #
# 5. pillow block — base with a raised housing and a horizontal bearing bore (EX)
# =========================================================================== #
def base_pillow_block(rng):
    L = _u(rng, 55, 100, 2)
    W = _u(rng, 30, 55, 2)
    base_t = _u(rng, 8, 16, 1)
    hous_l = _u(rng, 0.5 * L, 0.8 * L, 2)
    hous_w = _u(rng, 22, W - 6, 2)
    hous_h = _u(rng, 18, 38, 1)
    # bore_r ceiling is set by bore_wall (hous_h/2 - bore_r - 3 > 0) as well as
    # the housing length; floor 5 keeps the range non-inverting at hous_h=18.
    bore_r = _u(rng, 5, min(0.35 * hous_h, hous_l / 2 - 4, hous_h / 2 - 3.5), 0.5)
    v = {"L": L, "W": W, "base_t": base_t, "hous_l": hous_l, "hous_w": hous_w,
         "hous_h": hous_h, "bore_r": bore_r}
    # base slab + a raised housing block; a horizontal bearing bore runs the
    # full housing width (along Y) at mid-height, clear of the base.
    body = ("L*W*base_t + hous_l*hous_w*hous_h - pi*bore_r**2*hous_w")
    return _draft(
        "pillow_block", v,
        [{"step": 1, "eq": "V = base + housing - pi*bore_r^2*hous_w",
          "why": "pillow block: a bearing-housing block on a base, a bearing "
                 "bore through the full housing width; housing sits on the "
                 "base (zero-vol interface), bore clears the base -> exact"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_base", "type": "Sketch", "parameters": {}},
            {"id": "base", "type": "Pad", "rationale": "base slab",
             "parameters": {"Length": "base_t", "Type": "Length"}},
            {"id": "s_hous", "type": "Sketch", "parameters": {}},
            {"id": "housing", "type": "Pad", "rationale": "raised bearing "
             "housing block",
             "parameters": {"Length": "hous_h", "Type": "Length"}},
            {"id": "s_bore", "type": "Sketch", "parameters": {}},
            {"id": "bore", "type": "Pocket", "rationale": "horizontal bearing "
             "bore through the housing width",
             "parameters": {"Length": "W", "Type": "Length",
                            "Length2": "W", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s_base", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_hous", "plane": "XY", "z": "base_t",
             "profile": {"builder": "rect",
                         "args": {"w": "hous_l", "h": "hous_w"}}},
            {"id": "s_bore", "plane": "XZ", "z": "0",
             # XZ: cx->world X (0, centred), cy->world Z (bore height in the
             # housing), extruded along Y through the full width.
             "profile": {"builder": "circle",
                         "args": {"r": "bore_r", "cx": "0",
                                  "cy": "base_t + hous_h/2"}}}],
         "dependencies": [
            {"source": "s_base", "target": "base", "kind": "profile"},
            {"source": "base", "target": "housing", "kind": "base"},
            {"source": "s_hous", "target": "housing", "kind": "profile"},
            {"source": "s_bore", "target": "bore", "kind": "profile"},
            {"source": "housing", "target": "bore", "kind": "base"}]},
        [{"id": "bore_wall", "kind": "precondition", "tier": 1,
          "target": "hous_h/2 - bore_r - 3"},
         {"id": "bore_above_base", "kind": "precondition", "tier": 1,
          "target": "hous_h/2 - bore_r - 2"},
         {"id": "hous_fit", "kind": "precondition", "tier": 1,
          "target": "W - hous_w - 4"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "base_t + hous_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "Sketch", "Pocket"], "bore",
        # land on an exposed base end, clear of the housing
        [{"id": "base_end", "kind": "flat_top", "z": "base_t",
          "land": {"type": "rect", "w": "(L - hous_l)/2 - 6", "h": "W - 8",
                   "cx": "L/4 + hous_l/4", "cy": "0"}, "thickness": "base_t"}])


BASES.update({
    "control_arm_mount": base_control_arm_mount,
    "suspension_knuckle": base_suspension_knuckle,
    "pump_housing": base_pump_housing,
    "structural_node": base_structural_node,
    "pillow_block": base_pillow_block,
})
