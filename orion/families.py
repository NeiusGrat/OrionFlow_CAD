"""Parametric component families an AssemblySpec can reference by name.

An assembly should not inline a full Blueprint per component — that is verbose,
unhashable as a unit, and nothing like how an engineer works. Real practice is
"an M8 hex bolt, 40 long", a catalogue reference plus parameters. This module is
that catalogue: every entry is a factory returning a frozen Blueprint whose
volume is asserted in closed form, so a component pulled from the library is
verified on exactly the same terms as a bespoke part.

Adding a family here immediately widens the assembly space, because the spec
layer composes families rather than geometry.
"""

from __future__ import annotations

import math

from .blueprint import Blueprint

# --------------------------------------------------------------------------- #
# fasteners (ISO metric)
# --------------------------------------------------------------------------- #
#: ISO 4014/4017 across-flats and head heights, by nominal thread diameter.
ISO_HEX = {
    5.0:  {"af": 8.0,  "head_h": 3.5,  "pitch": 0.8,  "nut_h": 4.7},
    6.0:  {"af": 10.0, "head_h": 4.0,  "pitch": 1.0,  "nut_h": 5.2},
    8.0:  {"af": 13.0, "head_h": 5.3,  "pitch": 1.25, "nut_h": 6.8},
    10.0: {"af": 16.0, "head_h": 6.4,  "pitch": 1.5,  "nut_h": 8.4},
    12.0: {"af": 18.0, "head_h": 7.5,  "pitch": 1.75, "nut_h": 10.8},
    16.0: {"af": 24.0, "head_h": 10.0, "pitch": 2.0,  "nut_h": 14.8},
}

#: property class -> proof stress (MPa); torque uses the standard K=0.2 rule.
BOLT_CLASS = {"8.8": 640.0, "10.9": 940.0, "12.9": 1100.0}


def bolt_torque_nm(d: float, cls: str = "8.8", k: float = 0.2) -> float:
    """T = K * F_preload * d, with preload at 65% of proof load on the
    tensile-stress area (ISO 898-1 A_s approximation)."""
    p = ISO_HEX[d]["pitch"]
    a_s = math.pi / 4 * (d - 0.9382 * p) ** 2
    f_pre = 0.65 * BOLT_CLASS[cls] * a_s
    return k * f_pre * d / 1000.0


def hex_bolt(d: float, length: float, cls: str = "8.8") -> Blueprint:
    """Hex-head bolt: plain shank plus hex head.

    The thread is carried as *data* (pitch, class, torque), not geometry. That
    is what production assembly CAD does — a modelled helix costs ~60 s per
    bolt in the kernel and teaches nothing that the spec does not already say.
    """
    g = ISO_HEX[d]
    return Blueprint(
        part_class="hex_bolt",
        variables={"d": d, "length": length, "af": g["af"],
                   "head_h": g["head_h"], "pitch": g["pitch"]},
        datums={"A": "underside of head (primary seating face)",
                "B": "shank axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V_shank = pi*(d/2)^2*length",
             "why": "plain cylindrical shank; thread is specified, not cut"},
            {"step": 2, "eq": "V_head = sqrt(3)/2*af^2*head_h",
             "why": "regular hexagon of across-flats af has area sqrt(3)/2*af^2"},
        ]},
        assertions=[
            {"id": "head_bigger", "kind": "precondition", "tier": 1,
             "target": "af - d - 1"},
            {"id": "grip", "kind": "precondition", "tier": 1,
             "target": "length - 2*pitch"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*(d/2)**2*length + sqrt(3)/2*af**2*head_h"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_head", "type": "Sketch", "parameters": {}},
                {"id": "head", "type": "Pad",
                 "rationale": "hex head, across-flats per ISO 4014",
                 "parameters": {"Length": "head_h", "Type": "Length"}},
                {"id": "s_shank", "type": "Sketch", "parameters": {}},
                {"id": "shank", "type": "Pad",
                 "rationale": "plain shank under the head",
                 "parameters": {"Length": "length", "Type": "Length"}},
            ],
            # Sketches are STACKED on Z rather than one being reversed: a
            # `Reversed` Pad did not take effect through the compiler, so head
            # and shank both grew upward and interpenetrated — the measured
            # volume came out exactly sum-minus-overlap. Offsetting the shank
            # sketch to the top of the head makes the two solids disjoint by
            # construction, so the closed form is a plain sum.
            "sketches": [
                {"id": "s_head", "plane": "XY",
                 "profile": {"builder": "regular_polygon",
                             "args": {"n": "6", "r_circum": "af/sqrt(3)"}}},
                {"id": "s_shank", "plane": "XY", "z": "head_h",
                 "profile": {"builder": "circle", "args": {"r": "d/2"}}},
            ],
            "dependencies": [
                {"source": "s_shank", "target": "shank", "kind": "profile"},
                {"source": "s_head", "target": "head", "kind": "profile"}],
        },
    ).freeze()


