"""Composable base library, tranche 3 (Phase-X Step 3 — union-body unlock).

The families the mesh-body composer support (spider_hub) opened up, plus the
exact rotational/prismatic ones from the same priority list. Discipline:
Tier-1 closed form wherever the body is summable; body_mesh_converged only
where the solid is a genuinely irreducible union (fused blades, overlapping
cylinders), always backed by mandatory connectivity + watertight checks and
Tier-1 per-feature tool volumes.
"""

from __future__ import annotations

import math

from .bases import BASES, _ring_land
from .bases_ext import _draft, _rev
from .recipes import _u


# =========================================================================== #
# 1. impeller — solid backplate disc with N swept blades on its face (MESH)
# =========================================================================== #
def base_impeller(rng):
    disc_r = _u(rng, 24, 45, 1)
    disc_t = _u(rng, 5, 10, 0.5)
    bore_r = _u(rng, 4, 0.35 * disc_r, 0.5)
    n = rng.choice([4, 5, 6, 7])
    blade_len = _u(rng, max(6, 0.3 * disc_r), disc_r - bore_r - 6, 1)
    blade_t = _u(rng, 2.5, 5.0, 0.25)
    blade_h = _u(rng, disc_t + 5, disc_t + 16, 1)
    r_mid = bore_r + 3 + blade_len / 2      # blade radial midpoint
    if 2 * r_mid * math.sin(math.pi / n) <= blade_t + 3:
        raise ValueError("impeller blades collide")
    if bore_r + 3 + blade_len > disc_r - 2:
        raise ValueError("impeller blade overruns the disc rim")
    v = {"disc_r": disc_r, "disc_t": disc_t, "bore_r": bore_r,
         "blade_len": blade_len, "blade_t": blade_t, "blade_h": blade_h,
         "arm_n": float(n)}
    body = ("pi*(disc_r**2 - bore_r**2)*disc_t"
            " + arm_n*blade_t*blade_len*blade_h")
    return _draft(
        "impeller", v,
        [{"step": 1, "eq": "V_disc = pi(disc_r^2-bore_r^2)*disc_t (exact tool)"},
         {"step": 2, "eq": "V_blade = blade_t*blade_len*blade_h (exact, x N)"},
         {"step": 3, "eq": "V_body: blades stand on the disc face and their "
                           "bases fuse into the disc solid — an irreducible "
                           "union, verified by mesh convergence to OCC",
          "why": "centrifugal impeller; per-feature tools exact, fused body "
                 "mesh-checked with connectivity + watertight"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_disc", "type": "Sketch", "parameters": {}},
            {"id": "disc", "type": "Pad", "rationale": "impeller backplate + "
             "shaft bore",
             "parameters": {"Length": "disc_t", "Type": "Length"}},
            {"id": "s_blade", "type": "Sketch", "parameters": {}},
            {"id": "blade0", "type": "Pad", "rationale": "one vane, base sunk "
             "into the backplate so it fuses",
             "parameters": {"Length": "blade_h", "Type": "Length"}},
            {"id": "blades", "type": "PolarPattern",
             "rationale": "N vanes around the hub",
             "parameters": {"Occurrences": "arm_n", "Angle": "360",
                            "_Axis": {"role": "Z_Axis", "subs": [""]},
                            "_Originals": ["blade0"]}}],
         "sketches": [
            {"id": "s_disc", "plane": "XY",
             "profile": {"builder": "annulus",
                         "args": {"r_outer": "disc_r", "r_inner": "bore_r"}}},
            {"id": "s_blade", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "blade_len", "h": "blade_t",
                                  "cx": "bore_r + 3 + blade_len/2"}}}],
         "dependencies": [
            {"source": "s_disc", "target": "disc", "kind": "profile"},
            {"source": "s_blade", "target": "blade0", "kind": "profile"},
            {"source": "disc", "target": "blade0", "kind": "base"},
            {"source": "blade0", "target": "blades", "kind": "base"}]},
        [{"id": "blade_spacing", "kind": "precondition", "tier": 1,
          "target": "2*(bore_r + 3 + blade_len/2)*sin(pi/arm_n) - blade_t - 3"},
         {"id": "blade_fits", "kind": "precondition", "tier": 1,
          "target": "disc_r - (bore_r + 3 + blade_len) - 2"},
         {"id": "disc_tool", "kind": "feature_volume", "feature": "disc",
          "tier": 1, "tol_rel": 1e-6,
          "target": "pi*(disc_r**2 - bore_r**2)*disc_t"},
         {"id": "blade_tool", "kind": "feature_volume", "feature": "blade0",
          "tier": 1, "tol_rel": 1e-6, "target": "blade_t*blade_len*blade_h"},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*disc_r"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "blade_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "PolarPattern"], "blades",
        _impeller_mount(bore_r, disc_r, blade_len), body_mesh=True)


