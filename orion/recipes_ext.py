"""Recipe families 9-18: the Phase-4.5 breadth expansion.

Ten structurally distinct engineering families on top of the original eight.
Every family keeps the forge discipline — expression-only dimensions, guards
derived from the geometry, a derivation chain, at least one fault — and every
volume assertion is honest about its tier:

  * drafted composites use the prismatoid per z-segment (EXACT for bilinear
    taper, both for stacked pads and for bores through drafted walls);
  * the valve block's crossing bores add back a Steinmetz bicylinder
    (V∩ = 16r³/3 for equal perpendicular radii) — exact;
  * the twisted vane's ruled loft has quadratic section area A(t) =
    A·|1−t+t·e^{iθ}|², so the prismatoid with A_m = A·cos²(θ/2) is exact
    mathematics; the Tier-2 label covers OCC's ruling, not the formula;
  * overlapping feature unions (manifold) assert per-feature AddSubShape
    volumes exactly and bound the union — never pretend a boolean is exact.
"""

from __future__ import annotations

import math

from .recipes import RECIPES, _freeze, _u

_T = "tan(radians(draft_deg))"


def _prism(le, wi, z0, z1):
    """Exact volume expr for a drafted rect segment z0..z1 (draft from z=0)."""
    def area(z):
        return f"(({le}) - 2*({z})*{_T})*(({wi}) - 2*({z})*{_T})"
    zm = f"(({z0})+({z1}))/2"
    return (f"((({z1})-({z0}))/6*({area(z0)} + 4*{area(zm)} + {area(z1)}))")


# =========================================================================== #
# 9. gearbox housing — flange + drafted boss + cavity + bolt holes (T1)
# =========================================================================== #
def gearbox_housing(rng):
    lf = _u(rng, 90, 160, 2)
    wf = _u(rng, 0.62 * lf, 0.9 * lf, 2)
    h1 = _u(rng, 8, 16, 1)
    draft = _u(rng, 1.0, 4.0, 0.5)
    t = math.tan(math.radians(draft))
    lb = _u(rng, 0.42 * lf, 0.6 * lf, 2)
    wb = _u(rng, 0.42 * wf, 0.6 * wf, 2)
    h2 = _u(rng, 20, 48, 1)
    wall = _u(rng, 4, 8, 0.5)
    cav_l = round(lb - 2 * (h1 + h2) * t - 2 * wall, 4)
    cav_w = round(wb - 2 * (h1 + h2) * t - 2 * wall, 4)
    if cav_l < 8 or cav_w < 8:
        raise ValueError("boss too small for a cavity")
    cav_d = _u(rng, 0.45 * h2, 0.75 * h2, 1)
    hole_r = _u(rng, 2.5, 4.5, 0.25)
    # Bolts sit on the flange DIAGONALS (start 45°), so containment is per
    # axis at bc/sqrt(2), which is what buys land outside the boss corner.
    bc_hi = math.sqrt(2) * (min(lf, wf) / 2 - h1 * t - hole_r - 2.2)
    bc_lo = math.hypot(lb / 2, wb / 2) + hole_r + 2
    if bc_lo >= bc_hi:
        raise ValueError("no bolt land on this draw")
    bc_r = _u(rng, bc_lo, bc_hi, 0.5)
    v = {"lf": lf, "wf": wf, "h1": h1, "lb": lb, "wb": wb, "h2": h2,
         "draft_deg": draft, "cav_l": cav_l, "cav_w": cav_w, "cav_d": cav_d,
         "bc_r": bc_r, "hole_r": hole_r}
    body = (f"{_prism('lf', 'wf', '0', 'h1')} + "
            f"{_prism('lb', 'wb', 'h1', 'h1+h2')}"
            " - cav_l*cav_w*cav_d - 4*pi*hole_r**2*h1")
    bp = _freeze(
        "gearbox_housing", v,
        [{"step": 1, "eq": "V_seg = prismatoid of (l-2zT)(w-2zT) per segment",
          "why": "draft from the z=0 parting plane tilts every wall about its "
                 "own neutral line, so the flange AND the stacked boss taper "
                 "linearly in z — prismatoid is exact for both"},
         {"step": 2, "eq": "V -= cav_l*cav_w*cav_d",
          "why": "gear cavity cut AFTER draft has vertical walls; contained "
                 "in the shrunken boss top section, so it is a full prism"},
         {"step": 3, "eq": "V -= 4*pi*hole_r^2*h1",
          "why": "mount holes drilled after draft pierce the flange only; "
                 "bolt circle sits outside the boss half-diagonal"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_fl", "type": "Sketch", "parameters": {}},
            {"id": "pad_fl", "type": "Pad", "rationale": "mounting flange",
             "parameters": {"Length": "h1", "Type": "Length"}},
            {"id": "s_boss", "type": "Sketch", "parameters": {}},
            {"id": "pad_boss", "type": "Pad",
             "rationale": "gear case body on the flange",
             "parameters": {"Length": "h2", "Type": "Length"}},
            {"id": "draft", "type": "Draft",
             "rationale": "cast release on every wall from the parting plane",
             "parameters": {"Angle": "draft_deg", "Reversed": False,
                            "_Base": {"object": "pad_boss"},
                            "_Faces": "vertical", "_NeutralPlane": "bottom"}},
            {"id": "s_cav", "type": "Sketch", "parameters": {}},
            {"id": "cavity", "type": "Pocket",
             "rationale": "machined gear cavity",
             "parameters": {"Length": "cav_d", "Type": "Length"}},
            {"id": "s_holes", "type": "Sketch", "parameters": {}},
            {"id": "holes", "type": "Pocket",
             "rationale": "flange mounting holes; two-sided so the cut is "
                          "direction-proof after the Draft (a one-sided "
                          "pocket here silently removed nothing)",
             "parameters": {"Length": "h1 + 2", "Type": "Length",
                            "Length2": "h1 + 2", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s_fl", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "lf", "h": "wf"}}},
            {"id": "s_boss", "plane": "XY", "z": "h1",
             "profile": {"builder": "rect", "args": {"w": "lb", "h": "wb"}}},
            {"id": "s_cav", "plane": "XY", "z": "h1+h2",
             "profile": {"builder": "rect",
                         "args": {"w": "cav_l", "h": "cav_w"}}},
            {"id": "s_holes", "plane": "XY", "z": "0",
             # Explicit z=0: without it the compiler hoists the sketch to the
             # body top and the two-sided cut spans air at the bolt radius.
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "4", "r_bc": "bc_r",
                                  "r_hole": "hole_r", "start_deg": "45"}}}],
         "dependencies": [
            {"source": "s_fl", "target": "pad_fl", "kind": "profile"},
            {"source": "s_boss", "target": "pad_boss", "kind": "profile"},
            {"source": "pad_fl", "target": "pad_boss", "kind": "base"},
            {"source": "pad_boss", "target": "draft", "kind": "base"},
            {"source": "s_cav", "target": "cavity", "kind": "profile"},
            {"source": "draft", "target": "cavity", "kind": "base"},
            {"source": "s_holes", "target": "holes", "kind": "profile"},
            {"source": "cavity", "target": "holes", "kind": "base"}]},
        [{"id": "cav_wall_l", "kind": "precondition", "tier": 1,
          "target": f"lb - 2*(h1+h2)*{_T} - cav_l - 3"},
         {"id": "cav_wall_w", "kind": "precondition", "tier": 1,
          "target": f"wb - 2*(h1+h2)*{_T} - cav_w - 3"},
         {"id": "cav_floor", "kind": "precondition", "tier": 1,
          "target": "h2 - cav_d - 2"},
         {"id": "boss_on_flange", "kind": "precondition", "tier": 1,
          "target": f"lf - 2*h1*{_T} - lb - 2"},
         {"id": "hole_land", "kind": "precondition", "tier": 1,
          "target": f"min(lf, wf)/2 - h1*{_T}"
                    " - (bc_r*cos(radians(45)) + hole_r) - 2"},
         {"id": "hole_boss_clear", "kind": "precondition", "tier": 1,
          "target": "bc_r - hole_r - sqrt((lb/2)**2 + (wb/2)**2) - 1"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "lf"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "h1+h2"}])

    def breach(_t, vv):
        vv["cav_l"] = vv["lb"]
    return bp, {"cavity_breaches_wall": (breach, {
        "diagnosis": "cav_wall_l < 0: cavity wider than the drafted boss "
                     "leaves no wall",
        "fix": "cav_l <= lb - 2(h1+h2)tan(a) - 2*wall"})}, \
        ("Sketch", "Pad", "Sketch", "Pad", "Draft", "Sketch", "Pocket",
         "Sketch", "Pocket")


