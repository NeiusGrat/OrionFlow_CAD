"""Parametric part recipes for the automated forge loop.

Each recipe generalizes a PROVEN hero pattern into a family: the sampler
draws variables from engineering-plausible ranges, the recipe assembles a
blueprint whose preconditions are checked statically before any build, and
every family carries its own applicable fault injections for the repair
corpus.

Design rules that keep Tier 1 honest under composition (learned in Phase 2):
  * dress-ups only on disjoint circular rims, selected by ``radius:<expr>``;
  * Draft precedes holes, and holes must clear the SHRUNK top section — the
    cross-section grows downward, so top containment implies containment
    everywhere;
  * Thickness stays terminal and alone on its blank;
  * mirrored geometry lives strictly on one side of the plane;
  * Sweep/Loft stay unmodified (their walls are curved — any cut through
    them leaves closed-form territory).

A recipe returns ``(blueprint, faults, feature_seq)`` where ``faults`` maps
fault name -> (mutator, diagnosis dict).
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .blueprint import Blueprint

Fault = tuple[Callable, dict]


def _freeze(part_class, variables, derivation, template, assertions,
            plan_extra=None) -> Blueprint:
    plan = {"derivation": derivation}
    if plan_extra:
        plan.update(plan_extra)
    return Blueprint(part_class=part_class, variables=variables,
                     datums={"A": "bottom face z=0", "B": "Z axis"},
                     design_plan=plan, assertions=assertions,
                     template=template).freeze()


def _u(rng, lo, hi, step=0.1):
    """Uniform draw snapped to a step — CAD dimensions, not noise."""
    v = rng.uniform(lo, hi)
    return round(round(v / step) * step, 6)


# =========================================================================== #
# plate family
# =========================================================================== #
def plate_shell(rng):
    length = _u(rng, 50, 140, 2)
    width = _u(rng, 30, 0.8 * length, 2)
    depth = _u(rng, 8, 26, 1)
    wall = _u(rng, 1.5, min(4.0, depth / 3, width / 8), 0.5)
    v = {"length": length, "width": width, "depth": depth, "wall": wall}
    sharp = ("length*width*depth - (length-2*wall)*(width-2*wall)"
             "*(depth-wall)")
    bp = _freeze(
        "tray_shell", v,
        [{"step": 1, "eq": "V_solid = length*width*depth"},
         {"step": 2, "eq": f"V_sharp = {sharp}",
          "why": "open-top tray; OCC owns corner joins -> Tier 3 bound"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "solid blank",
             "parameters": {"Length": "depth", "Type": "Length"}},
            {"id": "shell", "type": "Thickness",
             "rationale": "constant-wall open tray",
             "parameters": {"Value": "wall", "Reversed": True,
                            "_Base": {"object": "pad"}, "_Faces": "top"}}],
         "sketches": [{"id": "s0", "plane": "XY",
                       "profile": {"builder": "rect",
                                   "args": {"w": "length", "h": "width"}}}],
         "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"},
                          {"source": "pad", "target": "shell", "kind": "base"}]},
        # OCC's Thickness with the default (sharp / intersection) join produces
        # EXACTLY the sharp-corner shell volume -- measured 1.6e-16 across 37
        # records -- so the earlier +/-10% band is replaced by the exact form.
        # Precondition documents the join: rounded joins would need a corner
        # correction and would fall to Tier 2.
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "depth - 2*wall"},
         {"id": "shelled", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": sharp},
         {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
          "target": "1"},
         {"id": "closed", "kind": "watertight", "tier": 1},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "length"}])

    def drop_shell(t, _v):
        t["features"] = [f for f in t["features"] if f["id"] != "shell"]
        t["dependencies"] = [d for d in t["dependencies"]
                             if d["target"] != "shell"]
    faults = {"missing_thickness": (drop_shell, {
        "diagnosis": "volume equals the solid blank, far above the shelled "
                     "bound ⇒ Thickness never applied",
        "fix": "restore the Thickness feature"})}
    return bp, faults, ("Sketch", "Pad", "Thickness")


def plate_drafted(rng):
    length = _u(rng, 40, 110, 2)
    width = _u(rng, 26, 0.9 * length, 2)
    height = _u(rng, 10, 30, 1)
    # keep the top section at >= 60% of the base in the narrow axis
    max_a = math.degrees(math.atan(0.2 * width / height))
    draft = _u(rng, 1.0, min(8.0, max_a), 0.5)
    n = rng.choice([4, 6])
    v = {"length": length, "width": width, "height": height,
         "draft_deg": draft, "hole_n": float(n)}
    shrink = "height*tan(radians(draft_deg))"
    top_min = f"(width - 2*{shrink})"
    v["hole_r"] = _u(rng, 1.5, 3.5, 0.5)
    # bolt circle inside the inscribed circle of the SHRUNK top face
    bc_hi = (min(width, length) / 2 - 2 * height * math.tan(math.radians(draft))
             - v["hole_r"] - 2.0)
    if bc_hi < 6.0:
        v["hole_n"] = 0.0     # no room: pure drafted block
    else:
        v["bc_r"] = _u(rng, max(5.0, 0.5 * bc_hi), bc_hi, 0.5)

    prism = ("height/6 * (length*width"
             f" + 4*(length - {shrink})*(width - {shrink})"
             f" + (length - 2*{shrink})*(width - 2*{shrink}))")
    feats = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s0", "type": "Sketch", "parameters": {}},
        {"id": "pad", "type": "Pad", "rationale": "blank at bottom section",
         "parameters": {"Length": "height", "Type": "Length"}},
        {"id": "draft", "type": "Draft",
         "rationale": "mold release; bottom is the parting plane",
         "parameters": {"Angle": "draft_deg", "Reversed": False,
                        "_Base": {"object": "pad"}, "_Faces": "vertical",
                        "_NeutralPlane": "bottom"}}]
    sketches = [{"id": "s0", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "length", "h": "width"}}}]
    deps = [{"source": "s0", "target": "pad", "kind": "profile"},
            {"source": "pad", "target": "draft", "kind": "base"}]
    target = prism
    seq = ["Sketch", "Pad", "Draft"]
    asserts = [
        {"id": "apex_guard", "kind": "precondition", "tier": 1,
         "target": f"{top_min} - 0.3*width"},
        {"id": "base_len", "kind": "bbox_extent", "axis": "x", "tier": 1,
         "tol_rel": 1e-6, "target": "length"}]
    derivation = [
        {"step": 1, "eq": f"A(z) shrinks linearly; V = {prism}",
         "why": "prismatoid is EXACT for bilinear taper"}]
    if v["hole_n"]:
        feats += [
            {"id": "s_holes", "type": "Sketch", "parameters": {}},
            {"id": "holes", "type": "Pocket",
             "rationale": "bolt circle drilled through the drafted block; "
                          "top containment implies full containment",
             "parameters": {"Length": "height", "Type": "Length"}}]
        sketches.append(
            {"id": "s_holes", "plane": "XY",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "hole_n", "r_bc": "bc_r",
                                  "r_hole": "hole_r"}}})
        deps += [{"source": "s_holes", "target": "holes", "kind": "profile"},
                 {"source": "draft", "target": "holes", "kind": "base"}]
        target = f"{prism} - hole_n*pi*hole_r**2*height"
        seq += ["Sketch", "Pocket"]
        asserts.append(
            {"id": "top_fit_guard", "kind": "precondition", "tier": 1,
             "target": f"min(length, width)/2 - {shrink} - bc_r - hole_r"})
        derivation.append(
            {"step": 2, "eq": "V -= hole_n*pi*hole_r^2*height",
             "why": "holes clear the shrunk top rect, so each removes a "
                    "full cylinder"})
    asserts.insert(1, {"id": "body", "kind": "body_volume", "tier": 1,
                       "tol_rel": 1e-6, "target": target})
    bp = _freeze("drafted_boss", v, derivation,
                 {"features": feats, "sketches": sketches,
                  "dependencies": deps}, asserts)

    def steep(_t, vv):
        vv["draft_deg"] = 45.0
    faults = {"draft_self_intersection": (steep, {
        "diagnosis": "apex_guard < 0: walls meet below the top face",
        "fix": "cap draft so 2*height*tan(a) leaves >=30% of width"})}
    return bp, faults, tuple(seq)


def plate_rim_dressup(rng):
    plate_l = _u(rng, 45, 120, 2)
    plate_w = _u(rng, 30, 0.85 * plate_l, 2)
    thick = _u(rng, 4, 12, 0.5)
    hole_r = _u(rng, 2.0, 4.5, 0.1)
    hole_dx = _u(rng, 0.28 * plate_l, 0.42 * plate_l, 0.5)
    hole_dy = _u(rng, 0.25 * plate_w, 0.4 * plate_w, 0.5)
    kind = rng.choice(["Fillet", "Chamfer"])
    if kind == "Fillet":
        size = _u(rng, 0.4, min(1.6, hole_r - 0.5, thick / 2 - 0.5), 0.1)
        dress_params = {"Radius": "dress"}
        ring = ("(dress**2*(1-pi/4)"
                "*2*pi*(hole_r + dress*(10-3*pi)/(12-3*pi)))")
    else:
        size = _u(rng, 0.3, min(1.2, thick / 2 - 0.5, hole_r - 0.5), 0.1)
        dress_params = {"Size": "dress"}
        ring = "((dress**2/2)*2*pi*(hole_r + dress/3))"
    v = {"plate_l": plate_l, "plate_w": plate_w, "thick": thick,
         "hole_dx": hole_dx, "hole_dy": hole_dy, "hole_r": hole_r,
         "dress": size}
    pad = "plate_l*plate_w*thick - 4*pi*hole_r**2*thick"
    bp = _freeze(
        f"{kind.lower()}_plate", v,
        [{"step": 1, "eq": f"V_pad = {pad}"},
         {"step": 2, "eq": f"ring = {ring}",
          "why": "8 disjoint circular rims (top+bottom of 4 holes): exact "
                 "Pappus, no corner terms"},
         {"step": 3, "eq": "V = V_pad - 8*ring"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "plate with holes in "
             "profile so rims are clean circular edges",
             "parameters": {"Length": "thick", "Type": "Length"}},
            {"id": "dress", "type": kind,
             "rationale": "rim treatment on all 8 hole rims via radius "
                          "selector — count is implied by the volume form",
             "parameters": {**dress_params,
                            "_Base": {"object": "pad"},
                            "_Edges": "radius:hole_r"}}],
         "sketches": [{"id": "s0", "plane": "XY",
                       "profile": {"builder": "rect_with_holes",
                                   "args": {"w": "plate_l", "h": "plate_w",
                                            "holes": [
                                                ["-hole_dx", "-hole_dy", "hole_r"],
                                                ["hole_dx", "-hole_dy", "hole_r"],
                                                ["hole_dx", "hole_dy", "hole_r"],
                                                ["-hole_dx", "hole_dy", "hole_r"]]}}}],
         "dependencies": [{"source": "s0", "target": "pad", "kind": "profile"},
                          {"source": "pad", "target": "dress", "kind": "base"}]},
        [{"id": "rim_guard", "kind": "precondition", "tier": 1,
          "target": "hole_r - dress"},
         {"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "thick - 2*dress"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": f"{pad} - 8*{ring}"},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "plate_l"}])

    def oversize(_t, vv):
        vv["dress"] = vv["hole_r"] + 5.0
    faults = {"dressup_exceeds_adjacent": (oversize, {
        "diagnosis": "rim_guard < 0: dress-up larger than its hole radius",
        "fix": "size < hole_r and < thick/2"})}
    return bp, faults, ("Sketch", "Pad", kind)


def plate_hole_line(rng):
    rail_l = _u(rng, 70, 160, 2)
    rail_w = _u(rng, 16, 36, 1)
    rail_h = _u(rng, 6, 16, 1)
    hole_r = _u(rng, 2.0, min(5.0, rail_w / 4 - 0.5), 0.25)
    n = rng.choice([3, 4, 5, 6])
    pitch_min = 2 * hole_r + 4.0
    span_hi = rail_l - 2 * hole_r - 12.0
    span = _u(rng, max(pitch_min * (n - 1), 0.4 * span_hi), span_hi, 1)
    v = {"rail_l": rail_l, "rail_w": rail_w, "rail_h": rail_h,
         "hole_r": hole_r, "hole_n": float(n), "span": span}
    bp = _freeze(
        "hole_rail", v,
        [{"step": 1, "eq": "pitch = span/(hole_n-1)",
          "why": "LinearPattern Length is total first-to-last span"},
         {"step": 2, "eq": "V = rail_l*rail_w*rail_h "
                           "- hole_n*pi*hole_r^2*rail_h"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "rail blank",
             "parameters": {"Length": "rail_h", "Type": "Length"}},
            {"id": "s_h", "type": "Sketch", "parameters": {}},
            {"id": "hole", "type": "Pocket", "rationale": "seed hole",
             "parameters": {"Length": "rail_h", "Type": "Length"}},
            {"id": "pattern", "type": "LinearPattern",
             "rationale": "equally spaced fixing holes",
             "parameters": {"Occurrences": "hole_n", "Length": "span",
                            "_Direction": {"role": "X_Axis", "subs": [""]},
                            "_Originals": ["hole"]}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "rail_l", "h": "rail_w"}}},
            {"id": "s_h", "plane": "XY",
             "profile": {"builder": "circle",
                         "args": {"r": "hole_r", "cx": "-span/2", "cy": "0"}}}],
         "dependencies": [
            {"source": "s0", "target": "pad", "kind": "profile"},
            {"source": "s_h", "target": "hole", "kind": "profile"},
            {"source": "pad", "target": "hole", "kind": "base"},
            {"source": "hole", "target": "pattern", "kind": "base"}]},
        [{"id": "overlap_guard", "kind": "precondition", "tier": 1,
          "target": "span/(hole_n-1) - 2*hole_r"},
         {"id": "margin_guard", "kind": "precondition", "tier": 1,
          "target": "(rail_l - span)/2 - hole_r"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "rail_l*rail_w*rail_h - hole_n*pi*hole_r**2*rail_h"},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "rail_l"}])

    def overspan(_t, vv):
        vv["span"] = vv["rail_l"] + 10.0
    faults = {"pattern_out_of_bounds": (overspan, {
        "diagnosis": "margin_guard < 0: end occurrences fall off the rail",
        "fix": "span <= rail_l - 2*hole_r - margin"})}
    return bp, faults, ("Sketch", "Pad", "Sketch", "Pocket", "LinearPattern")


def mirror_wing(rng):
    half_w = _u(rng, 20, 60, 1)
    depth = _u(rng, 25, 70, 1)
    thick = _u(rng, 4, 12, 0.5)
    hole_r = _u(rng, 2.0, min(5.0, half_w / 5), 0.25)
    hole_x = _u(rng, hole_r + 4.0, half_w - hole_r - 3.0, 0.5)
    hole_y = _u(rng, -0.3 * depth, 0.3 * depth, 0.5)
    v = {"half_w": half_w, "depth": depth, "thick": thick,
         "hole_r": hole_r, "hole_x": hole_x, "hole_y": hole_y}
    bp = _freeze(
        "mirror_wing", v,
        [{"step": 1, "eq": "V_half = half_w*depth*thick - pi*hole_r^2*thick"},
         {"step": 2, "eq": "V = 2*V_half; width extent = 2*half_w",
          "why": "wing strictly in x>0 -> mirroring across YZ doubles "
                 "exactly; bbox is the assertion that catches a wrong plane"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s0", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad", "rationale": "right wing",
             "parameters": {"Length": "thick", "Type": "Length"}},
            {"id": "s_h", "type": "Sketch", "parameters": {}},
            {"id": "hole", "type": "Pocket", "rationale": "dowel hole",
             "parameters": {"Length": "thick", "Type": "Length"}},
            {"id": "mirror", "type": "Mirrored",
             "rationale": "one edit drives both wings",
             "parameters": {"_Plane": {"role": "YZ_Plane"},
                            "_Originals": ["pad", "hole"]}}],
         "sketches": [
            {"id": "s0", "plane": "XY",
             "profile": {"builder": "rect",
                         "args": {"w": "half_w", "h": "depth",
                                  "cx": "half_w/2", "cy": "0"}}},
            {"id": "s_h", "plane": "XY",
             "profile": {"builder": "circle",
                         "args": {"r": "hole_r", "cx": "hole_x",
                                  "cy": "hole_y"}}}],
         "dependencies": [
            {"source": "s0", "target": "pad", "kind": "profile"},
            {"source": "s_h", "target": "hole", "kind": "profile"},
            {"source": "pad", "target": "hole", "kind": "base"},
            {"source": "hole", "target": "mirror", "kind": "base"}]},
        [{"id": "straddle_guard", "kind": "precondition", "tier": 1,
          "target": "hole_x - hole_r"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "2*(half_w*depth*thick - pi*hole_r**2*thick)"},
         {"id": "width_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*half_w"},
         {"id": "thick_extent", "kind": "bbox_extent", "axis": "z", "tier": 1,
          "tol_rel": 1e-6, "target": "thick"}])

    def wrong_plane(t, _v):
        for f in t["features"]:
            if f["id"] == "mirror":
                f["parameters"]["_Plane"] = {"role": "XY_Plane"}
    faults = {"wrong_mirror_plane": (wrong_plane, {
        "diagnosis": "volume passes (any mirror doubles it) but width/thick "
                     "extents betray the XY plane",
        "fix": "YZ_Plane restores the wing pair"})}
    return bp, faults, ("Sketch", "Pad", "Sketch", "Pocket", "Mirrored")


# =========================================================================== #
# revolved family
# =========================================================================== #
def flange_polar(rng):
    flange_r = _u(rng, 28, 60, 1)
    flange_t = _u(rng, 6, 14, 0.5)
    hub_r = _u(rng, 0.3 * flange_r, 0.45 * flange_r, 0.5)
    hub_h = _u(rng, flange_t + 6, flange_t + 22, 1)
    bore_r = _u(rng, 3, 0.6 * hub_r, 0.5)
    n = rng.choice([4, 6, 8])
    hole_r = _u(rng, 2.0, 4.0, 0.25)
    lo = hub_r + hole_r + 2.0
    hi = flange_r - hole_r - 2.5
    bc_r = _u(rng, lo, hi, 0.5)
    v = {"flange_r": flange_r, "flange_t": flange_t, "hub_r": hub_r,
         "hub_h": hub_h, "bore_r": bore_r, "bc_r": bc_r,
         "hole_r": hole_r, "hole_n": float(n)}
    with_groove = rng.random() < 0.5
    rev = ("pi*(flange_r**2-bore_r**2)*flange_t "
           "+ pi*(hub_r**2-bore_r**2)*(hub_h-flange_t)")
    feats = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_rev", "type": "Sketch", "parameters": {}},
        {"id": "rev", "type": "Revolution",
         "rationale": "turned flange: disc + hub in one setup",
         "parameters": {"Angle": "360", "Reversed": False,
                        "_ReferenceAxis": {"object": "s_rev",
                                           "is_sketch": True,
                                           "subs": ["V_Axis"]}}},
        {"id": "s_h", "type": "Sketch", "parameters": {}},
        {"id": "hole", "type": "Pocket", "rationale": "seed bolt hole",
         "parameters": {"Length": "hub_h", "Type": "Length"}},
        {"id": "pattern", "type": "PolarPattern",
         "rationale": "bolt circle",
         "parameters": {"Occurrences": "hole_n", "Angle": "360",
                        "_Axis": {"role": "Z_Axis", "subs": [""]},
                        "_Originals": ["hole"]}}]
    sketches = [
        {"id": "s_rev", "plane": "XZ", "z": "0",
         "profile": {"builder": "polyline", "args": {"points": [
             ["bore_r", "0"], ["flange_r", "0"],
             ["flange_r", "flange_t"], ["hub_r", "flange_t"],
             ["hub_r", "hub_h"], ["bore_r", "hub_h"]]}}},
        {"id": "s_h", "plane": "XY",
         "profile": {"builder": "circle",
                     "args": {"r": "hole_r", "cx": "bc_r", "cy": "0"}}}]
    deps = [
        {"source": "s_rev", "target": "rev", "kind": "profile"},
        {"source": "s_h", "target": "hole", "kind": "profile"},
        {"source": "rev", "target": "hole", "kind": "base"},
        {"source": "hole", "target": "pattern", "kind": "base"}]
    target = f"{rev} - hole_n*pi*hole_r**2*flange_t"
    seq = ["Sketch", "Revolution", "Sketch", "Pocket", "PolarPattern"]
    derivation = [
        {"step": 1, "eq": f"V_rev = {rev}", "why": "L-section, Pappus"},
        {"step": 2, "eq": "V -= hole_n*pi*hole_r^2*flange_t",
         "why": "holes pierce flange thickness only (hub is inboard)"}]
    asserts = [
        {"id": "land_guard", "kind": "precondition", "tier": 1,
         "target": "flange_r - (bc_r + hole_r)"},
        {"id": "hub_guard", "kind": "precondition", "tier": 1,
         "target": "(bc_r - hole_r) - hub_r"},
        {"id": "spacing_guard", "kind": "precondition", "tier": 1,
         "target": "2*bc_r*sin(pi/hole_n) - 2*hole_r"},
        {"id": "rev_tool", "kind": "feature_volume", "feature": "rev",
         "tier": 1, "tol_rel": 1e-6, "target": rev}]
    if with_groove:
        gw = _u(rng, 2.0, 4.0, 0.25)
        gd = _u(rng, 1.5, min(3.5, (hub_h - flange_t) / 2), 0.25)
        glo = bore_r + gw / 2 + 1.5
        ghi = hub_r - gw / 2 - 1.5
        if ghi > glo:
            v.update({"groove_r": _u(rng, glo, ghi, 0.25),
                      "groove_w": gw, "groove_d": gd})
            feats.insert(3, {
                "id": "s_g", "type": "Sketch", "parameters": {}})
            feats.insert(4, {
                "id": "groove", "type": "Groove",
                "rationale": "O-ring gland on the hub face",
                "parameters": {"Angle": "360", "Reversed": False,
                               "_ReferenceAxis": {"object": "s_g",
                                                  "is_sketch": True,
                                                  "subs": ["V_Axis"]}}})
            sketches.append({
                "id": "s_g", "plane": "XZ", "z": "0",
                "profile": {"builder": "polyline", "args": {"points": [
                    ["groove_r - groove_w/2", "hub_h - groove_d"],
                    ["groove_r + groove_w/2", "hub_h - groove_d"],
                    ["groove_r + groove_w/2", "hub_h"],
                    ["groove_r - groove_w/2", "hub_h"]]}}})
            deps += [{"source": "s_g", "target": "groove", "kind": "profile"},
                     {"source": "rev", "target": "groove", "kind": "base"}]
            target += " - 2*pi*groove_r*groove_w*groove_d"
            seq = seq[:2] + ["Sketch", "Groove"] + seq[2:]
            derivation.append(
                {"step": 3, "eq": "V -= 2*pi*groove_r*groove_w*groove_d",
                 "why": "gland ring, exact Pappus at centroid radius"})
            asserts += [
                {"id": "gland_guard", "kind": "precondition", "tier": 1,
                 "target": "hub_r - (groove_r + groove_w/2)"},
                {"id": "groove_tool", "kind": "feature_volume",
                 "feature": "groove", "tier": 1, "tol_rel": 1e-6,
                 "target": "2*pi*groove_r*groove_w*groove_d"}]
    asserts.append({"id": "body", "kind": "body_volume", "tier": 1,
                    "tol_rel": 1e-6, "target": target})
    bp = _freeze("bolted_flange", v, derivation,
                 {"features": feats, "sketches": sketches,
                  "dependencies": deps}, asserts)

    def rim_break(_t, vv):
        vv["bc_r"] = vv["flange_r"] - 2.0
    faults = {"pattern_breaks_rim": (rim_break, {
        "diagnosis": "land_guard < 0: bolt holes notch the flange OD",
        "fix": "bc_r <= flange_r - hole_r - land"})}
    return bp, faults, tuple(seq)


# =========================================================================== #
# curved family (Tier 2)
# =========================================================================== #
def sweep_bend(rng):
    section_r = _u(rng, 4, 16, 0.5)
    bend_r = _u(rng, 3 * section_r, 12 * section_r, 1)
    bend_deg = _u(rng, 30, 180, 5)
    v = {"section_r": section_r, "bend_r": bend_r, "bend_deg": bend_deg}
    bp = _freeze(
        "pipe_bend", v,
        [{"step": 1, "eq": "V = pi*section_r^2 * radians(bend_deg) * bend_r",
          "why": "generalized Pappus, Frenet framing, centroid on spine"},
         {"step": 2, "eq": "precondition bend_r > section_r",
          "why": "inner-wall self-intersection bound"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_sec", "type": "Sketch", "parameters": {}},
            {"id": "s_path", "type": "Sketch", "parameters": {}},
            {"id": "sweep", "type": "Sweep",
             "rationale": "constant-section bend",
             "parameters": {"Mode": "Frenet", "_Spine": "s_path"}}],
         "sketches": [
            {"id": "s_sec", "plane": "YZ", "z": "0",
             "profile": {"builder": "circle", "args": {"r": "section_r"}}},
            {"id": "s_path", "plane": "XY", "z": "0",
             "profile": {"builder": "arc_spine",
                         "args": {"radius": "bend_r",
                                  "sweep_deg": "bend_deg"}}}],
         "dependencies": [
            {"source": "s_sec", "target": "sweep", "kind": "profile"},
            {"source": "s_path", "target": "sweep", "kind": "spine"}]},
        # A constant circular section swept on a circular arc with Frenet
        # framing is an EXACT torus segment: generalised Pappus V=A*theta*R is
        # exact (centroid on the spine, e=0), and OCC builds the exact torus
        # (measured 1e-16 across the family). Tier 1, not the earlier hedge.
        [{"id": "self_intersect_guard", "kind": "precondition", "tier": 1,
          "target": "bend_r - section_r"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "pi*section_r**2 * radians(bend_deg) * bend_r"},
         {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 0,
          "target": "1"},
         {"id": "closed", "kind": "watertight", "tier": 1}])

    def tight(_t, vv):
        vv["bend_r"] = max(1.0, vv["section_r"] / 2)
    faults = {"self_intersecting_sweep": (tight, {
        "diagnosis": "self_intersect_guard < 0: bend tighter than the pipe",
        "fix": "bend_r > section_r, practice >= 1.5x OD"})}
    return bp, faults, ("Sketch", "Sketch", "Sweep")


def loft_transition(rng):
    bot_r = _u(rng, 12, 35, 0.5)
    top_r = _u(rng, 0.35 * bot_r, 0.8 * bot_r, 0.5)
    height = _u(rng, 15, 60, 1)
    v = {"bot_r": bot_r, "top_r": top_r, "height": height}
    bp = _freeze(
        "duct_reducer", v,
        [{"step": 1, "eq": "V = pi*height/3*(bot_r^2 + bot_r*top_r + top_r^2)",
          "why": "ruled circle-to-circle loft between parallel planes is a "
                 "cone frustum; prismatoid reduces to this exactly"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_bot", "type": "Sketch", "parameters": {}},
            {"id": "s_top", "type": "Sketch", "parameters": {}},
            {"id": "loft", "type": "Loft",
             "rationale": "flow-area transition in one feature",
             "parameters": {"Ruled": True, "Closed": False,
                            "_Sections": ["s_top"]}}],
         "sketches": [
            {"id": "s_bot", "plane": "XY", "z": "0",
             "profile": {"builder": "circle", "args": {"r": "bot_r"}}},
            {"id": "s_top", "plane": "XY", "z": "height",
             "profile": {"builder": "circle", "args": {"r": "top_r"}}}],
         "dependencies": [
            {"source": "s_bot", "target": "loft", "kind": "profile"},
            {"source": "s_top", "target": "loft", "kind": "section"}]},
        # Ruled circle-to-circle loft between parallel planes IS a cone
        # frustum; the prismatoid is exact and OCC builds the exact frustum
        # (measured 1e-16, and the real gNucleus loft master verified 1.9e-16).
        [{"id": "taper_guard", "kind": "precondition", "tier": 1,
          "target": "top_r"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": "pi*height/3*(bot_r**2 + bot_r*top_r + top_r**2)"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "height"}])

    def strip(t, _v):
        for f in t["features"]:
            if f["id"] == "loft":
                f["parameters"].pop("_Sections", None)
        t["dependencies"] = [d for d in t["dependencies"]
                             if d.get("kind") != "section"]
    faults = {"missing_sections_dependency": (strip, {
        "diagnosis": "compile error: Loft needs _Sections",
        "fix": "restore _Sections + section dependency"})}
    return bp, faults, ("Sketch", "Sketch", "Loft")


#: recipe name -> generator. The sampler owns weighting; this is the palette.
RECIPES: dict[str, Callable[[Any], tuple[Blueprint, dict, tuple]]] = {
    "tray_shell": plate_shell,
    "drafted_boss": plate_drafted,
    "rim_dressup_plate": plate_rim_dressup,
    "hole_rail": plate_hole_line,
    "mirror_wing": mirror_wing,
    "bolted_flange": flange_polar,
    "pipe_bend": sweep_bend,
    "duct_reducer": loft_transition,
}

# Families 9-18 register themselves on import (kept in a separate module so
# this file stays the core-eight reference implementation).
from . import recipes_ext  # noqa: E402,F401  (self-registering)