def hex_nut(d: float) -> Blueprint:
    g = ISO_HEX[d]
    return Blueprint(
        part_class="hex_nut",
        variables={"d": d, "af": g["af"], "nut_h": g["nut_h"]},
        datums={"A": "bearing face", "B": "thread axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = sqrt(3)/2*af^2*nut_h - pi*(d/2)^2*nut_h",
             "why": "hex prism less the tapping drill; thread specified as data"},
        ]},
        assertions=[
            {"id": "wall", "kind": "precondition", "tier": 1,
             "target": "af - d - 2"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "(sqrt(3)/2*af**2 - pi*(d/2)**2)*nut_h"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_nut", "type": "Sketch", "parameters": {}},
                {"id": "nut", "type": "Pad",
                 "rationale": "hex nut blank with tapping bore",
                 "parameters": {"Length": "nut_h", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_nut", "plane": "XY", "profile": {
                    "builder": "poly_with_holes",
                    "args": {"points": [
                        [f"af/sqrt(3)*cos({i}*pi/3)", f"af/sqrt(3)*sin({i}*pi/3)"]
                        for i in range(6)],
                        "holes": [["0", "0", "d/2"]]}}},
            ],
            "dependencies": [
                {"source": "s_nut", "target": "nut", "kind": "profile"}],
        },
    ).freeze()


def washer(d: float, od: float, t: float) -> Blueprint:
    return Blueprint(
        part_class="washer",
        variables={"d": d, "od": od, "t": t},
        datums={"A": "bearing face", "B": "bore axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = pi*((od/2)^2 - (d/2)^2)*t",
             "why": "plain annular washer, spreads the head load over the plate"},
        ]},
        assertions=[
            {"id": "annulus", "kind": "precondition", "tier": 1,
             "target": "od - d - 2"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*((od/2)**2 - (d/2)**2)*t"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_w", "type": "Sketch", "parameters": {}},
                {"id": "w", "type": "Pad", "rationale": "plain washer",
                 "parameters": {"Length": "t", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_w", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "od/2", "r_inner": "d/2"}}},
            ],
            "dependencies": [{"source": "s_w", "target": "w", "kind": "profile"}],
        },
    ).freeze()


# --------------------------------------------------------------------------- #
# structural / rotating
# --------------------------------------------------------------------------- #
def clearance_plate(length: float, width: float, t: float, hole_r: float,
                    hole_dx: float) -> Blueprint:
    """Flat plate with two clearance holes on the X axis — the joined member
    in a bolted joint."""
    return Blueprint(
        part_class="clearance_plate",
        variables={"length": length, "width": width, "t": t,
                   "hole_r": hole_r, "hole_dx": hole_dx},
        datums={"A": "bottom face z=0", "B": "long edge", "C": "first hole"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = length*width*t - 2*pi*hole_r^2*t",
             "why": "plate blank less two clearance holes, disjoint"},
        ]},
        assertions=[
            {"id": "edge_distance", "kind": "precondition", "tier": 1,
             "target": "length/2 - hole_dx - hole_r - 1.5*hole_r"},
            {"id": "side_land", "kind": "precondition", "tier": 1,
             "target": "width/2 - hole_r - 1.5*hole_r"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "length*width*t - 2*pi*hole_r**2*t"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_p", "type": "Sketch", "parameters": {}},
                {"id": "plate", "type": "Pad", "rationale": "bolted member",
                 "parameters": {"Length": "t", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_p", "plane": "XY", "profile": {
                    "builder": "rect_with_holes",
                    "args": {"w": "length", "h": "width",
                             "holes": [["-hole_dx", "0", "hole_r"],
                                       ["hole_dx", "0", "hole_r"]]}}},
            ],
            "dependencies": [{"source": "s_p", "target": "plate",
                              "kind": "profile"}],
        },
    ).freeze()


def bearing_ring(r_inner: float, r_outer: float, width: float,
                 kind: str = "ring") -> Blueprint:
    """One ring of a rolling bearing, modelled as a plain annular section.

    Rolling elements and cage are deliberately not modelled: they contribute
    nothing a fit calculation needs, and their geometry is manufacturer
    specific. What matters for an assembly — bore, outside diameter, width,
    and the interference implied by the shaft and housing tolerances — is fully
    captured here.
    """
    return Blueprint(
        part_class=f"bearing_{kind}",
        variables={"r_inner": r_inner, "r_outer": r_outer, "width": width},
        datums={"A": "bearing face", "B": "rotation axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = pi*(r_outer^2 - r_inner^2)*width",
             "why": "annular ring section"},
        ]},
        assertions=[
            {"id": "section", "kind": "precondition", "tier": 1,
             "target": "r_outer - r_inner - 1.5"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*(r_outer**2 - r_inner**2)*width"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_r", "type": "Sketch", "parameters": {}},
                {"id": "ring", "type": "Pad", "rationale": f"bearing {kind}",
                 "parameters": {"Length": "width", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_r", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "r_outer", "r_inner": "r_inner"}}},
            ],
            "dependencies": [{"source": "s_r", "target": "ring",
                              "kind": "profile"}],
        },
    ).freeze()