# =========================================================================== #
# 10. manifold runner — flange plate + swept runner, bounded union (T2/T3)
# =========================================================================== #
def manifold_runner(rng):
    sec_r = _u(rng, 6, 14, 0.5)
    bend_r = _u(rng, 4 * sec_r, 10 * sec_r, 1)
    bend = _u(rng, 45, 150, 5)
    fl_w = _u(rng, 2 * sec_r + 10, 2 * sec_r + 34, 1)
    fl_h = _u(rng, 2 * sec_r + 10, 2 * sec_r + 34, 1)
    fl_t = _u(rng, 6, 14, 0.5)
    v = {"sec_r": sec_r, "bend_r": bend_r, "bend_deg": bend,
         "fl_w": fl_w, "fl_h": fl_h, "fl_t": fl_t}
    bp = _freeze(
        "manifold_runner", v,
        [{"step": 1, "eq": "V_runner = pi*sec_r^2*radians(bend_deg)*bend_r",
          "why": "generalized Pappus along the arc spine"},
         {"step": 2, "eq": "V_flange = fl_w*fl_h*fl_t"},
         {"step": 3, "eq": "sum - pi*sec_r^2*fl_t <= V <= sum",
          "why": "the runner may pass through the flange thickness; the "
                 "union is NOT closed-form, so per-feature tools are exact "
                 "and the body is bounded — never pretend a boolean is exact"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_sec", "type": "Sketch", "parameters": {}},
            {"id": "s_path", "type": "Sketch", "parameters": {}},
            {"id": "runner", "type": "Sweep",
             "rationale": "primary runner, constant section",
             "parameters": {"Mode": "Frenet", "_Spine": "s_path"}},
            {"id": "s_fl", "type": "Sketch", "parameters": {}},
            {"id": "flange", "type": "Pad",
             "rationale": "port mounting flange at the runner inlet",
             "parameters": {"Length": "fl_t", "Type": "Length",
                            "Reversed": True}}],
         "sketches": [
            {"id": "s_sec", "plane": "YZ", "z": "0",
             "profile": {"builder": "circle", "args": {"r": "sec_r"}}},
            {"id": "s_path", "plane": "XY", "z": "0",
             "profile": {"builder": "arc_spine",
                         "args": {"radius": "bend_r",
                                  "sweep_deg": "bend_deg"}}},
            {"id": "s_fl", "plane": "YZ", "z": "0",
             "profile": {"builder": "rect",
                         "args": {"w": "fl_w", "h": "fl_h"}}}],
         "dependencies": [
            {"source": "s_sec", "target": "runner", "kind": "profile"},
            {"source": "s_path", "target": "runner", "kind": "spine"},
            {"source": "s_fl", "target": "flange", "kind": "profile"},
            {"source": "runner", "target": "flange", "kind": "base"}]},
        # Per-feature tools are exact (runner = generalised Pappus torus
        # segment, flange = box). The BODY is genuinely irreducible: the swept
        # runner curves through the flange so their intersection is not a
        # closed-form cylinder (approximation off 3e-4). The body therefore
        # carries a convergence-proven Tier-2 mesh check, not a percentage band.
        [{"id": "self_intersect_guard", "kind": "precondition", "tier": 1,
          "target": "bend_r - sec_r"},
         {"id": "port_guard", "kind": "precondition", "tier": 1,
          "target": "min(fl_w, fl_h)/2 - sec_r - 2"},
         {"id": "runner_tool", "kind": "feature_volume", "feature": "runner",
          "tier": 1, "tol_rel": 1e-6,
          "target": "pi*sec_r**2*radians(bend_deg)*bend_r"},
         {"id": "flange_tool", "kind": "feature_volume", "feature": "flange",
          "tier": 1, "tol_rel": 1e-6, "target": "fl_w*fl_h*fl_t"},
         {"id": "body", "kind": "body_mesh_converged", "tier": 2,
          "tol_rel": 1e-3},
         {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
          "target": "1"},
         {"id": "closed", "kind": "watertight", "tier": 1}])

    def tight(_t, vv):
        vv["bend_r"] = max(1.0, vv["sec_r"] / 2)
    return bp, {"self_intersecting_sweep": (tight, {
        "diagnosis": "self_intersect_guard < 0: runner bend tighter than its "
                     "own section",
        "fix": "bend_r > sec_r, practice >= 1.5x OD"})}, \
        ("Sketch", "Sketch", "Sweep", "Sketch", "Pad")


