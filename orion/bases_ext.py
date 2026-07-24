"""Composable base library — the Phase-5A breadth expansion (W1).

Ten further base topologies spanning the directive's domains. Each is a
genuinely distinct SHAPE class, not a renamed flange: turned steps, thin-wall
cups, folded sections, V-grooves, polygon bores, tapers, fins, triangles.
Composed with the attachment palette they generate the family space the audit
measures by topological signature rather than by name.

Domain coverage of the 42 named families:
  bearing_carrier   -> Bearing Carrier, Wheel Hub, Harmonic Drive Cover,
                       Hydraulic Cylinder Head/End Cap, Valve Bonnet
  cylindrical_shell -> Pump Housing, Compressor Casing, Cable Routing Housing,
                       Check Valve Housing, Robot Wrist Housing
  l_bracket         -> Sensor Bracket, Bulkhead Bracket, Equipment Mount,
                       Pylon Bracket, Rib-Spar Junction, Servo Mount
  u_channel         -> Structural Rib, Linear Rail Carriage, Core Pull Block
  stepped_shaft     -> Spline Hub, Tool Holder, Flow Distributor
  v_pulley          -> Pulley Block, Flywheel Carrier
  hex_hub           -> Spline Hub (polygon bore), Coupling Flange
  tapered_collar    -> Fastener Collar, Nozzle Block, Pressure Relief Body
  finned_rail       -> Heat Exchanger Header, Jig Block, Fixture Plate
  gusset_plate      -> Chassis Gusset, Control Arm Mount, Suspension Bellcrank

Every body volume is exact closed form; every mount declares its land as a
region provably free of base geometry, with ``thickness`` measured to OPEN
AIR (see the hub_top lesson in bases.py).
"""

from __future__ import annotations

from .bases import BASES, _disc_land, _ring_land
from .recipes import _u


def _draft(part_class, variables, derivation, template, assertions,
           body_expr, seq, last_solid, mounts, body_mesh=False):
    return {"part_class": part_class, "variables": variables,
            "derivation": derivation, "template": template,
            "assertions": assertions, "body_expr": body_expr,
            "seq": seq, "last_solid": last_solid, "mounts": mounts,
            "body_mesh": body_mesh}


def _rev(sid, fid, points, rationale):
    """A revolved solid from an XZ half-profile polyline about the V axis."""
    return (
        [{"id": sid, "type": "Sketch", "parameters": {}},
         {"id": fid, "type": "Revolution", "rationale": rationale,
          "parameters": {"Angle": "360", "Reversed": False,
                         "_ReferenceAxis": {"object": sid, "is_sketch": True,
                                            "subs": ["V_Axis"]}}}],
        [{"id": sid, "plane": "XZ", "z": "0",
          "profile": {"builder": "polyline", "args": {"points": points}}}],
        [{"source": sid, "target": fid, "kind": "profile"}])


# =========================================================================== #
# 1. bearing carrier — annular disc with a counterbored bearing seat
# =========================================================================== #
def base_bearing_carrier(rng):
    R = _u(rng, 28, 65, 1)
    rb = _u(rng, 6, 0.35 * R, 0.5)
    rs = _u(rng, rb + 4, min(0.75 * R, rb + 18), 0.5)
    T = _u(rng, 10, 24, 0.5)
    ds = _u(rng, 3, min(T - 4, 10), 0.5)
    ring = _ring_land(rs, R)
    if ring is None:
        raise ValueError("carrier: seat ring too narrow")
    v = {"R": R, "rb": rb, "rs": rs, "T": T, "ds": ds}
    body = "pi*(R**2 - rb**2)*(T - ds) + pi*(R**2 - rs**2)*ds"
    feats, sk, deps = _rev(
        "s_car", "carrier",
        [["rb", "0"], ["R", "0"], ["R", "T"], ["rs", "T"],
         ["rs", "T - ds"], ["rb", "T - ds"]],
        "turned bearing carrier: through bore plus a counterbored seat "
        "that locates the outer race axially")
    return _draft(
        "bearing_carrier", v,
        [{"step": 1, "eq": "V = pi(R^2-rb^2)(T-ds) + pi(R^2-rs^2)ds",
          "why": "two stacked annuli: full section below the seat, reduced "
                 "section where the race sits"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "seat_step", "kind": "precondition", "tier": 1,
          "target": "rs - rb - 3"},
         {"id": "rim_land", "kind": "precondition", "tier": 1,
          "target": "R - rs - 4"},
         {"id": "seat_floor", "kind": "precondition", "tier": 1,
          "target": "T - ds - 3"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "T"}],
        body, ["Sketch", "Revolution"], "carrier",
        [{"id": "rim_face", "kind": "flat_top", "z": "T",
          "land": {"type": "rect", "w": f"{2 * ring[1]}",
                   "h": f"{2 * ring[1]}", "cx": f"{ring[0]}", "cy": "0"},
          "thickness": "T"}])


