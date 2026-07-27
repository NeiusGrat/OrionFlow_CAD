"""AssemblySpec — the contract a model authors for an assembly.

V2's lesson applies unchanged: the model authors, the harness derives. For a
single part the authored object is a Blueprint; for an assembly it is this —
which components (by family and parameters), how they relate (mates), and what
must be true (assertions). Masses, inertias, ratios, mobility and the
verification report are all *derived* downstream and must never be generated,
because the model cannot do arithmetic and the kernel can.

A spec is compact for the same reason a drawing is: it references a catalogue
("M8x40 hex bolt") instead of restating geometry.

Three reference assemblies are built here, one per capability tier:

* :func:`bolted_joint`  — fasteners: grip length, thread engagement, torque
* :func:`bearing_stack` — bearings: seat fits, shoulder location, ring clearance
* :func:`four_bar`      — motion: loop closure and the Grashof condition
"""

from __future__ import annotations

import math

from . import families as F


def resolve_spec(spec: dict) -> dict:
    """Turn family references into frozen Blueprints ready for the builder."""
    parts = []
    for c in spec["components"]:
        bp = F.make(c["family"], **c["params"])
        parts.append({"id": c["id"], "blueprint": bp,
                      "pos": c.get("pos", [0.0, 0.0, 0.0]),
                      "rot_z": c.get("rot_z", 0.0),
                      "process": c.get("process", "machined")})
    return {"name": spec["assembly_class"], "variables": spec["variables"],
            "parts": parts, "assertions": spec["assertions"],
            "mates": spec.get("mates", [])}


# --------------------------------------------------------------------------- #
# Tier 3 — a real bolted joint
# --------------------------------------------------------------------------- #
def bolted_joint(d: float = 8.0, plate_t: float = 10.0, n_bolts: int = 2,
                 cls: str = "8.8") -> dict:
    """Two plates clamped by hex bolts, each with a washer and nut.

    The engineering content is in the stack-up, not the shapes. Grip length is
    ``2*plate_t``; the bolt must be long enough for the grip plus washer plus
    nut plus thread protrusion, and clearance holes must leave enough edge
    distance that the joint does not tear out.
    """
    g = F.ISO_HEX[d]
    hole_r = (d + 1.0) / 2.0                      # normal clearance, ISO 273
    washer_t = 1.6 if d <= 8 else 2.5
    washer_od = 2.0 * d
    grip = 2.0 * plate_t
    # protrude at least two pitches past the nut, the usual shop rule
    length = grip + washer_t + g["nut_h"] + 2.0 * g["pitch"]
    length = math.ceil(length / 5.0) * 5.0        # to the next stock length
    hole_dx = 25.0 + 2.0 * d
    plate_l = 2.0 * hole_dx + 6.0 * d
    plate_w = 6.0 * d
    torque = F.bolt_torque_nm(d, cls)

    comps = [
        {"id": "plate_lower", "family": "clearance_plate",
         "params": dict(length=plate_l, width=plate_w, t=plate_t,
                        hole_r=hole_r, hole_dx=hole_dx),
         "pos": [0.0, 0.0, 0.0], "process": "laser cut + drilled"},
        {"id": "plate_upper", "family": "clearance_plate",
         "params": dict(length=plate_l, width=plate_w, t=plate_t,
                        hole_r=hole_r, hole_dx=hole_dx),
         "pos": [0.0, 0.0, plate_t], "process": "laser cut + drilled"},
    ]
    mates = [{"id": "faying_surface", "type": "coincident",
              "between": ["plate_lower", "plate_upper"],
              "reference": "upper face of lower plate to lower face of upper",
              "dof_removed": 3, "dof_remaining": ["slide X", "slide Y", "spin Z"],
              "assembly_order": 1, "tolerance": "flatness 0.1 over the faying area"}]

    for k in range(n_bolts):
        x = -hole_dx if k == 0 else hole_dx
        comps += [
            {"id": f"bolt{k}", "family": "hex_bolt",
             "params": dict(d=d, length=length, cls=cls),
             # head sits below the lower plate; shank rises through both
             "pos": [x, 0.0, -g["head_h"]], "process": "cold formed, rolled thread"},
            {"id": f"washer{k}", "family": "washer",
             "params": dict(d=d + 1.0, od=washer_od, t=washer_t),
             "pos": [x, 0.0, grip], "process": "stamped"},
            {"id": f"nut{k}", "family": "hex_nut", "params": dict(d=d),
             "pos": [x, 0.0, grip + washer_t], "process": "cold formed, tapped"},
        ]
        mates += [
            {"id": f"bolt{k}_through", "type": "concentric",
             "between": [f"bolt{k}", "plate_lower"],
             "reference": f"bolt {k} shank to clearance hole {k}",
             "dof_removed": 4, "dof_remaining": ["slide Z", "spin Z"],
             "assembly_order": 2, "tolerance": "H13 clearance hole"},
            {"id": f"nut{k}_thread", "type": "screw",
             "between": [f"bolt{k}", f"nut{k}"],
             "reference": f"M{d:g}x{g['pitch']} thread",
             "constraint": f"pitch {g['pitch']} mm, class {cls}, "
                           f"tightening torque {torque:.1f} Nm",
             "dof_removed": 5, "dof_remaining": ["helical"],
             "assembly_order": 4, "tolerance": "6H/6g"},
        ]

    variables = {
        "d": d, "plate_t": plate_t, "n_bolts": float(n_bolts),
        "hole_r": hole_r, "washer_t": washer_t, "nut_h": g["nut_h"],
        "head_h": g["head_h"], "pitch": g["pitch"], "grip": grip,
        "length": length, "hole_dx": hole_dx, "plate_l": plate_l,
        "plate_w": plate_w, "torque_nm": torque,
    }
    return {
        "assembly_class": "bolted_joint",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            # the bolt must actually reach through everything it clamps
            {"id": "bolt_long_enough", "kind": "precondition", "tier": 1,
             "target": "length - grip - washer_t - nut_h - 2*pitch"},
            # ...and not be so long the thread runs out into the grip
            {"id": "not_overlong", "kind": "precondition", "tier": 1,
             "target": "grip + washer_t + nut_h + 8*pitch - length"},
            {"id": "edge_distance", "kind": "precondition", "tier": 1,
             "target": "plate_l/2 - hole_dx - 1.5*d"},
            {"id": "clearance_fit", "kind": "precondition", "tier": 1,
             "target": "hole_r - d/2"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1,
             "target": "2 + 3*n_bolts"},
            # Bolts come in stock lengths, so the shank protrudes past the
            # nut by whatever the rounding left over; the Z extent is
            # therefore head + full bolt length, not head + the clamped stack.
            {"id": "stack_height", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "head_h + length"},
            # everything in a bolted joint touches something: one body
            {"id": "joined", "kind": "fused_solids", "tier": 1, "target": "1"},
        ],
    }