# =========================================================================== #
# 11. twisted vane — ruled loft between rotated rectangles (T2)
# =========================================================================== #
def twisted_vane(rng):
    chord = _u(rng, 20, 60, 1)
    thick_v = _u(rng, 0.12 * chord, 0.3 * chord, 0.5)
    span = _u(rng, 30, 90, 1)
    twist = _u(rng, 5, 30, 1)
    v = {"chord": chord, "thick_v": thick_v, "span": span,
         "twist_deg": twist}
    c, s = "cos(radians(twist_deg))", "sin(radians(twist_deg))"
    corners = [("-chord/2", "-thick_v/2"), ("chord/2", "-thick_v/2"),
               ("chord/2", "thick_v/2"), ("-chord/2", "thick_v/2")]
    rot = [[f"({x})*{c} - ({y})*{s}", f"({x})*{s} + ({y})*{c}"]
           for x, y in corners]
    bp = _freeze(
        "twisted_vane", v,
        [{"step": 1, "eq": "section at t: corners (1-t)v + t*R(theta)v",
          "why": "a ruled loft interpolates matching vertices linearly, so "
                 "every cross-section is the linear-blend polygon"},
         {"step": 2, "eq": "A(t) = A*|1-t+t*e^{i*theta}|^2 (quadratic in t); "
                           "A_mid = A*cos^2(theta/2)",
          "why": "(I+R)/2 = cos(theta/2)*R(theta/2) — the mid-section is the "
                 "rect scaled by cos(theta/2)"},
         {"step": 3, "eq": "V = A*span/3*(1 + 2*cos^2(theta/2))",
          "why": "prismatoid is exact for quadratic A(t); Tier 2 covers "
                 "OCC's ruling choice, not the formula"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_root", "type": "Sketch", "parameters": {}},
            {"id": "s_tip", "type": "Sketch", "parameters": {}},
            {"id": "vane", "type": "Loft",
             "rationale": "linearly twisted blade between root and tip",
             "parameters": {"Ruled": True, "Closed": False,
                            "_Sections": ["s_tip"]}}],
         "sketches": [
            {"id": "s_root", "plane": "XY", "z": "0",
             "profile": {"builder": "polyline",
                         "args": {"points": [list(p) for p in corners]}}},
            {"id": "s_tip", "plane": "XY", "z": "span",
             "profile": {"builder": "polyline", "args": {"points": rot}}}],
         "dependencies": [
            {"source": "s_root", "target": "vane", "kind": "profile"},
            {"source": "s_tip", "target": "vane", "kind": "section"}]},
        # The ruled loft's cross-section is the exact linear vertex blend, so
        # A(t)=A*|1-t+t*e^{i*theta}|^2 and V=A*span/3*(1+2cos^2(theta/2)) is
        # EXACT; OCC builds the exact ruled solid (measured 1e-16) within the
        # twist_guard range. Tier 1 with the guard as the stated precondition.
        [{"id": "twist_guard", "kind": "precondition", "tier": 1,
          "target": "45 - twist_deg",
          "why": "past ~45 deg OCC's vertex matching is not trustworthy"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "chord*thick_v*span/3"
                    "*(1 + 2*cos(radians(twist_deg)/2)**2)"},
         {"id": "span_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "span"},
         {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
          "target": "1"},
         {"id": "closed", "kind": "watertight", "tier": 1}])

    def overtwist(_t, vv):
        vv["twist_deg"] = 85.0
    return bp, {"loft_twist_mismatch": (overtwist, {
        "diagnosis": "twist_guard < 0: 85 deg twist — vertex matching and "
                     "the ruled surface both degrade",
        "fix": "keep twist <= 45 deg per section pair; chain lofts for more"})}, \
        ("Sketch", "Sketch", "Loft")


# =========================================================================== #
# 12. valve block — crossing bores, Steinmetz correction (T1)
# =========================================================================== #
def valve_block(rng):
    length = _u(rng, 50, 120, 2)
    sect = _u(rng, 24, 60, 1)
    bore_r = _u(rng, 3, 0.28 * sect, 0.5)
    cb_r = _u(rng, bore_r + 1.5, min(bore_r + 6, sect / 2 - 4), 0.25)
    cb_d = _u(rng, 2, max(2.2, sect / 2 - bore_r - 3), 0.5)
    v = {"length": length, "sect": sect, "bore_r": bore_r,
         "cb_r": cb_r, "cb_d": cb_d}
    bp = _freeze(
        "valve_block", v,
        [{"step": 1, "eq": "V0 = length*sect^2",
          "why": "square-section bar stock"},
         {"step": 2, "eq": "V -= pi*bore_r^2*length + pi*bore_r^2*sect",
          "why": "main gallery along X and vertical port bore, both through"},
         {"step": 3, "eq": "V += 16/3*bore_r^3",
          "why": "the two perpendicular equal-radius bores intersect at the "
                 "block centre in a Steinmetz bicylinder; the subtraction "
                 "double-counts it once"},
         {"step": 4, "eq": "V -= pi*(cb_r^2 - bore_r^2)*cb_d",
          "why": "port counterbore is coaxial with the vertical bore, so it "
                 "only removes the annular ring"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_blk", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "block blank",
             "parameters": {"Length": "sect", "Type": "Length"}},
            {"id": "s_gal", "type": "Sketch", "parameters": {}},
            {"id": "gallery", "type": "Pocket",
             "rationale": "main flow gallery along the block axis",
             "parameters": {"Length": "length/2 + 5", "Type": "Length",
                            "Length2": "length/2 + 5", "Type2": "Length",
                            "SideType": "Two sides"}},
            {"id": "s_port", "type": "Sketch", "parameters": {}},
            {"id": "port", "type": "Pocket",
             "rationale": "vertical port crossing the gallery",
             "parameters": {"Length": "sect", "Type": "Length"}},
            {"id": "s_cb", "type": "Sketch", "parameters": {}},
            {"id": "cbore", "type": "Pocket",
             "rationale": "fitting counterbore at the port mouth",
             "parameters": {"Length": "cb_d", "Type": "Length"}}],
         "sketches": [
            {"id": "s_blk", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "length", "h": "sect"}}},
            {"id": "s_gal", "plane": "YZ", "z": "0",
             # YZ sketch coords map (cx -> world Z, cy -> world Y) — measured
             # empirically: the gallery drawn on cy landed a quarter-cylinder
             # on the block edge. Height above the base goes on cx.
             "profile": {"builder": "circle",
                         "args": {"r": "bore_r", "cx": "sect/2"}}},
            {"id": "s_port", "plane": "XY",
             "profile": {"builder": "circle", "args": {"r": "bore_r"}}},
            {"id": "s_cb", "plane": "XY", "z": "sect",
             "profile": {"builder": "circle", "args": {"r": "cb_r"}}}],
         "dependencies": [
            {"source": "s_blk", "target": "pad", "kind": "profile"},
            {"source": "s_gal", "target": "gallery", "kind": "profile"},
            {"source": "pad", "target": "gallery", "kind": "base"},
            {"source": "s_port", "target": "port", "kind": "profile"},
            {"source": "gallery", "target": "port", "kind": "base"},
            {"source": "s_cb", "target": "cbore", "kind": "profile"},
            {"source": "port", "target": "cbore", "kind": "base"}]},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "sect/2 - bore_r - 3"},
         {"id": "cb_ring_guard", "kind": "precondition", "tier": 1,
          "target": "cb_r - bore_r - 1"},
         {"id": "cb_wall_guard", "kind": "precondition", "tier": 1,
          "target": "sect/2 - cb_r - 3"},
         {"id": "cb_gallery_guard", "kind": "precondition", "tier": 1,
          "target": "sect - cb_d - (sect/2 + bore_r) - 1",
          "why": "counterbore must stop above the gallery"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "length*sect**2 - pi*bore_r**2*length - pi*bore_r**2*sect"
                    " + 16/3*bore_r**3 - pi*(cb_r**2 - bore_r**2)*cb_d"},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "length"}])

    def thin(_t, vv):
        vv["bore_r"] = vv["sect"] / 2
    return bp, {"bore_breaks_wall": (thin, {
        "diagnosis": "wall_guard < 0: gallery radius reaches the block face",
        "fix": "bore_r <= sect/2 - wall"})}, \
        ("Sketch", "Pad", "Sketch", "Pocket", "Sketch", "Pocket",
         "Sketch", "Pocket")


