"""Phase-1 hero part: O-ring sealed bearing end cap.

Revolution + Groove + Pocket (bolt circle) — Tier-1 dominant on purpose: every
assertion has an exact closed form, so this part proves the whole forge loop
(clean pass, differential, scale invariance, fault → repair trace) with zero
tolerance for hand-waving.

The design_plan.derivation is the reasoning corpus seed: every number the
FeatureGraph uses is produced by a numbered step citing its equation. Nothing
is narrated after the fact — the chain IS the design computation.

Usage:  python -m orion.hero_cap
"""

from __future__ import annotations

import copy
import json
import sys

from .blueprint import Blueprint
from .forge import (differential_test, run_blueprint, save_record,
                    scale_invariance_test, workdir)

LENGTH_VARS = ["od", "bore", "height", "groove_r", "groove_w", "groove_d",
               "hole_d", "bolt_circle_r"]


def author_blueprint() -> Blueprint:
    variables = {
        "od": 62.0,            # housing counterbore it seats into
        "bore": 25.0,          # shaft clearance bore
        "height": 12.0,        # axial stack height
        "groove_r": 22.0,      # O-ring gland centreline radius
        "groove_w": 3.6,       # gland width  (AS568-214 proportions)
        "groove_d": 2.4,       # gland depth  (≈0.75 × cord for ~25% squeeze)
        "bolt_count": 6.0,
        "bolt_circle_r": 27.5,
        "hole_d": 4.5,         # M4 clearance, ISO 273 medium fit
    }
    derivation = [
        {"step": 1, "what": "cap body = annular cylinder",
         "eq": "V_body_raw = pi*((od/2)^2 - (bore/2)^2) * height",
         "why": "revolved L-section about the shaft axis; bore passes the "
                "shaft, od seats in the housing counterbore"},
        {"step": 2, "what": "O-ring gland on the sealing face",
         "eq": "V_groove = 2*pi*groove_r * (groove_w*groove_d)  (Pappus)",
         "why": "rectangular gland section, centroid exactly at groove_r; "
                "depth 2.4 gives ~25% squeeze on a 3.53 cord"},
        {"step": 3, "what": "radial stackup must not intersect",
         "eq": "bore/2 < groove_r - groove_w/2  AND  "
               "groove_r + groove_w/2 < bolt_circle_r - hole_d/2  AND  "
               "bolt_circle_r + hole_d/2 < od/2",
         "check": "12.5 < 20.2 < 25.25 ... 29.75 < 31.0  — all hold",
         "why": "gland, bolt holes and rims each need an unbroken land; "
                "this is what makes the volume assertions exactly additive"},
        {"step": 4, "what": "bolt holes, one sketch, through",
         "eq": "V_holes = bolt_count * pi*(hole_d/2)^2 * height",
         "why": "6x M4 clearance on a single bolt-circle sketch; through-"
                "drilled so the tool volume is exact"},
        {"step": 5, "what": "final mass property",
         "eq": "V = V_body_raw - V_groove - V_holes",
         "why": "step-3 disjointness makes the subtraction exact, not "
                "approximate"},
    ]
    template = {
        "features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_rev", "type": "Sketch", "parameters": {}},
            {"id": "rev", "type": "Revolution", "parameters": {
                "Angle": "360", "Reversed": False,
                "_ReferenceAxis": {"object": "s_rev", "is_sketch": True,
                                   "subs": ["V_Axis"]}}},
            {"id": "s_groove", "type": "Sketch", "parameters": {}},
            {"id": "groove", "type": "Groove", "parameters": {
                "Angle": "360", "Reversed": False,
                "_ReferenceAxis": {"object": "s_groove", "is_sketch": True,
                                   "subs": ["V_Axis"]}}},
            {"id": "s_bolts", "type": "Sketch", "parameters": {}},
            {"id": "holes", "type": "Pocket", "parameters": {
                "Length": "height", "Type": "Length", "Reversed": False}},
        ],
        "sketches": [
            {"id": "s_rev", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["bore/2", "0"], ["od/2", "0"],
                 ["od/2", "height"], ["bore/2", "height"]]}}},
            {"id": "s_groove", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["groove_r - groove_w/2", "height - groove_d"],
                 ["groove_r + groove_w/2", "height - groove_d"],
                 ["groove_r + groove_w/2", "height"],
                 ["groove_r - groove_w/2", "height"]]}}},
            {"id": "s_bolts", "plane": "XY",
             "profile": {"builder": "bolt_circle",
                         "args": {"n": "bolt_count", "r_bc": "bolt_circle_r",
                                  "r_hole": "hole_d/2"}}},
        ],
        "dependencies": [
            {"source": "s_rev", "target": "rev", "kind": "profile"},
            {"source": "s_groove", "target": "groove", "kind": "profile"},
            {"source": "s_bolts", "target": "holes", "kind": "profile"},
        ],
    }
    assertions = [
        {"id": "rev_tool", "kind": "feature_volume", "feature": "rev",
         "tier": 1, "tol_rel": 1e-6,
         "target": "pi*((od/2)**2 - (bore/2)**2) * height"},
        {"id": "groove_tool", "kind": "feature_volume", "feature": "groove",
         "tier": 1, "tol_rel": 1e-6,
         "target": "2*pi*groove_r * groove_w*groove_d"},
        {"id": "holes_tool", "kind": "feature_volume", "feature": "holes",
         "tier": 1, "tol_rel": 1e-6,
         "target": "bolt_count * pi*(hole_d/2)**2 * height"},
        {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
         "target": "pi*((od/2)**2 - (bore/2)**2)*height"
                   " - 2*pi*groove_r*groove_w*groove_d"
                   " - bolt_count*pi*(hole_d/2)**2*height"},
        {"id": "od_extent", "kind": "bbox_extent", "axis": "x",
         "tier": 1, "tol_rel": 1e-6, "target": "od"},
        {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
         "tier": 1, "tol_rel": 1e-6, "target": "height"},
    ]
    bp = Blueprint(
        part_class="bearing_end_cap",
        variables=variables,
        datums={"A": "sealing face z=height", "B": "spigot axis Z",
                "C": "bolt-1 angular position"},
        design_plan={
            "function": "closes a bearing housing bore; static face seal",
            "manufacturing": "turn od/bore/groove from bar, then drill the "
                             "bolt circle on a rotary fixture",
            "datum_strategy": "A|B|C — seal face primary (function), spigot "
                              "axis secondary (location), bolt hole tertiary "
                              "(clocking)",
            "derivation": derivation,
        },
        assertions=assertions,
        template=template,
    )
    return bp.freeze()