# --------------------------------------------------------------------------- #
# Tier 4 — shaft / bearing stack
# --------------------------------------------------------------------------- #
def bearing_stack(bore: float = 30.0, ring_t: float = 6.0,
                  ball_gap: float = 4.0, width: float = 14.0,
                  shaft_len: float = 70.0) -> dict:
    """A shaft located in a rolling bearing: seat, inner ring, outer ring.

    Rings are nominally *tangent* to what they mount on, never overlapping.
    That is not a simplification of the fit — an interference fit is a
    *tolerance*, expressed as data (k6 on the shaft, H7 in the housing), while
    nominal geometry is coincident. Modelling the interference as overlapping
    solids would be wrong CAD and would break the additivity proof.
    """
    r_seat = bore / 2.0
    r_inner_out = r_seat + ring_t
    r_outer_in = r_inner_out + ball_gap
    r_outer_out = r_outer_in + ring_t
    seat_len = width

    comps = [
        {"id": "shaft", "family": "bearing_shaft",
         "params": dict(r_shaft=r_seat - 2.0, r_seat=r_seat,
                        length=shaft_len, seat_len=seat_len),
         "pos": [0.0, 0.0, 0.0], "process": "turned + ground"},
        {"id": "inner_ring", "family": "bearing_ring",
         "params": dict(r_inner=r_seat, r_outer=r_inner_out, width=width,
                        kind="inner_ring"),
         "pos": [0.0, 0.0, shaft_len], "process": "hardened + ground"},
        {"id": "outer_ring", "family": "bearing_ring",
         "params": dict(r_inner=r_outer_in, r_outer=r_outer_out, width=width,
                        kind="outer_ring"),
         "pos": [0.0, 0.0, shaft_len], "process": "hardened + ground"},
    ]
    mates = [
        {"id": "inner_on_seat", "type": "concentric",
         "between": ["shaft", "inner_ring"],
         "reference": "bearing bore to shaft seat",
         "constraint": f"nominal {bore:g} mm, shaft k6 / bore H7 -> "
                       "interference 0.002-0.021 mm (press fit)",
         "dof_removed": 5, "dof_remaining": [],
         "assembly_order": 1, "tolerance": "k6"},
        {"id": "shoulder_locate", "type": "coincident",
         "between": ["shaft", "inner_ring"],
         "reference": "shaft shoulder to inner-ring face",
         "constraint": "axial location; shoulder must clear the ring bore "
                       "chamfer but not foul the rolling elements",
         "dof_removed": 1, "dof_remaining": [], "assembly_order": 1,
         "tolerance": "perpendicularity 0.02 to datum B"},
        {"id": "rolling_pair", "type": "cylindrical",
         "between": ["inner_ring", "outer_ring"],
         "reference": "raceways, rolling elements not modelled",
         "constraint": f"radial space {ball_gap:g} mm for the ball set",
         "dof_removed": 4, "dof_remaining": ["rotation Z"],
         "assembly_order": 2, "tolerance": "C3 internal clearance"},
    ]
    variables = {
        "bore": bore, "r_seat": r_seat, "ring_t": ring_t,
        "ball_gap": ball_gap, "width": width, "shaft_len": shaft_len,
        "r_inner_out": r_inner_out, "r_outer_in": r_outer_in,
        "r_outer_out": r_outer_out,
    }
    return {
        "assembly_class": "bearing_stack",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            {"id": "ring_section", "kind": "precondition", "tier": 1,
             "target": "ring_t - 2"},
            {"id": "ball_space", "kind": "precondition", "tier": 1,
             "target": "ball_gap - 2"},
            {"id": "seat_shoulder", "kind": "precondition", "tier": 1,
             "target": "r_seat - (r_seat - 2) - 1"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "3"},
            {"id": "od_extent", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "2*r_outer_out"},
        ],
    }