# =========================================================================== #
# 2. cylindrical shell — thin-wall cup (pump / compressor / wrist housing)
# =========================================================================== #
def base_cylindrical_shell(rng):
    R = _u(rng, 25, 60, 1)
    wall = _u(rng, 2.5, min(6.0, R / 6), 0.25)
    H = _u(rng, 25, 70, 1)
    floor_t = _u(rng, 3, min(9.0, H / 4), 0.5)
    s = _disc_land(R - wall)
    if s is None:
        raise ValueError("shell: bore too small for a land")
    v = {"R": R, "wall": wall, "H": H, "floor_t": floor_t}
    body = "pi*R**2*floor_t + pi*(R**2 - (R - wall)**2)*(H - floor_t)"
    feats, sk, deps = _rev(
        "s_shell", "shell",
        [["0", "0"], ["R", "0"], ["R", "H"], ["R - wall", "H"],
         ["R - wall", "floor_t"], ["0", "floor_t"]],
        "thin-wall housing turned in one setup: solid floor_t, constant-"
        "thickness barrel")
    return _draft(
        "cylindrical_shell", v,
        [{"step": 1, "eq": "V = pi R^2 floor_t + pi(R^2-(R-wall)^2)(H-floor_t)",
          "why": "solid disc below the bore, annular barrel above it"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "wall_guard", "kind": "precondition", "tier": 1,
          "target": "R - wall - 8"},
         {"id": "floor_guard", "kind": "precondition", "tier": 1,
          "target": "H - floor_t - 6"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "H"}],
        body, ["Sketch", "Revolution"], "shell",
        [{"id": "inner_floor", "kind": "flat_top", "z": "floor_t",
          "land": {"type": "rect", "w": f"{2 * s}", "h": f"{2 * s}",
                   "cx": "0", "cy": "0"},
          "thickness": "floor_t"}])


# =========================================================================== #
# 3. L bracket — folded angle (sensor / bulkhead / pylon / servo mount)
# =========================================================================== #
def base_l_bracket(rng):
    L = _u(rng, 50, 120, 2)
    W = _u(rng, 40, 90, 2)
    t = _u(rng, 5, 12, 0.5)
    tw = _u(rng, 5, 12, 0.5)
    h = _u(rng, 20, 55, 1)
    if W - tw < 24:
        raise ValueError("bracket: no land beside the wall")
    v = {"L": L, "W": W, "t": t, "tw": tw, "h": h}
    body = "L*W*t + L*tw*h"
    return _draft(
        "l_bracket", v,
        [{"step": 1, "eq": "V = L*W*t + L*tw*h",
          "why": "base flange plus an upstand wall along one edge; the wall "
                 "sits ON the flange so the interface adds no volume"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_base", "type": "Sketch", "parameters": {}},
            {"id": "base", "type": "Pad", "rationale": "mounting flange",
             "parameters": {"Length": "t", "Type": "Length"}},
            {"id": "s_wall", "type": "Sketch", "parameters": {}},
            {"id": "wall", "type": "Pad",
             "rationale": "upstand that carries the load into the flange",
             "parameters": {"Length": "h", "Type": "Length"}}],
         "sketches": [
            {"id": "s_base", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_wall", "plane": "XY", "z": "t",
             "profile": {"builder": "rect",
                         "args": {"w": "L", "h": "tw",
                                  "cy": "-W/2 + tw/2"}}}],
         "dependencies": [
            {"source": "s_base", "target": "base", "kind": "profile"},
            {"source": "s_wall", "target": "wall", "kind": "profile"},
            {"source": "base", "target": "wall", "kind": "base"}]},
        [{"id": "land_guard", "kind": "precondition", "tier": 1,
          "target": "W - tw - 20"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "t + h"}],
        body, ["Sketch", "Pad", "Sketch", "Pad"], "wall",
        [{"id": "flange_field", "kind": "flat_top", "z": "t",
          "land": {"type": "rect", "w": "L - 8", "h": "W - tw - 10",
                   "cx": "0", "cy": "tw/2"},
          "thickness": "t"}])


