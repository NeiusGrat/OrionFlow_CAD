"""Compositional generation: base draft + attachments -> one verified part.

The diversity engine of Phase 5A. A *composable base* is an UN-frozen draft
exposing mount interfaces; *attachments* are exact volume-delta modules the
composer places on those mounts. Because every attachment must land inside a
declared free region and stay disjoint from its siblings (enforced as frozen
precondition guards), the body volume remains a closed-form SUM — composition
never degrades the verification tier.

    BaseDraft = {
      part_class, variables, derivation, template, assertions[],
      body_expr,               # exact body volume expression (pre-attachment)
      mounts: [{
        id, kind: "flat_top",  # planar face normal +Z (axisym lands later)
        z,                     # expression: mount plane height
        land,                  # {"type": "rect", w, h, cx, cy} expressions —
                               #   free region no base feature occupies
        thickness,             # expression: solid depth under the land
      }],
    }

An attachment module returns feature/sketch/dep fragments plus its exact
``delta`` volume expression, its 2D footprint radius (for disjointness), and
guards. The composer:

  1. samples 0-3 attachments and a mount for each,
  2. places them at NUMERIC offsets inside the land (positions become
     variables, so the no-magic-number rule still holds),
  3. injects fragments, extends the body expression, adds containment +
     pairwise-separation guards,
  4. freezes — one blueprint, one hash, the standard forge cycle.

Every composed record logs base_family / attachments / datum_strategy /
feature_sequence_hash for the Phase-5A audit.
"""

from __future__ import annotations

import hashlib
import math
from typing import Callable

from .blueprint import Blueprint
from .recipes import _u

MAX_ATTACHMENTS = 3


# --------------------------------------------------------------------------- #
# attachment modules — each returns a dict fragment, or raises ValueError
# when the land cannot host it. All volume deltas are exact Tier 1.
# --------------------------------------------------------------------------- #
def _att_bolt_boss(rng, i, mount, land_w, land_h):
    """Raised cylindrical boss with a concentric through-hole (its own bolt
    landing). +pi*(R^2 - r^2)*h above the mount, minus the hole through the
    base thickness underneath."""
    br = _u(rng, 4, min(9.0, land_w / 2 - 1, land_h / 2 - 1), 0.5)
    if br < 4:
        raise ValueError("boss: no room")
    hr = _u(rng, 1.6, br - 2.0, 0.2)
    bh = _u(rng, 3, 10, 0.5)
    p = f"att{i}"
    v = {f"{p}_br": br, f"{p}_hr": hr, f"{p}_bh": bh}
    frag = {
        "features": [
            {"id": f"{p}_boss", "type": "Pad",
             "rationale": "bolt boss: raised seat so the fastener clamps on "
                          "a machined pad, not the raw surface",
             "parameters": {"Length": f"{p}_bh", "Type": "Length"}},
            {"id": f"{p}_hole", "type": "Pocket",
             "rationale": "through-hole down the boss axis",
             "parameters": {"Length": f"{p}_bh + {mount['thickness']} + 2",
                            "Type": "Length", "Length2": "2",
                            "Type2": "Length", "SideType": "Two sides"}}],
        "sketches": [
            {"id": f"s_{p}_boss", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_br", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}},
            {"id": f"s_{p}_hole", "plane": "XY",
             "z": f"{mount['z']} + {p}_bh",
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_hr", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_boss", f"{p}_boss"),
                         (f"s_{p}_hole", f"{p}_hole")],
        "delta": (f"(pi*{p}_br**2*{p}_bh"
                  f" - pi*{p}_hr**2*({p}_bh + {mount['thickness']}))"),
        "footprint": br,
        "variables": v,
        "guards": [(f"{p}_ring", f"{p}_br - {p}_hr - 1.5")],
        "protrusion": f"{p}_bh",
        "seq": ("Sketch", "Pad", "Sketch", "Pocket"),
    }
    return frag, br


def _att_locating_pin(rng, i, mount, land_w, land_h):
    """Solid dowel pin standing on the mount: +pi*r^2*h."""
    pr = _u(rng, 1.5, min(4.0, land_w / 2 - 1, land_h / 2 - 1), 0.25)
    if pr < 1.5:
        raise ValueError("pin: no room")
    ph = _u(rng, 3, 9, 0.5)
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_pin", "type": "Pad",
             "rationale": "locating pin: mates the counterpart bore so bolts "
                          "carry no shear",
             "parameters": {"Length": f"{p}_ph", "Type": "Length"}}],
        "sketches": [
            {"id": f"s_{p}_pin", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_pr", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_pin", f"{p}_pin")],
        "delta": f"pi*{p}_pr**2*{p}_ph",
        "footprint": pr,
        "variables": {f"{p}_pr": pr, f"{p}_ph": ph},
        "guards": [],
        "protrusion": f"{p}_ph",
        "seq": ("Sketch", "Pad"),
    }
    return frag, pr


