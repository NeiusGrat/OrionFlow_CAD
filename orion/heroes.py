"""Phase-2 hero parts: one minimal blueprint per empty feature cell.

Nine parts, each proving one feature the training corpus has zero examples
of — Thickness, Draft, Fillet, Chamfer, LinearPattern, PolarPattern,
Mirrored, Sweep, Loft. Every hero runs the full forge cycle twice: once
clean, once with its designated fault, and both records (with the repair
trace) are persisted.

Discipline enforced here, per the Phase-2 contract:
  * dress-up edges are DISJOINT CIRCULAR rims only — no corner interaction,
    so the Pappus ring forms are exact and Tier 1 is honest;
  * Thickness is Tier 3 (OCC corner handling has no public closed form);
  * Sweep/Loft are Tier 2 with preconditions as first-class assertions.

Usage:  python -m orion.heroes            # all nine
        python -m orion.heroes fillet_plate sweep_elbow
"""

from __future__ import annotations

import copy
import sys

from .blueprint import Blueprint
from .forge import run_blueprint, save_record, workdir


def _bp(part_class, variables, derivation, template, assertions, datums=None,
        plan_extra=None):
    plan = {"derivation": derivation}
    if plan_extra:
        plan.update(plan_extra)
    return Blueprint(part_class=part_class, variables=variables,
                     datums=datums or {"A": "bottom face z=0", "B": "Z axis"},
                     design_plan=plan, assertions=assertions,
                     template=template).freeze()


def _refreeze(bp: Blueprint, mutate) -> Blueprint:
    """Author-level fault: mutate a deep copy of the template and refreeze.
    The faulted blueprint keeps the ORIGINAL assertions — that asymmetry is
    the whole point: the contract stays right, the implementation goes wrong."""
    t = copy.deepcopy(bp.template)
    v = dict(bp.variables)
    mutate(t, v)
    return Blueprint(part_class=bp.part_class + "_faulted", variables=v,
                     datums=bp.datums, design_plan=bp.design_plan,
                     assertions=bp.assertions, template=t).freeze()


# =========================================================================== #
# 1. SHEET SHELL — Thickness (Tier 3)
# =========================================================================== #
def sheet_shell():
    bp = _bp(
        "sheet_shell",
        {"length": 80.0, "width": 40.0, "depth": 10.0, "wall": 2.0},
        [{"step": 1, "eq": "V_solid = length*width*depth",
          "why": "blank before shelling"},
         {"step": 2, "eq": "V_sharp = V_solid - (length-2*wall)*(width-2*wall)"
                           "*(depth-wall)",
          "why": "open-top shell, planar walls, IF corners stay sharp — OCC "
                 "owns the corner treatment, so this bounds, not certifies: "
                 "Tier 3"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_base", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad",
                 "rationale": "solid blank the shell is cut from",
                 "parameters": {"Length": "depth", "Type": "Length"}},
                {"id": "shell", "type": "Thickness",
                 "rationale": "open-top enclosure wall; top face removed so "
                              "the tray is accessible",
                 "parameters": {"Value": "wall", "Reversed": True,
                                "_Base": {"object": "pad"},
                                "_Faces": "top"}},
            ],
            "sketches": [
                {"id": "s_base", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "length", "h": "width"}}},
            ],
            "dependencies": [
                {"source": "s_base", "target": "pad", "kind": "profile"},
                {"source": "pad", "target": "shell", "kind": "base"},
            ],
        },
        [
            {"id": "pad_tool", "kind": "feature_volume", "feature": "pad",
             "tier": 1, "tol_rel": 1e-6, "target": "length*width*depth"},
            {"id": "shelled", "kind": "volume_between", "tier": 3,
             "lo": "0.9*(length*width*depth - (length-2*wall)*(width-2*wall)"
                   "*(depth-wall))",
             "hi": "1.1*(length*width*depth - (length-2*wall)*(width-2*wall)"
                   "*(depth-wall))"},
            {"id": "one_solid", "kind": "solids", "tier": 3, "tol_rel": 0,
             "target": "1"},
            {"id": "closed", "kind": "watertight", "tier": 3},
            {"id": "len_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "length"},
        ],
        plan_extra={"tier_note": "Thickness volume is Tier 3: OCC corner "
                                 "joins have no public closed form"})

    def fault(t, _v):  # remove the shell entirely — silent solid plate
        t["features"] = [f for f in t["features"] if f["id"] != "shell"]
        t["dependencies"] = [d for d in t["dependencies"]
                             if d["target"] != "shell"]
    return bp, fault, {
        "fault": "missing_thickness",
        "diagnosis": "volume equals the solid blank (V_solid) and lands far "
                     "above the shelled bound ⇒ the Thickness feature was "
                     "never applied",
        "fix": "restore the Thickness feature (wall=2, top face open)"}