# =========================================================================== #
# 4. U channel — pocketed section (structural rib / rail carriage)
# =========================================================================== #
def base_u_channel(rng):
    L = _u(rng, 60, 140, 2)
    W = _u(rng, 35, 80, 2)
    H = _u(rng, 20, 50, 1)
    t = _u(rng, 4, min(9.0, W / 6, H / 4), 0.5)
    if W - 2 * t < 22:
        raise ValueError("channel: interior too narrow")
    v = {"L": L, "W": W, "H": H, "t": t}
    body = "L*W*H - L*(W - 2*t)*(H - t)"
    return _draft(
        "u_channel", v,
        [{"step": 1, "eq": "V = L*W*H - L*(W-2t)*(H-t)",
          "why": "channel milled from solid: the pocket overshoots in X so "
                 "the removal is exactly the interior prism"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_blk", "type": "Sketch", "parameters": {}},
            {"id": "blk", "type": "Pad", "rationale": "section blank",
             "parameters": {"Length": "H", "Type": "Length"}},
            {"id": "s_pocket", "type": "Sketch", "parameters": {}},
            {"id": "channel", "type": "Pocket",
             "rationale": "open channel: web plus two flanges",
             "parameters": {"Length": "H - t", "Type": "Length"}}],
         "sketches": [
            {"id": "s_blk", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_pocket", "plane": "XY", "z": "H",
             "profile": {"builder": "rect",
                         "args": {"w": "L + 4", "h": "W - 2*t"}}}],
         "dependencies": [
            {"source": "s_blk", "target": "blk", "kind": "profile"},
            {"source": "s_pocket", "target": "channel", "kind": "profile"},
            {"source": "blk", "target": "channel", "kind": "base"}]},
        [{"id": "flange_guard", "kind": "precondition", "tier": 1,
          "target": "W - 2*t - 20"},
         {"id": "web_guard", "kind": "precondition", "tier": 1,
          "target": "H - t - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "H"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "channel",
        [{"id": "web_floor", "kind": "flat_top", "z": "t",
          "land": {"type": "rect", "w": "L - 10", "h": "W - 2*t - 8",
                   "cx": "0", "cy": "0"},
          "thickness": "t"}])


# =========================================================================== #
# 5. stepped shaft — turned two-diameter hub (spline hub / tool holder)
# =========================================================================== #
def base_stepped_shaft(rng):
    r1 = _u(rng, 22, 45, 0.5)
    r2 = _u(rng, 14, r1 - 4, 0.5)
    rb = _u(rng, 3, r2 - 9, 0.5)
    L1 = _u(rng, 8, 25, 0.5)
    L2 = _u(rng, 10, 40, 1)
    ring = _ring_land(rb, r2)
    if ring is None:
        raise ValueError("shaft: nose ring too narrow")
    v = {"r1": r1, "r2": r2, "rb": rb, "L1": L1, "L2": L2}
    body = "pi*(r1**2 - rb**2)*L1 + pi*(r2**2 - rb**2)*L2"
    feats, sk, deps = _rev(
        "s_shaft", "shaft",
        [["rb", "0"], ["r1", "0"], ["r1", "L1"], ["r2", "L1"],
         ["r2", "L1 + L2"], ["rb", "L1 + L2"]],
        "stepped hub: large register diameter for the housing, reduced "
        "nose for the mating part, common through bore")
    return _draft(
        "stepped_shaft", v,
        [{"step": 1, "eq": "V = pi(r1^2-rb^2)L1 + pi(r2^2-rb^2)L2",
          "why": "two coaxial annuli stacked at the shoulder"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "shoulder", "kind": "precondition", "tier": 1,
          "target": "r1 - r2 - 3"},
         {"id": "nose_wall", "kind": "precondition", "tier": 1,
          "target": "r2 - rb - 3"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*r1"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "L1 + L2"}],
        body, ["Sketch", "Revolution"], "shaft",
        [{"id": "nose_face", "kind": "flat_top", "z": "L1 + L2",
          "land": {"type": "rect", "w": f"{2 * ring[1]}",
                   "h": f"{2 * ring[1]}", "cx": f"{ring[0]}", "cy": "0"},
          "thickness": "L1 + L2"}])


# =========================================================================== #
# 6. V pulley — disc with a revolved V groove
# =========================================================================== #
def base_v_pulley(rng):
    R = _u(rng, 30, 70, 1)
    rb = _u(rng, 5, 0.25 * R, 0.5)
    T = _u(rng, 12, 26, 0.5)
    gw = _u(rng, 5, min(T - 6, 14), 0.5)
    gd = _u(rng, 4, min(0.35 * R, 14), 0.5)
    ring = _ring_land(rb, R - gd)
    v = {"R": R, "rb": rb, "T": T, "gw": gw, "gd": gd}
    groove = "(gw*gd/2)*2*pi*(R - gd/3)"
    body = f"pi*(R**2 - rb**2)*T - {groove}"
    mounts = []
    if ring is not None:
        mounts.append({"id": "hub_face", "kind": "flat_top", "z": "T",
                       "land": {"type": "rect", "w": f"{2 * ring[1]}",
                                "h": f"{2 * ring[1]}",
                                "cx": f"{ring[0]}", "cy": "0"},
                       "thickness": "T"})
    return _draft(
        "v_pulley", v,
        [{"step": 1, "eq": "V_disc = pi(R^2-rb^2)T"},
         {"step": 2, "eq": f"V_groove = {groove}",
          "why": "the V section is a triangle whose centroid sits at "
                 "R - gd/3; Pappus revolves it exactly"},
         {"step": 3, "eq": "V = V_disc - V_groove"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_disc", "type": "Sketch", "parameters": {}},
            {"id": "disc", "type": "Revolution",
             "rationale": "pulley blank turned between centres",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_disc",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}},
            {"id": "s_vee", "type": "Sketch", "parameters": {}},
            {"id": "vee", "type": "Groove",
             "rationale": "V groove: the belt wedges in and grips on the "
                          "flanks, not the root",
             "parameters": {"Angle": "360", "Reversed": False,
                            "_ReferenceAxis": {"object": "s_vee",
                                               "is_sketch": True,
                                               "subs": ["V_Axis"]}}}],
         "sketches": [
            {"id": "s_disc", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["rb", "0"], ["R", "0"], ["R", "T"], ["rb", "T"]]}}},
            {"id": "s_vee", "plane": "XZ", "z": "0",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["R", "T/2 - gw/2"], ["R", "T/2 + gw/2"],
                 ["R - gd", "T/2"]]}}}],
         "dependencies": [
            {"source": "s_disc", "target": "disc", "kind": "profile"},
            {"source": "s_vee", "target": "vee", "kind": "profile"},
            {"source": "disc", "target": "vee", "kind": "base"}]},
        [{"id": "rim_guard", "kind": "precondition", "tier": 1,
          "target": "T - gw - 5"},
         {"id": "root_guard", "kind": "precondition", "tier": 1,
          "target": "R - gd - rb - 8"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "T"}],
        body, ["Sketch", "Revolution", "Sketch", "Groove"], "vee", mounts)