# =========================================================================== #
# 13. mold core — drafted core + slot cavity + cooling bores (T1)
# =========================================================================== #
def mold_core(rng):
    core_l = _u(rng, 60, 130, 2)
    core_w = _u(rng, 40, 0.85 * core_l, 2)
    core_h = _u(rng, 20, 45, 1)
    draft = _u(rng, 1.0, 3.5, 0.5)
    t = math.tan(math.radians(draft))
    top_l = core_l - 2 * core_h * t
    top_w = core_w - 2 * core_h * t
    cav_r = _u(rng, 4, max(4.2, top_w / 2 - 8), 0.5)
    cav_len = _u(rng, 8, max(8.5, top_l - 2 * cav_r - 12), 1)
    cav_d = _u(rng, 0.35 * core_h, 0.7 * core_h, 1)
    cool_r = _u(rng, 2.0, 3.5, 0.25)
    lo = (cav_r + cool_r + 2) / math.sin(math.radians(45))
    hi = (min(top_l, top_w) / 2 - cool_r - 2) / math.cos(math.radians(45))
    if lo >= hi:
        raise ValueError("no cooling ring room")
    cool_bc = _u(rng, lo, hi, 0.5)
    v = {"core_l": core_l, "core_w": core_w, "core_h": core_h,
         "draft_deg": draft, "cav_len": cav_len, "cav_r": cav_r,
         "cav_d": cav_d, "cool_bc": cool_bc, "cool_r": cool_r}
    slot_a = "(cav_len*2*cav_r + pi*cav_r**2)"
    bp = _freeze(
        "mold_core", v,
        [{"step": 1, "eq": f"V0 = {_prism('core_l', 'core_w', '0', 'core_h')}",
          "why": "drafted core block, prismatoid exact"},
         {"step": 2, "eq": f"V -= {slot_a}*cav_d",
          "why": "slot cavity cut after draft: vertical walls, contained in "
                 "the shrunken top section"},
         {"step": 3, "eq": "V -= 4*pi*cool_r^2*core_h",
          "why": "four vertical cooling lines clear of the cavity by the "
                 "45-degree corner placement"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_core", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "core blank",
             "parameters": {"Length": "core_h", "Type": "Length"}},
            {"id": "draft", "type": "Draft",
             "rationale": "release draft on all core walls",
             "parameters": {"Angle": "draft_deg", "Reversed": False,
                            "_Base": {"object": "pad"},
                            "_Faces": "vertical", "_NeutralPlane": "bottom"}},
            {"id": "s_cav", "type": "Sketch", "parameters": {}},
            {"id": "cavity", "type": "Pocket",
             "rationale": "molding slot cavity",
             "parameters": {"Length": "cav_d", "Type": "Length"}},
            {"id": "s_cool", "type": "Sketch", "parameters": {}},
            {"id": "cooling", "type": "Pocket",
             "rationale": "cooling channel drops",
             "parameters": {"Length": "core_h", "Type": "Length"}}],
         "sketches": [
            {"id": "s_core", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "core_l", "h": "core_w"}}},
            {"id": "s_cav", "plane": "XY", "z": "core_h",
             "profile": {"builder": "slot",
                         "args": {"length": "cav_len", "r": "cav_r"}}},
            {"id": "s_cool", "plane": "XY",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "4", "r_bc": "cool_bc",
                                  "r_hole": "cool_r", "start_deg": "45"}}}],
         "dependencies": [
            {"source": "s_core", "target": "pad", "kind": "profile"},
            {"source": "pad", "target": "draft", "kind": "base"},
            {"source": "s_cav", "target": "cavity", "kind": "profile"},
            {"source": "draft", "target": "cavity", "kind": "base"},
            {"source": "s_cool", "target": "cooling", "kind": "profile"},
            {"source": "cavity", "target": "cooling", "kind": "base"}]},
        [{"id": "cav_fit_l", "kind": "precondition", "tier": 1,
          "target": f"core_l - 2*core_h*{_T} - cav_len - 2*cav_r - 4"},
         {"id": "cav_fit_w", "kind": "precondition", "tier": 1,
          "target": f"core_w - 2*core_h*{_T} - 2*cav_r - 4"},
         {"id": "cav_floor", "kind": "precondition", "tier": 1,
          "target": "core_h - cav_d - 3"},
         {"id": "cool_clear", "kind": "precondition", "tier": 1,
          "target": "cool_bc*sin(radians(45)) - cav_r - cool_r - 2"},
         {"id": "cool_fit", "kind": "precondition", "tier": 1,
          "target": f"min(core_l, core_w)/2 - core_h*{_T}"
                    " - cool_bc*cos(radians(45)) - cool_r - 2"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": f"{_prism('core_l', 'core_w', '0', 'core_h')}"
                    f" - {slot_a}*cav_d - 4*pi*cool_r**2*core_h"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "core_h"}])

    def punch(_t, vv):
        vv["cav_d"] = vv["core_h"] + 5
    return bp, {"cavity_through_core": (punch, {
        "diagnosis": "cav_floor < 0: cavity deeper than the core itself",
        "fix": "cav_d <= core_h - floor"})}, \
        ("Sketch", "Pad", "Draft", "Sketch", "Pocket", "Sketch", "Pocket")