def stepped_shaft(r_shaft: float, r_seat: float, length: float,
                  seat_len: float) -> Blueprint:
    """Shaft with a larger bearing seat at one end (a shoulder to locate
    against)."""
    return Blueprint(
        part_class="bearing_shaft",
        variables={"r_shaft": r_shaft, "r_seat": r_seat, "length": length,
                   "seat_len": seat_len},
        datums={"A": "shoulder face", "B": "shaft axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = pi*r_shaft^2*length + pi*r_seat^2*seat_len",
             "why": "plain shaft plus the raised bearing seat, stacked so the "
                    "shoulder locates the inner ring axially"},
        ]},
        assertions=[
            {"id": "shoulder", "kind": "precondition", "tier": 1,
             "target": "r_seat - r_shaft - 1"},
            {"id": "slender", "kind": "precondition", "tier": 1,
             "target": "length - 2*r_shaft"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*r_shaft**2*length + pi*r_seat**2*seat_len"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_a", "type": "Sketch", "parameters": {}},
                {"id": "shaft", "type": "Pad", "rationale": "plain shaft",
                 "parameters": {"Length": "length", "Type": "Length"}},
                {"id": "s_b", "type": "Sketch", "parameters": {}},
                {"id": "seat", "type": "Pad",
                 "rationale": "bearing seat with locating shoulder",
                 "parameters": {"Length": "seat_len", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_a", "plane": "XY",
                 "profile": {"builder": "circle", "args": {"r": "r_shaft"}}},
                # stacked on Z (see hex_bolt) so shaft and seat are disjoint
                {"id": "s_b", "plane": "XY", "z": "length",
                 "profile": {"builder": "circle", "args": {"r": "r_seat"}}},
            ],
            "dependencies": [
                {"source": "s_a", "target": "shaft", "kind": "profile"},
                {"source": "s_b", "target": "seat", "kind": "profile"}],
        },
    ).freeze()


#: ISO 2904 trapezoidal (Tr) screw threads — nominal diameter -> pitch.
ISO_TRAPEZOIDAL = {
    10.0: 2.0, 12.0: 3.0, 14.0: 3.0, 16.0: 4.0, 18.0: 4.0, 20.0: 4.0,
    24.0: 5.0, 28.0: 5.0, 30.0: 6.0, 36.0: 6.0, 40.0: 7.0,
}

#: sliding friction coefficient, steel screw on bronze nut, lightly greased
MU_SCREW = 0.15


def screw_kinematics(d: float, starts: int = 1, mu: float = MU_SCREW) -> dict:
    """Lead, helix angle, self-locking and efficiency for a Tr screw.

    ``lead = pitch * starts`` is the axial travel per revolution and is the
    quantity that actually matters; pitch alone only describes the thread form.
    Confusing the two is the classic multi-start error, so both are carried.

    The helix angle at the pitch diameter is ``lambda = atan(lead/(pi*dm))``.
    A screw **self-locks** when ``tan(lambda) < mu`` — it will not back-drive
    under load, which is what lets a lead screw hold position without a brake.
    Efficiency ``eta = tan(lambda)/tan(lambda+phi)`` with ``phi = atan(mu)``
    trades directly against that: the more self-locking, the less efficient.
    """
    pitch = ISO_TRAPEZOIDAL[d]
    lead = pitch * starts
    dm = d - 0.5 * pitch                     # pitch (mean) diameter, Tr form
    lam = math.atan(lead / (math.pi * dm))
    phi = math.atan(mu)
    return {
        "pitch": pitch, "starts": starts, "lead": lead, "mean_dia": dm,
        "helix_deg": math.degrees(lam),
        "self_locking": math.tan(lam) < mu,
        "efficiency": math.tan(lam) / math.tan(lam + phi),
    }