def inject_wrong_depth(bp: Blueprint) -> Blueprint:
    """Authoring-level fault: bolt holes drilled to half depth. Passes the
    static checker (it is a well-formed expression), recomputes clean, and is
    exactly the class of silent error only the verifier can catch."""
    t = copy.deepcopy(bp.template)
    for f in t["features"]:
        if f["id"] == "holes":
            f["parameters"]["Length"] = "height/2"
    return Blueprint(part_class=bp.part_class, variables=bp.variables,
                     datums=bp.datums, design_plan=bp.design_plan,
                     assertions=bp.assertions, template=t).freeze()


def main() -> int:
    wd = workdir()
    bp = author_blueprint()
    print(f"blueprint frozen: {bp.blueprint_hash[:16]}…")

    # 1. clean pass -------------------------------------------------------- #
    rec = run_blueprint(bp, "cap_clean", wd)
    print(f"\nCLEAN: passed={rec['passed']}  ({rec['elapsed_s']}s)")
    for a in rec["assertions"]:
        print(f"  {a['id']:14} target={a['target']:.6f} "
              f"measured={a['measured'] if a['measured'] is not None else float('nan'):.6f} "
              f"err={a.get('rel_err', 1):.2e} {'ok' if a['passed'] else 'FAIL'}")
    if not rec["passed"]:
        print(json.dumps(rec["build_log"], indent=1)[:2000])
        return 1

    # 2. differential ------------------------------------------------------ #
    diffs = differential_test(bp, ["od", "height", "hole_d"], wd)
    print("\nDIFFERENTIAL:")
    for d in diffs:
        print(f"  {d['variable']:8} +{d['delta']:.3f}  "
              f"{'ok' if d['passed'] else 'FAIL'}")

    # 3. scale invariance -------------------------------------------------- #
    inv = scale_invariance_test(bp, LENGTH_VARS, wd)
    print(f"\nSCALE x2: passed={inv['passed']}  rel_err={inv.get('rel_err')}")

    # 4. fault -> repair trace -------------------------------------------- #
    faulted = inject_wrong_depth(bp)
    frec = run_blueprint(faulted, "cap_fault", wd)
    caught = not frec["passed"]
    failed_ids = [a["id"] for a in frec["assertions"] if not a["passed"]]
    print(f"\nFAULT (holes at height/2): caught={caught}  failing={failed_ids}")
    repair_trace = {
        "fault": "wrong_hole_depth",
        "faulted_blueprint_hash": faulted.blueprint_hash,
        "failing_assertions": failed_ids,
        "diagnosis": "holes_tool measured ≈ 50% of target while rev/groove "
                     "pass ⇒ the pocket depth expression is wrong, not the "
                     "sketch; blueprint step 4 requires through-drilling "
                     "(Length = height)",
        "fix": {"feature": "holes", "parameter": "Length",
                "from": "height/2", "to": "height"},
    }
    rrec = run_blueprint(bp, "cap_repaired", wd)
    repair_trace["reverified"] = rrec["passed"]
    print(f"REPAIR: re-verified={rrec['passed']}")

    ok = (rec["passed"] and all(d["passed"] for d in diffs)
          and inv["passed"] and caught and rrec["passed"])

    # 5. persist ----------------------------------------------------------- #
    graph = bp.resolve()
    path = save_record(rec, bp, graph, extras={
        "differential": diffs,
        "scale_invariance": inv,
        "repair_trace": repair_trace,
        "tier_profile": {"1": len(bp.assertions), "2": 0, "3": 0},
    })
    print(f"\nrecord: {path}")
    print(f"\nPHASE 1 {'COMPLETE' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