# --------------------------------------------------------------------------- #
# planetary stage, expressed like every other family
# --------------------------------------------------------------------------- #
def planetary_stage_spec(module: float = 2.0, z_sun: int = 24,
                         z_planet: int = 18, n_planets: int = 3,
                         face_width: float = 12.0, sun_bore: float = 8.0,
                         planet_bore: float = 5.0) -> dict:
    """Sun plus N planets at their true meshing centre distance.

    Restated as family references with a full mate graph. The original version
    returned already-resolved Blueprints, so the packer had nothing to put in
    the ``mates`` field and a quarter of the assembly corpus would have taught
    assemblies *without relationships* — which is the one thing an assembly
    dataset must not do.
    """
    a = module * (z_sun + z_planet) / 2.0
    z_ring = z_sun + 2 * z_planet
    d_tip_planet = module * (z_planet + 2)

    # Gear rules live in gear_family and are called, never restated — three
    # separate samplers previously re-derived them and one forgot a rule.
    from .gear_family import flank_points_for as _fpts, teeth_problems
    for z in (z_sun, z_planet):
        probs = teeth_problems(z)
        if probs:
            raise ValueError(f"planetary gear z={z}: " + "; ".join(probs))

    comps = [{"id": "sun", "family": "spur_gear",
              "params": dict(module=module, teeth=z_sun, bore_r=sun_bore,
                             t=face_width, alpha=20.0, fpts=_fpts(z_sun)),
              "pos": [0.0, 0.0, 0.0], "rot_z": 0.0,
              "process": "CNC hobbed, case hardened"}]
    mates = []
    for k in range(n_planets):
        th = 2.0 * math.pi * k / n_planets
        comps.append({
            "id": f"planet{k}", "family": "spur_gear",
            "params": dict(module=module, teeth=z_planet, bore_r=planet_bore,
                           t=face_width, alpha=20.0, fpts=_fpts(z_planet)),
            "pos": [a * math.cos(th), a * math.sin(th), 0.0],
            # phase each planet so its teeth land in the sun's gaps
            "rot_z": math.degrees(th) * (1.0 + z_sun / z_planet)
                     + 180.0 / z_planet,
            "process": "CNC hobbed, case hardened"})
        mates += [
            {"id": f"mesh_sun_planet{k}", "type": "gear",
             "between": ["sun", f"planet{k}"],
             "reference": "pitch circles, external mesh",
             "constraint": f"centre distance {a:.3f} mm, module {module:g}, "
                           f"ratio -{z_sun}/{z_planet}",
             "dof_removed": 1, "dof_remaining": ["coupled rotation"],
             "assembly_order": 2 + k, "tolerance": "backlash 0.05-0.12 mm"},
            {"id": f"planet{k}_on_pin", "type": "revolute",
             "between": ["carrier", f"planet{k}"],
             "reference": f"planet {k} bore on its carrier pin",
             "dof_removed": 5, "dof_remaining": ["rotation Z"],
             "assembly_order": 2 + k, "tolerance": "H7/g6 running fit"},
        ]
    mates.append({"id": "sun_on_axis", "type": "concentric",
                  "between": ["frame", "sun"],
                  "reference": "sun bore to stage axis",
                  "dof_removed": 4, "dof_remaining": ["rotation Z"],
                  "assembly_order": 1, "tolerance": "H7/g6"})

    variables = {
        "module": module, "z_sun": float(z_sun), "z_planet": float(z_planet),
        "n_planets": float(n_planets), "face_width": face_width,
        "sun_bore": sun_bore, "planet_bore": planet_bore,
        "a": a, "z_ring": float(z_ring), "d_tip_planet": d_tip_planet,
    }
    return {
        "assembly_class": "planetary_stage",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            {"id": "assembly_condition", "kind": "precondition", "tier": 1,
             "target": "0.5 - abs((z_sun + z_ring)/n_planets "
                       "- round((z_sun + z_ring)/n_planets))"},
            {"id": "planet_clearance", "kind": "precondition", "tier": 1,
             "target": "2*a*sin(pi/n_planets) - d_tip_planet - 1.0"},
            {"id": "sun_rim", "kind": "precondition", "tier": 1,
             "target": "module*z_sun/2 - 1.25*module - sun_bore - 1.5*module"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1,
             "target": "n_planets + 1"},
            # gears run on clearance, so nothing fuses: N separate bodies
            {"id": "free_running", "kind": "fused_solids", "tier": 1,
             "target": "n_planets + 1"},
            {"id": "stage_height", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "face_width"},
        ],
    }