def lead_screw(d: float, length: float, starts: int = 1) -> Blueprint:
    """Trapezoidal lead screw shaft.

    Thread form is carried as data — pitch, lead, starts, helix angle — for the
    same reason bolt threads are: a modelled helix costs kernel time and adds
    nothing the specification does not already state exactly. The solid is the
    screw blank at its mean diameter, which is the load-bearing section.
    """
    k = screw_kinematics(d, starts)
    return Blueprint(
        part_class="lead_screw",
        # `lead` is deliberately NOT a stored variable: it is exactly
        # pitch*starts, and the static checker is right that a variable no
        # expression references is a magic number wearing a label. Anything
        # that needs the lead derives it.
        variables={"d": d, "length": length, "pitch": k["pitch"],
                   "starts": float(starts), "dm": k["mean_dia"]},
        datums={"A": "bearing journal face", "B": "screw axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "dm = d - 0.5*pitch",
             "why": "ISO 2904 trapezoidal mean diameter, the load section"},
            {"step": 2, "eq": "V = pi*(dm/2)^2*length",
             "why": "screw blank at the mean diameter; the thread is specified "
                    "rather than cut, so the blank is the verified solid"},
        ]},
        assertions=[
            {"id": "slenderness", "kind": "precondition", "tier": 1,
             "target": "40*d - length"},
            {"id": "thread_form", "kind": "precondition", "tier": 1,
             "target": "d - 2*pitch"},
            # a very steep helix is hard to cut and weak in the flank; 30 deg
            # is the practical ceiling and it is where multi-start screws land
            {"id": "helix_limit", "kind": "precondition", "tier": 1,
             "target": "30 - atan(pitch*starts/(pi*dm))*180/pi"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*(dm/2)**2*length"},
            {"id": "screw_dia", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "dm"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_screw", "type": "Sketch", "parameters": {}},
                {"id": "screw", "type": "Pad",
                 "rationale": "lead screw blank at the mean diameter",
                 "parameters": {"Length": "length", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_screw", "plane": "XY", "profile": {
                    "builder": "circle", "args": {"r": "dm/2"}}},
            ],
            "dependencies": [{"source": "s_screw", "target": "screw",
                              "kind": "profile"}],
        },
    ).freeze()


def screw_nut(d: float, od: float, length: float) -> Blueprint:
    """Bronze travelling nut running on a lead screw."""
    k = screw_kinematics(d)
    return Blueprint(
        part_class="screw_nut",
        variables={"d": d, "od": od, "length": length, "dm": k["mean_dia"]},
        datums={"A": "mounting face", "B": "thread axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = pi*((od/2)^2 - (dm/2)^2)*length",
             "why": "annular nut body bored to the screw mean diameter"},
        ]},
        assertions=[
            {"id": "wall", "kind": "precondition", "tier": 1,
             "target": "od - dm - 6"},
            {"id": "engagement", "kind": "precondition", "tier": 1,
             "target": "length - 1.5*d"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*((od/2)**2 - (dm/2)**2)*length"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_nut", "type": "Sketch", "parameters": {}},
                {"id": "nut", "type": "Pad", "rationale": "travelling nut",
                 "parameters": {"Length": "length", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_nut", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "od/2", "r_inner": "dm/2"}}},
            ],
            "dependencies": [{"source": "s_nut", "target": "nut",
                              "kind": "profile"}],
        },
    ).freeze()


#: shear modulus (MPa) and allowable shear stress by common spring materials
SPRING_MATERIALS = {
    "music_wire_astm_a228":   {"G": 81000.0, "tau_allow": 700.0},
    "chrome_silicon_a401":    {"G": 77200.0, "tau_allow": 800.0},
    "stainless_302_a313":     {"G": 69000.0, "tau_allow": 550.0},
}


def spring_mechanics(wire_d: float, coil_d: float, n_active: float,
                     free_len: float, material: str = "music_wire_astm_a228",
                     ends: str = "squared_ground") -> dict:
    """Closed-form helical compression spring behaviour.

    Everything here is standard machine-design result, and every one of them is
    invisible in the geometry — two springs with identical wire and coil
    diameters behave completely differently if the active coil count differs.

        C     = D/d                     spring index
        k     = G*d^4 / (8*D^3*Na)      rate, N/mm
        Kw    = (4C-1)/(4C-4) + 0.615/C Wahl correction for curvature
        tau   = Kw * 8*F*D/(pi*d^3)     corrected shear stress
        Ls    = d*Nt                    solid height (squared+ground)
        buckle: free length / D > 2.6   slenderness limit, fixed-fixed ends

    The **spring index** C is the quietly important one: below ~4 the wire
    cannot be coiled without cracking, above ~12 the spring tangles and buckles.
    Neither limit is visible in a model of the spring.
    """
    m = SPRING_MATERIALS[material]
    d, D, na = wire_d, coil_d, n_active
    c = D / d
    n_total = na + (2.0 if ends == "squared_ground" else 0.0)
    rate = m["G"] * d ** 4 / (8.0 * D ** 3 * na)
    solid_len = d * n_total
    max_defl = free_len - solid_len
    kw = (4 * c - 1) / (4 * c - 4) + 0.615 / c
    f_solid = rate * max_defl
    tau_solid = kw * 8.0 * f_solid * D / (math.pi * d ** 3)
    return {
        "index": c, "rate_n_per_mm": rate, "n_total": n_total,
        "solid_length": solid_len, "max_deflection": max_defl,
        "wahl": kw, "force_at_solid": f_solid,
        "shear_at_solid": tau_solid, "tau_allow": m["tau_allow"],
        "slenderness": free_len / D,
        "buckles": free_len / D > 2.6,
        "material": material,
    }


