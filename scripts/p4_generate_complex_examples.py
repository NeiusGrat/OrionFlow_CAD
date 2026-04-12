"""Complex build123d-FTC example generator.

6 categories x 50 variants = 300 complex, multi-feature training examples
that exercise advanced build123d operations (revolve, shell, polar patterns,
NEMA bolt patterns, etc.).

Usage:
    python scripts/generate_complex_examples.py \
        --output data/build123d_ftc/complex_examples.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Callable

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)

NEMA = {
    14: {"size": 35.2, "pcd": 26.0, "bore": 22.0, "bolt_dia": 3.4},
    17: {"size": 42.3, "pcd": 31.0, "bore": 22.0, "bolt_dia": 3.4},
    23: {"size": 57.2, "pcd": 47.14, "bore": 38.1, "bolt_dia": 5.5},
    34: {"size": 86.4, "pcd": 69.6, "bore": 73.0, "bolt_dia": 6.6},
}


def fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.2f}".rstrip("0").rstrip(".")


def build_code(
    params: list[tuple[str, float, str]],
    body_lines: list[str],
) -> str:
    out = ["from build123d import *", "", "# --- Parameters ---"]
    for name, val, comment in params:
        c = f"  # {comment}" if comment else ""
        out.append(f"{name} = {fmt(val)}{c}")
    out.append("")
    out.append("# --- Feature Tree ---")
    out.append("with BuildPart() as part:")
    for ln in body_lines:
        out.append("    " + ln if ln else "")
    out.append("")
    out.append("# --- Export ---")
    out.append("result = part.part")
    out.append('export_step(result, "output.step")')
    return "\n".join(out)


def snap(val: float, step: float) -> float:
    return round(val / step) * step


# ===========================================================================
# CATEGORY 1: NEMA motor mounts (50)
# ===========================================================================

def nema_mount(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    nema_size = rng.choice([14, 17, 23, 34])
    spec = NEMA[nema_size]
    t = float(rng.choice([3, 4, 5, 6, 8, 10]))
    margin = float(rng.choice([4, 6, 8, 10, 12]))
    rounded = rng.random() < 0.5
    has_cable_slot = rng.random() < 0.4
    has_ring = rng.random() < 0.5

    params = [
        ("nema_size", spec["size"], f"mm - NEMA{nema_size} frame"),
        ("pcd", spec["pcd"], "mm - bolt pattern"),
        ("bolt_dia", spec["bolt_dia"], "mm"),
        ("bore_dia", spec["bore"], "mm - pilot bore"),
        ("thickness", t, "mm"),
        ("margin", margin, "mm"),
    ]
    if rounded:
        params.append(("corner_r", 4.0, "mm - corner radius"))
    if has_ring:
        params.append(("ring_od", spec["bore"] + 6, "mm - centering ring OD"))
        params.append(("ring_h", 2.0, "mm"))
    if has_cable_slot:
        params.append(("slot_w", 12.0, "mm"))
        params.append(("slot_h", 4.0, "mm"))

    body = [
        "# Feature 1: Mount plate",
        "with BuildSketch(Plane.XY):",
    ]
    if rounded:
        body.append("    RectangleRounded(nema_size + 2 * margin, nema_size + 2 * margin, corner_r)")
    else:
        body.append("    Rectangle(nema_size + 2 * margin, nema_size + 2 * margin)")
    body.append("extrude(amount=thickness)")
    body.append("")
    body.append("# Feature 2: Pilot bore for motor shaft")
    body.append("with BuildSketch(Plane.XY.offset(thickness)):")
    body.append("    Circle(bore_dia / 2)")
    body.append("extrude(amount=-thickness, mode=Mode.SUBTRACT)")
    body.append("")
    body.append("# Feature 3: NEMA bolt pattern")
    body.append("with BuildSketch(Plane.XY.offset(thickness)):")
    body.append("    with GridLocations(pcd, pcd, 2, 2):")
    body.append("        Circle(bolt_dia / 2)")
    body.append("extrude(amount=-thickness, mode=Mode.SUBTRACT)")

    feat_idx = 4
    if has_ring:
        body.append("")
        body.append(f"# Feature {feat_idx}: Centering ring (front side)")
        body.append("with BuildSketch(Plane.XY.offset(thickness)):")
        body.append("    Circle(ring_od / 2)")
        body.append("    Circle(bore_dia / 2, mode=Mode.SUBTRACT)")
        body.append("extrude(amount=ring_h)")
        feat_idx += 1

    if has_cable_slot:
        body.append("")
        body.append(f"# Feature {feat_idx}: Cable clearance slot on the edge")
        body.append("with BuildSketch(Plane.XY.offset(thickness)):")
        body.append("    with Locations(((nema_size / 2 + margin / 2), 0)):")
        body.append("        SlotOverall(slot_w, slot_h)")
        body.append("extrude(amount=-thickness, mode=Mode.SUBTRACT)")

    code = build_code(params, body)

    desc_extras = []
    if has_ring:
        desc_extras.append("a centering ring around the bore")
    if has_cable_slot:
        desc_extras.append("a cable clearance slot")
    extras_str = (" with " + " and ".join(desc_extras)) if desc_extras else ""

    prompt = rng.choice([
        f"Design a NEMA{nema_size} stepper motor mount plate, {fmt(t)}mm thick, with the "
        f"standard {fmt(spec['pcd'])}mm bolt pattern and {fmt(spec['bore'])}mm pilot bore"
        f"{extras_str}.",
        f"Create a mount for a NEMA{nema_size} motor{extras_str}.",
    ])
    return code, prompt, 4


# ===========================================================================
# CATEGORY 2: Flanges with bolt circles (50)
# ===========================================================================

def flange(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    outer = float(rng.choice([60, 80, 100, 120, 150, 180, 200, 250, 300]))
    bore = float(rng.choice([10, 15, 20, 25, 32, 40, 50]))
    if bore > outer * 0.5:
        bore = float(snap(outer * 0.35, 1))
    t = float(rng.choice([5, 6, 8, 10, 12, 14]))
    n_bolts = rng.choice([4, 6, 8, 12])
    bolt_m = rng.choice([5, 6, 8, 10, 12])
    bolt_dia = {5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5}[bolt_m]
    pcd = float(snap((outer + bore) / 2 + (outer - bore) * 0.1, 2))
    has_raised_face = rng.random() < 0.5
    has_gasket_groove = rng.random() < 0.35

    params = [
        ("outer_dia", outer, "mm"),
        ("bore_dia", bore, "mm"),
        ("thickness", t, "mm"),
        ("n_bolts", n_bolts, "bolts"),
        ("pcd", pcd, "mm - bolt circle"),
        ("bolt_dia", bolt_dia, f"mm - M{bolt_m} clearance"),
    ]
    if has_raised_face:
        params.append(("rf_dia", (outer + bore) / 2 + 10, "mm - raised face OD"))
        params.append(("rf_h", 2.0, "mm - raised face height"))
    if has_gasket_groove:
        params.append(("groove_od", (outer + bore) / 2 + 6, "mm"))
        params.append(("groove_id", (outer + bore) / 2 + 2, "mm"))
        params.append(("groove_d", 1.5, "mm - groove depth"))

    body = [
        "# Feature 1: Flange body",
        "with BuildSketch(Plane.XY):",
        "    Circle(outer_dia / 2)",
        "extrude(amount=thickness)",
        "",
        "# Feature 2: Central bore",
        "with BuildSketch(Plane.XY):",
        "    Circle(bore_dia / 2)",
        "extrude(amount=thickness, mode=Mode.SUBTRACT)",
        "",
        "# Feature 3: Bolt circle",
        "with BuildSketch(Plane.XY.offset(thickness)):",
        "    with PolarLocations(pcd / 2, int(n_bolts)):",
        "        Circle(bolt_dia / 2)",
        "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
    ]
    fi = 4
    if has_raised_face:
        body.append("")
        body.append(f"# Feature {fi}: Raised sealing face")
        body.append("with BuildSketch(Plane.XY.offset(thickness)):")
        body.append("    Circle(rf_dia / 2)")
        body.append("    Circle(bore_dia / 2, mode=Mode.SUBTRACT)")
        body.append("extrude(amount=rf_h)")
        fi += 1
    if has_gasket_groove:
        body.append("")
        body.append(f"# Feature {fi}: Gasket groove on top face")
        offset_expr = "thickness + rf_h" if has_raised_face else "thickness"
        body.append(f"with BuildSketch(Plane.XY.offset({offset_expr})):")
        body.append("    Circle(groove_od / 2)")
        body.append("    Circle(groove_id / 2, mode=Mode.SUBTRACT)")
        body.append("extrude(amount=-groove_d, mode=Mode.SUBTRACT)")

    code = build_code(params, body)
    extras = []
    if has_raised_face:
        extras.append("a raised sealing face")
    if has_gasket_groove:
        extras.append("a gasket groove")
    extras_str = (" with " + " and ".join(extras)) if extras else ""

    prompt = rng.choice([
        f"Design a circular flange, {fmt(outer)}mm OD, {fmt(bore)}mm bore, {fmt(t)}mm thick, "
        f"with {n_bolts}x M{bolt_m} bolts on a {fmt(pcd)}mm PCD{extras_str}.",
        f"Create a pipe flange{extras_str}, about {fmt(outer)}mm outer diameter.",
    ])
    return code, prompt, 4


# ===========================================================================
# CATEGORY 3: Multi-feature brackets (50)
# ===========================================================================

def multi_feature_bracket(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    style = rng.choice(["L", "Z", "U"])
    w = float(snap(rng.uniform(40, 100), 5))
    h = float(snap(rng.uniform(40, 100), 5))
    t = float(rng.choice([3, 4, 5, 6, 8]))
    fillet_r = float(rng.choice([1, 2, 3]))
    chamfer_d = float(rng.choice([0.5, 1.0, 1.5]))
    bolt_dia = float(rng.choice([4.5, 5.5, 6.6]))
    slot_len = float(snap(w * 0.3, 2))

    params = [
        ("flange_len", w, "mm"),
        ("flange_h", h, "mm"),
        ("thickness", t, "mm"),
        ("fillet_r", fillet_r, "mm"),
        ("chamfer_d", chamfer_d, "mm"),
        ("bolt_dia", bolt_dia, "mm"),
        ("slot_len", slot_len, "mm - adjustment slot length"),
        ("slot_wd", bolt_dia + 0.5, "mm - slot width"),
    ]
    body: list[str] = []
    if style == "L":
        body += [
            "# Feature 1: Horizontal flange",
            "with BuildSketch(Plane.XY):",
            "    with Locations((flange_len / 2, 0)):",
            "        Rectangle(flange_len, flange_h)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Vertical flange",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, flange_h / 2)):",
            "        Rectangle(flange_h, flange_h)",
            "extrude(amount=thickness)",
        ]
    elif style == "Z":
        body += [
            "# Feature 1: Lower flange",
            "with BuildSketch(Plane.XY):",
            "    with Locations((-flange_len / 2, 0)):",
            "        Rectangle(flange_len, flange_h)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Riser",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, flange_h / 2)):",
            "        Rectangle(flange_h, flange_h)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Upper flange",
            "with BuildSketch(Plane.XY.offset(flange_h)):",
            "    with Locations((flange_len / 2 + thickness, 0)):",
            "        Rectangle(flange_len, flange_h)",
            "extrude(amount=thickness)",
        ]
    else:  # U
        body += [
            "# Feature 1: Base",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(flange_len + 2 * thickness, flange_h)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Left wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((-(flange_len + thickness) / 2, 0)):",
            "        Rectangle(thickness, flange_h)",
            "extrude(amount=flange_h)",
            "",
            "# Feature 3: Right wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations(((flange_len + thickness) / 2, 0)):",
            "        Rectangle(thickness, flange_h)",
            "extrude(amount=flange_h)",
        ]

    fi = len([1 for ln in body if ln.startswith("# Feature")]) + 1
    body.append("")
    body.append(f"# Feature {fi}: Adjustment slot in horizontal flange")
    body.append("with BuildSketch(Plane.XY.offset(thickness)):")
    body.append("    with Locations((flange_len * 0.7, 0)):" if style != "U" else "    Locations((0, 0))")
    body.append("        SlotOverall(slot_len, slot_wd)" if style != "U" else "    SlotOverall(slot_len, slot_wd)")
    body.append("extrude(amount=-thickness, mode=Mode.SUBTRACT)")
    fi += 1

    body.append("")
    body.append(f"# Feature {fi}: Fillet top-face edges")
    body.append("fillet(part.faces().sort_by(Axis.Z)[-1].edges(), radius=fillet_r)")
    fi += 1

    body.append("")
    body.append(f"# Feature {fi}: Chamfer bottom-face edges")
    body.append("chamfer(part.faces().sort_by(Axis.Z)[0].edges(), length=chamfer_d)")

    code = build_code(params, body)
    prompt = rng.choice([
        f"Design a {style}-bracket with {fmt(t)}mm walls, a {fmt(slot_len)}mm adjustment slot, "
        f"filleted top edges and chamfered bottom edges. Flange size around {fmt(w)}mm.",
        f"Create a multi-feature {style}-bracket for a structural mount with adjustment slots and rounded edges.",
    ])
    return code, prompt, 5


# ===========================================================================
# CATEGORY 4: Revolved (turned) parts (50)
# ===========================================================================

def revolve_part(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    kind = rng.choice(["stepped_shaft", "bushing", "handwheel_blank", "pulley_grooved"])

    if kind == "stepped_shaft":
        d1 = float(rng.choice([20, 25, 30, 40, 50]))
        d2 = float(d1 - rng.choice([4, 6, 8]))
        d3 = float(d2 - rng.choice([3, 4, 5]))
        l1 = float(rng.choice([15, 20, 25, 30]))
        l2 = float(rng.choice([20, 25, 30, 40]))
        l3 = float(rng.choice([15, 20, 25]))
        params = [
            ("d1", d1, "mm"), ("d2", d2, "mm"), ("d3", d3, "mm"),
            ("l1", l1, "mm"), ("l2", l2, "mm"), ("l3", l3, "mm"),
        ]
        body = [
            "# Feature 1: Half-profile for the revolve",
            "with BuildSketch(Plane.XZ):",
            "    with BuildLine() as ln:",
            "        Polyline(",
            "            (0, 0),",
            "            (d1 / 2, 0),",
            "            (d1 / 2, l1),",
            "            (d2 / 2, l1),",
            "            (d2 / 2, l1 + l2),",
            "            (d3 / 2, l1 + l2),",
            "            (d3 / 2, l1 + l2 + l3),",
            "            (0, l1 + l2 + l3),",
            "            close=True,",
            "        )",
            "    make_face()",
            "",
            "# Feature 2: Revolve around the Z axis",
            "revolve(axis=Axis.Z)",
        ]
        prompt = (f"Design a three-step turned shaft: d1={fmt(d1)}mm x l1={fmt(l1)}mm, "
                  f"d2={fmt(d2)}mm x l2={fmt(l2)}mm, d3={fmt(d3)}mm x l3={fmt(l3)}mm, using a revolve.")

    elif kind == "bushing":
        od = float(rng.choice([20, 25, 30, 40]))
        id_ = float(rng.choice([8, 10, 12, 16]))
        h = float(rng.choice([15, 20, 25, 30]))
        flange_od = float(od + rng.choice([6, 8, 10]))
        flange_h = float(rng.choice([3, 4, 5]))
        params = [
            ("od", od, "mm"),
            ("id", id_, "mm - bore"),
            ("h", h, "mm"),
            ("flange_od", flange_od, "mm"),
            ("flange_h", flange_h, "mm"),
        ]
        body = [
            "# Feature 1: Bushing half profile",
            "with BuildSketch(Plane.XZ):",
            "    with BuildLine() as ln:",
            "        Polyline(",
            "            (id / 2, 0),",
            "            (flange_od / 2, 0),",
            "            (flange_od / 2, flange_h),",
            "            (od / 2, flange_h),",
            "            (od / 2, flange_h + h),",
            "            (id / 2, flange_h + h),",
            "            close=True,",
            "        )",
            "    make_face()",
            "",
            "# Feature 2: Revolve",
            "revolve(axis=Axis.Z)",
        ]
        prompt = (f"Design a flanged bushing by revolving a half-profile: bore {fmt(id_)}mm, "
                  f"body OD {fmt(od)}mm, flange OD {fmt(flange_od)}mm.")

    elif kind == "handwheel_blank":
        od = float(rng.choice([80, 100, 120, 150]))
        hub_od = float(rng.choice([25, 30, 35]))
        bore = float(rng.choice([8, 10, 12]))
        rim_h = float(rng.choice([10, 12, 15]))
        hub_h = float(rng.choice([20, 25, 30]))
        params = [
            ("od", od, "mm"), ("hub_od", hub_od, "mm"),
            ("bore", bore, "mm"), ("rim_h", rim_h, "mm"), ("hub_h", hub_h, "mm"),
        ]
        body = [
            "# Feature 1: Handwheel profile",
            "with BuildSketch(Plane.XZ):",
            "    with BuildLine() as ln:",
            "        Polyline(",
            "            (bore / 2, 0),",
            "            (od / 2, 0),",
            "            (od / 2, rim_h),",
            "            (hub_od / 2 + 4, rim_h),",
            "            (hub_od / 2 + 4, rim_h + 2),",
            "            (hub_od / 2, rim_h + 2),",
            "            (hub_od / 2, hub_h),",
            "            (bore / 2, hub_h),",
            "            close=True,",
            "        )",
            "    make_face()",
            "",
            "# Feature 2: Revolve",
            "revolve(axis=Axis.Z)",
        ]
        prompt = (f"Design a {fmt(od)}mm handwheel blank with a {fmt(hub_od)}mm hub, "
                  f"{fmt(bore)}mm shaft bore, using a revolve.")

    else:  # pulley_grooved
        od = float(rng.choice([40, 50, 60, 80]))
        groove_r = float(rng.choice([3, 4, 5]))
        width = float(rng.choice([15, 20, 25]))
        bore = float(rng.choice([6, 8, 10]))
        params = [
            ("od", od, "mm"),
            ("groove_r", groove_r, "mm - V groove radius"),
            ("width", width, "mm"),
            ("bore", bore, "mm"),
        ]
        body = [
            "# Feature 1: Pulley profile with V-groove",
            "with BuildSketch(Plane.XZ):",
            "    with BuildLine() as ln:",
            "        Polyline(",
            "            (bore / 2, 0),",
            "            (od / 2, 0),",
            "            (od / 2, width / 2 - groove_r),",
            "            (od / 2 - groove_r, width / 2),",
            "            (od / 2, width / 2 + groove_r),",
            "            (od / 2, width),",
            "            (bore / 2, width),",
            "            close=True,",
            "        )",
            "    make_face()",
            "",
            "# Feature 2: Revolve",
            "revolve(axis=Axis.Z)",
        ]
        prompt = (f"Design a V-belt pulley, {fmt(od)}mm OD, {fmt(width)}mm wide, "
                  f"{fmt(bore)}mm bore, with a V-groove of radius {fmt(groove_r)}mm.")

    code = build_code(params, body)
    return code, prompt, 4


# ===========================================================================
# CATEGORY 5: Shell / enclosure parts (50)
# ===========================================================================

def shell_enclosure(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    w = float(snap(rng.uniform(60, 150), 5))
    d = float(snap(rng.uniform(40, 120), 5))
    h = float(snap(rng.uniform(25, 60), 5))
    wall = float(rng.choice([2.0, 2.5, 3.0]))
    n_bosses = rng.choice([2, 4])
    boss_d = float(rng.choice([6.0, 8.0]))
    boss_hole = float(rng.choice([2.5, 3.0, 3.5]))
    has_cable = rng.random() < 0.7
    has_vent = rng.random() < 0.5

    params = [
        ("width", w, "mm"),
        ("depth", d, "mm"),
        ("height", h, "mm"),
        ("wall", wall, "mm"),
        ("boss_d", boss_d, "mm"),
        ("boss_hole", boss_hole, "mm"),
        ("boss_h", h * 0.5, "mm"),
    ]
    if has_cable:
        params.append(("cable_d", 8.0, "mm"))
    if has_vent:
        params.append(("vent_w", 30.0, "mm"))
        params.append(("vent_h", 3.0, "mm"))

    body = [
        "# Feature 1: Outer block",
        "Box(width, depth, height)",
        "",
        "# Feature 2: Hollow the box from the top",
        "top = part.faces().sort_by(Axis.Z)[-1]",
        "offset(amount=-wall, openings=top)",
        "",
        "# Feature 3: PCB mounting bosses",
        "with BuildSketch(Plane.XY.offset(wall)):",
    ]
    if n_bosses == 4:
        body.append("    with GridLocations(width - 3 * boss_d, depth - 3 * boss_d, 2, 2):")
        body.append("        Circle(boss_d / 2)")
    else:
        body.append("    with Locations((-(width / 2 - 2 * boss_d), 0), ((width / 2 - 2 * boss_d), 0)):")
        body.append("        Circle(boss_d / 2)")
    body += [
        "extrude(amount=boss_h)",
        "",
        "# Feature 4: Pilot holes in bosses",
        "with BuildSketch(Plane.XY.offset(wall + boss_h)):",
    ]
    if n_bosses == 4:
        body.append("    with GridLocations(width - 3 * boss_d, depth - 3 * boss_d, 2, 2):")
        body.append("        Circle(boss_hole / 2)")
    else:
        body.append("    with Locations((-(width / 2 - 2 * boss_d), 0), ((width / 2 - 2 * boss_d), 0)):")
        body.append("        Circle(boss_hole / 2)")
    body.append("extrude(amount=-boss_h, mode=Mode.SUBTRACT)")

    fi = 5
    if has_cable:
        body.append("")
        body.append(f"# Feature {fi}: Cable entry hole on +X side")
        body.append("with BuildSketch(Plane.YZ.offset(width / 2)):")
        body.append("    with Locations((0, height / 2)):")
        body.append("        Circle(cable_d / 2)")
        body.append("extrude(amount=-wall * 1.5, mode=Mode.SUBTRACT)")
        fi += 1
    if has_vent:
        body.append("")
        body.append(f"# Feature {fi}: Ventilation slots on -Y side")
        body.append("with BuildSketch(Plane.XZ.offset(-depth / 2)):")
        body.append("    with Locations((0, height * 0.25), (0, height * 0.5), (0, height * 0.75)):")
        body.append("        SlotOverall(vent_w, vent_h)")
        body.append("extrude(amount=wall * 2, mode=Mode.SUBTRACT)")

    code = build_code(params, body)
    extras = []
    extras.append(f"{n_bosses} PCB bosses")
    if has_cable:
        extras.append("a cable gland hole")
    if has_vent:
        extras.append("ventilation slots")
    extras_str = ", ".join(extras)
    prompt = rng.choice([
        f"Design a shelled enclosure {fmt(w)}x{fmt(d)}x{fmt(h)}mm with {fmt(wall)}mm walls, "
        f"{extras_str}.",
        f"Create a hollow project box about {fmt(w)}mm wide with internal PCB mounts.",
    ])
    return code, prompt, 5


# ===========================================================================
# CATEGORY 6: Patterned parts (50)
# ===========================================================================

def patterned_part(seed: int) -> tuple[str, str, int]:
    rng = random.Random(seed)
    kind = rng.choice(["heat_sink", "perforated_panel", "polar_disc"])

    if kind == "heat_sink":
        w = float(snap(rng.uniform(40, 80), 5))
        d = float(snap(rng.uniform(40, 80), 5))
        base_h = float(rng.choice([3, 4, 5]))
        fin_h = float(rng.choice([10, 15, 20]))
        fin_t = float(rng.choice([1.0, 1.5, 2.0]))
        n_fins = rng.choice([5, 7, 9, 11])
        params = [
            ("width", w, "mm"), ("depth", d, "mm"),
            ("base_h", base_h, "mm"), ("fin_h", fin_h, "mm"),
            ("fin_t", fin_t, "mm"), ("n_fins", n_fins, "fins"),
            ("fin_pitch", w / (n_fins + 1), "mm - fin spacing"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, depth)",
            "extrude(amount=base_h)",
            "",
            "# Feature 2: Array of cooling fins",
            "with BuildSketch(Plane.XY.offset(base_h)):",
            "    with GridLocations(fin_pitch, 0, int(n_fins), 1):",
            "        Rectangle(fin_t, depth)",
            "extrude(amount=fin_h)",
        ]
        prompt = (f"Design a {fmt(w)}x{fmt(d)}mm heat sink with {n_fins} parallel fins "
                  f"{fmt(fin_t)}mm thick and {fmt(fin_h)}mm tall on a {fmt(base_h)}mm base.")

    elif kind == "perforated_panel":
        w = float(snap(rng.uniform(80, 200), 5))
        d = float(snap(rng.uniform(60, 160), 5))
        t = float(rng.choice([2, 3, 4]))
        hole_d = float(rng.choice([3, 4, 5, 6, 8]))
        pitch = float(snap(hole_d * rng.uniform(2.0, 3.0), 1))
        nx = int((w - pitch) / pitch)
        ny = int((d - pitch) / pitch)
        nx = max(3, min(nx, 15))
        ny = max(3, min(ny, 12))
        params = [
            ("width", w, "mm"), ("depth", d, "mm"), ("thickness", t, "mm"),
            ("hole_d", hole_d, "mm"), ("pitch", pitch, "mm"),
            ("nx", nx, "columns"), ("ny", ny, "rows"),
        ]
        body = [
            "# Feature 1: Plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, depth)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Perforation grid",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(pitch, pitch, int(nx), int(ny)):",
            "        Circle(hole_d / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        prompt = (f"Design a perforated panel {fmt(w)}x{fmt(d)}x{fmt(t)}mm with a {nx}x{ny} "
                  f"grid of {fmt(hole_d)}mm holes on {fmt(pitch)}mm pitch.")

    else:  # polar_disc
        od = float(rng.choice([80, 100, 120, 150, 180]))
        bore = float(rng.choice([10, 15, 20, 25]))
        t = float(rng.choice([5, 6, 8, 10]))
        n_slots = rng.choice([6, 8, 10, 12])
        slot_w = float(rng.choice([6, 8, 10]))
        slot_h = float(rng.choice([3, 4, 5]))
        radial = float(snap(od * 0.35, 1))
        params = [
            ("od", od, "mm"), ("bore", bore, "mm"), ("thickness", t, "mm"),
            ("n_slots", n_slots, "slots"),
            ("slot_w", slot_w, "mm"),
            ("slot_h", slot_h, "mm"),
            ("slot_r", radial, "mm - slot radius from center"),
        ]
        body = [
            "# Feature 1: Disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(od / 2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore / 2)",
            "extrude(amount=thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Polar array of radial slots",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(slot_r, int(n_slots)):",
            "        SlotOverall(slot_w, slot_h)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        prompt = (f"Design a disc {fmt(od)}mm OD with a {fmt(bore)}mm bore and {n_slots} radial "
                  f"slots arranged in a polar pattern around the center.")

    code = build_code(params, body)
    return code, prompt, 5


# ---------------------------------------------------------------------------
# Registry + main
# ---------------------------------------------------------------------------

CATEGORIES: list[tuple[str, Callable[[int], tuple[str, str, int]]]] = [
    ("nema_mount", nema_mount),
    ("flange", flange),
    ("multi_feature_bracket", multi_feature_bracket),
    ("revolve_part", revolve_part),
    ("shell_enclosure", shell_enclosure),
    ("patterned_part", patterned_part),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--per-category", type=int, default=50)
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with args.output.open("w", encoding="utf-8") as fout:
        for ci, (name, fn) in enumerate(CATEGORIES):
            for i in range(args.per_category):
                seed = 50000 + ci * 1000 + i
                code, prompt, complexity = fn(seed)
                rec = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": code},
                    ],
                    "source": "complex_generated",
                    "category": name,
                    "complexity": complexity,
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total += 1

    print(f"Wrote {total} complex examples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