# --------------------------------------------------------------------------- #
# Power transmission — open belt drive
# --------------------------------------------------------------------------- #
def belt_drive(d1: float = 80.0, d2: float = 200.0, centres: float = 320.0,
               width: float = 25.0, bore1: float = 19.0, bore2: float = 25.0
               ) -> dict:
    """Two pulleys on parallel shafts, driven by an open belt.

    Closed-form drive geometry, all of it standard:

    * **speed ratio**  ``i = d2/d1`` — the pitch diameters set it, which is why
      the pulley is modelled to its pitch diameter and nothing else.
    * **pitch length**  ``L = 2C + pi*(d1+d2)/2 + (d2-d1)^2/(4C)`` — the open
      belt wraps each pulley over a different arc and runs straight between the
      tangent points; this is the exact length of that path.
    * **wrap angle on the small pulley**
      ``theta = pi - 2*asin((d2-d1)/(2C))`` — the binding constraint in
      practice. Below roughly 120 degrees a friction belt slips before it
      transmits rated torque, so that is a precondition, not a note.

    The belt is carried as data rather than geometry. It is a flexible closed
    loop tangent to two circles; modelling it as a solid would add kernel cost
    and would make the *non-interference* proof meaningless, since a belt is
    supposed to touch both pulleys.
    """
    r1, r2 = d1 / 2.0, d2 / 2.0
    ratio = d2 / d1
    length = (2 * centres + math.pi * (d1 + d2) / 2.0
              + (d2 - d1) ** 2 / (4.0 * centres))
    wrap_small = math.degrees(math.pi - 2 * math.asin(
        min(1.0, (d2 - d1) / (2.0 * centres))))
    wrap_large = 360.0 - wrap_small

    comps = [
        {"id": "driver", "family": "flat_pulley",
         "params": dict(pitch_r=r1, bore_r=bore1 / 2.0, width=width),
         "pos": [0.0, 0.0, 0.0], "process": "turned + bored"},
        {"id": "driven", "family": "flat_pulley",
         "params": dict(pitch_r=r2, bore_r=bore2 / 2.0, width=width),
         "pos": [centres, 0.0, 0.0], "process": "turned + bored"},
    ]
    mates = [
        {"id": "driver_on_shaft", "type": "concentric",
         "between": ["frame", "driver"],
         "reference": "driver bore to input shaft",
         "dof_removed": 4, "dof_remaining": ["rotation Z"],
         "assembly_order": 1, "tolerance": "H7/k6 with key"},
        {"id": "driven_on_shaft", "type": "concentric",
         "between": ["frame", "driven"],
         "reference": "driven bore to output shaft",
         "dof_removed": 4, "dof_remaining": ["rotation Z"],
         "assembly_order": 2, "tolerance": "H7/k6 with key"},
        {"id": "belt_coupling", "type": "belt",
         "between": ["driver", "driven"],
         "reference": "belt tangent to both pitch circles",
         "constraint": f"open belt, pitch length {length:.1f} mm, "
                       f"ratio {ratio:.3f}:1, wrap {wrap_small:.1f} deg on the "
                       f"small pulley",
         "dof_removed": 1, "dof_remaining": ["coupled rotation"],
         "assembly_order": 3,
         "tolerance": "centre distance adjustable +/- 2% for tensioning"},
    ]
    variables = {
        "d1": d1, "d2": d2, "centres": centres, "width": width,
        "bore1": bore1, "bore2": bore2, "r1": r1, "r2": r2,
        "ratio": ratio, "belt_length": length,
        "wrap_small_deg": wrap_small, "wrap_large_deg": wrap_large,
    }
    return {
        "assembly_class": "belt_drive",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            # pulleys must not touch, with room to fit and tension the belt
            {"id": "pulley_gap", "kind": "precondition", "tier": 1,
             "target": "centres - r1 - r2 - 10"},
            # a friction belt below ~120 deg of wrap slips before it pulls
            {"id": "wrap_angle", "kind": "precondition", "tier": 1,
             "target": "180 - 2*asin((d2-d1)/(2*centres))*180/pi - 120"},
            # very high ratios need an idler or a second stage
            {"id": "ratio_sane", "kind": "precondition", "tier": 1,
             "target": "6 - d2/d1"},
            {"id": "bore_rim", "kind": "precondition", "tier": 1,
             "target": "r1 - bore1/2 - 4"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "2"},
            # pulleys run on separate shafts and never touch
            {"id": "free_running", "kind": "fused_solids", "tier": 1,
             "target": "2"},
            # exact: outer tangent of both pitch circles along the centre line
            {"id": "drive_extent", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-06, "target": "centres + r1 + r2"},
        ],
    }