# =========================================================================== #
# 7. hex hub — disc with a hexagonal bore (spline/coupling)
# =========================================================================== #
def base_hex_hub(rng):
    R = _u(rng, 25, 55, 1)
    rc = _u(rng, 8, 0.6 * R, 0.5)
    T = _u(rng, 10, 26, 0.5)
    ring = _ring_land(rc, R)
    if ring is None:
        raise ValueError("hex hub: rim too narrow")
    v = {"R": R, "rc": rc, "T": T}
    hexa = "0.5*6*rc**2*sin(2*pi/6)"
    body = f"pi*R**2*T - ({hexa})*T"
    return _draft(
        "hex_hub", v,
        [{"step": 1, "eq": f"A_hex = {hexa}",
          "why": "regular hexagon of circumradius rc"},
         {"step": 2, "eq": "V = pi R^2 T - A_hex*T",
          "why": "broached hex bore runs the full thickness, so the removal "
                 "is a straight prism"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_disc", "type": "Sketch", "parameters": {}},
            {"id": "disc", "type": "Pad", "rationale": "hub blank",
             "parameters": {"Length": "T", "Type": "Length"}},
            {"id": "s_hex", "type": "Sketch", "parameters": {}},
            {"id": "hexbore", "type": "Pocket",
             "rationale": "hex bore transmits torque without a key",
             # BOTH legs overshoot the full thickness: the sketch sits on the
             # z=0 face, so which leg points into material depends on the
             # sketch normal. Symmetric legs remove exactly T either way —
             # an asymmetric pair silently removed only the 1mm return leg.
             "parameters": {"Length": "T + 1", "Type": "Length",
                            "Length2": "T + 1", "Type2": "Length",
                            "SideType": "Two sides"}}],
         "sketches": [
            {"id": "s_disc", "plane": "XY",
             "profile": {"builder": "circle", "args": {"r": "R"}}},
            {"id": "s_hex", "plane": "XY", "z": "0",
             "profile": {"builder": "regular_polygon",
                         "args": {"n": "6", "r_circum": "rc"}}}],
         "dependencies": [
            {"source": "s_disc", "target": "disc", "kind": "profile"},
            {"source": "s_hex", "target": "hexbore", "kind": "profile"},
            {"source": "disc", "target": "hexbore", "kind": "base"}]},
        [{"id": "rim_guard", "kind": "precondition", "tier": 1,
          "target": "R - rc - 6"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "T"}],
        body, ["Sketch", "Pad", "Sketch", "Pocket"], "hexbore",
        [{"id": "hub_face", "kind": "flat_top", "z": "T",
          "land": {"type": "rect", "w": f"{2 * ring[1]}",
                   "h": f"{2 * ring[1]}", "cx": f"{ring[0]}", "cy": "0"},
          "thickness": "T"}])