# =========================================================================== #
# 2. DRAFT WEDGE — Draft on all vertical faces (Tier 1 via prismatoid)
# =========================================================================== #
def draft_wedge():
    bp = _bp(
        "draft_wedge",
        {"length": 50.0, "width": 30.0, "height": 20.0, "draft_deg": 3.0},
        [{"step": 1, "eq": "top_l = length - 2*height*tan(radians(draft_deg))",
          "why": "all four walls draft inward from the bottom neutral plane"},
         {"step": 2, "eq": "top_w = width - 2*height*tan(radians(draft_deg))"},
         {"step": 3, "eq": "V = height/6 * (A_bot + 4*A_mid + A_top)",
          "why": "linear taper in both axes makes A(z) quadratic — the "
                 "prismatoid formula is EXACT, not an approximation"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_base", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad",
                 "rationale": "prismatic blank at the maximum (bottom) section",
                 "parameters": {"Length": "height", "Type": "Length"}},
                {"id": "draft", "type": "Draft",
                 "rationale": "mold-release taper; bottom face is the parting "
                              "plane so bottom dimensions are the mold cavity",
                 "parameters": {"Angle": "draft_deg", "Reversed": False,
                                "_Base": {"object": "pad"},
                                "_Faces": "vertical",
                                "_NeutralPlane": "bottom"}},
            ],
            "sketches": [
                {"id": "s_base", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "length", "h": "width"}}},
            ],
            "dependencies": [
                {"source": "s_base", "target": "pad", "kind": "profile"},
                {"source": "pad", "target": "draft", "kind": "base"},
            ],
        },
        [
            {"id": "apex_guard", "kind": "precondition", "tier": 1,
             "target": "width - 2*height*tan(radians(draft_deg))",
             "why": "draft must not consume the narrow dimension"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target":
                 "height/6 * (length*width"
                 " + 4*(length - height*tan(radians(draft_deg)))"
                 "*(width - height*tan(radians(draft_deg)))"
                 " + (length - 2*height*tan(radians(draft_deg)))"
                 "*(width - 2*height*tan(radians(draft_deg))))"},
            {"id": "base_len", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "length"},
            {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "height"},
        ])

    def fault(_t, v):   # 45° on a 30mm-wide, 20mm-tall block: 2·20·tan45 > 30
        v["draft_deg"] = 45.0
    return bp, fault, {
        "fault": "draft_self_intersection",
        "diagnosis": "apex_guard = width - 2*height*tan(45°) = -10 < 0: the "
                     "walls meet below the top face, the prismatoid form is "
                     "invalid — refused before build",
        "fix": "cap draft_deg so 2*height*tan(angle) < width (here < 36.87°)"}


