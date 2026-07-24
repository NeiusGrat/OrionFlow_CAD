"""Composable base drafts — the un-frozen half of the composition system.

Each builder returns a BaseDraft dict (see orion/compose.py): exact body
expression, mount interfaces with free lands, and the standard derivation /
guard discipline. The composer injects attachments and freezes.

Starter set proves the architecture; the Phase-5A base library (~24 covering
all directive domains) extends this module.
"""

from __future__ import annotations

from .recipes import _u


def _ring_land(r_in, r_out, margin=3.0):
    """Largest axis-aligned SQUARE land provably inside an annulus.

    A square of half-size s centred at radius Rc has its far corner at
    ((Rc+s), s), so it fits iff (Rc+s)^2 + s^2 <= (r_out-margin)^2 and
    Rc - s >= r_in + margin. Returns (Rc, s) or None when the ring is too
    narrow to host anything. Without this a "ring land" quietly hangs its
    corners off the outside diameter and attachments land in mid-air.
    """
    best = None
    K = r_out - margin
    if K <= r_in + margin:
        return None
    for i in range(1, 40):
        Rc = r_in + (r_out - r_in) * i / 40.0
        s1 = Rc - r_in - margin
        disc = 8.0 * K * K - 4.0 * Rc * Rc
        if disc < 0:
            continue
        s2 = (-2.0 * Rc + disc ** 0.5) / 4.0
        s = min(s1, s2)
        if s > 1.5 and (best is None or s > best[1]):
            best = (Rc, s)
    return best


def _disc_land(r, margin=3.0):
    """Half-size of the largest square inscribed in a disc of radius r."""
    s = (r - margin) / (2 ** 0.5)
    return s if s > 1.5 else None


def base_mount_plate(rng):
    """Rectangular mounting plate with corner bolt holes; the whole midfield
    is one flat_top land."""
    pl = _u(rng, 70, 150, 2)
    pw = _u(rng, 45, 0.8 * pl, 2)
    pt = _u(rng, 6, 14, 0.5)
    hr = _u(rng, 2.2, 4.0, 0.2)
    mx = pl / 2 - hr - 5
    my = pw / 2 - hr - 5
    v = {"pl": pl, "pw": pw, "pt": pt, "hr": hr,
         "mx": round(mx, 2), "my": round(my, 2)}
    body = "pl*pw*pt - 4*pi*hr**2*pt"
    return {
        "part_class": "mount_plate",
        "variables": v,
        "derivation": [
            {"step": 1, "eq": f"V = {body}",
             "why": "plate blank minus four corner fixing holes baked into "
                    "the pad profile"}],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_plate", "type": "Sketch", "parameters": {}},
                {"id": "plate", "type": "Pad",
                 "rationale": "base plate with corner holes in-profile",
                 "parameters": {"Length": "pt", "Type": "Length"}}],
            "sketches": [
                {"id": "s_plate", "plane": "XY",
                 "profile": {"builder": "rect_with_holes",
                             "args": {"w": "pl", "h": "pw",
                                      "holes": [["-mx", "-my", "hr"],
                                                ["mx", "-my", "hr"],
                                                ["mx", "my", "hr"],
                                                ["-mx", "my", "hr"]]}}}],
            "dependencies": [
                {"source": "s_plate", "target": "plate", "kind": "profile"}],
        },
        "assertions": [
            {"id": "corner_margin", "kind": "precondition", "tier": 1,
             "target": "min(pl/2 - mx, pw/2 - my) - hr - 2"},
            {"id": "body", "kind": "body_volume", "tier": 1,
             "tol_rel": 1e-6, "target": body},
            {"id": "len_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "pl"},
            # z extent is what catches a protruding attachment that the
            # volume sum alone would accept
            {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "pt"}],
        "body_expr": body,
        "seq": ["Sketch", "Pad"],
        "last_solid": "plate",
        "mounts": [{
            "id": "top_field", "kind": "flat_top", "z": "pt",
            # midfield between the corner holes: hole-free by construction
            "land": {"type": "rect", "w": "2*mx - 2*hr - 8",
                     "h": "2*my - 2*hr - 8", "cx": "0", "cy": "0"},
            "thickness": "pt",
        }],
    }