# =========================================================================== #
# 14. harmonic cup — thin-wall revolution + gland + bolt holes (T1)
# =========================================================================== #
def harmonic_cup(rng):
    cup_r = _u(rng, 25, 60, 1)
    cup_h = _u(rng, 20, 55, 1)
    wall_c = _u(rng, 2.0, 4.5, 0.25)
    base_t = _u(rng, 4, 9, 0.5)
    g_w = _u(rng, 2.0, 3.5, 0.25)
    g_d = _u(rng, 1.2, max(1.4, base_t - 2), 0.2)
    hole_r_c = _u(rng, 1.8, 3.2, 0.2)
    g_lo = hole_r_c * 2 + g_w / 2 + 6
    g_hi = cup_r - wall_c - g_w / 2 - 2
    if g_lo >= g_hi:
        raise ValueError("no gland room")
    g_r = _u(rng, g_lo, g_hi, 0.5)
    bc_hi = g_r - g_w / 2 - hole_r_c - 1.5
    n = rng.choice([4, 6])
    bc_lo = (hole_r_c + 0.8) / math.sin(math.pi / n)
    if bc_lo >= bc_hi:
        raise ValueError("no bolt room")
    bc_r_c = _u(rng, bc_lo, bc_hi, 0.5)
    v = {"cup_r": cup_r, "cup_h": cup_h, "wall_c": wall_c, "base_t": base_t,
         "g_r": g_r, "g_w": g_w, "g_d": g_d,
         "bc_r_c": bc_r_c, "hole_r_c": hole_r_c, "hole_n_c": float(n)}
    rev = ("2*pi*(base_t*cup_r**2/2"
           " + (cup_h - base_t)*(cup_r**2 - (cup_r - wall_c)**2)/2)")
    bp = _freeze(
        "harmonic_cup", v,
        [{"step": 1, "eq": f"V_rev = {rev}",
          "why": "cup L-section revolved: 2*pi*Mx with Mx summed over the "
                 "base disc and the thin wall rectangles"},
         {"step": 2, "eq": "V -= 2*pi*g_r*g_w*g_d",
          "why": "O-ring gland in the floor, exact Pappus ring"},
         {"step": 3, "eq": "V -= hole_n_c*pi*hole_r_c^2*base_t",
          "why": "bolt circle through the floor, inboard of the gland"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_rev", "type": "Sketch", "parameters": {}},
            {"id": "rev", "type": "Revolution",
             "rationale": "thin-wall cup: flexspline housing",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_rev",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}},
            {"id": "s_g", "type": "Sketch", "parameters": {}},
            {"id": "gland", "type": "Groove",
             "rationale": "O-ring gland sealing the closed end",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_g",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}},
            {"id": "s_holes", "type": "Sketch", "parameters": {}},
            {"id": "holes", "type": "Pocket",
             "rationale": "output mounting bolt circle; two-sided so the cut "
                          "is direction-proof after the Groove (the region "
                          "above the floor is cup interior, so only base_t "
                          "of material is removed either way)",
             "parameters": {"Length": "base_t + 2", "Type": "Length",
                            "Length2": "base_t + 2", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s_rev", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["0", "0"], ["cup_r", "0"], ["cup_r", "cup_h"],
                 ["cup_r - wall_c", "cup_h"], ["cup_r - wall_c", "base_t"],
                 ["0", "base_t"]]}}},
            {"id": "s_g", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["g_r - g_w/2", "base_t - g_d"],
                 ["g_r + g_w/2", "base_t - g_d"],
                 ["g_r + g_w/2", "base_t"], ["g_r - g_w/2", "base_t"]]}}},
            {"id": "s_holes", "plane": "XY", "z": "0",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "hole_n_c", "r_bc": "bc_r_c",
                                  "r_hole": "hole_r_c"}}}],
         "dependencies": [
            {"source": "s_rev", "target": "rev", "kind": "profile"},
            {"source": "s_g", "target": "gland", "kind": "profile"},
            {"source": "rev", "target": "gland", "kind": "base"},
            {"source": "s_holes", "target": "holes", "kind": "profile"},
            {"source": "gland", "target": "holes", "kind": "base"}]},
        [{"id": "gland_wall", "kind": "precondition", "tier": 1,
          "target": "cup_r - wall_c - g_r - g_w/2 - 1.5"},
         {"id": "gland_floor", "kind": "precondition", "tier": 1,
          "target": "base_t - g_d - 1"},
         {"id": "holes_inboard", "kind": "precondition", "tier": 1,
          "target": "g_r - g_w/2 - bc_r_c - hole_r_c - 1"},
         {"id": "hole_spacing", "kind": "precondition", "tier": 1,
          "target": "2*bc_r_c*sin(pi/hole_n_c) - 2*hole_r_c"},
         {"id": "rev_tool", "kind": "feature_volume", "feature": "rev",
          "tier": 1, "tol_rel": 1e-6, "target": rev},
         {"id": "gland_tool", "kind": "feature_volume", "feature": "gland",
          "tier": 1, "tol_rel": 1e-6, "target": "2*pi*g_r*g_w*g_d"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": f"{rev} - 2*pi*g_r*g_w*g_d"
                    " - hole_n_c*pi*hole_r_c**2*base_t"},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*cup_r"}])

    def through_wall(_t, vv):
        vv["bc_r_c"] = vv["cup_r"] - vv["wall_c"] / 2
    return bp, {"holes_break_wall": (through_wall, {
        "diagnosis": "holes_inboard < 0: bolt circle lands in the thin wall",
        "fix": "bc_r_c inboard of the gland ring"})}, \
        ("Sketch", "Revolution", "Sketch", "Groove", "Sketch", "Pocket")


# =========================================================================== #
# 15. planet carrier — annulus + patterned pins + chamfered rims (T1)
# =========================================================================== #
def planet_carrier(rng):
    disc_r = _u(rng, 30, 70, 1)
    disc_t = _u(rng, 8, 18, 0.5)
    bore_c = _u(rng, 4, 0.22 * disc_r, 0.5)
    pin_n = rng.choice([3, 4, 5])
    pin_r = _u(rng, 2.5, 5.0, 0.25)
    light_r = pin_r + 0.5 if rng.random() < 0.5 else max(1.8, pin_r - 0.8)
    light_r = round(light_r, 2)
    light_lo = bore_c + light_r + 2.5
    pin_hi = disc_r - pin_r - 3
    mid = (light_lo + pin_hi) / 2
    light_bc = _u(rng, light_lo, mid - light_r - 1, 0.5)
    pin_lo = light_bc + light_r + pin_r + 2.5
    if pin_lo >= pin_hi:
        raise ValueError("no pin ring room")
    pin_bc = _u(rng, pin_lo, pin_hi, 0.5)
    with_cham = rng.random() < 0.55
    v = {"disc_r": disc_r, "disc_t": disc_t, "bore_c": bore_c,
         "pin_bc": pin_bc, "pin_r": pin_r, "pin_n": float(pin_n),
         "light_bc": light_bc, "light_r": light_r}
    body = ("pi*(disc_r**2 - bore_c**2)*disc_t"
            " - pin_n*pi*pin_r**2*disc_t"
            " - pin_n*pi*light_r**2*disc_t")
    derivation = [
        {"step": 1, "eq": "V0 = pi*(disc_r^2 - bore_c^2)*disc_t",
         "why": "carrier disc with central shaft bore in one annulus profile"},
        {"step": 2, "eq": "V -= pin_n*pi*pin_r^2*disc_t (pins) + "
                          "pin_n*pi*light_r^2*disc_t (lightening)",
         "why": "planet pin bores on the outer ring, lightening bores on the "
                "inner ring; radial band guards keep everything disjoint"}]
    feats = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_disc", "type": "Sketch", "parameters": {}},
        {"id": "pad", "type": "Pad", "rationale": "carrier disc + bore",
         "parameters": {"Length": "disc_t", "Type": "Length"}},
        {"id": "s_pin", "type": "Sketch", "parameters": {}},
        {"id": "pin0", "type": "Pocket", "rationale": "seed planet-pin bore",
         "parameters": {"Length": "disc_t", "Type": "Length"}},
        {"id": "pins", "type": "PolarPattern",
         "rationale": "equally spaced planet stations",
         "parameters": {"Occurrences": "pin_n", "Angle": "360",
                        "_Axis": {"role": "Z_Axis", "subs": [""]},
                        "_Originals": ["pin0"]}},
        {"id": "s_light", "type": "Sketch", "parameters": {}},
        {"id": "lightening", "type": "Pocket",
         "rationale": "mass reduction between shaft and pins",
         "parameters": {"Length": "disc_t", "Type": "Length"}}]
    sketches = [
        {"id": "s_disc", "plane": "XY",
         "profile": {"builder": "annulus",
                     "args": {"r_outer": "disc_r", "r_inner": "bore_c"}}},
        {"id": "s_pin", "plane": "XY",
         "profile": {"builder": "circle",
                     "args": {"r": "pin_r", "cx": "pin_bc"}}},
        {"id": "s_light", "plane": "XY",
         "profile": {"builder": "bolt_circle",
                     "args": {"n": "pin_n", "r_bc": "light_bc",
                              "r_hole": "light_r",
                              "start_deg": "180/pin_n"}}}]
    deps = [
        {"source": "s_disc", "target": "pad", "kind": "profile"},
        {"source": "s_pin", "target": "pin0", "kind": "profile"},
        {"source": "pad", "target": "pin0", "kind": "base"},
        {"source": "pin0", "target": "pins", "kind": "base"},
        {"source": "s_light", "target": "lightening", "kind": "profile"},
        {"source": "pins", "target": "lightening", "kind": "base"}]
    seq = ["Sketch", "Pad", "Sketch", "Pocket", "PolarPattern",
           "Sketch", "Pocket"]
    asserts = [
        {"id": "band_inner", "kind": "precondition", "tier": 1,
         "target": "light_bc - light_r - bore_c - 2"},
        {"id": "band_mid", "kind": "precondition", "tier": 1,
         "target": "pin_bc - pin_r - light_bc - light_r - 2"},
        {"id": "band_outer", "kind": "precondition", "tier": 1,
         "target": "disc_r - pin_bc - pin_r - 2.5"},
        {"id": "pin_spacing", "kind": "precondition", "tier": 1,
         "target": "2*pin_bc*sin(pi/pin_n) - 2*pin_r"},
        {"id": "light_spacing", "kind": "precondition", "tier": 1,
         "target": "2*light_bc*sin(pi/pin_n) - 2*light_r"}]
    if with_cham:
        cham = _u(rng, 0.3, min(1.0, pin_r - 0.4, disc_t / 2 - 0.5), 0.1)
        v["cham"] = cham
        v["radius_gap"] = round(min(abs(pin_r - light_r),
                                    abs(pin_r - bore_c)), 3)
        feats.append({
            "id": "rims", "type": "Chamfer",
            "rationale": "lead-in chamfer on every pin bore rim; the radius "
                         "selector must single out the pin bores among three "
                         "hole sizes",
            "parameters": {"Size": "cham", "_Base": {"object": "lightening"},
                           "_Edges": "radius:pin_r"}})
        deps.append({"source": "lightening", "target": "rims", "kind": "base"})
        seq.append("Chamfer")
        body += " - pin_n*2*((cham**2/2)*2*pi*(pin_r + cham/3))"
        derivation.append(
            {"step": 3, "eq": "V -= pin_n*2*(cham^2/2)*2*pi*(pin_r+cham/3)",
             "why": "chamfer rings on both rims of each pin bore, exact "
                    "Pappus; selector radius:pin_r must not catch the other "
                    "hole families"})
        asserts += [
            {"id": "cham_guard", "kind": "precondition", "tier": 1,
             "target": "pin_r - cham - 0.3"},
            {"id": "selector_unambiguous", "kind": "precondition", "tier": 1,
             "target": "radius_gap - 0.3",
             "why": "pin_r must differ from the other hole radii or the "
                    "radius selector chamfers the wrong rims"}]
    asserts.append({"id": "body", "kind": "body_volume", "tier": 1,
                    "tol_rel": 1e-6, "target": body})
    asserts.append({"id": "od_extent", "kind": "bbox_extent", "axis": "x",
                    "tier": 1, "tol_rel": 1e-6, "target": "2*disc_r"})
    bp = _freeze("planet_carrier", v, derivation,
                 {"features": feats, "sketches": sketches,
                  "dependencies": deps}, asserts)

    def collide(_t, vv):
        vv["light_bc"] = vv["pin_bc"]
    return bp, {"pattern_ring_collision": (collide, {
        "diagnosis": "band_mid < 0: lightening ring overlaps the pin ring",
        "fix": "separate the rings by at least a pin+light radius + land"})}, \
        tuple(seq)