# =========================================================================== #
# 8. tapered collar — bored frustum (fastener collar / nozzle)
# =========================================================================== #
def base_tapered_collar(rng):
    R1 = _u(rng, 26, 55, 1)
    R2 = _u(rng, 16, R1 - 5, 1)
    h = _u(rng, 15, 45, 1)
    rb = _u(rng, 4, R2 - 10, 0.5)
    ring = _ring_land(rb, R2)
    if ring is None:
        raise ValueError("collar: top ring too narrow")
    v = {"R1": R1, "R2": R2, "h": h, "rb": rb}
    body = "pi*h/3*(R1**2 + R1*R2 + R2**2) - pi*rb**2*h"
    feats, sk, deps = _rev(
        "s_collar", "collar",
        [["rb", "0"], ["R1", "0"], ["R2", "h"], ["rb", "h"]],
        "tapered collar: the cone spreads the clamp load and sheds stress "
        "concentration at the seat")
    return _draft(
        "tapered_collar", v,
        [{"step": 1, "eq": "V = pi h/3 (R1^2+R1R2+R2^2) - pi rb^2 h",
          "why": "the revolved trapezoid is a cone frustum; the bore is a "
                 "straight cylinder through it"}],
        {"features": [{"id": "Body", "type": "Body", "parameters": {}}] + feats,
         "sketches": sk, "dependencies": deps},
        [{"id": "taper_guard", "kind": "precondition", "tier": 1,
          "target": "R1 - R2 - 4"},
         {"id": "top_wall", "kind": "precondition", "tier": 1,
          "target": "R2 - rb - 4"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "2*R1"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "h"}],
        body, ["Sketch", "Revolution"], "collar",
        [{"id": "top_face", "kind": "flat_top", "z": "h",
          "land": {"type": "rect", "w": f"{2 * ring[1]}",
                   "h": f"{2 * ring[1]}", "cx": f"{ring[0]}", "cy": "0"},
          "thickness": "h"}])