# =========================================================================== #
# 3./4. FILLET / CHAMFER PLATE — disjoint hole rims only (Tier 1)
# =========================================================================== #
def _plate_template(dress_id, dress_type, dress_params, rationale):
    return {
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_plate", "type": "Sketch", "parameters": {}},
            {"id": "pad", "type": "Pad",
             "rationale": "mounting plate blank; holes are in the pad profile "
                          "so their rims exist as clean circular edges",
             "parameters": {"Length": "thick", "Type": "Length"}},
            {"id": dress_id, "type": dress_type,
             "rationale": rationale,
             "parameters": {**dress_params,
                            "_Base": {"object": "pad"},
                            "_Edges": "radius:hole_r"}},
        ],
        "sketches": [
            {"id": "s_plate", "plane": "XY",
             "profile": {"builder": "rect_with_holes",
                         "args": {"w": "plate_l", "h": "plate_w",
                                  "holes": [
                                      ["-hole_dx", "-hole_dy", "hole_r"],
                                      ["hole_dx", "-hole_dy", "hole_r"],
                                      ["hole_dx", "hole_dy", "hole_r"],
                                      ["-hole_dx", "hole_dy", "hole_r"]]}}},
        ],
        "dependencies": [
            {"source": "s_plate", "target": "pad", "kind": "profile"},
            {"source": "pad", "target": dress_id, "kind": "base"},
        ],
    }


_PLATE_VARS = {"plate_l": 60.0, "plate_w": 40.0, "thick": 5.0,
               "hole_dx": 20.0, "hole_dy": 12.0, "hole_r": 3.3}
_PAD_VOL = ("plate_l*plate_w*thick - 4*pi*hole_r**2*thick")