def compression_spring(wire_d: float, coil_d: float, n_active: float,
                       free_len: float,
                       material: str = "music_wire_astm_a228") -> Blueprint:
    """Helical compression spring, modelled as its swept annular envelope.

    The helix itself is not cut. A coiled wire is a swept solid that costs real
    kernel time and teaches nothing the closed form does not state exactly —
    and the quantities that matter (rate, solid height, stress, buckling) are
    all analytic. What is verified is the **envelope**: the annulus the spring
    occupies, which is what a designer actually has to make room for.
    """
    k = spring_mechanics(wire_d, coil_d, n_active, free_len, material)
    return Blueprint(
        part_class="compression_spring",
        variables={"wire_d": wire_d, "coil_d": coil_d,
                   "n_active": n_active, "free_len": free_len,
                   "G": SPRING_MATERIALS[material]["G"],
                   "tau_allow": SPRING_MATERIALS[material]["tau_allow"]},
        datums={"A": "ground bearing face", "B": "coil axis"},
        design_plan={"derivation": [
            {"step": 1, "eq": "C = coil_d/wire_d",
             "why": "spring index; below 4 the wire cracks when coiled, above "
                    "12 the spring tangles"},
            {"step": 2,
             "eq": "k = G*wire_d^4/(8*coil_d^3*n_active)",
             "why": "rate depends on the FOURTH power of wire diameter, which "
                    "is why small wire changes dominate the design"},
            {"step": 3, "eq": "V_envelope = pi*((coil_d+wire_d)^2 "
                              "- (coil_d-wire_d)^2)/4*free_len",
             "why": "the annular envelope the coil sweeps — the space that "
                    "must be reserved for it"},
        ]},
        assertions=[
            {"id": "spring_index", "kind": "precondition", "tier": 1,
             "target": "coil_d/wire_d - 4"},
            {"id": "index_upper", "kind": "precondition", "tier": 1,
             "target": "12 - coil_d/wire_d"},
            {"id": "solid_clearance", "kind": "precondition", "tier": 1,
             "target": "free_len - wire_d*(n_active + 2) - 2"},
            # A slender spring buckles sideways instead of compressing. The
            # fixed-fixed limit is free length / coil diameter <= 2.6, and it
            # is invisible in the geometry — a buckling spring and a sound one
            # are the same shape.
            {"id": "no_buckling", "kind": "precondition", "tier": 1,
             "target": "2.6*coil_d - free_len"},
            # Corrected shear stress if the spring is compressed solid must
            # stay under the material allowable, or it takes a permanent set.
            # Wahl's factor corrects for curvature: the inner fibre of a coiled
            # wire sees far more stress than straight-torsion theory predicts.
            {"id": "stress_at_solid", "kind": "precondition", "tier": 1,
             "target": "tau_allow - ((4*coil_d/wire_d - 1)"
                       "/(4*coil_d/wire_d - 4) + 0.615*wire_d/coil_d)"
                       "*8*(G*wire_d**4/(8*coil_d**3*n_active))"
                       "*(free_len - wire_d*(n_active + 2))*coil_d"
                       "/(pi*wire_d**3)"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*((coil_d + wire_d)**2 - (coil_d - wire_d)**2)"
                       "/4*free_len"},
            {"id": "outer_dia", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "coil_d + wire_d"},
            {"id": "free_length", "kind": "bbox_extent", "axis": "z",
             "tier": 1, "tol_rel": 1e-06, "target": "free_len"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_env", "type": "Sketch", "parameters": {}},
                {"id": "envelope", "type": "Pad",
                 "rationale": "swept envelope of the coil at free length",
                 "parameters": {"Length": "free_len", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_env", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "(coil_d + wire_d)/2",
                             "r_inner": "(coil_d - wire_d)/2"}}},
            ],
            "dependencies": [{"source": "s_env", "target": "envelope",
                              "kind": "profile"}],
        },
    ).freeze()


#: DIN 6885-1 parallel keys: shaft band (lo, hi] -> key width b, height h.
DIN_6885 = [
    (10.0, 12.0, 4.0, 4.0), (12.0, 17.0, 5.0, 5.0), (17.0, 22.0, 6.0, 6.0),
    (22.0, 30.0, 8.0, 7.0), (30.0, 38.0, 10.0, 8.0), (38.0, 44.0, 12.0, 8.0),
    (44.0, 50.0, 14.0, 9.0), (50.0, 58.0, 16.0, 10.0), (58.0, 65.0, 18.0, 11.0),
    (65.0, 75.0, 20.0, 12.0),
]

#: allowable stresses (MPa), steady load, steel key in a steel hub
KEY_ALLOW = {"shear": 60.0, "bearing": 100.0}


def key_for_shaft(shaft_d: float) -> tuple[float, float]:
    """DIN 6885 key section for a shaft. The section is *set by* the shaft
    diameter rather than chosen — that is the point of the standard."""
    for lo, hi, b, h in DIN_6885:
        if lo < shaft_d <= hi:
            return b, h
    raise ValueError(f"shaft {shaft_d} outside the DIN 6885-1 table")