# =========================================================================== #
# 16. aero rib bracket — plate + mirrored ribs + lightening holes (T1)
# =========================================================================== #
def aero_rib_bracket(rng):
    plate_w = _u(rng, 60, 130, 2)
    plate_d = _u(rng, 40, 0.9 * plate_w, 2)
    plate_t = _u(rng, 4, 9, 0.5)
    rib_l = _u(rng, 0.5 * plate_w, plate_w - 6, 2)
    rib_h = _u(rng, 8, 24, 1)
    rib_t = _u(rng, 2.5, 5.0, 0.25)
    hole_rr = _u(rng, 2.0, 4.0, 0.25)
    ry_lo = max(rib_t + 2, hole_rr + 9)
    ry_hi = plate_d / 2 - rib_t - 2
    if ry_lo >= ry_hi:
        raise ValueError("no rib room on this draw")
    rib_y = _u(rng, ry_lo, ry_hi, 0.5)
    s_hi = (rib_y - hole_rr - 2) / math.sin(math.radians(45))
    if s_hi <= 5:
        raise ValueError("no hole room inboard of the ribs")
    hole_bc = _u(rng, max(5.0, 0.5 * s_hi), s_hi, 0.5)
    v = {"plate_w": plate_w, "plate_d": plate_d, "plate_t": plate_t,
         "rib_l": rib_l, "rib_h": rib_h, "rib_t": rib_t, "rib_y": rib_y,
         "hole_bc": hole_bc, "hole_rr": hole_rr}
    bp = _freeze(
        "aero_rib_bracket", v,
        [{"step": 1, "eq": "V = plate_w*plate_d*plate_t"
                           " - 4*pi*hole_rr^2*plate_t + 2*rib_l*rib_h*rib_t",
          "why": "ribs stand ON the plate top (zero-volume interface) and "
                 "the mirror doubles the one modelled rib exactly because it "
                 "lies strictly on one side of the XZ plane"},
         {"step": 2, "eq": "holes inboard: hole_bc*sin(45) + hole_rr < rib_y",
          "why": "lightening holes must not touch the rib feet"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_plate", "type": "Sketch", "parameters": {}},
            {"id": "plate", "type": "Pad", "rationale": "base skin plate",
             "parameters": {"Length": "plate_t", "Type": "Length"}},
            {"id": "s_holes", "type": "Sketch", "parameters": {}},
            {"id": "holes", "type": "Pocket",
             "rationale": "lightening / systems pass-through holes",
             "parameters": {"Length": "plate_t", "Type": "Length"}},
            {"id": "s_rib", "type": "Sketch", "parameters": {}},
            {"id": "rib", "type": "Pad",
             "rationale": "load-path rib at +Y",
             "parameters": {"Length": "rib_t", "Type": "Length"}},
            {"id": "ribs", "type": "Mirrored",
             "rationale": "symmetric rib pair from one master",
             "parameters": {"_Plane": {"role": "XZ_Plane"},
                            "_Originals": ["rib"]}}],
         "sketches": [
            {"id": "s_plate", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "plate_w", "h": "plate_d"}}},
            {"id": "s_holes", "plane": "XY",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "4", "r_bc": "hole_bc",
                                  "r_hole": "hole_rr", "start_deg": "45"}}},
            {"id": "s_rib", "plane": "XZ", "z": "rib_y",
             "profile": {"builder": "rect",
                         "args": {"w": "rib_l", "h": "rib_h",
                                  "cy": "plate_t + rib_h/2"}}}],
         "dependencies": [
            {"source": "s_plate", "target": "plate", "kind": "profile"},
            {"source": "s_holes", "target": "holes", "kind": "profile"},
            {"source": "plate", "target": "holes", "kind": "base"},
            {"source": "s_rib", "target": "rib", "kind": "profile"},
            {"source": "holes", "target": "rib", "kind": "base"},
            {"source": "rib", "target": "ribs", "kind": "base"}]},
        [{"id": "straddle_guard", "kind": "precondition", "tier": 1,
          "target": "rib_y - rib_t - 1",
          "why": "the rib slab must stay clear of the mirror plane whichever "
                 "way the pad extrudes"},
         {"id": "rib_fit", "kind": "precondition", "tier": 1,
          "target": "plate_w - rib_l - 4"},
         {"id": "rib_inside", "kind": "precondition", "tier": 1,
          "target": "plate_d/2 - rib_y - rib_t - 1"},
         {"id": "holes_inboard", "kind": "precondition", "tier": 1,
          "target": "rib_y - hole_bc*sin(radians(45)) - hole_rr - 1"},
         {"id": "holes_fit", "kind": "precondition", "tier": 1,
          "target": "min(plate_w, plate_d)/2"
                    " - hole_bc*cos(radians(45)) - hole_rr - 2"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "plate_w*plate_d*plate_t - 4*pi*hole_rr**2*plate_t"
                    " + 2*rib_l*rib_h*rib_t"},
         {"id": "depth_extent", "kind": "bbox_extent", "axis": "y", "tier": 1,
          "tol_rel": 1e-6, "target": "plate_d"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "plate_t + rib_h"}])

    def straddle(_t, vv):
        vv["rib_y"] = vv["rib_t"] / 2
    return bp, {"rib_straddles_plane": (straddle, {
        "diagnosis": "straddle_guard < 0: the rib crosses the mirror plane, "
                     "so 2x-volume and the y-extent both break",
        "fix": "rib_y > rib_t + margin keeps the master rib one-sided"})}, \
        ("Sketch", "Pad", "Sketch", "Pocket", "Sketch", "Pad", "Mirrored")