# =========================================================================== #
# 9. finned rail — base with a patterned fin array (heat exchanger / jig)
# =========================================================================== #
def base_finned_rail(rng):
    L = _u(rng, 90, 170, 2)
    W = _u(rng, 40, 80, 2)
    T = _u(rng, 8, 16, 0.5)
    ft = _u(rng, 3, 6, 0.5)
    fh = _u(rng, 8, 22, 1)
    fl = _u(rng, 0.5 * W, W - 6, 1)
    n = rng.choice([3, 4, 5])
    span_hi = L / 2 - 10 - ft
    pitch_min = ft + 4
    if pitch_min * (n - 1) >= span_hi:
        raise ValueError("rail: fin array does not fit in the left half")
    span = _u(rng, pitch_min * (n - 1), span_hi, 1)
    seed_cx = round(-L / 2 + 6 + ft / 2, 2)
    v = {"L": L, "W": W, "T": T, "ft": ft, "fh": fh, "fl": fl,
         "fn": float(n), "span": span, "seed_cx": seed_cx}
    body = "L*W*T + fn*ft*fl*fh"
    return _draft(
        "finned_rail", v,
        [{"step": 1, "eq": "V = L*W*T + fn*ft*fl*fh",
          "why": "fins stand on the base plate; the pattern replicates one "
                 "master so the array volume is exactly N times a fin"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_base", "type": "Sketch", "parameters": {}},
            {"id": "plate", "type": "Pad", "rationale": "rail base",
             "parameters": {"Length": "T", "Type": "Length"}},
            {"id": "s_fin", "type": "Sketch", "parameters": {}},
            {"id": "fin", "type": "Pad", "rationale": "master cooling fin",
             "parameters": {"Length": "fh", "Type": "Length"}},
            {"id": "fins", "type": "LinearPattern",
             "rationale": "fin array along the flow direction",
             "parameters": {"Occurrences": "fn", "Length": "span",
                            "_Direction": {"role": "X_Axis", "subs": [""]},
                            "_Originals": ["fin"]}}],
         "sketches": [
            {"id": "s_base", "plane": "XY",
             "profile": {"builder": "rect", "args": {"w": "L", "h": "W"}}},
            {"id": "s_fin", "plane": "XY", "z": "T",
             "profile": {"builder": "rect",
                         "args": {"w": "ft", "h": "fl", "cx": "seed_cx"}}}],
         "dependencies": [
            {"source": "s_base", "target": "plate", "kind": "profile"},
            {"source": "s_fin", "target": "fin", "kind": "profile"},
            {"source": "plate", "target": "fin", "kind": "base"},
            {"source": "fin", "target": "fins", "kind": "base"}]},
        [{"id": "pitch_guard", "kind": "precondition", "tier": 1,
          "target": "span/(fn - 1) - ft - 3"},
         {"id": "array_fits", "kind": "precondition", "tier": 1,
          "target": "-(seed_cx + span + ft/2) - 3",
          "why": "the fin array must end before mid-length, leaving the "
                 "downstream half as a clear mounting land"},
         {"id": "fin_width", "kind": "precondition", "tier": 1,
          "target": "W - fl - 4"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "L"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "T + fh"}],
        body, ["Sketch", "Pad", "Sketch", "Pad", "LinearPattern"], "fins",
        [{"id": "clear_end", "kind": "flat_top", "z": "T",
          "land": {"type": "rect", "w": "L/2 - 10", "h": "W - 10",
                   "cx": "L/4 + 3", "cy": "0"},
          "thickness": "T"}])


# =========================================================================== #
# 10. gusset plate — right-triangle web (chassis gusset / arm mount)
# =========================================================================== #
def base_gusset_plate(rng):
    a = _u(rng, 55, 130, 2)
    b = _u(rng, 45, 110, 2)
    t = _u(rng, 5, 12, 0.5)
    v = {"a": a, "b": b, "t": t}
    body = "0.5*a*b*t"
    return _draft(
        "gusset_plate", v,
        [{"step": 1, "eq": "V = 0.5*a*b*t",
          "why": "right-triangle web: the hypotenuse is the free edge, the "
                 "two legs weld to the members being braced"}],
        {"features": [
            {"id": "Body", "type": "Body", "parameters": {}},
            {"id": "s_tri", "type": "Sketch", "parameters": {}},
            {"id": "web", "type": "Pad", "rationale": "gusset web",
             "parameters": {"Length": "t", "Type": "Length"}}],
         "sketches": [
            {"id": "s_tri", "plane": "XY",
             "profile": {"builder": "polyline", "args": {"points": [
                 ["0", "0"], ["a", "0"], ["0", "b"]]}}}],
         "dependencies": [
            {"source": "s_tri", "target": "web", "kind": "profile"}]},
        [{"id": "aspect_guard", "kind": "precondition", "tier": 1,
          "target": "min(a, b) - 40"},
         {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-6,
          "target": body},
         {"id": "len_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
          "tol_rel": 1e-6, "target": "a"},
         {"id": "height_extent", "kind": "bbox_extent", "axis": "z",
          "tier": 1, "tol_rel": 1e-6, "target": "t"}],
        body, ["Sketch", "Pad"], "web",
        # land near the right angle: the far corner (0.325a, 0.325b) satisfies
        # x/a + y/b = 0.65 < 1, so the square is provably inside the triangle
        [{"id": "corner_field", "kind": "flat_top", "z": "t",
          "land": {"type": "rect", "w": "a/4", "h": "b/4",
                   "cx": "a/5", "cy": "b/5"},
          "thickness": "t"}])


BASES.update({
    "bearing_carrier": base_bearing_carrier,
    "cylindrical_shell": base_cylindrical_shell,
    "l_bracket": base_l_bracket,
    "u_channel": base_u_channel,
    "stepped_shaft": base_stepped_shaft,
    "v_pulley": base_v_pulley,
    "hex_hub": base_hex_hub,
    "tapered_collar": base_tapered_collar,
    "finned_rail": base_finned_rail,
    "gusset_plate": base_gusset_plate,
})