def key_capacity(shaft_d: float, key_len: float) -> dict:
    """Torque a parallel key carries, by both failure modes.

    A key fails two ways and the lower one governs::

        shear    F = tau_allow * b * L         sheared across its width
        bearing  F = sig_allow * (h/2) * L     crushed into the keyway

    with ``T = F * d/2``. For standard proportions **bearing almost always
    governs**, because only half the key height bears against the hub. Nothing
    about the geometry shows which mode is critical, and sizing against the
    wrong one is how keyed joints fail in service.
    """
    b, h = key_for_shaft(shaft_d)
    r = shaft_d / 2.0
    f_shear = KEY_ALLOW["shear"] * b * key_len
    f_bear = KEY_ALLOW["bearing"] * (h / 2.0) * key_len
    return {
        "b": b, "h": h,
        "torque_shear_nm": f_shear * r / 1000.0,
        "torque_bearing_nm": f_bear * r / 1000.0,
        "torque_nm": min(f_shear, f_bear) * r / 1000.0,
        "governed_by": "bearing" if f_bear < f_shear else "shear",
    }


def parallel_key(shaft_d: float, key_len: float) -> Blueprint:
    """DIN 6885 parallel key — a plain rectangular bar."""
    b, h = key_for_shaft(shaft_d)
    return Blueprint(
        part_class="parallel_key",
        variables={"b": b, "h": h, "key_len": key_len},
        datums={"A": "bottom face, seats in the shaft keyway",
                "B": "driving flank"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = b*h*key_len",
             "why": "key bar; section fixed by shaft diameter per DIN 6885-1"},
        ]},
        assertions=[
            {"id": "proportion", "kind": "precondition", "tier": 1,
             "target": "b - h + 4"},
            {"id": "length_min", "kind": "precondition", "tier": 1,
             "target": "key_len - b"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "b*h*key_len"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_key", "type": "Sketch", "parameters": {}},
                {"id": "key", "type": "Pad", "rationale": "parallel key bar",
                 "parameters": {"Length": "key_len", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_key", "plane": "XY", "profile": {
                    "builder": "rect", "args": {"w": "b", "h": "h"}}},
            ],
            "dependencies": [{"source": "s_key", "target": "key",
                              "kind": "profile"}],
        },
    ).freeze()


def keyed_shaft(shaft_d: float, length: float, key_len: float) -> Blueprint:
    """Shaft with a milled keyseat.

    A parallel key sits *half in the shaft and half in the hub* — that is what
    makes it a parallel key rather than a flat one. Without the seat the key
    has nowhere to go: assembled against a plain shaft it is simply absorbed
    into it, and the assembly's volume-additivity check fails by exactly the
    key volume, which is how this was caught.
    """
    b, h = key_for_shaft(shaft_d)
    return Blueprint(
        part_class="keyed_shaft",
        variables={"shaft_d": shaft_d, "length": length, "key_len": key_len,
                   "b": b, "h": h},
        datums={"A": "shaft end face", "B": "shaft axis", "C": "keyseat flank"},
        design_plan={"derivation": [
            {"step": 1,
             "eq": "A_seat = (b/2)*sqrt(r^2-(b/2)^2) + r^2*asin(b/(2r)) "
                   "- b*(r - h/2),  r = shaft_d/2",
             "why": "a keyseat is milled OPEN at the shaft OD, so the removed "
                    "section is the slot rectangle intersected with the round "
                    "shaft, not the full b*(h/2). The naive rectangle "
                    "over-removes by the two corners that fall outside the "
                    "circle — 1.44 mm^2 on a 30 mm shaft, which is small and "
                    "not zero"},
            {"step": 2, "eq": "V = pi*r^2*length - A_seat*key_len",
             "why": "shaft blank less the seat; the seat takes half the key "
                    "height and the hub keyway the other half"},
        ]},
        assertions=[
            {"id": "seat_fits", "kind": "precondition", "tier": 1,
             "target": "shaft_d/2 - h/2 - 2"},
            {"id": "seat_shorter", "kind": "precondition", "tier": 1,
             "target": "length - key_len - 5"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*(shaft_d/2)**2*length "
                       "- ((b/2)*sqrt((shaft_d/2)**2 - (b/2)**2) "
                       "+ (shaft_d/2)**2*asin(b/shaft_d) "
                       "- b*(shaft_d/2 - h/2))*key_len"},
            {"id": "shaft_dia", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "shaft_d"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_shaft", "type": "Sketch", "parameters": {}},
                {"id": "shaft", "type": "Pad", "rationale": "shaft blank",
                 "parameters": {"Length": "length", "Type": "Length"}},
                {"id": "s_seat", "type": "Sketch", "parameters": {}},
                {"id": "keyseat", "type": "Pocket",
                 "rationale": "milled keyseat, half the key height deep",
                 "parameters": {"Length": "key_len", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_shaft", "plane": "XY", "profile": {
                    "builder": "circle", "args": {"r": "shaft_d/2"}}},
                # seat cut downward from the top of the shaft OD
                {"id": "s_seat", "plane": "XY", "z": "key_len",
                 "profile": {"builder": "rect",
                             "args": {"w": "b", "h": "h/2",
                                      "cx": "0", "cy": "shaft_d/2 - h/4"}}},
            ],
            "dependencies": [
                {"source": "s_shaft", "target": "shaft", "kind": "profile"},
                {"source": "s_seat", "target": "keyseat", "kind": "profile"}],
        },
    ).freeze()