def _impeller_mount(bore_r, disc_r, blade_len):
    # land on the clear inner annulus between the bore and the blade roots
    ring = _ring_land(bore_r, bore_r + 3)
    return [] if ring is None else [
        {"id": "hub_face", "kind": "flat_top", "z": "disc_t",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"}, "thickness": "disc_t"}]


# =========================================================================== #
# 2. turbine disk — thick rim disc with N blades on the OD (MESH)
# =========================================================================== #
def base_turbine_disk(rng):
    rim_r = _u(rng, 30, 55, 1)
    web_r = _u(rng, 0.4 * rim_r, 0.7 * rim_r, 1)
    bore_r = _u(rng, 5, 0.5 * web_r, 0.5)
    rim_t = _u(rng, 10, 20, 1)
    web_t = _u(rng, 5, rim_t - 3, 0.5)
    n = rng.choice([8, 10, 12])
    blade_len = _u(rng, 8, 18, 1)
    blade_t = _u(rng, 3, 6, 0.5)
    blade_h = _u(rng, 0.6 * rim_t, rim_t, 0.5)
    if 2 * rim_r * math.sin(math.pi / n) <= blade_t + 2:
        raise ValueError("turbine blades collide on the rim")
    v = {"rim_r": rim_r, "web_r": web_r, "bore_r": bore_r, "rim_t": rim_t,
         "web_t": web_t, "blade_len": blade_len, "blade_t": blade_t,
         "blade_h": blade_h, "arm_n": float(n)}
    # stepped disc: full-thickness rim ring + thinner central web, both bored.
    disc_v = ("pi*(rim_r**2 - web_r**2)*rim_t"
              " + pi*(web_r**2 - bore_r**2)*web_t")
    body = f"{disc_v} + arm_n*blade_t*blade_len*blade_h"
    return _draft(
        "turbine_disk", v,
        [{"step": 1, "eq": f"V_disc = {disc_v} (stepped disc, exact tool)"},
         {"step": 2, "eq": "V = V_disc + N blades (fused to the rim OD): "
                           "irreducible union -> mesh body, tools exact"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_disc", "type": "Sketch", "parameters": {}},
            {"id": "disc", "type": "Revolution", "rationale": "stepped turbine "
             "disc: rim + web + bore",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_disc",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}},
            {"id": "s_blade", "type": "Sketch", "parameters": {}},
            {"id": "blade0", "type": "Pad", "rationale": "one rim blade, root "
             "sunk into the rim",
             "parameters": {"Length": "blade_h", "Type": "Length"}},
            {"id": "blades", "type": "PolarPattern",
             "rationale": "blade ring on the rim OD",
             "parameters": {"Occurrences": "arm_n", "Angle": "360",
                            "_Axis": {"role": "Z_Axis", "subs": [""]},
                            "_Originals": ["blade0"]}}],
         "sketches": [
            {"id": "s_disc", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["bore_r", "0"], ["rim_r", "0"], ["rim_r", "rim_t"],
                 ["web_r", "rim_t"], ["web_r", "web_t"], ["bore_r", "web_t"]]}}},
            {"id": "s_blade", "plane": "XY", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "blade_len", "h": "blade_t",
                                  "cx": "rim_r + blade_len/2 - 3"}}}],
         "dependencies": [
            {"source": "s_disc", "target": "disc", "kind": "profile"},
            {"source": "s_blade", "target": "blade0", "kind": "profile"},
            {"source": "disc", "target": "blade0", "kind": "base"},
            {"source": "blade0", "target": "blades", "kind": "base"}]},
        [{"id": "blade_spacing", "kind": "precondition", "tier": 1,
          "target": "2*rim_r*sin(pi/arm_n) - blade_t - 2"},
         {"id": "web_step", "kind": "precondition", "tier": 1,
          "target": "rim_r - web_r - 4"},
         {"id": "disc_tool", "kind": "feature_volume", "feature": "disc",
          "tier": 1, "tol_rel": 1e-6, "target": disc_v},
         {"id": "blade_tool", "kind": "feature_volume", "feature": "blade0",
          "tier": 1, "tol_rel": 1e-6, "target": "blade_t*blade_len*blade_h"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "rim_t"}],
        body, ["Sketch", "Revolution", "Sketch", "Pad", "PolarPattern"],
        "blades", _turbine_mount(bore_r, web_r), body_mesh=True)