def fillet_plate():
    bp = _bp(
        "fillet_plate",
        {**_PLATE_VARS, "fillet_r": 1.2},
        [{"step": 1, "eq": f"V_pad = {_PAD_VOL}",
          "why": "plate minus four clearance holes, baked into one profile"},
         {"step": 2, "eq": "ring = fillet section r²(1-pi/4), centroid at "
                           "hole_r + r(10-3pi)/(12-3pi), Pappus",
          "why": "hole rims are DISJOINT circular edges — no corner terms, "
                 "so the ring form is exact; 8 rims (top+bottom of 4 holes)"},
         {"step": 3, "eq": "V = V_pad - 8*ring"}],
        _plate_template("fillet", "Fillet", {"Radius": "fillet_r"},
                        "break the sharp rims for handling and fatigue; "
                        "selector radius:hole_r → exactly the 8 rims"),
        [
            {"id": "rim_guard", "kind": "precondition", "tier": 1,
             "target": "hole_r - fillet_r",
             "why": "fillet must be smaller than the hole radius"},
            {"id": "thick_guard", "kind": "precondition", "tier": 1,
             "target": "thick - 2*fillet_r",
             "why": "top and bottom rim fillets must not meet mid-wall"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": f"{_PAD_VOL}"
                       " - 8*(fillet_r**2*(1-pi/4)"
                       "*2*pi*(hole_r + fillet_r*(10-3*pi)/(12-3*pi)))"},
            {"id": "len_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "plate_l"},
        ])

    def fault(_t, v):   # r > hole radius: geometrically impossible
        v["fillet_r"] = 10.0
    return bp, fault, {
        "fault": "fillet_radius_exceeds_adjacent",
        "diagnosis": "rim_guard = hole_r - fillet_r = -6.7 < 0: the fillet "
                     "cannot roll inside a smaller hole — refused before build",
        "fix": "fillet_r < hole_r (and < thick/2); 1.2mm restores validity"}


def chamfer_plate():
    bp = _bp(
        "chamfer_plate",
        {**_PLATE_VARS, "cham": 0.8},
        [{"step": 1, "eq": f"V_pad = {_PAD_VOL}"},
         {"step": 2, "eq": "ring = (cham²/2) * 2pi*(hole_r + cham/3)",
          "why": "45° chamfer triangle revolved at its centroid radius — "
                 "exact Pappus on each of the 8 disjoint rims"},
         {"step": 3, "eq": "V = V_pad - 8*ring"}],
        _plate_template("chamfer", "Chamfer", {"Size": "cham"},
                        "deburr and lead-in for fasteners on all hole rims"),
        [
            {"id": "size_guard", "kind": "precondition", "tier": 1,
             "target": "thick - 2*cham",
             "why": "chamfers from both faces must leave a cylindrical land"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": f"{_PAD_VOL}"
                       " - 8*((cham**2/2)*2*pi*(hole_r + cham/3))"},
            {"id": "len_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "plate_l"},
        ])

    def fault(_t, v):   # 5mm chamfer on a 5mm plate: cuts clean through
        v["cham"] = 5.0
    return bp, fault, {
        "fault": "chamfer_exceeds_thickness",
        "diagnosis": "size_guard = thick - 2*cham = -5 < 0: opposing rim "
                     "chamfers would consume the full wall — refused",
        "fix": "cham < thick/2; 0.8mm restores validity"}


# =========================================================================== #
# 5. LINEAR RAIL — LinearPattern (Tier 1)
# =========================================================================== #
def linear_rail():
    bp = _bp(
        "linear_rail",
        {"rail_l": 100.0, "rail_w": 20.0, "rail_h": 10.0,
         "hole_r": 4.0, "hole_n": 4.0, "span": 60.0},
        [{"step": 1, "eq": "pitch = span/(hole_n - 1) = 20",
          "why": "FreeCAD LinearPattern Length is the TOTAL span, first to "
                 "last occurrence"},
         {"step": 2, "eq": "edge_margin = (rail_l - span)/2 - hole_r = 16 > 0",
          "why": "all holes stay on the part; also guarantees non-overlap "
                 "since pitch (20) > 2*hole_r (8)"},
         {"step": 3, "eq": "V = rail_l*rail_w*rail_h "
                           "- hole_n*pi*hole_r²*rail_h"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_rail", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad",
                 "rationale": "rail blank",
                 "parameters": {"Length": "rail_h", "Type": "Length"}},
                {"id": "s_hole", "type": "Sketch", "parameters": {}},
                {"id": "hole", "type": "Pocket",
                 "rationale": "first mounting hole; the pattern replicates it",
                 "parameters": {"Length": "rail_h", "Type": "Length"}},
                {"id": "pattern", "type": "LinearPattern",
                 "rationale": "equally spaced mounting holes along the rail",
                 "parameters": {"Occurrences": "hole_n", "Length": "span",
                                "_Direction": {"role": "X_Axis", "subs": [""]},
                                "_Originals": ["hole"]}},
            ],
            "sketches": [
                {"id": "s_rail", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "rail_l", "h": "rail_w"}}},
                {"id": "s_hole", "plane": "XY",
                 "profile": {"builder": "circle",
                             "args": {"r": "hole_r", "cx": "-span/2",
                                      "cy": "0"}}},
            ],
            "dependencies": [
                {"source": "s_rail", "target": "pad", "kind": "profile"},
                {"source": "s_hole", "target": "hole", "kind": "profile"},
                {"source": "pad", "target": "hole", "kind": "base"},
                {"source": "hole", "target": "pattern", "kind": "base"},
            ],
        },
        [
            {"id": "overlap_guard", "kind": "precondition", "tier": 1,
             "target": "span/(hole_n - 1) - 2*hole_r",
             "why": "pitch must exceed the hole diameter"},
            {"id": "margin_guard", "kind": "precondition", "tier": 1,
             "target": "(rail_l - span)/2 - hole_r",
             "why": "end holes must stay clear of the rail ends"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": "rail_l*rail_w*rail_h - hole_n*pi*hole_r**2*rail_h"},
            {"id": "len_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "rail_l"},
        ])

    def fault(_t, v):   # span 100 on a 100 rail: end holes hang off the part
        v["span"] = 100.0
    return bp, fault, {
        "fault": "pattern_out_of_bounds",
        "diagnosis": "margin_guard = (rail_l - span)/2 - hole_r = -4 < 0: "
                     "the end occurrences cut the rail ends — refused",
        "fix": "span <= rail_l - 2*hole_r - end margin; 60mm restores it"}


# =========================================================================== #
# 6. POLAR FLANGE — PolarPattern (Tier 1)
# =========================================================================== #
def polar_flange():
    bp = _bp(
        "polar_flange",
        {"flange_r": 40.0, "flange_t": 8.0, "hub_r": 15.0, "hub_h": 20.0,
         "bore_r": 5.0, "bc_r": 27.5, "hole_r": 5.0, "hole_n": 6.0},
        [{"step": 1, "eq": "V_rev = pi*(flange_r²-bore_r²)*flange_t "
                           "+ pi*(hub_r²-bore_r²)*(hub_h-flange_t)",
          "why": "L-section revolved 360°: flange disc plus hub collar"},
         {"step": 2, "eq": "radial: hub_r < bc_r - hole_r  AND  "
                           "bc_r + hole_r < flange_r",
          "check": "15 < 22.5 and 32.5 < 40 — bolt land is unbroken"},
         {"step": 3, "eq": "circumferential: 2*bc_r*sin(pi/hole_n) = 27.5 "
                           "> 2*hole_r = 10",
          "why": "adjacent holes must not merge"},
         {"step": 4, "eq": "V = V_rev - hole_n*pi*hole_r²*flange_t",
          "why": "each hole removes flange thickness only — the hub is "
                 "radially inboard of the bolt circle"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_rev", "type": "Sketch", "parameters": {}},
                {"id": "rev", "type": "Revolution",
                 "rationale": "turned flange body: disc + hub, single setup",
                 "parameters": {"Angle": "360", "Reversed": False,
                                "_ReferenceAxis": {"object": "s_rev",
                                                   "is_sketch": True,
                                                   "subs": ["V_Axis"]}}},
                {"id": "s_hole", "type": "Sketch", "parameters": {}},
                {"id": "hole", "type": "Pocket",
                 "rationale": "first bolt hole at the 3 o'clock position",
                 "parameters": {"Length": "hub_h", "Type": "Length"}},
                {"id": "pattern", "type": "PolarPattern",
                 "rationale": "bolt circle: hole_n equally spaced",
                 "parameters": {"Occurrences": "hole_n", "Angle": "360",
                                "_Axis": {"role": "Z_Axis", "subs": [""]},
                                "_Originals": ["hole"]}},
            ],
            "sketches": [
                {"id": "s_rev", "plane": "XZ", "z": "0",
                 "profile": {"builder": "polyline", "args": {"points": [
                     ["bore_r", "0"], ["flange_r", "0"],
                     ["flange_r", "flange_t"], ["hub_r", "flange_t"],
                     ["hub_r", "hub_h"], ["bore_r", "hub_h"]]}}},
                {"id": "s_hole", "plane": "XY",
                 "profile": {"builder": "circle",
                             "args": {"r": "hole_r", "cx": "bc_r",
                                      "cy": "0"}}},
            ],
            "dependencies": [
                {"source": "s_rev", "target": "rev", "kind": "profile"},
                {"source": "s_hole", "target": "hole", "kind": "profile"},
                {"source": "rev", "target": "hole", "kind": "base"},
                {"source": "hole", "target": "pattern", "kind": "base"},
            ],
        },
        [
            {"id": "land_guard", "kind": "precondition", "tier": 1,
             "target": "flange_r - (bc_r + hole_r)",
             "why": "holes must not break the flange rim"},
            {"id": "hub_guard", "kind": "precondition", "tier": 1,
             "target": "(bc_r - hole_r) - hub_r",
             "why": "holes must clear the hub"},
            {"id": "spacing_guard", "kind": "precondition", "tier": 1,
             "target": "2*bc_r*sin(pi/hole_n) - 2*hole_r",
             "why": "adjacent holes must not merge"},
            {"id": "rev_tool", "kind": "feature_volume", "feature": "rev",
             "tier": 1, "tol_rel": 1e-6,
             "target": "pi*(flange_r**2-bore_r**2)*flange_t "
                       "+ pi*(hub_r**2-bore_r**2)*(hub_h-flange_t)"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": "pi*(flange_r**2-bore_r**2)*flange_t "
                       "+ pi*(hub_r**2-bore_r**2)*(hub_h-flange_t)"
                       " - hole_n*pi*hole_r**2*flange_t"},
        ])

    def fault(_t, v):   # bolt circle pushed out: holes break the rim
        v["bc_r"] = 37.0
    return bp, fault, {
        "fault": "pattern_breaks_rim",
        "diagnosis": "land_guard = flange_r - (bc_r + hole_r) = -2 < 0: the "
                     "bolt holes notch the flange OD — refused",
        "fix": "bc_r <= flange_r - hole_r - land; 27.5 restores validity"}


# =========================================================================== #
# 7. MIRROR BRACKET — Mirrored (Tier 1)
# =========================================================================== #
def mirror_bracket():
    bp = _bp(
        "mirror_bracket",
        {"half_w": 30.0, "depth": 40.0, "thick": 6.0,
         "hole_r": 4.0, "hole_x": 20.0, "hole_y": 10.0},
        [{"step": 1, "eq": "V_half = half_w*depth*thick - pi*hole_r²*thick",
          "why": "one wing with its dowel hole"},
         {"step": 2, "eq": "V = 2*V_half",
          "why": "the wing lies entirely in x>0, so mirroring across YZ "
                 "exactly doubles it — the non-straddle precondition"},
         {"step": 3, "eq": "width extent = 2*half_w",
          "why": "the assertion that catches a WRONG mirror plane: mirroring "
                 "across XY instead would double thickness, not width"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_half", "type": "Sketch", "parameters": {}},
                {"id": "pad", "type": "Pad",
                 "rationale": "right-hand wing of the symmetric bracket",
                 "parameters": {"Length": "thick", "Type": "Length"}},
                {"id": "s_hole", "type": "Sketch", "parameters": {}},
                {"id": "hole", "type": "Pocket",
                 "rationale": "dowel hole, mirrored with the wing",
                 "parameters": {"Length": "thick", "Type": "Length"}},
                {"id": "mirror", "type": "Mirrored",
                 "rationale": "left wing is the mirror image — one edit "
                              "drives both sides",
                 "parameters": {"_Plane": {"role": "YZ_Plane"},
                                "_Originals": ["pad", "hole"]}},
            ],
            "sketches": [
                {"id": "s_half", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "half_w", "h": "depth",
                                      "cx": "half_w/2", "cy": "0"}}},
                {"id": "s_hole", "plane": "XY",
                 "profile": {"builder": "circle",
                             "args": {"r": "hole_r", "cx": "hole_x",
                                      "cy": "hole_y"}}},
            ],
            "dependencies": [
                {"source": "s_half", "target": "pad", "kind": "profile"},
                {"source": "s_hole", "target": "hole", "kind": "profile"},
                {"source": "pad", "target": "hole", "kind": "base"},
                {"source": "hole", "target": "mirror", "kind": "base"},
            ],
        },
        [
            {"id": "straddle_guard", "kind": "precondition", "tier": 1,
             "target": "hole_x - hole_r",
             "why": "the wing (and its hole) must not cross the mirror plane"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
             "target": "2*(half_w*depth*thick - pi*hole_r**2*thick)"},
            {"id": "width_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "2*half_w"},
            {"id": "thick_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "thick"},
        ])

    def fault(t, _v):   # wrong mirror plane: volume still doubles, bbox lies
        for f in t["features"]:
            if f["id"] == "mirror":
                f["parameters"]["_Plane"] = {"role": "XY_Plane"}
    return bp, fault, {
        "fault": "wrong_mirror_plane",
        "diagnosis": "body volume PASSES (mirroring any plane doubles it) "
                     "but width_extent measures half_w and thick_extent "
                     "doubles ⇒ the mirror plane is XY, not YZ — exactly why "
                     "volume-only verification is insufficient",
        "fix": "_Plane role YZ_Plane restores the symmetric wing pair"}


# =========================================================================== #
# 8. SWEEP ELBOW — Sweep along a circular arc (Tier 2)
# =========================================================================== #
def sweep_elbow():
    bp = _bp(
        "sweep_elbow",
        {"section_r": 10.0, "bend_r": 100.0, "bend_deg": 90.0},
        [{"step": 1, "eq": "V = pi*section_r² * radians(bend_deg) * bend_r",
          "why": "generalized Pappus with Frenet framing: section centroid "
                 "rides the spine, offset e=0"},
         {"step": 2, "eq": "precondition bend_r > section_r",
          "why": "otherwise the inner wall self-intersects and Pappus "
                 "overcounts — the verifier must refuse, not approximate"},
         {"step": 3, "why": "Tier 2: OCC sweeps the surface as NURBS; the "
                            "solid is analytically a torus segment but the "
                            "kernel's tolerance is looser than Tier 1",
          "eq": "tol_rel = 1e-3"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_section", "type": "Sketch", "parameters": {}},
                {"id": "s_path", "type": "Sketch", "parameters": {}},
                {"id": "sweep", "type": "Sweep",
                 "rationale": "constant-section elbow: the minimal true sweep "
                              "(an extrude cannot make this)",
                 "parameters": {"Mode": "Frenet",
                                "_Spine": "s_path"}},
            ],
            "sketches": [
                {"id": "s_section", "plane": "YZ", "z": "0",
                 "profile": {"builder": "circle",
                             "args": {"r": "section_r"}}},
                {"id": "s_path", "plane": "XY", "z": "0",
                 "profile": {"builder": "arc_spine",
                             "args": {"radius": "bend_r",
                                      "sweep_deg": "bend_deg"}}},
            ],
            "dependencies": [
                {"source": "s_section", "target": "sweep", "kind": "profile"},
                {"source": "s_path", "target": "sweep", "kind": "spine"},
            ],
        },
        [
            {"id": "self_intersect_guard", "kind": "precondition", "tier": 2,
             "target": "bend_r - section_r",
             "why": "R_path must exceed the section radius"},
            {"id": "body", "kind": "body_volume", "tier": 2, "tol_rel": 1e-3,
             "target": "pi*section_r**2 * radians(bend_deg) * bend_r"},
            {"id": "one_solid", "kind": "solids", "tier": 2, "tol_rel": 0,
             "target": "1"},
            {"id": "closed", "kind": "watertight", "tier": 2},
        ])

    def fault(_t, v):   # bend radius smaller than the pipe: impossible elbow
        v["bend_r"] = 5.0
    return bp, fault, {
        "fault": "self_intersecting_sweep",
        "diagnosis": "self_intersect_guard = bend_r - section_r = -5 < 0: "
                     "the inner wall crosses the bend centre — the Tier-2 "
                     "prediction is undefined, so the verifier refuses",
        "fix": "bend_r > section_r (practice: >= 1.5x pipe OD); 100 restores"}


# =========================================================================== #
# 9. LOFT REDUCER — Loft between parallel circles (Tier 2)
# =========================================================================== #
def loft_reducer():
    bp = _bp(
        "loft_reducer",
        {"bot_r": 20.0, "top_r": 10.0, "height": 30.0},
        [{"step": 1, "eq": "V = pi*height/3 * (bot_r² + bot_r*top_r + top_r²)",
          "why": "circle-to-circle ruled loft between parallel planes IS a "
                 "cone frustum — prismatoid h/6(A1+4Am+A2) reduces to this "
                 "exactly"},
         {"step": 2, "why": "Tier 2: exact only under the parallel-planes + "
                            "ruled preconditions; a B-spline loft would be "
                            "Tier 3", "eq": "tol_rel = 1e-4"}],
        {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_bot", "type": "Sketch", "parameters": {}},
                {"id": "s_top", "type": "Sketch", "parameters": {}},
                {"id": "loft", "type": "Loft",
                 "rationale": "duct reducer: transitions flow area in one "
                              "feature; Ruled keeps the wall conical",
                 "parameters": {"Ruled": True, "Closed": False,
                                "_Sections": ["s_top"]}},
            ],
            "sketches": [
                {"id": "s_bot", "plane": "XY", "z": "0",
                 "profile": {"builder": "circle", "args": {"r": "bot_r"}}},
                {"id": "s_top", "plane": "XY", "z": "height",
                 "profile": {"builder": "circle", "args": {"r": "top_r"}}},
            ],
            "dependencies": [
                {"source": "s_bot", "target": "loft", "kind": "profile"},
                {"source": "s_top", "target": "loft", "kind": "section"},
            ],
        },
        [
            {"id": "taper_guard", "kind": "precondition", "tier": 2,
             "target": "top_r",
             "why": "zero top radius is a cone apex — a different closed "
                    "form; keep the frustum regime"},
            {"id": "body", "kind": "body_volume", "tier": 2, "tol_rel": 1e-4,
             "target": "pi*height/3 * (bot_r**2 + bot_r*top_r + top_r**2)"},
            {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "height"},
            {"id": "od_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "2*bot_r"},
        ])

    def fault(t, _v):   # strip the section list: loft has nothing to loft to
        for f in t["features"]:
            if f["id"] == "loft":
                f["parameters"].pop("_Sections", None)
        t["dependencies"] = [d for d in t["dependencies"]
                             if d.get("kind") != "section"]
    return bp, fault, {
        "fault": "missing_sections_dependency",
        "diagnosis": "compile error 'Loft needs parameters._Sections': the "
                     "loft degenerated to a single profile — no solid built",
        "fix": "restore _Sections=[s_top] and the section dependency edge"}


HEROES = {
    "sheet_shell": sheet_shell,
    "fillet_plate": fillet_plate,
    "chamfer_plate": chamfer_plate,
    "linear_rail": linear_rail,
    "polar_flange": polar_flange,
    "mirror_bracket": mirror_bracket,
    "draft_wedge": draft_wedge,
    "sweep_elbow": sweep_elbow,
    "loft_reducer": loft_reducer,
}


def run_hero(name, wd) -> dict:
    bp, fault_fn, trace_meta = HEROES[name]()
    out = {"name": name, "clean": None, "fault": None}

    rec = run_blueprint(bp, f"{name}_clean", wd)
    out["clean"] = rec["passed"]
    graph = bp.resolve()

    faulted = _refreeze(bp, fault_fn)
    frec = run_blueprint(faulted, f"{name}_fault", wd)
    caught = not frec["passed"]
    out["fault"] = caught
    out["refused"] = bool(frec.get("refused"))

    repair = dict(trace_meta)
    repair["faulted_blueprint_hash"] = faulted.blueprint_hash
    repair["caught"] = caught
    repair["refused_before_build"] = bool(frec.get("refused"))
    repair["failing"] = (frec.get("failed_preconditions")
                         or [a["id"] for a in frec["assertions"]
                             if not a["passed"]])
    rrec = run_blueprint(bp, f"{name}_repaired", wd)
    repair["reverified"] = rrec["passed"]
    out["reverified"] = rrec["passed"]

    tiers = {"1": 0, "2": 0, "3": 0}
    for a in bp.assertions:
        tiers[str(a.get("tier"))] = tiers.get(str(a.get("tier")), 0) + 1
    path = save_record(rec, bp, graph, extras={
        "repair_trace": repair,
        "faulted_verdict": {k: v for k, v in frec.items()
                            if k not in ("measured", "build_log")},
        "tier_profile": tiers,
    })
    out["record"] = path
    return out


def main() -> int:
    names = sys.argv[1:] or list(HEROES)
    wd = workdir()
    results = []
    for n in names:
        r = run_hero(n, wd)
        flag = "OK " if (r["clean"] and r["fault"] and r["reverified"]) else "FAIL"
        print(f"[{flag}] {n:16} clean={r['clean']} fault_caught={r['fault']}"
              f" (refused={r.get('refused')}) reverified={r['reverified']}")
        results.append(r)
    ok = all(r["clean"] and r["fault"] and r["reverified"] for r in results)
    print(f"\nPHASE 2 {'COMPLETE' if ok else 'INCOMPLETE'}: "
          f"{sum(1 for r in results if r['clean'])}/{len(results)} clean, "
          f"{sum(1 for r in results if r['fault'])}/{len(results)} faults caught")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