def keyed_hub(shaft_d: float, hub_od: float, hub_len: float) -> Blueprint:
    """Hub bored for a shaft, with the keyway broached to half the key height.

    The keyway removes material exactly where the hub wall is thinnest, so the
    outside diameter is governed by the wall remaining *over the keyway*, not
    by the bore. Two hubs with the same bore and different outside diameters
    are not interchangeable for that reason alone.
    """
    b, h = key_for_shaft(shaft_d)
    return Blueprint(
        part_class="keyed_hub",
        variables={"shaft_d": shaft_d, "hub_od": hub_od, "hub_len": hub_len,
                   "b": b, "h": h},
        datums={"A": "hub face", "B": "bore axis", "C": "keyway flank"},
        design_plan={"derivation": [
            {"step": 1,
             "eq": "A_key_in_hub = b*h - A_seat,  "
                   "A_seat = (b/2)*sqrt(r^2-(b/2)^2) + r^2*asin(b/(2r)) "
                   "- b*(r - h/2),  r = shaft_d/2",
             "why": "the broach cuts the FULL key height from the bore, not "
                    "h/2 from the nominal circle. The shaft seat is a "
                    "rectangle clipped by the round shaft, so the key's upper "
                    "corners sit outside the shaft but inside hub material — "
                    "the hub keyway must clear them or the key cannot seat"},
            {"step": 2,
             "eq": "V = pi*((hub_od/2)^2 - (shaft_d/2)^2)*hub_len "
                   "- A_key_in_hub*hub_len",
             "why": "annular hub less the broached keyway"},
        ]},
        assertions=[
            {"id": "wall_over_keyway", "kind": "precondition", "tier": 1,
             "target": "(hub_od - shaft_d)/2 - h/2 - 3"},
            {"id": "hub_length", "kind": "precondition", "tier": 1,
             "target": "hub_len - 1.2*shaft_d"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*((hub_od/2)**2 - (shaft_d/2)**2)*hub_len "
                       "- (b*h - ((b/2)*sqrt((shaft_d/2)**2 - (b/2)**2) "
                       "+ (shaft_d/2)**2*asin(b/shaft_d) "
                       "- b*(shaft_d/2 - h/2)))*hub_len"},
            {"id": "hub_dia", "kind": "bbox_extent", "axis": "x", "tier": 1,
             "tol_rel": 1e-06, "target": "hub_od"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_hub", "type": "Sketch", "parameters": {}},
                {"id": "hub", "type": "Pad", "rationale": "hub blank on bore",
                 "parameters": {"Length": "hub_len", "Type": "Length"}},
                {"id": "s_kw", "type": "Sketch", "parameters": {}},
                {"id": "keyway", "type": "Pocket",
                 "rationale": "keyway broached to half the key height",
                 "parameters": {"Length": "hub_len + 2", "Type": "Length",
                                "Length2": "1", "Type2": "Length",
                                "SideType": "Two sides"}},
            ],
            "sketches": [
                {"id": "s_hub", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "hub_od/2", "r_inner": "shaft_d/2"}}},
                {"id": "s_kw", "plane": "XY", "profile": {
                    "builder": "rect",
                    "args": {"w": "b", "h": "h",
                             "cx": "0", "cy": "shaft_d/2"}}},
            ],
            "dependencies": [
                {"source": "s_hub", "target": "hub", "kind": "profile"},
                {"source": "s_kw", "target": "keyway", "kind": "profile"}],
        },
    ).freeze()