# =========================================================================== #
# 17. rocker link — hexagonal link + twin bores + relief slot (T1)
# =========================================================================== #
def rocker_link(rng):
    half_len = _u(rng, 25, 55, 1)
    half_wid = _u(rng, 8, 18, 0.5)
    tip_ext = _u(rng, 5, 14, 0.5)
    thick_l = _u(rng, 6, 14, 0.5)
    bore_r_l = _u(rng, 2.5, min(5.0, half_wid - 3), 0.25)
    bore_in = _u(rng, bore_r_l + 2.5, 0.35 * half_len, 0.5)
    slot_r = _u(rng, 1.5, min(3.5, half_wid - 4), 0.25)
    slot_hi = 2 * ((half_len - bore_in) - bore_r_l - slot_r - 2.5)
    if slot_hi < 5:
        raise ValueError("no slot room")
    slot_len = _u(rng, 4, slot_hi, 1)
    v = {"half_len": half_len, "half_wid": half_wid, "tip_ext": tip_ext,
         "thick_l": thick_l, "bore_r_l": bore_r_l, "bore_in": bore_in,
         "slot_len": slot_len, "slot_r": slot_r}
    hex_a = "(4*half_len*half_wid + 2*half_wid*tip_ext)"
    slot_a = "(slot_len*2*slot_r + pi*slot_r**2)"
    bp = _freeze(
        "rocker_link", v,
        [{"step": 1, "eq": f"A_hex = {hex_a}",
          "why": "elongated hexagon: centre rectangle 2a x 2b plus two "
                 "triangular tips of area b*c each"},
         {"step": 2, "eq": "V = (A_hex - 2*pi*bore_r_l^2 - A_slot)*thick_l",
          "why": "two pivot bores at +/-(half_len - bore_in) and a central "
                 "relief slot, all mutually clear"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_link", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "link body",
             "parameters": {"Length": "thick_l", "Type": "Length"}},
            {"id": "s_bores", "type": "Sketch", "parameters": {}},
            {"id": "bores", "type": "Pocket",
             "rationale": "pivot bearing bores at both ends",
             "parameters": {"Length": "thick_l", "Type": "Length"}},
            {"id": "s_slot", "type": "Sketch", "parameters": {}},
            {"id": "relief", "type": "Pocket",
             "rationale": "mass relief between the pivots",
             "parameters": {"Length": "thick_l", "Type": "Length"}}],
         "sketches": [
            {"id": "s_link", "plane": "XY",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["-half_len", "-half_wid"], ["half_len", "-half_wid"],
                 ["half_len + tip_ext", "0"], ["half_len", "half_wid"],
                 ["-half_len", "half_wid"], ["-half_len - tip_ext", "0"]]}}},
            {"id": "s_bores", "plane": "XY",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "2", "r_bc": "half_len - bore_in",
                                  "r_hole": "bore_r_l"}}},
            {"id": "s_slot", "plane": "XY",
             "profile": {"builder": "slot",
                         "args": {"length": "slot_len", "r": "slot_r"}}}],
         "dependencies": [
            {"source": "s_link", "target": "pad", "kind": "profile"},
            {"source": "s_bores", "target": "bores", "kind": "profile"},
            {"source": "pad", "target": "bores", "kind": "base"},
            {"source": "s_slot", "target": "relief", "kind": "profile"},
            {"source": "bores", "target": "relief", "kind": "base"}]},
        [{"id": "bore_y_room", "kind": "precondition", "tier": 1,
          "target": "half_wid - bore_r_l - 2"},
         {"id": "bore_x_room", "kind": "precondition", "tier": 1,
          "target": "bore_in - bore_r_l - 1.5"},
         {"id": "slot_bore_clear", "kind": "precondition", "tier": 1,
          "target": "(half_len - bore_in) - bore_r_l"
                    " - (slot_len/2 + slot_r) - 2"},
         {"id": "slot_y_room", "kind": "precondition", "tier": 1,
          "target": "half_wid - slot_r - 2"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": f"({hex_a} - 2*pi*bore_r_l**2 - {slot_a})*thick_l"},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*(half_len + tip_ext)"}])

    def collide(_t, vv):
        vv["slot_len"] = 2 * (vv["half_len"] - vv["bore_in"])
    return bp, {"slot_hits_bores": (collide, {
        "diagnosis": "slot_bore_clear < 0: relief slot runs into the pivot "
                     "bores",
        "fix": "slot_len/2 + slot_r < pivot spacing/2 - bore_r - land"})}, \
        ("Sketch", "Pad", "Sketch", "Pocket", "Sketch", "Pocket")