# --------------------------------------------------------------------------- #
# Power transmission — lead screw drive
# --------------------------------------------------------------------------- #
def lead_screw_drive(d: float = 16.0, length: float = 300.0, starts: int = 1,
                     nut_od: float = 32.0, nut_len: float = 40.0,
                     travel: float = 200.0) -> dict:
    """Trapezoidal lead screw with a travelling nut.

    The design decision this family teaches is the one every lead screw turns
    on: **self-locking versus efficiency**, and they are the same variable.

        lead   = pitch * starts              axial travel per revolution
        lambda = atan(lead / (pi * dm))      helix angle at the mean diameter
        self-locks when tan(lambda) < mu     (~0.15, steel on bronze)
        eta    = tan(lambda)/tan(lambda+phi) with phi = atan(mu)

    A single-start screw self-locks and holds position with no brake, at about
    a third efficiency. Adding starts raises the lead, the helix angle and the
    efficiency together — and past ``tan(lambda) = mu`` the screw back-drives
    under load. Both facts are carried, and whichever regime the parameters
    land in is recorded rather than assumed.

    The thread is data, not geometry: the verified solid is the screw blank at
    its mean diameter, which is the section that actually carries load.
    """
    from .families import screw_kinematics

    k = screw_kinematics(d, starts)
    dm = k["mean_dia"]
    # nut sits mid-travel; bore is nominally tangent to the screw blank
    nut_z = (length - nut_len) / 2.0

    comps = [
        {"id": "screw", "family": "lead_screw",
         "params": dict(d=d, length=length, starts=starts),
         "pos": [0.0, 0.0, 0.0], "process": "rolled thread, induction hardened"},
        {"id": "nut", "family": "screw_nut",
         "params": dict(d=d, od=nut_od, length=nut_len),
         "pos": [0.0, 0.0, nut_z], "process": "bronze, single-point tapped"},
    ]
    mates = [
        {"id": "screw_nut_pair", "type": "screw",
         "between": ["screw", "nut"],
         "reference": "trapezoidal thread flanks",
         "constraint": f"Tr{d:g}x{k['pitch']:g}"
                       + (f" {starts}-start" if starts > 1 else "")
                       + f", lead {k['lead']:g} mm/rev, helix "
                         f"{k['helix_deg']:.2f} deg, "
                       + ("self-locking" if k["self_locking"]
                          else "back-drives under load")
                       + f", efficiency {k['efficiency']:.1%}",
         "dof_removed": 5, "dof_remaining": ["helical (1 DOF: rotation "
                                             "coupled to translation)"],
         "assembly_order": 1, "tolerance": "7H/7e free-running fit"},
        {"id": "screw_journal", "type": "revolute",
         "between": ["frame", "screw"],
         "reference": "bearing journal at the driven end",
         "dof_removed": 5, "dof_remaining": ["rotation Z"],
         "assembly_order": 2, "tolerance": "H7/k6"},
    ]
    variables = {
        "d": d, "length": length, "starts": float(starts), "nut_od": nut_od,
        "nut_len": nut_len, "travel": travel, "pitch": k["pitch"],
        "lead": k["lead"], "dm": dm, "helix_deg": k["helix_deg"],
        "efficiency": k["efficiency"],
        "self_locking": 1.0 if k["self_locking"] else 0.0,
        "revs_per_travel": travel / k["lead"],
    }
    return {
        "assembly_class": "lead_screw_drive",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            # the screw must be long enough for the stroke plus the nut
            {"id": "stroke_fits", "kind": "precondition", "tier": 1,
             "target": "length - travel - nut_len - 20"},
            # a long unsupported screw buckles; 40:1 is the usual working limit
            {"id": "slenderness", "kind": "precondition", "tier": 1,
             "target": "40*d - length"},
            # enough engaged threads to spread the load
            {"id": "engagement", "kind": "precondition", "tier": 1,
             "target": "nut_len - 1.5*d"},
            {"id": "nut_wall", "kind": "precondition", "tier": 1,
             "target": "nut_od - dm - 6"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "2"},
            # nut bore is tangent to the screw blank, so they fuse to one body
            {"id": "engaged", "kind": "fused_solids", "tier": 1, "target": "1"},
            {"id": "envelope", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "nut_od"},
            {"id": "screw_length", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "length"},
        ],
    }