def _turbine_mount(bore_r, web_r):
    ring = _ring_land(bore_r, web_r)
    return [] if ring is None else [
        {"id": "web_face", "kind": "flat_top", "z": "web_t",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"}, "thickness": "web_t"}]


# =========================================================================== #
# 3. clevis mount — base block with two prongs and a cross bore (EXACT)
# =========================================================================== #
def base_clevis_mount(rng):
    base_l = _u(rng, 40, 80, 2)
    base_w = _u(rng, 30, 60, 2)
    base_h = _u(rng, 8, 16, 1)
    prong_t = _u(rng, 6, 12, 0.5)
    prong_h = _u(rng, 24, 44, 1)
    gmax = base_w - 2 * prong_t - 6
    if gmax < 10:
        raise ValueError("clevis: base too narrow for the fork")
    gap = _u(rng, 10, gmax, 1)
    bore_r = _u(rng, 3, min(0.35 * prong_h, prong_t + gap / 2 - 2), 0.5)
    v = {"base_l": base_l, "base_w": base_w, "base_h": base_h,
         "prong_t": prong_t, "prong_h": prong_h, "gap": gap, "bore_r": bore_r}
    # two prongs stand on the base (zero-vol interface), the cross bore passes
    # through BOTH prongs (not the gap), removing 2 * pi r^2 * prong_t.
    yc = "gap/2 + prong_t/2"
    body = ("base_l*base_w*base_h + 2*base_l*prong_t*prong_h"
            " - 2*pi*bore_r**2*prong_t")
    return _draft(
        "clevis_mount", v,
        [{"step": 1, "eq": "V = base + 2 prongs - cross bore (both prongs)",
          "why": "U-fork: two prongs on a base straddling a gap, a pivot bore "
                 "through both prong walls; prongs disjoint from each other so "
                 "the sum is exact, bore removes 2 x prong-wall cylinders"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_base", "type": "Sketch", "parameters": {}},
            {"id": "base", "type": "Pad", "rationale": "mounting base",
             "parameters": {"Length": "base_h", "Type": "Length"}},
            {"id": "s_pA", "type": "Sketch", "parameters": {}},
            {"id": "prongA", "type": "Pad", "rationale": "+Y fork prong",
             "parameters": {"Length": "prong_h", "Type": "Length"}},
            {"id": "s_pB", "type": "Sketch", "parameters": {}},
            {"id": "prongB", "type": "Pad", "rationale": "-Y fork prong",
             "parameters": {"Length": "prong_h", "Type": "Length"}},
            {"id": "s_bore", "type": "Sketch", "parameters": {}},
            {"id": "bore", "type": "Pocket", "rationale": "pivot cross bore "
             "through both prongs",
             "parameters": {"Length": "base_w", "Type": "Length",
                            "Length2": "base_w", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s_base", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "base_l", "h": "base_w"}}},
            {"id": "s_pA", "plane": "XY", "z": "base_h",
             "profile": {"builder": "rect",
                         "args": {"w": "base_l", "h": "prong_t", "cy": yc}}},
            {"id": "s_pB", "plane": "XY", "z": "base_h",
             "profile": {"builder": "rect",
                         "args": {"w": "base_l", "h": "prong_t",
                                  "cy": f"-({yc})"}}},
            {"id": "s_bore", "plane": "XZ", "z": "0",
             # XZ sketch maps cx->world X, cy->world Z: the pivot bore is
             # centred in X and raised into the prongs, extruded along Y.
             "profile": {"builder": "circle",
                         "args": {"r": "bore_r", "cx": "0",
                                  "cy": "base_h + prong_h*0.6"}}}],
         "dependencies": [
            {"source": "s_base", "target": "base", "kind": "profile"},
            {"source": "s_pA", "target": "prongA", "kind": "profile"},
            {"source": "base", "target": "prongA", "kind": "base"},
            {"source": "s_pB", "target": "prongB", "kind": "profile"},
            {"source": "prongA", "target": "prongB", "kind": "base"},
            {"source": "s_bore", "target": "bore", "kind": "profile"},
            {"source": "prongB", "target": "bore", "kind": "base"}]},
        [{"id": "gap_guard", "kind": "precondition", "tier": 1,
          "target": "base_w - 2*prong_t - gap - 4"},
         {"id": "bore_height", "kind": "precondition", "tier": 1,
          "target": "prong_h - 2*bore_r - 6"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "base_l"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "base_h + prong_h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "Sketch", "Pad",
               "Sketch", "Pocket"], "bore",
        # land on the base top, in the gap between the prongs
        [{"id": "base_gap", "kind": "flat_top", "z": "base_h",
          "land": {"type": "rect", "w": "base_l - 8", "h": "gap - 6",
                   "cx": "0", "cy": "0"}, "thickness": "base_h"}])


# =========================================================================== #
# 4. heat-exchanger header — thick disc, central bore, ring of tube holes (EX.)
# =========================================================================== #
def base_hx_header(rng):
    R = _u(rng, 30, 60, 1)
    T = _u(rng, 12, 26, 1)
    bore_r = _u(rng, 5, 0.3 * R, 0.5)
    n = rng.choice([6, 8, 10, 12])
    tube_r = _u(rng, 2.0, 4.0, 0.25)
    bc_lo = bore_r + tube_r + 4
    bc_hi = R - tube_r - 5
    if bc_lo >= bc_hi or 2 * bc_lo * math.sin(math.pi / n) <= 2 * tube_r + 2:
        raise ValueError("hx tube ring does not fit")
    bc_r = _u(rng, bc_lo, bc_hi, 0.5)
    v = {"R": R, "T": T, "bore_r": bore_r, "bc_r": bc_r, "tube_r": tube_r,
         "tube_n": float(n)}
    body = "pi*(R**2 - bore_r**2)*T - tube_n*pi*tube_r**2*T"
    return _draft(
        "hx_header", v,
        [{"step": 1, "eq": "V = pi(R^2-bore_r^2)*T - tube_n*pi*tube_r^2*T",
          "why": "heat-exchanger header: bored disc with a ring of through "
                 "tube holes; all disjoint through-cuts, exact"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_disc", "type": "Sketch", "parameters": {}},
            {"id": "disc", "type": "Pad", "rationale": "header disc + central "
             "manifold bore",
             "parameters": {"Length": "T", "Type": "Length"}},
            {"id": "s_tubes", "type": "Sketch", "parameters": {}},
            {"id": "tubes", "type": "Pocket", "rationale": "tube-sheet holes "
             "on a bolt circle, drilled down from the top face",
             "parameters": {"Length": "T + 2", "Type": "Length"}}],
         "sketches": [
            {"id": "s_disc", "plane": "XY",
             "profile": {"builder": "annulus",
                         "args": {"r_outer": "R", "r_inner": "bore_r"}}},
            {"id": "s_tubes", "plane": "XY", "z": "T",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "tube_n", "r_bc": "bc_r",
                                  "r_hole": "tube_r"}}}],
         "dependencies": [
            {"source": "s_disc", "target": "disc", "kind": "profile"},
            {"source": "disc", "target": "tubes", "kind": "base"},
            {"source": "s_tubes", "target": "tubes", "kind": "profile"}]},
        [{"id": "tube_ring_in", "kind": "precondition", "tier": 1,
          "target": "bc_r - tube_r - bore_r - 3"},
         {"id": "tube_ring_out", "kind": "precondition", "tier": 1,
          "target": "R - bc_r - tube_r - 3"},
         {"id": "tube_spacing", "kind": "precondition", "tier": 1,
          "target": "2*bc_r*sin(pi/tube_n) - 2*tube_r - 2"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "T"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "tubes",
        _hx_mount(bore_r, bc_r, tube_r))


def _hx_mount(bore_r, bc_r, tube_r):
    ring = _ring_land(bore_r, bc_r - tube_r)
    return [] if ring is None else [
        {"id": "inner_face", "kind": "flat_top", "z": "T",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"}, "thickness": "T"}]


# =========================================================================== #
# 5. wheel hub — turned barrel + flange with a pilot bore and bolt circle (EX.)
# =========================================================================== #
def base_wheel_hub(rng):
    flange_r = _u(rng, 35, 60, 1)
    flange_t = _u(rng, 8, 16, 1)
    barrel_r = _u(rng, 0.4 * flange_r, 0.6 * flange_r, 1)
    barrel_h = _u(rng, flange_t + 10, flange_t + 30, 1)
    bore_r = _u(rng, 6, 0.6 * barrel_r, 0.5)
    n = rng.choice([4, 5, 6])
    hole_r = _u(rng, 2.5, 4.5, 0.25)
    bc_lo = barrel_r + hole_r + 3
    bc_hi = flange_r - hole_r - 4
    if bc_lo >= bc_hi:
        raise ValueError("wheel hub bolt circle does not fit")
    bc_r = _u(rng, bc_lo, bc_hi, 0.5)
    v = {"flange_r": flange_r, "flange_t": flange_t, "barrel_r": barrel_r,
         "barrel_h": barrel_h, "bore_r": bore_r, "bc_r": bc_r,
         "hole_r": hole_r, "hole_n": float(n)}
    rev = ("pi*(flange_r**2 - bore_r**2)*flange_t"
           " + pi*(barrel_r**2 - bore_r**2)*(barrel_h - flange_t)")
    body = f"{rev} - hole_n*pi*hole_r**2*flange_t"
    feats, sk, deps = _rev(
        "s_hub", "hub",
        [["bore_r", "0"], ["flange_r", "0"], ["flange_r", "flange_t"],
         ["barrel_r", "flange_t"], ["barrel_r", "barrel_h"],
         ["bore_r", "barrel_h"]],
        "turned wheel hub: mounting flange + bearing barrel + pilot bore")
    feats += [
        {"id": "s_holes", "type": "Sketch", "parameters": {}},
        {"id": "holes", "type": "Pocket", "rationale": "lug bolt circle "
         "through the flange",
         "parameters": {"Length": "flange_t + 2", "Type": "Length",
                        "Length2": "flange_t + 2", "Type2": "Length",
                        "SideType": "Two sides"}}]
    sk.append({"id": "s_holes", "plane": "XY", "z": "0",
               "profile": {"builder": "bolt_circle",
                           "args": {"n": "hole_n", "r_bc": "bc_r",
                                    "r_hole": "hole_r"}}})
    deps += [{"source": "s_holes", "target": "holes", "kind": "profile"},
             {"source": "hub", "target": "holes", "kind": "base"}]
    return _draft(
        "wheel_hub", v,
        [{"step": 1, "eq": f"V_rev = {rev} (turned L-section)"},
         {"step": 2, "eq": "V = V_rev - hole_n*pi*hole_r^2*flange_t",
          "why": "lug holes pierce the flange only; bolt circle outside the "
                 "barrel, inside the flange rim"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "lug_inside", "kind": "precondition", "tier": 1,
          "target": "bc_r - hole_r - barrel_r - 2"},
         {"id": "lug_rim", "kind": "precondition", "tier": 1,
          "target": "flange_r - bc_r - hole_r - 3"},
         {"id": "lug_spacing", "kind": "precondition", "tier": 1,
          "target": "2*bc_r*sin(pi/hole_n) - 2*hole_r"},
         {"id": "rev_tool", "kind": "feature_volume", "feature": "hub",
          "tier": 1, "tol_rel": 1e-6, "target": rev},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*flange_r"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "barrel_h"}],
        body, ["Sketch", "Revolution", "Sketch", "Pocket"], "holes",
        _wheel_mount(barrel_r, bore_r, barrel_h, flange_t))


def _wheel_mount(barrel_r, bore_r, barrel_h, flange_t):
    ring = _ring_land(bore_r, barrel_r)
    return [] if ring is None else [
        {"id": "barrel_top", "kind": "flat_top", "z": "barrel_h",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"},
         "thickness": "barrel_h - flange_t"}]


# =========================================================================== #
# 6. compressor casing — hollow cylinder with two end flanges (EXACT)
# =========================================================================== #
def base_compressor_casing(rng):
    out_r = _u(rng, 30, 55, 1)
    wall = _u(rng, 4, 9, 0.5)
    length = _u(rng, 50, 110, 2)
    fl_r = _u(rng, out_r + 6, out_r + 16, 1)
    fl_t = _u(rng, 6, 12, 0.5)
    v = {"out_r": out_r, "wall": wall, "length": length, "fl_r": fl_r,
         "fl_t": fl_t}
    # two end flanges (fl_r x fl_t) + the barrel between them; the barrel is a
    # tube (out_r, in_r) over the full length, flanges are annular discs whose
    # bore matches the barrel bore, sitting at each end -> they merge into the
    # barrel over fl_t, so model the whole thing as ONE revolved profile.
    body = ("pi*(fl_r**2 - (out_r - wall)**2)*fl_t*2"
            " + pi*(out_r**2 - (out_r - wall)**2)*(length - 2*fl_t)")
    feats, sk, deps = _rev(
        "s_case", "casing",
        [["out_r - wall", "0"], ["fl_r", "0"], ["fl_r", "fl_t"],
         ["out_r", "fl_t"], ["out_r", "length - fl_t"],
         ["fl_r", "length - fl_t"], ["fl_r", "length"],
         ["out_r - wall", "length"]],
        "compressor casing: bored barrel with an integral mounting flange at "
        "each end, turned in one setup")
    return _draft(
        "compressor_casing", v,
        [{"step": 1, "eq": "V = 2 flange rings*fl_t + barrel tube*(L-2 fl_t)",
          "why": "hollow cylinder with a flange at each end; all annular, one "
                 "revolved profile, exact"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "out_r - wall - 10"},
         {"id": "flange_step", "kind": "precondition", "tier": 1,
          "target": "fl_r - out_r - 4"},
         {"id": "length_guard", "kind": "precondition", "tier": 1,
          "target": "length - 2*fl_t - 10"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*fl_r"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "length"}],
        body, ["Sketch", "Revolution"], "casing",
        # land on an end flange face ring
        _casing_mount(out_r, wall, fl_r))


def _casing_mount(out_r, wall, fl_r):
    ring = _ring_land(out_r, fl_r)
    return [] if ring is None else [
        {"id": "flange_face", "kind": "flat_top", "z": "0",
         "land": {"type": "rect", "w": f"{2 * ring[1]}", "h": f"{2 * ring[1]}",
                  "cx": f"{ring[0]}", "cy": "0"}, "thickness": "fl_t"}]


BASES.update({
    "impeller": base_impeller,
    "turbine_disk": base_turbine_disk,
    "clevis_mount": base_clevis_mount,
    "hx_header": base_hx_header,
    "wheel_hub": base_wheel_hub,
    "compressor_casing": base_compressor_casing,
})