def _att_thermal_relief(rng, i, mount, land_w, land_h):
    """Rectangular relief pocket, partial depth: -l*w*d."""
    rl = _u(rng, 6, min(24.0, land_w - 3), 1)
    rw = _u(rng, 4, min(16.0, land_h - 3), 1)
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_relief", "type": "Pocket",
             "rationale": "thermal relief: thins the section locally to cut "
                          "heat-sink mass and casting distortion",
             "parameters": {"Length": f"{p}_rd", "Type": "Length"}}],
        "sketches": [
            {"id": f"s_{p}_relief", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "rect",
                         "args": {"w": f"{p}_rl", "h": f"{p}_rw",
                                  "cx": f"{p}_cx", "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_relief", f"{p}_relief")],
        "delta": f"(-{p}_rl*{p}_rw*{p}_rd)",
        "footprint": math.hypot(rl / 2, rw / 2),
        "variables": {f"{p}_rl": rl, f"{p}_rw": rw,
                      f"{p}_rd": None},   # depth needs thickness: set below
        "guards": [],
        "seq": ("Sketch", "Pocket"),
        "_needs_depth": True,
    }
    return frag, math.hypot(rl / 2, rw / 2)


def _att_vent_slot(rng, i, mount, land_w, land_h):
    """Stadium slot cut through the full land thickness: -A_slot*t."""
    sr = _u(rng, 1.5, min(3.0, land_h / 2 - 2), 0.25)
    sl = _u(rng, 6, min(20.0, land_w - 2 * sr - 3), 1)
    if sl < 6:
        raise ValueError("vent: no room")
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_vent", "type": "Pocket",
             "rationale": "vent slot through the section for airflow / wire "
                          "pass-through",
             "parameters": {"Length": f"{mount['thickness']} + 1",
                            "Type": "Length", "Length2": "1",
                            "Type2": "Length", "SideType": "Two sides"}}],
        "sketches": [
            {"id": f"s_{p}_vent", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "slot",
                         "args": {"length": f"{p}_sl", "r": f"{p}_sr",
                                  "cx": f"{p}_cx", "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_vent", f"{p}_vent")],
        "delta": (f"(-({p}_sl*2*{p}_sr + pi*{p}_sr**2)"
                  f"*{mount['thickness']})"),
        "footprint": sl / 2 + sr,
        "variables": {f"{p}_sl": sl, f"{p}_sr": sr},
        "guards": [],
        "seq": ("Sketch", "Pocket"),
    }
    return frag, sl / 2 + sr


def _att_counterbore(rng, i, mount, land_w, land_h):
    """Counterbored through-hole: -(pi*r^2*t + pi*(R^2-r^2)*d)."""
    hr = _u(rng, 1.6, min(3.5, land_w / 4, land_h / 4), 0.2)
    cr = _u(rng, hr + 1.2, hr + 3.5, 0.25)
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_thru", "type": "Pocket",
             "rationale": "fastener clearance hole",
             "parameters": {"Length": f"{mount['thickness']} + 1",
                            "Type": "Length", "Length2": "1",
                            "Type2": "Length", "SideType": "Two sides"}},
            {"id": f"{p}_cb", "type": "Pocket",
             "rationale": "counterbore seats the cap head flush",
             "parameters": {"Length": f"{p}_cd", "Type": "Length"}}],
        "sketches": [
            {"id": f"s_{p}_thru", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_hr", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}},
            {"id": f"s_{p}_cb", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_cr", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_thru", f"{p}_thru"),
                         (f"s_{p}_cb", f"{p}_cb")],
        "delta": (f"(-(pi*{p}_hr**2*{mount['thickness']}"
                  f" + pi*({p}_cr**2 - {p}_hr**2)*{p}_cd))"),
        "footprint": cr,
        "variables": {f"{p}_hr": hr, f"{p}_cr": cr, f"{p}_cd": None},
        "guards": [(f"{p}_cb_ring", f"{p}_cr - {p}_hr - 1")],
        "seq": ("Sketch", "Pocket", "Sketch", "Pocket"),
        "_needs_depth": True,
        "_depth_frac": (0.25, 0.5),
    }
    return frag, cr