# --------------------------------------------------------------------------- #
# Stiffness — spring-loaded plunger
# --------------------------------------------------------------------------- #
def spring_plunger(wire_d: float = 2.0, coil_d: float = 16.0,
                   n_active: float = 8.0, free_len: float = 40.0,
                   plunger_d: float = 10.0, bore_d: float = 20.0,
                   preload_mm: float = 6.0, stroke: float = 12.0) -> dict:
    """A spring acting on a plunger inside a guide bore — the first family in
    the corpus where the governing quantity is *stiffness* rather than shape.

    Two springs of identical wire and coil diameter behave completely
    differently if their active coil count differs, and nothing about the
    geometry shows it. What the assembly records is the force the mechanism
    actually produces:

        k       = G*d^4/(8*D^3*Na)          rate, N/mm
        F_pre   = k * preload               force at assembly
        F_max   = k * (preload + stroke)    force at full stroke
        L_solid = d*(Na+2)                  the spring cannot compress past this

    The binding design check is that ``preload + stroke`` must not drive the
    spring solid: coil clash spikes the stress, and the rate becomes infinite
    at that point rather than linear.
    """
    from .families import spring_mechanics

    k = spring_mechanics(wire_d, coil_d, n_active, free_len)
    rate = k["rate_n_per_mm"]
    f_pre = rate * preload_mm
    f_max = rate * (preload_mm + stroke)
    working_len = free_len - preload_mm - stroke

    comps = [
        {"id": "spring", "family": "compression_spring",
         "params": dict(wire_d=wire_d, coil_d=coil_d, n_active=n_active,
                        free_len=free_len),
         "pos": [0.0, 0.0, 0.0], "process": "cold coiled, shot peened"},
        {"id": "plunger", "family": "bearing_shaft",
         "params": dict(r_shaft=plunger_d / 2.0,
                        r_seat=(coil_d - wire_d) / 2.0 - 0.5,
                        length=free_len + 10.0, seat_len=6.0),
         "pos": [0.0, 0.0, 0.0], "process": "turned, hardened tip"},
    ]
    mates = [
        {"id": "spring_on_plunger", "type": "concentric",
         "between": ["plunger", "spring"],
         "reference": "spring inner diameter guided by the plunger stem",
         "constraint": f"guide clearance keeps the coil from buckling "
                       f"sideways; rate {rate:.2f} N/mm",
         "dof_removed": 4, "dof_remaining": ["slide Z", "spin Z"],
         "assembly_order": 1, "tolerance": "0.5 mm diametral guide clearance"},
        {"id": "spring_preload", "type": "spring",
         "between": ["frame", "spring"],
         "reference": "spring seated between the housing shoulder and plunger",
         "constraint": f"rate {rate:.2f} N/mm, preload {preload_mm:g} mm "
                       f"= {f_pre:.1f} N, at full {stroke:g} mm stroke "
                       f"= {f_max:.1f} N, solid height "
                       f"{k['solid_length']:.1f} mm",
         "dof_removed": 0, "dof_remaining": ["axial compression"],
         "assembly_order": 2, "tolerance": "free length +/- 2%"},
    ]
    variables = {
        "wire_d": wire_d, "coil_d": coil_d, "n_active": n_active,
        "free_len": free_len, "plunger_d": plunger_d, "bore_d": bore_d,
        "preload_mm": preload_mm, "stroke": stroke,
        "rate_n_per_mm": rate, "force_preload_n": f_pre,
        "force_max_n": f_max, "solid_length": k["solid_length"],
        "working_len": working_len, "spring_index": k["index"],
    }
    return {
        "assembly_class": "spring_plunger",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            # the spring must not reach solid height at full stroke: coil clash
            # spikes stress and the rate stops being linear
            {"id": "no_coil_clash", "kind": "precondition", "tier": 1,
             "target": "free_len - preload_mm - stroke "
                       "- wire_d*(n_active + 2) - 1"},
            {"id": "spring_index", "kind": "precondition", "tier": 1,
             "target": "coil_d/wire_d - 4"},
            {"id": "bore_clearance", "kind": "precondition", "tier": 1,
             "target": "bore_d - coil_d - wire_d - 1"},
            {"id": "plunger_guides", "kind": "precondition", "tier": 1,
             "target": "coil_d - wire_d - plunger_d - 1"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "2"},
            {"id": "envelope", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "coil_d + wire_d"},
        ],
    }