def base_flanged_disc(rng):
    """Turned disc with a raised hub — flange annulus and hub top are two
    separate lands with different thicknesses."""
    fr = _u(rng, 35, 70, 1)
    ft = _u(rng, 7, 14, 0.5)
    hubr = _u(rng, 0.35 * fr, 0.5 * fr, 0.5)
    hubh = _u(rng, ft + 6, ft + 20, 1)
    borer = _u(rng, 4, 0.5 * hubr, 0.5)
    v = {"fr": fr, "ft": ft, "hubr": hubr, "hubh": hubh, "borer": borer}
    body = ("pi*(fr**2 - borer**2)*ft"
            " + pi*(hubr**2 - borer**2)*(hubh - ft)")
    ring = _ring_land(hubr, fr)
    if ring is None:
        raise ValueError("flange ring too narrow for a land")
    return {
        "part_class": "flanged_disc",
        "variables": v,
        "derivation": [
            {"step": 1, "eq": f"V = {body}",
             "why": "L-section revolved: flange disc plus hub collar, both "
                    "sharing the centre bore"}],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_rev", "type": "Sketch", "parameters": {}},
                {"id": "rev", "type": "Revolution",
                 "rationale": "single-setup turned body",
                 "parameters": {"Angle": "360", "Reversed": False,
                                "_ReferenceAxis": {"object": "s_rev",
                                                   "is_sketch": True,
                                                   "subs": ["V_Axis"]}}}],
            "sketches": [
                {"id": "s_rev", "plane": "XZ", "z": "0",
                 "profile": {"builder": "polyline", "args": {"points": [
                     ["borer", "0"], ["fr", "0"], ["fr", "ft"],
                     ["hubr", "ft"], ["hubr", "hubh"], ["borer", "hubh"]]}}}],
            "dependencies": [
                {"source": "s_rev", "target": "rev", "kind": "profile"}],
        },
        "assertions": [
            {"id": "hub_wall", "kind": "precondition", "tier": 1,
             "target": "hubr - borer - 2.5"},
            {"id": "body", "kind": "body_volume", "tier": 1,
             "tol_rel": 1e-6, "target": body},
            {"id": "od_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-6, "target": "2*fr"},
            {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "hubh"}],
        "body_expr": body,
        "seq": ["Sketch", "Revolution"],
        "last_solid": "rev",
        "mounts": [
            {"id": "flange_ring", "kind": "flat_top", "z": "ft",
             # provably inside the annulus: a naive w=fr-hubr-6 square hangs
             # its far corner past the OD for most draws
             "land": {"type": "rect", "w": f"{2 * ring[1]}",
                      "h": f"{2 * ring[1]}",
                      "cx": f"{ring[0]}", "cy": "0"},
             "thickness": "ft"},
            {"id": "hub_top", "kind": "flat_top", "z": "hubh",
             "land": {"type": "rect",
                      "w": "(hubr - borer)*0.9", "h": "(hubr - borer)*0.9",
                      "cx": "(hubr + borer)/2", "cy": "0"},
             # thickness = depth to OPEN AIR, not to the next feature: the
             # hub sits on the flange, so a cut here travels hubh before it
             # breaks out. Declaring hubh-ft made through-cuts overshoot into
             # live material and broke the exact volume delta.
             "thickness": "hubh"}],
    }


def base_drafted_pedestal(rng):
    """Drafted rectangular pedestal (cast) — the shrunken top face is the
    machined land."""
    ln = _u(rng, 60, 120, 2)
    wd = _u(rng, 40, 0.85 * ln, 2)
    ht = _u(rng, 18, 40, 1)
    draft = _u(rng, 1.0, 3.0, 0.5)
    v = {"ln": ln, "wd": wd, "ht": ht, "draft_deg": draft}
    T = "tan(radians(draft_deg))"
    def area(z):
        return f"((ln - 2*({z})*{T})*(wd - 2*({z})*{T}))"
    body = (f"(ht/6*({area('0')} + 4*{area('ht/2')} + {area('ht')}))")
    top_w = f"(ln - 2*ht*{T})"
    top_h = f"(wd - 2*ht*{T})"
    return {
        "part_class": "drafted_pedestal",
        "variables": v,
        "derivation": [
            {"step": 1, "eq": f"V = {body}",
             "why": "cast pedestal drafted from the z=0 parting plane; "
                    "prismatoid exact for the bilinear taper"}],
        "template": {
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_ped", "type": "Sketch", "parameters": {}},
                {"id": "ped", "type": "Pad", "rationale": "cast blank",
                 "parameters": {"Length": "ht", "Type": "Length"}},
                {"id": "draft", "type": "Draft",
                 "rationale": "release draft on all walls",
                 "parameters": {"Angle": "draft_deg", "Reversed": False,
                                "_Base": {"object": "ped"},
                                "_Faces": "vertical",
                                "_NeutralPlane": "bottom"}}],
            "sketches": [
                {"id": "s_ped", "plane": "XY",
                 "profile": {"builder": "rect",
                             "args": {"w": "ln", "h": "wd"}}}],
            "dependencies": [
                {"source": "s_ped", "target": "ped", "kind": "profile"},
                {"source": "ped", "target": "draft", "kind": "base"}],
        },
        "assertions": [
            {"id": "taper_guard", "kind": "precondition", "tier": 1,
             "target": f"{top_h} - 0.5*wd"},
            {"id": "body", "kind": "body_volume", "tier": 1,
             "tol_rel": 1e-6, "target": body},
            {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-6, "target": "ht"}],
        "body_expr": body,
        "seq": ["Sketch", "Pad", "Draft"],
        "last_solid": "draft",
        "mounts": [{
            "id": "machined_top", "kind": "flat_top", "z": "ht",
            "land": {"type": "rect", "w": f"({top_w} - 6)",
                     "h": f"({top_h} - 6)", "cx": "0", "cy": "0"},
            "thickness": "ht",
        }],
    }


BASES = {
    "mount_plate": base_mount_plate,
    "flanged_disc": base_flanged_disc,
    "drafted_pedestal": base_drafted_pedestal,
}

# Families beyond the starter three register themselves on import.
from . import bases_ext  # noqa: E402,F401  (self-registering)

from . import bases_ext2  # noqa: E402,F401  (self-registering, tranche 2)

from . import bases_ext3  # noqa: E402,F401  (self-registering, tranche 3)

from . import bases_ext4  # noqa: E402,F401  (self-registering, tranche 4)