def _att_alignment_rib(rng, i, mount, land_w, land_h):
    """Thin standing rib: +l*w*h."""
    rl = _u(rng, 8, min(30.0, land_w - 3), 1)
    rt = _u(rng, 2, 4, 0.25)
    rh = _u(rng, 3, 10, 0.5)
    if rl < 8 or rt > land_h - 2:
        raise ValueError("rib: no room")
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_rib", "type": "Pad",
             "rationale": "alignment rib: keys the mating part and stiffens "
                          "the face",
             "parameters": {"Length": f"{p}_rh", "Type": "Length"}}],
        "sketches": [
            {"id": f"s_{p}_rib", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "rect",
                         "args": {"w": f"{p}_rl", "h": f"{p}_rt",
                                  "cx": f"{p}_cx", "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_rib", f"{p}_rib")],
        "delta": f"({p}_rl*{p}_rt*{p}_rh)",
        "footprint": math.hypot(rl / 2, rt / 2),
        "variables": {f"{p}_rl": rl, f"{p}_rt": rt, f"{p}_rh": rh},
        "guards": [],
        "protrusion": f"{p}_rh",
        "seq": ("Sketch", "Pad"),
    }
    return frag, math.hypot(rl / 2, rt / 2)


def _att_lightening(rng, i, mount, land_w, land_h):
    """Round lightening hole through the land: -pi*r^2*t."""
    lr = _u(rng, 3, min(8.0, land_w / 2 - 1.5, land_h / 2 - 1.5), 0.5)
    if lr < 3:
        raise ValueError("lightening: no room")
    p = f"att{i}"
    frag = {
        "features": [
            {"id": f"{p}_light", "type": "Pocket",
             "rationale": "lightening hole: mass removal where the section "
                          "carries no load path",
             "parameters": {"Length": f"{mount['thickness']} + 1",
                            "Type": "Length", "Length2": "1",
                            "Type2": "Length", "SideType": "Two sides"}}],
        "sketches": [
            {"id": f"s_{p}_light", "plane": "XY", "z": mount["z"],
             "profile": {"builder": "circle",
                         "args": {"r": f"{p}_lr", "cx": f"{p}_cx",
                                  "cy": f"{p}_cy"}}}],
        "profile_deps": [(f"s_{p}_light", f"{p}_light")],
        "delta": f"(-pi*{p}_lr**2*{mount['thickness']})",
        "footprint": lr,
        "variables": {f"{p}_lr": lr},
        "guards": [],
        "seq": ("Sketch", "Pocket"),
    }
    return frag, lr


ATTACHMENTS: dict[str, Callable] = {
    "bolt_boss": _att_bolt_boss,
    "locating_pin": _att_locating_pin,
    "thermal_relief": _att_thermal_relief,
    "vent_slot": _att_vent_slot,
    "counterbore_set": _att_counterbore,
    "alignment_rib": _att_alignment_rib,
    "lightening_pocket": _att_lightening,
}

DATUM_STRATEGIES = [
    {"A": "mount face (function)", "B": "Z axis (location)",
     "C": "attachment 1 (clocking)"},
    {"A": "bottom face z=0 (primary)", "B": "long edge (secondary)",
     "C": "first bore (tertiary)"},
    {"A": "machined top land", "B": "datum bore axis", "C": "edge of land"},
]