# --------------------------------------------------------------------------- #
# Stress-based sizing — keyed shaft coupling
# --------------------------------------------------------------------------- #
def keyed_coupling(shaft_d: float = 30.0, hub_od: float = 60.0,
                   hub_len: float = 45.0, shaft_len: float = 90.0,
                   torque_nm: float = 150.0) -> dict:
    """A hub keyed to a shaft — the first family sized by *load*, not by fit.

    Everything before this was sized geometrically: a bore matches a shaft, a
    bolt spans a stack, a belt reaches around two pulleys. A keyed joint is
    different — the key section is fixed by DIN 6885 from the shaft diameter,
    and the only free variable is *length*, chosen so the joint carries the
    torque it must::

        shear    T = tau_allow * b * L * d/2
        bearing  T = sig_allow * (h/2) * L * d/2

    **Bearing governs at every standard size**, because only half the key
    height bears against the hub. Sizing against shear — the intuitive mode —
    overestimates capacity by roughly 2x on larger shafts. That is invisible in
    geometry and is how keyed joints fail in service, so the required torque is
    an input and the capacity check is a precondition.
    """
    from .families import KEY_ALLOW, key_capacity, key_for_shaft

    b, h = key_for_shaft(shaft_d)
    cap = key_capacity(shaft_d, hub_len)

    comps = [
        {"id": "shaft", "family": "keyed_shaft",
         "params": dict(shaft_d=shaft_d, length=shaft_len, key_len=hub_len),
         "pos": [0.0, 0.0, 0.0], "process": "turned + keyseat milled"},
        {"id": "hub", "family": "keyed_hub",
         "params": dict(shaft_d=shaft_d, hub_od=hub_od, hub_len=hub_len),
         "pos": [0.0, 0.0, 0.0],
         "process": "bored + keyway broached"},
        {"id": "key", "family": "parallel_key",
         "params": dict(shaft_d=shaft_d, key_len=hub_len),
         # seated in the shaft keyseat, half its height proud into the hub
         "pos": [0.0, shaft_d / 2.0, 0.0],
         "process": "cold drawn key steel"},
    ]
    mates = [
        {"id": "hub_on_shaft", "type": "concentric",
         "between": ["shaft", "hub"],
         "reference": "hub bore to shaft outside diameter",
         "constraint": "H7/k6 transition fit — located, not clamped; the key "
                       "carries the torque, not friction",
         "dof_removed": 4, "dof_remaining": ["slide Z", "spin Z"],
         "assembly_order": 1, "tolerance": "H7/k6"},
        {"id": "key_in_shaft", "type": "coincident",
         "between": ["shaft", "key"],
         "reference": "key bottom face on the shaft keyseat",
         "constraint": f"DIN 6885 key {b:g}x{h:g}x{hub_len:g}",
         "dof_removed": 5, "dof_remaining": ["slide Z"],
         "assembly_order": 2, "tolerance": "P9 keyseat width"},
        {"id": "key_drives_hub", "type": "coincident",
         "between": ["key", "hub"],
         "reference": "key flanks against the hub keyway",
         "constraint": f"transmits {cap['torque_nm']:.0f} Nm, governed by "
                       f"{cap['governed_by']} "
                       f"(shear {cap['torque_shear_nm']:.0f} Nm, "
                       f"bearing {cap['torque_bearing_nm']:.0f} Nm)",
         "dof_removed": 1, "dof_remaining": [],
         "assembly_order": 3, "tolerance": "JS9 hub keyway width"},
    ]
    variables = {
        "shaft_d": shaft_d, "hub_od": hub_od, "hub_len": hub_len,
        "shaft_len": shaft_len, "torque_nm": torque_nm,
        "b": b, "h": h,
        "tau_allow": KEY_ALLOW["shear"], "sig_allow": KEY_ALLOW["bearing"],
        "capacity_nm": cap["torque_nm"],
        "capacity_shear_nm": cap["torque_shear_nm"],
        "capacity_bearing_nm": cap["torque_bearing_nm"],
    }
    return {
        "assembly_class": "keyed_coupling",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            # the joint must actually carry the duty torque, by the LOWER of
            # the two failure modes
            {"id": "torque_capacity", "kind": "precondition", "tier": 1,
             "target": "min(tau_allow*b*hub_len, sig_allow*(h/2)*hub_len)"
                       "*shaft_d/2/1000 - torque_nm"},
            # ...and not be grossly oversized, which wastes hub length
            {"id": "not_overspecified", "kind": "precondition", "tier": 1,
             "target": "4*torque_nm - min(tau_allow*b*hub_len, "
                       "sig_allow*(h/2)*hub_len)*shaft_d/2/1000"},
            {"id": "wall_over_keyway", "kind": "precondition", "tier": 1,
             "target": "(hub_od - shaft_d)/2 - h/2 - 3"},
            {"id": "hub_seats", "kind": "precondition", "tier": 1,
             "target": "shaft_len - hub_len - 15"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "3"},
            {"id": "hub_dia", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "hub_od"},
        ],
    }