def flat_pulley(pitch_r: float, bore_r: float, width: float,
                flange_h: float = 0.0) -> Blueprint:
    """Belt pulley blank: an annular rim on a bore.

    The engineering content of a belt drive lives in the *drive* — pitch
    length, wrap angle, speed ratio — not in the pulley section, so the part is
    deliberately a plain annulus whose volume is exact. Detailing the V-groove
    would add kernel cost and teach nothing the drive constraints do not.
    """
    return Blueprint(
        part_class="flat_pulley",
        variables={"pitch_r": pitch_r, "bore_r": bore_r, "width": width},
        datums={"A": "belt face", "B": "bore axis (rotation)",
                "C": "hub face"},
        design_plan={"derivation": [
            {"step": 1, "eq": "V = pi*(pitch_r^2 - bore_r^2)*width",
             "why": "annular rim; the belt runs on the pitch diameter, which "
                    "is what sets the drive ratio"},
        ]},
        assertions=[
            {"id": "rim_section", "kind": "precondition", "tier": 1,
             "target": "pitch_r - bore_r - 4"},
            {"id": "face_width", "kind": "precondition", "tier": 1,
             "target": "width - 4"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "pi*(pitch_r**2 - bore_r**2)*width"},
            {"id": "pitch_diameter", "kind": "bbox_extent", "axis": "x",
             "tier": 1, "tol_rel": 1e-06, "target": "2*pitch_r"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_rim", "type": "Sketch", "parameters": {}},
                {"id": "rim", "type": "Pad", "rationale": "pulley rim on bore",
                 "parameters": {"Length": "width", "Type": "Length"}},
            ],
            "sketches": [
                {"id": "s_rim", "plane": "XY", "profile": {
                    "builder": "annulus",
                    "args": {"r_outer": "pitch_r", "r_inner": "bore_r"}}},
            ],
            "dependencies": [{"source": "s_rim", "target": "rim",
                              "kind": "profile"}],
        },
    ).freeze()


def link_bar(centres: float, width: float, t: float, hole_r: float
             ) -> Blueprint:
    """Binary link: a rounded bar with a pin hole at each end.

    ``centres`` is the kinematically meaningful dimension — the pin-to-pin
    distance that sets the linkage's behaviour — so it is the variable, and the
    outline follows from it.
    """
    return Blueprint(
        part_class="link_bar",
        variables={"centres": centres, "width": width, "t": t,
                   "hole_r": hole_r},
        datums={"A": "bottom face z=0", "B": "first pin bore",
                "C": "second pin bore"},
        design_plan={"derivation": [
            {"step": 1,
             "eq": "A = (centres + width)*width - (4-pi)*(width/2)^2 "
                   "- 2*pi*hole_r^2",
             "why": "rounded bar of overall length centres+width with fully "
                    "radiused ends, less the two pin bores"},
            {"step": 2, "eq": "V = A*t", "why": "prismatic link"},
        ]},
        assertions=[
            {"id": "pin_land", "kind": "precondition", "tier": 1,
             "target": "width/2 - hole_r - 2"},
            {"id": "reach", "kind": "precondition", "tier": 1,
             "target": "centres - width"},
            {"id": "body", "kind": "body_volume", "tier": 1, "tol_rel": 1e-06,
             "target": "((centres + width)*width - (4-pi)*(width/2)**2 "
                       "- 2*pi*hole_r**2)*t"},
            {"id": "one_solid", "kind": "solids", "tier": 1, "tol_rel": 1e-09,
             "target": "1"},
            {"id": "closed", "kind": "watertight", "tier": 1},
        ],
        template={
            "features": [
                {"id": "Body", "type": "Body", "parameters": {}},
                {"id": "s_l", "type": "Sketch", "parameters": {}},
                {"id": "link", "type": "Pad", "rationale": "binary link bar",
                 "parameters": {"Length": "t", "Type": "Length"}},
                {"id": "s_h", "type": "Sketch", "parameters": {}},
                {"id": "pins", "type": "Pocket",
                 "rationale": "pin bores at both ends",
                 "parameters": {"Length": "t + 2", "Type": "Length",
                                "Length2": "1", "Type2": "Length",
                                "SideType": "Two sides"}},
            ],
            "sketches": [
                {"id": "s_l", "plane": "XY", "profile": {
                    "builder": "slot",
                    "args": {"length": "centres", "r": "width/2"}}},
                {"id": "s_h", "plane": "XY", "profile": {
                    "builder": "bolt_circle",
                    "args": {"n": "2", "r_bc": "centres/2",
                             "r_hole": "hole_r", "start_deg": "0"}}},
            ],
            "dependencies": [
                {"source": "s_l", "target": "link", "kind": "profile"},
                {"source": "s_h", "target": "pins", "kind": "profile"}],
        },
    ).freeze()


#: name -> factory. The AssemblySpec layer composes these by name.
FAMILIES = {
    "hex_bolt": hex_bolt,
    "hex_nut": hex_nut,
    "washer": washer,
    "clearance_plate": clearance_plate,
    "bearing_ring": bearing_ring,
    "bearing_shaft": stepped_shaft,
    "link_bar": link_bar,
    "flat_pulley": flat_pulley,
    "lead_screw": lead_screw,
    "compression_spring": compression_spring,
    "parallel_key": parallel_key,
    "keyed_hub": keyed_hub,
    "keyed_shaft": keyed_shaft,
    "screw_nut": screw_nut,
}


def make(family: str, **params) -> Blueprint:
    if family == "spur_gear":                      # lives with the gear tier
        from .gear_family import make_blueprint
        return make_blueprint(**params)
    if family not in FAMILIES:
        raise KeyError(f"unknown family {family!r}; have "
                       f"{sorted(list(FAMILIES) + ['spur_gear'])}")
    return FAMILIES[family](**params)