def compose(base_draft: dict, rng, n_attachments: int | None = None):
    """Sample attachments onto a base draft and freeze the composed blueprint.

    Returns (blueprint, meta) where meta carries base_family / attachments /
    datum_strategy / feature_sequence_hash for the corpus audit.
    """
    n = rng.randint(0, MAX_ATTACHMENTS) if n_attachments is None \
        else n_attachments
    variables = dict(base_draft["variables"])
    template = {
        "features": [dict(f) for f in base_draft["template"]["features"]],
        "sketches": [dict(s) for s in base_draft["template"]["sketches"]],
        "dependencies": list(base_draft["template"]["dependencies"]),
    }
    assertions = list(base_draft["assertions"])
    derivation = list(base_draft["derivation"])
    body = base_draft["body_expr"]
    seq = list(base_draft["seq"])
    placed: list[dict] = []   # {mount, cx, cy, footprint}
    chosen: list[str] = []
    protrusions: list[tuple[str, str]] = []   # (mount_z_expr, height_expr)

    mounts = base_draft.get("mounts", [])
    last_solid = base_draft["last_solid"]

    from . import expr as E
    for i in range(n):
        if not mounts:
            break
        mount = mounts[rng.randrange(len(mounts))]
        # Parenthesise before interpolation: a mount thickness of "hubh - ft"
        # spliced raw into "pi*r**2*{thickness}" parses as (pi*r**2*hubh) - ft.
        mount = {**mount,
                 "z": f"({mount['z']})",
                 "thickness": f"({mount['thickness']})"}
        land = mount["land"]
        lw = E.evaluate(land["w"], variables)
        lh = E.evaluate(land["h"], variables)
        lcx = E.evaluate(land.get("cx", "0"), variables)
        lcy = E.evaluate(land.get("cy", "0"), variables)
        name = rng.choice(list(ATTACHMENTS))
        try:
            frag, footprint = ATTACHMENTS[name](rng, i, mount, lw, lh)
        except ValueError:
            continue
        # The land must actually fit the attachment's footprint with the 1.5mm
        # inset; otherwise the placement range inverts and the attachment would
        # land OUTSIDE the land. Skip it rather than place it out of bounds.
        if (lw / 2 - footprint - 1.5 < 0) or (lh / 2 - footprint - 1.5 < 0):
            continue
        # Position: uniform inside the land, honouring footprint + siblings.
        ok_pos = None
        for _try in range(25):
            cx = round(rng.uniform(lcx - lw / 2 + footprint + 1.5,
                                   lcx + lw / 2 - footprint - 1.5), 2)
            cy = round(rng.uniform(lcy - lh / 2 + footprint + 1.5,
                                   lcy + lh / 2 - footprint - 1.5), 2)
            if all(math.hypot(cx - q["cx"], cy - q["cy"])
                   > footprint + q["footprint"] + 2.0
                   for q in placed if q["mount"] == mount["id"]):
                ok_pos = (cx, cy)
                break
        if ok_pos is None:
            continue
        cx, cy = ok_pos
        p = f"att{i}"
        variables[f"{p}_cx"] = cx
        variables[f"{p}_cy"] = cy
        for k, val in frag["variables"].items():
            if val is None:                       # depth-fraction fills
                lo, hi = frag.get("_depth_frac", (0.3, 0.6))
                t_num = E.evaluate(mount["thickness"], variables)
                variables[k] = round(rng.uniform(lo * t_num, hi * t_num), 2)
            else:
                variables[k] = val
        # A sketch must appear BOTH as an ordered feature entry (that is what
        # makes the compiler build it, and when) and in the sketches list
        # (its geometry). Interleave sketch-then-consumer in profile_deps
        # order so a sketch placed on top of an earlier attachment feature
        # is created only after that feature exists.
        by_id = {f["id"]: f for f in frag["features"]}
        for s_id, f_id in frag["profile_deps"]:
            template["features"].append(
                {"id": s_id, "type": "Sketch", "parameters": {}})
            template["features"].append(by_id[f_id])
        template["sketches"].extend(frag["sketches"])
        for s_id, f_id in frag["profile_deps"]:
            template["dependencies"].append(
                {"source": s_id, "target": f_id, "kind": "profile"})
        # chain solids: first new feature bases on the current last solid
        template["dependencies"].append(
            {"source": last_solid, "target": frag["features"][0]["id"],
             "kind": "base"})
        for a, b in zip(frag["features"], frag["features"][1:]):
            template["dependencies"].append(
                {"source": a["id"], "target": b["id"], "kind": "base"})
        last_solid = frag["features"][-1]["id"]
        body = f"{body} + {frag['delta']}"
        for gid, gexpr in frag["guards"]:
            assertions.append({"id": gid, "kind": "precondition",
                               "tier": 1, "target": gexpr})
        derivation.append(
            {"step": len(derivation) + 1,
             "eq": f"V += {frag['delta']}",
             "why": f"{name} at ({cx}, {cy}) on {mount['id']}: "
                    f"{frag['features'][0]['rationale']}"})
        if frag.get("protrusion"):
            protrusions.append((mount["z"], frag["protrusion"]))
        placed.append({"mount": mount["id"], "cx": cx, "cy": cy,
                       "footprint": footprint, "idx": i})
        chosen.append(name)
        seq.extend(frag["seq"])

    # Replace the base's body assertion. For an additive base the composed
    # body is an exact closed-form SUM. For a mesh-body base (a non-summable
    # union like a radial-arm hub) there is no closed form for the composed
    # solid either, so the body is verified numerically by mesh convergence to
    # OCC — which measures whatever was actually built, attachments included —
    # backed by connectivity + watertightness to catch a disconnected result.
    assertions = [a for a in assertions if a.get("id") != "body"]
    mesh_body = bool(base_draft.get("body_mesh"))
    if mesh_body:
        assertions.append({"id": "body", "kind": "body_mesh_converged",
                           "tier": 2, "tol_rel": 1e-3})
    else:
        assertions.append({"id": "body", "kind": "body_volume", "tier": 1,
                           "tol_rel": 1e-6, "target": body})
    # Connectivity is mandatory for a mesh base (the volume no longer catches a
    # disconnected solid) and worth having on any composed part.
    if (mesh_body or chosen) and not any(a.get("kind") == "solids"
                                         for a in assertions):
        assertions.append({"id": "one_solid", "kind": "solids", "tier": 1,
                           "tol_rel": 0, "target": "1"})
        assertions.append({"id": "closed", "kind": "watertight", "tier": 1})

    # A protruding attachment raises the top of the part, so the base's own
    # z-extent assertion is no longer the whole story. Rebuild it as the max
    # over the base height and every mount plane plus what stands on it.
    if protrusions:
        rebuilt = []
        for a in assertions:
            if a.get("kind") == "bbox_extent" and a.get("axis") == "z":
                t = a["target"]
                for mz, prot in protrusions:
                    t = f"max({t}, {mz} + {prot})"
                a = {**a, "target": t}
            rebuilt.append(a)
        assertions = rebuilt

    datum = rng.choice(DATUM_STRATEGIES)
    part_class = base_draft["part_class"] + (
        "" if not chosen else "_plus_" + "_".join(sorted(set(chosen))))
    bp = Blueprint(
        part_class=part_class[:70],
        variables=variables,
        datums=datum,
        design_plan={"derivation": derivation,
                     **base_draft.get("plan_extra", {})},
        assertions=assertions,
        template=template,
    ).freeze()
    sig = hashlib.sha256(("|".join(seq) + "::" + base_draft["part_class"]
                          + "::" + ",".join(sorted(chosen))
                          ).encode()).hexdigest()[:16]
    meta = {
        "base_family": base_draft["part_class"],
        "attachments": chosen,
        "datum_strategy": datum,
        "feature_sequence_hash": sig,
        "feature_seq": seq,
        "attachment_mounts": [q["mount"] for q in placed],
        "attachment_index": [q["idx"] for q in placed],
    }
    return bp, meta