# --------------------------------------------------------------------------- #
# Tier 5 — four-bar linkage
# --------------------------------------------------------------------------- #
def _circle_intersect(p0, r0, p1, r1):
    """The two points at distance r0 from p0 and r1 from p1, or None."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy)
    if dist > r0 + r1 or dist < abs(r0 - r1) or dist == 0:
        return None
    a = (r0 * r0 - r1 * r1 + dist * dist) / (2 * dist)
    h2 = r0 * r0 - a * a
    if h2 < 0:
        return None
    h = math.sqrt(h2)
    xm, ym = p0[0] + a * dx / dist, p0[1] + a * dy / dist
    return ((xm + h * dy / dist, ym - h * dx / dist),
            (xm - h * dy / dist, ym + h * dx / dist))


def four_bar(ground: float = 100.0, crank: float = 30.0, coupler: float = 90.0,
             rocker: float = 70.0, theta_deg: float = 60.0,
             link_w: float = 18.0, link_t: float = 6.0,
             hole_r: float = 4.0) -> dict | None:
    """Planar four-bar solved at one crank angle by loop closure.

    The coupler/rocker joint is the intersection of a circle of radius
    ``coupler`` about the crank pin and one of radius ``rocker`` about the
    fixed pivot. If those circles do not intersect the linkage *cannot be
    assembled at that angle* — the function returns None rather than emitting
    a spec that would fail downstream.

    The **Grashof condition** (s + l <= p + q) decides whether any link can
    fully rotate, which is what separates a crank-rocker from a
    double-rocker. It is carried as a precondition so the dataset records the
    classification, not just the geometry.

    Links sit on separate Z layers, as a real linkage does with spacers, so
    the pins align while the bars never share space.
    """
    a = (0.0, 0.0)                                 # crank ground pivot
    dpt = (ground, 0.0)                            # rocker ground pivot
    th = math.radians(theta_deg)
    b = (crank * math.cos(th), crank * math.sin(th))
    sol = _circle_intersect(b, coupler, dpt, rocker)
    if sol is None:
        return None
    c = sol[0]                                     # open configuration

    lay = link_t + 1.0                             # z pitch between layers

    def place(p, q, z):
        return {"pos": [round((p[0] + q[0]) / 2, 6),
                        round((p[1] + q[1]) / 2, 6), z],
                "rot_z": round(math.degrees(
                    math.atan2(q[1] - p[1], q[0] - p[0])), 6)}

    def link(cid, p, q, centres, z, process):
        return {"id": cid, "family": "link_bar",
                "params": dict(centres=round(centres, 6), width=link_w,
                               t=link_t, hole_r=hole_r),
                "process": process, **place(p, q, z)}

    comps = [
        link("ground_link", a, dpt, ground, 0.0, "welded frame"),
        link("crank", a, b, crank, lay, "waterjet + reamed"),
        link("coupler", b, c, coupler, 2 * lay, "waterjet + reamed"),
        link("rocker", dpt, c, rocker, 3 * lay, "waterjet + reamed"),
    ]
    mates = [
        {"id": "pivot_A", "type": "revolute", "between": ["ground_link", "crank"],
         "reference": "pin bore at ground origin", "dof_removed": 5,
         "dof_remaining": ["rotation Z"], "assembly_order": 1,
         "tolerance": "H7/g6"},
        {"id": "pin_B", "type": "revolute", "between": ["crank", "coupler"],
         "reference": "crank far bore", "dof_removed": 5,
         "dof_remaining": ["rotation Z"], "assembly_order": 2,
         "tolerance": "H7/g6"},
        {"id": "pin_C", "type": "revolute", "between": ["coupler", "rocker"],
         "reference": "coupler far bore", "dof_removed": 5,
         "dof_remaining": ["rotation Z"], "assembly_order": 3,
         "tolerance": "H7/g6"},
        {"id": "pivot_D", "type": "revolute", "between": ["rocker", "ground_link"],
         "reference": "pin bore at (ground, 0)", "dof_removed": 5,
         "dof_remaining": ["rotation Z"], "assembly_order": 4,
         "tolerance": "H7/g6"},
    ]
    lengths = sorted([ground, crank, coupler, rocker])
    # s/p/q/l is Grashof's own notation (shortest, the two intermediates,
    # longest); renaming `l` here would obscure the criterion it feeds.
    s, p, q, l = lengths  # noqa: E741
    variables = {
        "ground": ground, "crank": crank, "coupler": coupler,
        "rocker": rocker, "theta_deg": theta_deg, "link_w": link_w,
        "link_t": link_t, "hole_r": hole_r, "lay": lay,
        "s": s, "p": p, "q": q, "l": l,
        "cx": round(c[0], 6), "cy": round(c[1], 6),
    }
    return {
        "assembly_class": "four_bar_linkage",
        "variables": variables,
        "components": comps,
        "mates": mates,
        "assertions": [
            {"id": "grashof", "kind": "precondition", "tier": 1,
             "target": "p + q - s - l"},
            {"id": "pin_land", "kind": "precondition", "tier": 1,
             "target": "link_w/2 - hole_r - 2"},
            {"id": "no_interference", "kind": "no_interference", "tier": 1,
             "tol_rel": 1e-09},
            {"id": "part_count", "kind": "part_count", "tier": 1, "target": "4"},
            {"id": "stack_height", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "3*lay + link_t"},
        ],
    }