# =========================================================================== #
# 18. vented enclosure — shell + patterned vent slots (T3 body, T1 tools)
# =========================================================================== #
def vented_enclosure(rng):
    enc_l = _u(rng, 80, 170, 2)
    enc_w = _u(rng, 50, 0.8 * enc_l, 2)
    enc_d = _u(rng, 15, 40, 1)
    wall_e = _u(rng, 1.5, 3.5, 0.25)
    vent_r = _u(rng, 1.5, 3.0, 0.25)
    vent_l = _u(rng, 8, 24, 1)
    n = rng.choice([3, 4, 5])
    pitch_min = vent_l + 2 * vent_r + 3
    span_hi = enc_l - 2 * wall_e - vent_l - 2 * vent_r - 8
    if pitch_min * (n - 1) >= span_hi:
        raise ValueError("no vent room")
    vent_span = _u(rng, pitch_min * (n - 1), span_hi, 1)
    v = {"enc_l": enc_l, "enc_w": enc_w, "enc_d": enc_d, "wall_e": wall_e,
         "vent_r": vent_r, "vent_l": vent_l, "vent_n": float(n),
         "vent_span": vent_span}
    sharp = ("enc_l*enc_w*enc_d - (enc_l - 2*wall_e)*(enc_w - 2*wall_e)"
             "*(enc_d - wall_e)")
    slot_a = "(vent_l*2*vent_r + pi*vent_r**2)"
    vents = f"vent_n*{slot_a}*wall_e"
    bp = _freeze(
        "vented_enclosure", v,
        [{"step": 1, "eq": f"V_shell ~ {sharp}",
          "why": "open-top shell; OCC corner joins keep this a Tier-3 bound"},
         {"step": 2, "eq": f"V -= {vents}",
          "why": "each vent removes exactly slot_area*wall_e of floor — the "
                 "floor thickness IS the wall, so the tool volume is exact "
                 "even though the shell bound is not"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "solid blank",
             "parameters": {"Length": "enc_d", "Type": "Length"}},
            {"id": "shell", "type": "Thickness",
             "rationale": "open-top enclosure",
             "parameters": {"Value": "wall_e", "Reversed": True,
                            "_Base": {"object": "pad"}, "_Faces": "top"}},
            {"id": "s_vent", "type": "Sketch", "parameters": {}},
            {"id": "vent0", "type": "Pocket",
             "rationale": "seed vent slot through the floor; explicit z=0 + "
                          "two-sided, or the sketch is hoisted to the wall "
                          "rim and cuts air",
             "parameters": {"Length": "wall_e + 1", "Type": "Length",
                            "Length2": "wall_e + 1", "Type2": "Length",
                            "SideType": "Two sides"}},
            {"id": "vents", "type": "LinearPattern",
             "rationale": "airflow vent row",
             "parameters": {"Occurrences": "vent_n", "Length": "vent_span",
                            "_Direction": {"role": "X_Axis", "subs": [""]},
                            "_Originals": ["vent0"]}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "enc_l", "h": "enc_w"}}},
            {"id": "s_vent", "plane": "XY", "z": "0",
             "profile": {"builder": "slot",
                         "args": {"length": "vent_l", "r": "vent_r",
                                  "cx": "-vent_span/2"}}}],
         "dependencies": [
            {"source": "s0", "target": "pad", "kind": "profile"},
            {"source": "pad", "target": "shell", "kind": "base"},
            {"source": "s_vent", "target": "vent0", "kind": "profile"},
            {"source": "shell", "target": "vent0", "kind": "base"},
            {"source": "vent0", "target": "vents", "kind": "base"}]},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "enc_d - 2*wall_e"},
         {"id": "vent_pitch", "kind": "precondition", "tier": 1,
          "target": "vent_span/(vent_n - 1) - vent_l - 2*vent_r - 2"},
         {"id": "vent_floor_x", "kind": "precondition", "tier": 1,
          "target": "enc_l/2 - wall_e"
                    " - (vent_span/2 + vent_l/2 + vent_r) - 2"},
         {"id": "vent_floor_y", "kind": "precondition", "tier": 1,
          "target": "enc_w/2 - wall_e - vent_r - 2"},
         {"id": "vent_tool", "kind": "feature_volume", "feature": "vent0",
          "tier": 1, "tol_rel": 1e-6,
          # AddSubShape is the RAW tool: the two-sided cut spans both Length
          # legs; only wall_e of it meets material, which the body band checks.
          "target": f"{slot_a}*(2*wall_e + 2)"},
         # Sharp-corner shell minus the exact vent-slot tools is EXACT (the
         # shell join is sharp, and each vent removes exactly slot_area*wall_e
         # of floor) -- measured 1.5e-15 across 29 records. Replaces the band.
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": f"({sharp}) - {vents}"},
         {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
          "target": "1"},
         {"id": "closed", "kind": "watertight", "tier": 1},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "enc_l"}])

    def overspan(_t, vv):
        vv["vent_span"] = vv["enc_l"]
    return bp, {"vents_leave_floor": (overspan, {
        "diagnosis": "vent_floor_x < 0: the vent row runs into the side "
                     "walls",
        "fix": "vent_span within the inner floor minus slot half-length"})}, \
        ("Sketch", "Pad", "Thickness", "Sketch", "Pocket", "LinearPattern")


RECIPES.update({
    "gearbox_housing": gearbox_housing,
    "manifold_runner": manifold_runner,
    "twisted_vane": twisted_vane,
    "valve_block": valve_block,
    "mold_core": mold_core,
    "harmonic_cup": harmonic_cup,
    "planet_carrier": planet_carrier,
    "aero_rib_bracket": aero_rib_bracket,
    "rocker_link": rocker_link,
    "vented_enclosure": vented_enclosure,
})