def compose_faults(meta: dict) -> dict:
    """Fault palette for a COMPOSED part, derived from the composition
    contract itself rather than from any one base.

    Both faults are pure variable moves, and both are caught by the body
    volume: overlapping attachments make the union smaller than the sum of
    the deltas, and an attachment pushed off its land loses the material it
    was supposed to add (or removes nothing where it was supposed to cut).

    The mutators discover the live attachment indices from the variables
    themselves — placement can fail for a slot, so indices are not
    contiguous, and inventing ``att0_cx`` on a part that never had one
    creates an unused variable the checker rightly rejects.
    """
    def _idx(v):
        return sorted(int(k[3:-3]) for k in v
                      if k.startswith("att") and k.endswith("_cx"))

    faults: dict = {}
    mounts = meta.get("attachment_mounts", [])
    idxs = meta.get("attachment_index", [])
    pair = None
    for i in range(len(mounts)):
        for j in range(i + 1, len(mounts)):
            if mounts[i] == mounts[j]:
                pair = (idxs[i], idxs[j])
                break
        if pair:
            break
    faults: dict = {}
    if pair:                    # two attachments on the SAME mount: moving
        def collide(_t, v):     # one onto the other genuinely overlaps
            a, b = pair
            if f"att{a}_cx" not in v or f"att{b}_cx" not in v:
                return
            v[f"att{b}_cx"] = v[f"att{a}_cx"]
            v[f"att{b}_cy"] = v[f"att{a}_cy"]
        faults["attachment_collision"] = (collide, {
            "diagnosis": "two attachments share a centre: the union of their "
                         "solids is smaller than the sum of the deltas, so "
                         "the composed volume over-predicts",
            "fix": "restore the pairwise separation (centre distance > sum "
                   "of footprints + land margin)"})
    if meta.get("attachments"):
        def off_land(_t, v):
            ix = _idx(v)
            if not ix:
                return
            v[f"att{ix[0]}_cx"] = v[f"att{ix[0]}_cx"] + 500.0
        faults["attachment_off_land"] = (off_land, {
            "diagnosis": "attachment centre lies far outside its mount land: "
                         "a pad lands in mid-air (or a pocket cuts nothing), "
                         "so its volume delta never materialises",
            "fix": "keep the centre inside the declared land, footprint and "
                   "margin included"})
    return faults
