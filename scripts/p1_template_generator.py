"""Parametric build123d-FTC template generator.

30 parametric templates across 6 categories. Each template produces a
seeded, reproducible build123d-FTC code sample plus 3 prompt variants
(precise / casual / functional).

Usage:
    python scripts/template_generator.py \
        --output data/build123d_ftc/templates_raw.jsonl \
        --variants 100
"""

from __future__ import annotations

import argparse
import json
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)

HOLE_SIZES = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 8.0, 10.0, 12.0]

# Rough M-size -> clearance dia
METRIC_CLEARANCE = {
    "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6,
    "M8": 9.0, "M10": 11.0, "M12": 13.5,
}

NEMA = {
    14: {"size": 35.2, "pcd": 26.0, "bore": 22.0, "bolt_dia": 3.4},
    17: {"size": 42.3, "pcd": 31.0, "bore": 22.0, "bolt_dia": 3.4},
    23: {"size": 57.2, "pcd": 47.14, "bore": 38.1, "bolt_dia": 5.5},
    34: {"size": 86.4, "pcd": 69.6, "bore": 73.0, "bolt_dia": 6.6},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def snap(val: float, step: float) -> float:
    return round(val / step) * step


def rand_thickness(lo: int = 2, hi: int = 20) -> float:
    return float(random.randint(lo, hi))


def rand_len(lo: float, hi: float, step: int = 5) -> float:
    return float(snap(random.uniform(lo, hi), step))


def rand_hole(min_dia: float = 3.0, max_dia: float = 12.0) -> float:
    choices = [d for d in HOLE_SIZES if min_dia <= d <= max_dia]
    return float(random.choice(choices))


def rand_mbolt(min_m: int = 3, max_m: int = 8) -> tuple[str, float]:
    sizes = [k for k in METRIC_CLEARANCE if min_m <= int(k[1:]) <= max_m]
    m = random.choice(sizes)
    return m, METRIC_CLEARANCE[m]


def fmt_num(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def build_code(
    params: list[tuple[str, float, str]],
    body_lines: list[str],
    filename: str = "output.step",
) -> str:
    """Assemble FTC-formatted code.

    params: [(name, value, comment), ...]
    body_lines: lines inside `with BuildPart() as part:` (no indent; 4-space added)
    """
    out: list[str] = ["from build123d import *", "", "# --- Parameters ---"]
    for name, val, comment in params:
        comment_str = f"  # {comment}" if comment else ""
        out.append(f"{name} = {fmt_num(val)}{comment_str}")
    out.append("")
    out.append("# --- Feature Tree ---")
    out.append("with BuildPart() as part:")
    for line in body_lines:
        out.append("    " + line if line else "")
    out.append("")
    out.append("# --- Export ---")
    out.append("result = part.part")
    out.append(f'export_step(result, "{filename}")')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

@dataclass
class TemplateSample:
    name: str
    category: str
    complexity: int
    params: dict
    code: str
    prompts: list[str]


class CADTemplate(ABC):
    name: str = ""
    category: str = ""
    complexity: int = 2

    def generate(self, seed: int) -> TemplateSample:
        random.seed(seed)
        params = self.randomize_params()
        code = self.generate_code(params)
        prompts = self.generate_prompts(params)
        return TemplateSample(
            name=self.name,
            category=self.category,
            complexity=self.complexity,
            params=params,
            code=code,
            prompts=prompts,
        )

    @abstractmethod
    def randomize_params(self) -> dict: ...

    @abstractmethod
    def generate_code(self, p: dict) -> str: ...

    @abstractmethod
    def generate_prompts(self, p: dict) -> list[str]: ...


# ===========================================================================
# PLATES (6)
# ===========================================================================

class MountingPlate(CADTemplate):
    name = "mounting_plate"
    category = "plate"
    complexity = 2

    def randomize_params(self):
        w = rand_len(40, 250)
        h = rand_len(30, min(w, 200))
        t = rand_thickness(2, 12)
        d = rand_hole(3.0, 10.0)
        margin = float(snap(random.uniform(8, 25), 1))
        r = float(random.choice([0, 2, 3, 4, 5]))
        return {"width": w, "height": h, "thickness": t, "hole_dia": d, "margin": margin, "corner_r": r}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm - mounting hole"),
            ("margin", p["margin"], "mm - hole inset from edge"),
            ("corner_r", p["corner_r"], "mm - corner radius (0 = sharp)"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    if corner_r > 0:",
            "        RectangleRounded(width, height, corner_r)",
            "    else:",
            "        Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Four corner mounting holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width - 2 * margin, height - 2 * margin, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        w, h, t, d, m = p["width"], p["height"], p["thickness"], p["hole_dia"], p["margin"]
        return [
            f"Create a {fmt_num(w)}mm by {fmt_num(h)}mm mounting plate, {fmt_num(t)}mm thick, "
            f"with four {fmt_num(d)}mm through-holes inset {fmt_num(m)}mm from each edge.",
            f"I need a flat plate about {fmt_num(w)} x {fmt_num(h)} millimeters with bolt holes "
            f"in the corners. Thickness around {fmt_num(t)}mm, holes for M{int(round(d - 0.5))} bolts.",
            f"Design a mounting plate for a sensor module. The module footprint is roughly "
            f"{fmt_num(w - 20)}mm wide and uses M{int(round(d - 0.5))} fasteners.",
        ]


class CoverPlate(CADTemplate):
    name = "cover_plate"
    category = "plate"
    complexity = 3

    def randomize_params(self):
        w = rand_len(60, 200)
        h = rand_len(50, min(w, 180))
        t = rand_thickness(2, 8)
        d = rand_hole(3.0, 6.0)
        cut_w = float(snap(random.uniform(w * 0.3, w * 0.6), 5))
        cut_h = float(snap(random.uniform(h * 0.3, h * 0.6), 5))
        margin = float(snap(random.uniform(6, 15), 1))
        return {"width": w, "height": h, "thickness": t, "hole_dia": d, "cut_w": cut_w, "cut_h": cut_h, "margin": margin}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
            ("cut_w", p["cut_w"], "mm - central opening width"),
            ("cut_h", p["cut_h"], "mm - central opening height"),
            ("margin", p["margin"], "mm - hole inset"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central rectangular cutout",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    Rectangle(cut_w, cut_h)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Four corner mounting holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width - 2 * margin, height - 2 * margin, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Design a cover plate {fmt_num(p['width'])}x{fmt_num(p['height'])}x{fmt_num(p['thickness'])}mm "
            f"with a {fmt_num(p['cut_w'])}x{fmt_num(p['cut_h'])}mm central opening and four corner mounting holes of {fmt_num(p['hole_dia'])}mm.",
            f"Make a cover with a rectangular window in the middle, about {fmt_num(p['width'])} by {fmt_num(p['height'])}, "
            f"mounting holes in each corner.",
            f"I need a faceplate to cover an opening with a display window roughly "
            f"{fmt_num(p['cut_w'])}mm wide. Overall size around {fmt_num(p['width'])}mm.",
        ]


class SlottedPlate(CADTemplate):
    name = "slotted_plate"
    category = "plate"
    complexity = 3

    def randomize_params(self):
        w = rand_len(80, 220)
        h = rand_len(40, 120)
        t = rand_thickness(3, 10)
        slot_w = float(snap(random.uniform(w * 0.4, w * 0.65), 5))
        slot_h = rand_hole(5.0, 10.0)
        n_slots = random.choice([2, 3, 4])
        spacing = float(snap(h / (n_slots + 1), 1))
        return {"width": w, "height": h, "thickness": t, "slot_w": slot_w, "slot_h": slot_h, "n_slots": n_slots, "spacing": spacing}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("slot_w", p["slot_w"], "mm - slot overall length"),
            ("slot_h", p["slot_h"], "mm - slot overall width"),
            ("n_slots", p["n_slots"], "count"),
            ("spacing", p["spacing"], "mm"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Adjustment slots",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations(*[(0, spacing * (i - (n_slots - 1) / 2)) for i in range(int(n_slots))]):",
            "        SlotOverall(slot_w, slot_h)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Create a {fmt_num(p['width'])}x{fmt_num(p['height'])}x{fmt_num(p['thickness'])}mm plate with "
            f"{p['n_slots']} horizontal adjustment slots, each {fmt_num(p['slot_w'])}mm long and {fmt_num(p['slot_h'])}mm wide.",
            f"I want a plate with slotted holes for adjustable mounting, about {fmt_num(p['width'])}mm long.",
            f"Design an adjustment bracket plate with slots so the bolt positions can be tuned.",
        ]


class PerforatedPlate(CADTemplate):
    name = "perforated_plate"
    category = "plate"
    complexity = 3

    def randomize_params(self):
        w = rand_len(80, 200)
        h = rand_len(60, 160)
        t = rand_thickness(2, 6)
        hole_d = rand_hole(3.0, 6.0)
        nx = random.randint(4, 10)
        ny = random.randint(3, 8)
        pitch = float(snap(random.uniform(hole_d * 2, hole_d * 3), 1))
        return {"width": w, "height": h, "thickness": t, "hole_dia": hole_d, "nx": nx, "ny": ny, "pitch": pitch}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
            ("nx", p["nx"], "holes along X"),
            ("ny", p["ny"], "holes along Y"),
            ("pitch", p["pitch"], "mm - hole spacing"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Grid of perforations",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(pitch, pitch, int(nx), int(ny)):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Perforated panel {fmt_num(p['width'])}x{fmt_num(p['height'])}mm, {fmt_num(p['thickness'])}mm thick, "
            f"with a {p['nx']}x{p['ny']} grid of {fmt_num(p['hole_dia'])}mm holes on {fmt_num(p['pitch'])}mm pitch.",
            f"Make a vented panel with a bunch of small holes for airflow, about {fmt_num(p['width'])}mm wide.",
            f"Design a ventilation cover with drilled holes in a regular grid.",
        ]


class BasePlate(CADTemplate):
    name = "base_plate"
    category = "plate"
    complexity = 3

    def randomize_params(self):
        w = rand_len(80, 200)
        h = rand_len(60, 180)
        t = rand_thickness(6, 20)
        m, clr = rand_mbolt(4, 8)
        cbore_d = clr + 4.0
        cbore_depth = float(snap(t * 0.4, 0.5))
        margin = float(snap(random.uniform(10, 20), 1))
        return {"width": w, "height": h, "thickness": t, "bolt_m": m, "hole_dia": clr, "cbore_dia": cbore_d, "cbore_depth": cbore_depth, "margin": margin}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], f"mm - {p['bolt_m']} clearance"),
            ("cbore_dia", p["cbore_dia"], "mm - counterbore"),
            ("cbore_depth", p["cbore_depth"], "mm"),
            ("margin", p["margin"], "mm"),
        ]
        body = [
            "# Feature 1: Thick base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Counterbored through-holes (4 corners)",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width - 2 * margin, height - 2 * margin, 2, 2):",
            "        Circle(cbore_dia / 2)",
            "extrude(amount=-cbore_depth, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Through-hole at each counterbore",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width - 2 * margin, height - 2 * margin, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Heavy base plate {fmt_num(p['width'])}x{fmt_num(p['height'])}x{fmt_num(p['thickness'])}mm "
            f"with four counterbored holes for {p['bolt_m']} bolts at {fmt_num(p['margin'])}mm from the edges.",
            f"I need a thick base with counterbored bolt holes so the bolt heads sit flush.",
            f"Design a rigid mounting base for a piece of equipment that bolts down with {p['bolt_m']} fasteners.",
        ]


class CircularFlange(CADTemplate):
    name = "circular_flange"
    category = "plate"
    complexity = 3

    def randomize_params(self):
        outer = rand_len(60, 200)
        bore = float(snap(random.uniform(outer * 0.2, outer * 0.45), 1))
        t = rand_thickness(4, 14)
        n_bolts = random.choice([4, 6, 8])
        pcd = float(snap((outer + bore) / 2, 1))
        bolt_d = rand_hole(4.0, 10.0)
        return {"outer_dia": outer, "bore_dia": bore, "thickness": t, "n_bolts": n_bolts, "pcd": pcd, "bolt_dia": bolt_d}

    def generate_code(self, p):
        params = [
            ("outer_dia", p["outer_dia"], "mm"),
            ("bore_dia", p["bore_dia"], "mm - central bore"),
            ("thickness", p["thickness"], "mm"),
            ("n_bolts", p["n_bolts"], "bolt count"),
            ("pcd", p["pcd"], "mm - bolt circle diameter"),
            ("bolt_dia", p["bolt_dia"], "mm - bolt clearance"),
        ]
        body = [
            "# Feature 1: Circular flange disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central bore",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Bolt circle",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(pcd / 2, int(n_bolts)):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Circular flange {fmt_num(p['outer_dia'])}mm OD with {fmt_num(p['bore_dia'])}mm bore, "
            f"{fmt_num(p['thickness'])}mm thick, {p['n_bolts']} bolt holes on a {fmt_num(p['pcd'])}mm PCD.",
            f"Make a round flange plate with a hole in the middle and bolt holes around the outside.",
            f"Design a pipe flange with {p['n_bolts']} bolts for mounting to a mating flange.",
        ]


# ===========================================================================
# BRACKETS (6)
# ===========================================================================

class LBracket(CADTemplate):
    name = "l_bracket"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        w = rand_len(40, 120)
        h1 = rand_len(30, 100)
        h2 = rand_len(30, 100)
        t = rand_thickness(3, 10)
        d = rand_hole(4.0, 8.0)
        return {"width": w, "flange1": h1, "flange2": h2, "thickness": t, "hole_dia": d}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm - bracket width along Y"),
            ("flange1", p["flange1"], "mm - horizontal flange length"),
            ("flange2", p["flange2"], "mm - vertical flange length"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
        ]
        body = [
            "# Feature 1: Horizontal flange",
            "with BuildSketch(Plane.XY):",
            "    with Locations((flange1 / 2, 0)):",
            "        Rectangle(flange1, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Vertical flange",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, flange2 / 2)):",
            "        Rectangle(width, flange2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Hole in horizontal flange",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((flange1 * 0.7, 0)):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 4: Hole in vertical flange",
            "with BuildSketch(Plane.YZ.offset(thickness)):",
            "    with Locations((0, flange2 * 0.7)):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"L-bracket {fmt_num(p['width'])}mm wide with {fmt_num(p['flange1'])}mm horizontal and "
            f"{fmt_num(p['flange2'])}mm vertical flanges, {fmt_num(p['thickness'])}mm thick, with "
            f"{fmt_num(p['hole_dia'])}mm mounting holes on each flange.",
            f"Need an L-shaped bracket to bolt a surface to a wall. About {fmt_num(p['width'])}mm wide.",
            f"Design an angle bracket for attaching a shelf to a vertical support.",
        ]


class ZBracket(CADTemplate):
    name = "z_bracket"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        w = rand_len(40, 80)
        leg = rand_len(30, 60)
        offset = rand_len(20, 60)
        t = rand_thickness(3, 6)
        d = rand_hole(4.0, 6.0)
        return {"width": w, "leg": leg, "offset": offset, "thickness": t, "hole_dia": d}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("leg", p["leg"], "mm - top/bottom leg length"),
            ("offset", p["offset"], "mm - Z offset between legs"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
        ]
        body = [
            "# Feature 1: Bottom leg",
            "with BuildSketch(Plane.XY):",
            "    with Locations((-leg / 2, 0)):",
            "        Rectangle(leg, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Vertical riser",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, offset / 2)):",
            "        Rectangle(width, offset)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Top leg",
            "with BuildSketch(Plane.XY.offset(offset)):",
            "    with Locations((leg / 2 + thickness, 0)):",
            "        Rectangle(leg, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 4: Mounting holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((-leg * 0.7, 0)):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Z-bracket {fmt_num(p['width'])}mm wide with {fmt_num(p['leg'])}mm legs offset by "
            f"{fmt_num(p['offset'])}mm in Z, {fmt_num(p['thickness'])}mm thick.",
            f"Make an offset bracket that steps up from one level to another.",
            f"Design a Z-shaped mounting bracket to connect two parallel surfaces at different heights.",
        ]


class UBracket(CADTemplate):
    name = "u_bracket"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        base_w = rand_len(40, 120)
        side_h = rand_len(30, 80)
        depth = rand_len(30, 80)
        t = rand_thickness(3, 8)
        d = rand_hole(4.0, 8.0)
        return {"base_w": base_w, "side_h": side_h, "depth": depth, "thickness": t, "hole_dia": d}

    def generate_code(self, p):
        params = [
            ("base_w", p["base_w"], "mm - inner base width"),
            ("side_h", p["side_h"], "mm - side wall height"),
            ("depth", p["depth"], "mm - along Y"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
        ]
        body = [
            "# Feature 1: Base",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(base_w + 2 * thickness, depth)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Left side wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((-(base_w / 2 + thickness / 2), 0)):",
            "        Rectangle(thickness, depth)",
            "extrude(amount=side_h)",
            "",
            "# Feature 3: Right side wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations(((base_w / 2 + thickness / 2), 0)):",
            "        Rectangle(thickness, depth)",
            "extrude(amount=side_h)",
            "",
            "# Feature 4: Holes in base",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(base_w * 0.6, depth * 0.6, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"U-bracket with {fmt_num(p['base_w'])}mm inner width, {fmt_num(p['side_h'])}mm side walls, "
            f"{fmt_num(p['depth'])}mm deep, {fmt_num(p['thickness'])}mm thick.",
            f"I need a U-shaped channel bracket to hold something between two walls.",
            f"Design a U-channel mounting bracket that will cradle a round or square object.",
        ]


class GussetBracket(CADTemplate):
    name = "gusset_bracket"
    category = "bracket"
    complexity = 4

    def randomize_params(self):
        w = rand_len(40, 100)
        h = rand_len(40, 100)
        t = rand_thickness(3, 8)
        gusset_t = rand_thickness(3, 6)
        d = rand_hole(4.0, 8.0)
        return {"width": w, "height": h, "thickness": t, "gusset_t": gusset_t, "hole_dia": d}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm - flange length"),
            ("height", p["height"], "mm - vertical leg"),
            ("thickness", p["thickness"], "mm - plate thickness"),
            ("gusset_t", p["gusset_t"], "mm - gusset thickness"),
            ("hole_dia", p["hole_dia"], "mm"),
        ]
        body = [
            "# Feature 1: Horizontal flange",
            "with BuildSketch(Plane.XY):",
            "    with Locations((width / 2, 0)):",
            "        Rectangle(width, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Vertical flange",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, height / 2)):",
            "        Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Triangular gusset reinforcement",
            "with BuildSketch(Plane.XZ):",
            "    with BuildLine():",
            "        l1 = Line((0, 0), (width * 0.8, 0))",
            "        l2 = Line((width * 0.8, 0), (0, height * 0.8))",
            "        l3 = Line((0, height * 0.8), (0, 0))",
            "    make_face()",
            "extrude(amount=gusset_t, both=True)",
            "",
            "# Feature 4: Holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((width * 0.75, 0)):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Gusseted L-bracket {fmt_num(p['width'])}x{fmt_num(p['height'])}mm with a triangular reinforcement "
            f"rib, {fmt_num(p['thickness'])}mm wall thickness.",
            f"Need a heavy-duty L-bracket with a gusset rib for extra stiffness.",
            f"Design a reinforced angle bracket that can handle significant vertical load.",
        ]


class MotorMountNEMA17(CADTemplate):
    name = "motor_mount_nema17"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        t = rand_thickness(4, 10)
        margin = float(snap(random.uniform(4, 10), 1))
        return {"thickness": t, "margin": margin}

    def generate_code(self, p):
        spec = NEMA[17]
        params = [
            ("thickness", p["thickness"], "mm"),
            ("nema_size", spec["size"], "mm - NEMA17 outer"),
            ("bolt_pcd", spec["pcd"], "mm - bolt pattern (square)"),
            ("bolt_dia", spec["bolt_dia"], "mm - M3 clearance"),
            ("bore_dia", spec["bore"], "mm - shaft bore"),
            ("margin", p["margin"], "mm"),
        ]
        body = [
            "# Feature 1: Mount plate",
            "with BuildSketch(Plane.XY):",
            "    RectangleRounded(nema_size + 2 * margin, nema_size + 2 * margin, 3)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central shaft bore",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: NEMA17 bolt pattern (square)",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(bolt_pcd, bolt_pcd, 2, 2):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"NEMA17 motor mount plate, {fmt_num(p['thickness'])}mm thick, with the standard 31mm bolt "
            f"pattern and 22mm centering bore.",
            f"I need a mount for a NEMA17 stepper motor.",
            f"Design a faceplate to bolt a NEMA17 stepper to a frame.",
        ]


class MotorMountNEMA23(CADTemplate):
    name = "motor_mount_nema23"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        t = rand_thickness(5, 12)
        margin = float(snap(random.uniform(5, 12), 1))
        return {"thickness": t, "margin": margin}

    def generate_code(self, p):
        spec = NEMA[23]
        params = [
            ("thickness", p["thickness"], "mm"),
            ("nema_size", spec["size"], "mm - NEMA23 outer"),
            ("bolt_pcd", spec["pcd"], "mm - bolt pattern"),
            ("bolt_dia", spec["bolt_dia"], "mm - M5 clearance"),
            ("bore_dia", spec["bore"], "mm"),
            ("margin", p["margin"], "mm"),
        ]
        body = [
            "# Feature 1: Mount plate",
            "with BuildSketch(Plane.XY):",
            "    RectangleRounded(nema_size + 2 * margin, nema_size + 2 * margin, 4)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Shaft bore",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: NEMA23 bolt pattern",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(bolt_pcd, bolt_pcd, 2, 2):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"NEMA23 motor mount, {fmt_num(p['thickness'])}mm thick, with the 47.14mm bolt pattern "
            f"and 38.1mm pilot bore.",
            f"Need a NEMA23 stepper mount plate.",
            f"Design a bracket to mount a NEMA23 motor to a gantry frame.",
        ]


# ===========================================================================
# ENCLOSURES (4)
# ===========================================================================

class OpenBox(CADTemplate):
    name = "open_box"
    category = "enclosure"
    complexity = 3

    def randomize_params(self):
        w = rand_len(40, 150)
        d = rand_len(30, 120)
        h = rand_len(20, 80)
        wall = float(random.choice([1.5, 2.0, 2.5, 3.0]))
        return {"width": w, "depth": d, "height": h, "wall": wall}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm - wall thickness"),
        ]
        body = [
            "# Feature 1: Solid block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Shell out the top to create an open box",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Open box {fmt_num(p['width'])}x{fmt_num(p['depth'])}x{fmt_num(p['height'])}mm with {fmt_num(p['wall'])}mm walls.",
            f"I need a simple tray about {fmt_num(p['width'])}mm long.",
            f"Design a hollow open-top enclosure for a small circuit board.",
        ]


class LiddedBox(CADTemplate):
    name = "lidded_box"
    category = "enclosure"
    complexity = 4

    def randomize_params(self):
        w = rand_len(50, 140)
        d = rand_len(40, 120)
        h = rand_len(25, 70)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        lid_t = float(random.choice([2.0, 3.0]))
        return {"width": w, "depth": d, "height": h, "wall": wall, "lid_t": lid_t}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm"),
            ("lid_t", p["lid_t"], "mm - lid thickness"),
        ]
        body = [
            "# Feature 1: Outer solid",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Shell out to form box body",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
            "",
            "# Feature 3: Lid lip on top inner edge",
            "with BuildSketch(Plane.XY.offset(height)):",
            "    Rectangle(width - 2 * wall - 0.2, depth - 2 * wall - 0.2)",
            "    Rectangle(width - 2 * wall - 2.0, depth - 2 * wall - 2.0, mode=Mode.SUBTRACT)",
            "extrude(amount=lid_t)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Lidded enclosure {fmt_num(p['width'])}x{fmt_num(p['depth'])}x{fmt_num(p['height'])}mm with "
            f"{fmt_num(p['wall'])}mm walls and an integrated lid lip.",
            f"Design a small project box with a lid that snaps over a lip.",
            f"I need an electronics enclosure with a removable top cover.",
        ]


class ElectronicsEnclosure(CADTemplate):
    name = "electronics_enclosure"
    category = "enclosure"
    complexity = 4

    def randomize_params(self):
        w = rand_len(60, 160)
        d = rand_len(50, 120)
        h = rand_len(25, 60)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        boss_d = float(random.choice([6.0, 8.0]))
        boss_hole = float(random.choice([2.5, 3.0, 3.5]))
        boss_h = float(snap(h * 0.6, 1))
        cable_d = float(random.choice([6.0, 8.0, 10.0]))
        return {"width": w, "depth": d, "height": h, "wall": wall, "boss_d": boss_d, "boss_hole": boss_hole, "boss_h": boss_h, "cable_d": cable_d}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm"),
            ("boss_d", p["boss_d"], "mm - PCB boss diameter"),
            ("boss_hole", p["boss_hole"], "mm - screw pilot"),
            ("boss_h", p["boss_h"], "mm - boss height"),
            ("cable_d", p["cable_d"], "mm - cable gland hole"),
        ]
        body = [
            "# Feature 1: Outer block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Hollow the box",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
            "",
            "# Feature 3: Four PCB mounting bosses",
            "with BuildSketch(Plane.XY.offset(wall)):",
            "    with GridLocations(width - 3 * boss_d, depth - 3 * boss_d, 2, 2):",
            "        Circle(boss_d / 2)",
            "extrude(amount=boss_h)",
            "",
            "# Feature 4: Pilot holes in bosses",
            "with BuildSketch(Plane.XY.offset(wall + boss_h)):",
            "    with GridLocations(width - 3 * boss_d, depth - 3 * boss_d, 2, 2):",
            "        Circle(boss_hole / 2)",
            "extrude(amount=-boss_h, mode=Mode.SUBTRACT)",
            "",
            "# Feature 5: Cable entry on one side",
            "with BuildSketch(Plane.YZ.offset(width / 2)):",
            "    with Locations((0, height / 2)):",
            "        Circle(cable_d / 2)",
            "extrude(amount=-wall * 1.5, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Electronics enclosure {fmt_num(p['width'])}x{fmt_num(p['depth'])}x{fmt_num(p['height'])}mm "
            f"with {fmt_num(p['wall'])}mm walls, four PCB mounting bosses, and a "
            f"{fmt_num(p['cable_d'])}mm cable gland hole.",
            f"Need a project enclosure with standoffs for a PCB and a hole for a cable grommet.",
            f"Design an electronics housing for a small sensor module with onboard PCB mounting.",
        ]


class VentedBox(CADTemplate):
    name = "vented_box"
    category = "enclosure"
    complexity = 4

    def randomize_params(self):
        w = rand_len(60, 140)
        d = rand_len(40, 100)
        h = rand_len(30, 80)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        slot_w = float(snap(random.uniform(20, 40), 1))
        slot_h = float(random.choice([2.0, 3.0]))
        n_slots = random.randint(3, 6)
        return {"width": w, "depth": d, "height": h, "wall": wall, "slot_w": slot_w, "slot_h": slot_h, "n_slots": n_slots}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm"),
            ("slot_w", p["slot_w"], "mm"),
            ("slot_h", p["slot_h"], "mm"),
            ("n_slots", p["n_slots"], "ventilation slots"),
        ]
        body = [
            "# Feature 1: Outer block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Hollow",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
            "",
            "# Feature 3: Ventilation slots on +Y side",
            "with BuildSketch(Plane.XZ.offset(-depth / 2)):",
            "    with Locations(*[(0, height * 0.2 + i * (slot_h + 3)) for i in range(int(n_slots))]):",
            "        SlotOverall(slot_w, slot_h)",
            "extrude(amount=wall * 2, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Vented enclosure {fmt_num(p['width'])}x{fmt_num(p['depth'])}x{fmt_num(p['height'])}mm with "
            f"{p['n_slots']} ventilation slots on one side.",
            f"Need an enclosure with cooling slots on the side for passive airflow.",
            f"Design a project box with ventilation for a small computer board.",
        ]


# ===========================================================================
# CYLINDRICAL (4)
# ===========================================================================

class Spacer(CADTemplate):
    name = "spacer"
    category = "cylindrical"
    complexity = 2

    def randomize_params(self):
        od = float(snap(random.uniform(8, 30), 1))
        id_ = float(snap(random.uniform(od * 0.3, od * 0.7), 0.5))
        h = float(snap(random.uniform(5, 40), 1))
        return {"outer_dia": od, "inner_dia": id_, "height": h}

    def generate_code(self, p):
        params = [
            ("outer_dia", p["outer_dia"], "mm"),
            ("inner_dia", p["inner_dia"], "mm"),
            ("height", p["height"], "mm"),
        ]
        body = [
            "# Feature 1: Outer cylinder",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Central bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(inner_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Tubular spacer, {fmt_num(p['outer_dia'])}mm OD, {fmt_num(p['inner_dia'])}mm ID, "
            f"{fmt_num(p['height'])}mm tall.",
            f"Need a hollow spacer sleeve for a bolt.",
            f"Design a spacer to set the distance between two mounted plates.",
        ]


class SteppedShaft(CADTemplate):
    name = "stepped_shaft"
    category = "cylindrical"
    complexity = 3

    def randomize_params(self):
        d1 = float(snap(random.uniform(10, 30), 1))
        d2 = float(snap(random.uniform(d1 * 0.5, d1 * 0.85), 1))
        d3 = float(snap(d2 * 0.7, 0.5))
        h1 = float(snap(random.uniform(10, 30), 1))
        h2 = float(snap(random.uniform(15, 40), 1))
        h3 = float(snap(random.uniform(10, 25), 1))
        return {"d1": d1, "d2": d2, "d3": d3, "h1": h1, "h2": h2, "h3": h3}

    def generate_code(self, p):
        params = [
            ("d1", p["d1"], "mm - largest diameter"),
            ("d2", p["d2"], "mm - middle"),
            ("d3", p["d3"], "mm - smallest"),
            ("h1", p["h1"], "mm"),
            ("h2", p["h2"], "mm"),
            ("h3", p["h3"], "mm"),
        ]
        body = [
            "# Feature 1: Largest section",
            "with BuildSketch(Plane.XY):",
            "    Circle(d1 / 2)",
            "extrude(amount=h1)",
            "",
            "# Feature 2: Middle section",
            "with BuildSketch(Plane.XY.offset(h1)):",
            "    Circle(d2 / 2)",
            "extrude(amount=h2)",
            "",
            "# Feature 3: Smallest section",
            "with BuildSketch(Plane.XY.offset(h1 + h2)):",
            "    Circle(d3 / 2)",
            "extrude(amount=h3)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Stepped shaft with three sections of decreasing diameter: {fmt_num(p['d1'])}mm, "
            f"{fmt_num(p['d2'])}mm, {fmt_num(p['d3'])}mm, heights "
            f"{fmt_num(p['h1'])}/{fmt_num(p['h2'])}/{fmt_num(p['h3'])}mm.",
            f"Need a stepped shaft, around {fmt_num(p['h1'] + p['h2'] + p['h3'])}mm total length.",
            f"Design a shaft with a bearing journal step-down for press-fit assembly.",
        ]


class FlangeBushing(CADTemplate):
    name = "flange_bushing"
    category = "cylindrical"
    complexity = 3

    def randomize_params(self):
        body_d = float(snap(random.uniform(10, 30), 1))
        bore_d = float(snap(body_d * 0.5, 0.5))
        body_h = float(snap(random.uniform(15, 40), 1))
        flange_d = float(snap(body_d * 1.8, 1))
        flange_h = float(snap(random.uniform(3, 6), 1))
        return {"body_d": body_d, "bore_d": bore_d, "body_h": body_h, "flange_d": flange_d, "flange_h": flange_h}

    def generate_code(self, p):
        params = [
            ("body_d", p["body_d"], "mm - bushing body OD"),
            ("bore_d", p["bore_d"], "mm - through bore"),
            ("body_h", p["body_h"], "mm"),
            ("flange_d", p["flange_d"], "mm - flange OD"),
            ("flange_h", p["flange_h"], "mm - flange thickness"),
        ]
        body = [
            "# Feature 1: Flange disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(flange_d / 2)",
            "extrude(amount=flange_h)",
            "",
            "# Feature 2: Cylindrical body",
            "with BuildSketch(Plane.XY.offset(flange_h)):",
            "    Circle(body_d / 2)",
            "extrude(amount=body_h)",
            "",
            "# Feature 3: Through bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_d / 2)",
            "extrude(amount=flange_h + body_h, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Flanged bushing, {fmt_num(p['body_d'])}mm body OD, {fmt_num(p['flange_d'])}mm flange OD, "
            f"{fmt_num(p['bore_d'])}mm bore, total length {fmt_num(p['body_h'] + p['flange_h'])}mm.",
            f"Need a flanged bushing to press into a plate.",
            f"Design a shoulder bushing for a pivot pin with a head that sits on the surface.",
        ]


class PulleyBlank(CADTemplate):
    name = "pulley_blank"
    category = "cylindrical"
    complexity = 3

    def randomize_params(self):
        od = float(snap(random.uniform(20, 80), 1))
        hub_d = float(snap(od * 0.35, 1))
        bore = float(snap(random.uniform(5, 12), 0.5))
        face_w = float(snap(random.uniform(8, 20), 1))
        hub_h = float(snap(face_w * 1.4, 1))
        return {"outer_dia": od, "hub_dia": hub_d, "bore": bore, "face_w": face_w, "hub_h": hub_h}

    def generate_code(self, p):
        params = [
            ("outer_dia", p["outer_dia"], "mm - pulley OD"),
            ("hub_dia", p["hub_dia"], "mm - hub OD"),
            ("bore", p["bore"], "mm - shaft bore"),
            ("face_w", p["face_w"], "mm - belt face width"),
            ("hub_h", p["hub_h"], "mm - total hub height"),
        ]
        body = [
            "# Feature 1: Pulley disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=face_w)",
            "",
            "# Feature 2: Hub boss",
            "with BuildSketch(Plane.XY.offset(face_w)):",
            "    Circle(hub_dia / 2)",
            "extrude(amount=hub_h - face_w)",
            "",
            "# Feature 3: Central shaft bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore / 2)",
            "extrude(amount=hub_h, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Pulley blank, {fmt_num(p['outer_dia'])}mm OD, {fmt_num(p['face_w'])}mm face width, "
            f"with a {fmt_num(p['hub_dia'])}mm hub and {fmt_num(p['bore'])}mm shaft bore.",
            f"I need a simple pulley blank to turn into a belt pulley later.",
            f"Design a flat-face pulley body with an integrated hub boss.",
        ]


# ===========================================================================
# STRUCTURAL (5)
# ===========================================================================

class IBeamSection(CADTemplate):
    name = "i_beam_section"
    category = "structural"
    complexity = 4

    def randomize_params(self):
        h = rand_len(50, 200)
        flange_w = rand_len(40, 120)
        web_t = float(random.choice([4.0, 5.0, 6.0, 8.0]))
        flange_t = float(random.choice([4.0, 6.0, 8.0, 10.0]))
        length = rand_len(100, 400)
        return {"h": h, "flange_w": flange_w, "web_t": web_t, "flange_t": flange_t, "length": length}

    def generate_code(self, p):
        params = [
            ("h", p["h"], "mm - section height"),
            ("flange_w", p["flange_w"], "mm - flange width"),
            ("web_t", p["web_t"], "mm - web thickness"),
            ("flange_t", p["flange_t"], "mm - flange thickness"),
            ("length", p["length"], "mm - beam length"),
        ]
        body = [
            "# Feature 1: I-beam cross section",
            "with BuildSketch(Plane.XY):",
            "    with Locations((0, (h - flange_t) / 2)):",
            "        Rectangle(flange_w, flange_t)",
            "    with Locations((0, -(h - flange_t) / 2)):",
            "        Rectangle(flange_w, flange_t)",
            "    Rectangle(web_t, h - 2 * flange_t)",
            "extrude(amount=length)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"I-beam section {fmt_num(p['h'])}mm tall x {fmt_num(p['flange_w'])}mm flange, "
            f"{fmt_num(p['web_t'])}mm web, {fmt_num(p['flange_t'])}mm flange thickness, "
            f"extruded {fmt_num(p['length'])}mm long.",
            f"Need an I-beam about {fmt_num(p['length'])}mm long.",
            f"Design a structural steel I-section for a small frame.",
        ]


class HingeLeaf(CADTemplate):
    name = "hinge_leaf"
    category = "structural"
    complexity = 4

    def randomize_params(self):
        w = rand_len(40, 120)
        h = rand_len(30, 80)
        t = rand_thickness(2, 6)
        knuckle_od = float(snap(t * 3, 0.5))
        knuckle_id = float(snap(knuckle_od * 0.5, 0.5))
        hole_d = rand_hole(3.0, 5.0)
        return {"width": w, "height": h, "thickness": t, "knuckle_od": knuckle_od, "knuckle_id": knuckle_id, "hole_d": hole_d}

    def generate_code(self, p):
        params = [
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("knuckle_od", p["knuckle_od"], "mm"),
            ("knuckle_id", p["knuckle_id"], "mm"),
            ("hole_d", p["hole_d"], "mm"),
        ]
        body = [
            "# Feature 1: Flat leaf",
            "with BuildSketch(Plane.XY):",
            "    with Locations((0, height / 2)):",
            "        Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Knuckle cylinder along the hinge axis",
            "with BuildSketch(Plane.XZ):",
            "    with Locations((0, thickness / 2)):",
            "        Circle(knuckle_od / 2)",
            "extrude(amount=width / 2, both=True)",
            "",
            "# Feature 3: Pin bore through knuckle",
            "with BuildSketch(Plane.XZ):",
            "    with Locations((0, thickness / 2)):",
            "        Circle(knuckle_id / 2)",
            "extrude(amount=width, both=True, mode=Mode.SUBTRACT)",
            "",
            "# Feature 4: Mounting holes in the leaf",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width * 0.6, height * 0.5, 2, 2):",
            "        Circle(hole_d / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Hinge leaf, {fmt_num(p['width'])}x{fmt_num(p['height'])}mm flat with a "
            f"{fmt_num(p['knuckle_od'])}mm knuckle and four mounting holes.",
            f"Need one half of a small hinge.",
            f"Design a hinge leaf that will pair with its mirror via a removable pin.",
        ]


class LeverArm(CADTemplate):
    name = "lever_arm"
    category = "structural"
    complexity = 3

    def randomize_params(self):
        length = rand_len(60, 200)
        width = rand_len(15, 40)
        t = rand_thickness(4, 10)
        pivot_d = rand_hole(5.0, 10.0)
        load_d = rand_hole(4.0, 8.0)
        return {"length": length, "width": width, "thickness": t, "pivot_d": pivot_d, "load_d": load_d}

    def generate_code(self, p):
        params = [
            ("length", p["length"], "mm"),
            ("width", p["width"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("pivot_d", p["pivot_d"], "mm - pivot hole"),
            ("load_d", p["load_d"], "mm - load hole"),
        ]
        body = [
            "# Feature 1: Flat bar body",
            "with BuildSketch(Plane.XY):",
            "    SlotOverall(length, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Pivot hole",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((-length / 2 + width / 2, 0)):",
            "        Circle(pivot_d / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Load hole at the other end",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((length / 2 - width / 2, 0)):",
            "        Circle(load_d / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Lever arm, {fmt_num(p['length'])}mm long, {fmt_num(p['width'])}mm wide, "
            f"{fmt_num(p['thickness'])}mm thick, with a {fmt_num(p['pivot_d'])}mm pivot hole and "
            f"{fmt_num(p['load_d'])}mm load hole.",
            f"Need a lever arm with rounded ends and a hole at each end.",
            f"Design a rocker lever with a pivot at one end and a load attachment at the other.",
        ]


class Clamp(CADTemplate):
    name = "clamp_body"
    category = "structural"
    complexity = 3

    def randomize_params(self):
        inner_w = rand_len(20, 60)
        inner_h = rand_len(15, 40)
        t = rand_thickness(4, 10)
        bolt_d = rand_hole(4.0, 8.0)
        depth = rand_len(20, 50)
        return {"inner_w": inner_w, "inner_h": inner_h, "thickness": t, "bolt_d": bolt_d, "depth": depth}

    def generate_code(self, p):
        params = [
            ("inner_w", p["inner_w"], "mm - inner gap width"),
            ("inner_h", p["inner_h"], "mm - inner gap height"),
            ("thickness", p["thickness"], "mm - wall thickness"),
            ("bolt_d", p["bolt_d"], "mm - clamp bolt"),
            ("depth", p["depth"], "mm - along Y"),
        ]
        body = [
            "# Feature 1: Outer U-shape",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(inner_w + 2 * thickness, inner_h + 2 * thickness)",
            "    with Locations((0, thickness / 2)):",
            "        Rectangle(inner_w, inner_h)",
            "extrude(amount=depth)",
            "",
            "# Feature 2: Bolt hole through both sides",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, inner_h / 2 + thickness * 1.5)):",
            "        Circle(bolt_d / 2)",
            "extrude(amount=inner_w / 2 + thickness * 1.5, both=True, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Clamp body with {fmt_num(p['inner_w'])}x{fmt_num(p['inner_h'])}mm inner opening, "
            f"{fmt_num(p['thickness'])}mm wall, {fmt_num(p['depth'])}mm deep, {fmt_num(p['bolt_d'])}mm clamp bolt.",
            f"Need a U-clamp body with a through-bolt to close it down.",
            f"Design a split clamp for holding a round bar.",
        ]


class HandleBar(CADTemplate):
    name = "handle_bar"
    category = "structural"
    complexity = 3

    def randomize_params(self):
        length = rand_len(80, 200)
        bar_d = float(snap(random.uniform(10, 20), 1))
        plate_w = rand_len(30, 60)
        plate_h = rand_len(30, 60)
        plate_t = rand_thickness(3, 6)
        hole_d = rand_hole(4.0, 8.0)
        return {"length": length, "bar_d": bar_d, "plate_w": plate_w, "plate_h": plate_h, "plate_t": plate_t, "hole_d": hole_d}

    def generate_code(self, p):
        params = [
            ("length", p["length"], "mm - between plates"),
            ("bar_d", p["bar_d"], "mm - bar diameter"),
            ("plate_w", p["plate_w"], "mm"),
            ("plate_h", p["plate_h"], "mm"),
            ("plate_t", p["plate_t"], "mm"),
            ("hole_d", p["hole_d"], "mm"),
        ]
        body = [
            "# Feature 1: Left mounting plate",
            "with BuildSketch(Plane.YZ.offset(-length / 2 - plate_t)):",
            "    Rectangle(plate_w, plate_h)",
            "extrude(amount=plate_t)",
            "",
            "# Feature 2: Right mounting plate",
            "with BuildSketch(Plane.YZ.offset(length / 2)):",
            "    Rectangle(plate_w, plate_h)",
            "extrude(amount=plate_t)",
            "",
            "# Feature 3: Connecting bar",
            "with BuildSketch(Plane.YZ):",
            "    Circle(bar_d / 2)",
            "extrude(amount=length / 2, both=True)",
            "",
            "# Feature 4: Mounting holes in plates",
            "with BuildSketch(Plane.YZ.offset(-length / 2 - plate_t)):",
            "    with GridLocations(plate_w * 0.6, plate_h * 0.6, 2, 2):",
            "        Circle(hole_d / 2)",
            "extrude(amount=plate_t, mode=Mode.SUBTRACT)",
            "",
            "with BuildSketch(Plane.YZ.offset(length / 2)):",
            "    with GridLocations(plate_w * 0.6, plate_h * 0.6, 2, 2):",
            "        Circle(hole_d / 2)",
            "extrude(amount=plate_t, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Handle bar, {fmt_num(p['length'])}mm long, {fmt_num(p['bar_d'])}mm diameter, "
            f"with {fmt_num(p['plate_w'])}x{fmt_num(p['plate_h'])}mm mounting plates on each end.",
            f"Need a pull handle, about {fmt_num(p['length'])}mm between the mounts.",
            f"Design a drawer handle with a round bar spanning two mounting plates.",
        ]


# ===========================================================================
# HARDWARE (5)
# ===========================================================================

class FlatWasher(CADTemplate):
    name = "flat_washer"
    category = "hardware"
    complexity = 1

    def randomize_params(self):
        od = float(snap(random.uniform(8, 30), 1))
        id_ = float(snap(od * 0.45, 0.5))
        t = float(random.choice([1.0, 1.5, 2.0, 2.5, 3.0]))
        return {"outer_dia": od, "inner_dia": id_, "thickness": t}

    def generate_code(self, p):
        params = [
            ("outer_dia", p["outer_dia"], "mm"),
            ("inner_dia", p["inner_dia"], "mm"),
            ("thickness", p["thickness"], "mm"),
        ]
        body = [
            "# Feature 1: Washer disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "    Circle(inner_dia / 2, mode=Mode.SUBTRACT)",
            "extrude(amount=thickness)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Flat washer, {fmt_num(p['outer_dia'])}mm OD, {fmt_num(p['inner_dia'])}mm ID, "
            f"{fmt_num(p['thickness'])}mm thick.",
            f"Need a simple washer for an M{int(round(p['inner_dia'] - 0.5))} bolt.",
            f"Design a plain round washer.",
        ]


class Standoff(CADTemplate):
    name = "standoff"
    category = "hardware"
    complexity = 2

    def randomize_params(self):
        height = float(snap(random.uniform(10, 50), 1))
        od = float(snap(random.uniform(6, 12), 1))
        bore = float(random.choice([2.5, 3.0, 3.5, 4.0]))
        hex_style = random.choice([True, False])
        return {"height": height, "outer_dia": od, "bore": bore, "hex": hex_style}

    def generate_code(self, p):
        params = [
            ("height", p["height"], "mm"),
            ("outer_dia", p["outer_dia"], "mm - across flats if hex"),
            ("bore", p["bore"], "mm - threaded bore"),
        ]
        if p["hex"]:
            sketch = [
                "with BuildSketch(Plane.XY):",
                "    RegularPolygon(outer_dia / 2, 6)",
                "extrude(amount=height)",
            ]
        else:
            sketch = [
                "with BuildSketch(Plane.XY):",
                "    Circle(outer_dia / 2)",
                "extrude(amount=height)",
            ]
        body = [
            f"# Feature 1: {'Hex' if p['hex'] else 'Round'} standoff body",
            *sketch,
            "",
            "# Feature 2: Central bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        shape = "hex" if p["hex"] else "round"
        return [
            f"{shape.capitalize()} standoff, {fmt_num(p['outer_dia'])}mm across, "
            f"{fmt_num(p['height'])}mm tall, {fmt_num(p['bore'])}mm bore.",
            f"Need a {shape} PCB standoff.",
            f"Design a threaded standoff to separate two PCBs.",
        ]


class ThreadedBoss(CADTemplate):
    name = "threaded_boss"
    category = "hardware"
    complexity = 2

    def randomize_params(self):
        base_w = rand_len(20, 60)
        base_t = rand_thickness(3, 8)
        boss_d = float(snap(random.uniform(8, 16), 1))
        boss_h = float(snap(random.uniform(8, 20), 1))
        bore = float(random.choice([3.0, 4.0, 5.0]))
        return {"base_w": base_w, "base_t": base_t, "boss_d": boss_d, "boss_h": boss_h, "bore": bore}

    def generate_code(self, p):
        params = [
            ("base_w", p["base_w"], "mm - base plate side"),
            ("base_t", p["base_t"], "mm - base thickness"),
            ("boss_d", p["boss_d"], "mm - boss OD"),
            ("boss_h", p["boss_h"], "mm - boss height"),
            ("bore", p["bore"], "mm - pilot hole"),
        ]
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(base_w, base_w)",
            "extrude(amount=base_t)",
            "",
            "# Feature 2: Boss on top",
            "with BuildSketch(Plane.XY.offset(base_t)):",
            "    Circle(boss_d / 2)",
            "extrude(amount=boss_h)",
            "",
            "# Feature 3: Central pilot hole",
            "with BuildSketch(Plane.XY.offset(base_t + boss_h)):",
            "    Circle(bore / 2)",
            "extrude(amount=-(base_t + boss_h), mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Threaded boss on a {fmt_num(p['base_w'])}x{fmt_num(p['base_w'])}x{fmt_num(p['base_t'])}mm base, "
            f"{fmt_num(p['boss_d'])}mm OD boss {fmt_num(p['boss_h'])}mm tall with a {fmt_num(p['bore'])}mm pilot.",
            f"Need a tapped boss on a small mounting pad.",
            f"Design a threaded stud mount for attaching a sensor to a frame.",
        ]


class DowelBlock(CADTemplate):
    name = "dowel_block"
    category = "hardware"
    complexity = 2

    def randomize_params(self):
        l = rand_len(40, 100)
        w = rand_len(20, 50)
        h = rand_thickness(8, 20)
        dowel_d = float(random.choice([4.0, 5.0, 6.0, 8.0]))
        spacing = float(snap(l * 0.6, 1))
        return {"length": l, "width": w, "height": h, "dowel_d": dowel_d, "spacing": spacing}

    def generate_code(self, p):
        params = [
            ("length", p["length"], "mm"),
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("dowel_d", p["dowel_d"], "mm - dowel bore"),
            ("spacing", p["spacing"], "mm - between dowels"),
        ]
        body = [
            "# Feature 1: Rectangular block",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(length, width)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Two press-fit dowel holes",
            "with BuildSketch(Plane.XY.offset(height)):",
            "    with Locations((-spacing / 2, 0), (spacing / 2, 0)):",
            "        Circle(dowel_d / 2)",
            "extrude(amount=-height, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Dowel block {fmt_num(p['length'])}x{fmt_num(p['width'])}x{fmt_num(p['height'])}mm with two "
            f"{fmt_num(p['dowel_d'])}mm dowel holes on {fmt_num(p['spacing'])}mm centers.",
            f"Need a locator block with two dowel pin holes.",
            f"Design a jig block for press-fitting two alignment dowels.",
        ]


class CableClamp(CADTemplate):
    name = "cable_clamp"
    category = "hardware"
    complexity = 3

    def randomize_params(self):
        cable_d = float(random.choice([6.0, 8.0, 10.0, 12.0, 16.0]))
        body_w = float(snap(cable_d * 3, 1))
        body_h = float(snap(cable_d * 2, 1))
        body_l = rand_len(20, 50)
        bolt_d = rand_hole(3.0, 5.0)
        return {"cable_d": cable_d, "body_w": body_w, "body_h": body_h, "body_l": body_l, "bolt_d": bolt_d}

    def generate_code(self, p):
        params = [
            ("cable_d", p["cable_d"], "mm - cable diameter"),
            ("body_w", p["body_w"], "mm - across clamp"),
            ("body_h", p["body_h"], "mm - clamp height"),
            ("body_l", p["body_l"], "mm - clamp length"),
            ("bolt_d", p["bolt_d"], "mm - mounting bolt"),
        ]
        body = [
            "# Feature 1: Clamp body",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(body_w, body_l)",
            "extrude(amount=body_h)",
            "",
            "# Feature 2: Cable channel",
            "with BuildSketch(Plane.XY.offset(body_h)):",
            "    Circle(cable_d / 2)",
            "extrude(amount=-cable_d, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Mounting bolt holes on either side of cable",
            "with BuildSketch(Plane.XY.offset(body_h)):",
            "    with Locations((-(cable_d / 2 + bolt_d), 0), ((cable_d / 2 + bolt_d), 0)):",
            "        Circle(bolt_d / 2)",
            "extrude(amount=-body_h, mode=Mode.SUBTRACT)",
        ]
        return build_code(params, body)

    def generate_prompts(self, p):
        return [
            f"Cable clamp for {fmt_num(p['cable_d'])}mm cable, body {fmt_num(p['body_w'])}x{fmt_num(p['body_l'])}x"
            f"{fmt_num(p['body_h'])}mm with two {fmt_num(p['bolt_d'])}mm mounting bolts.",
            f"Need a P-clip-style cable clamp for a {fmt_num(p['cable_d'])}mm cable.",
            f"Design a block-style cable retainer with bolts on either side of the cable.",
        ]


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES: list[CADTemplate] = [
    MountingPlate(), CoverPlate(), SlottedPlate(), PerforatedPlate(), BasePlate(), CircularFlange(),
    LBracket(), ZBracket(), UBracket(), GussetBracket(), MotorMountNEMA17(), MotorMountNEMA23(),
    OpenBox(), LiddedBox(), ElectronicsEnclosure(), VentedBox(),
    Spacer(), SteppedShaft(), FlangeBushing(), PulleyBlank(),
    IBeamSection(), HingeLeaf(), LeverArm(), Clamp(), HandleBar(),
    FlatWasher(), Standoff(), ThreadedBoss(), DowelBlock(), CableClamp(),
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def sample_to_sharegpt(sample: TemplateSample, prompt: str, source: str = "template") -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": sample.code},
        ],
        "source": source,
        "template": sample.name,
        "category": sample.category,
        "complexity": sample.complexity,
        "params": sample.params,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--variants", type=int, default=100, help="variants per template")
    ap.add_argument("--seed-base", type=int, default=0)
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    by_category: dict[str, int] = {}
    by_complexity: dict[int, int] = {}
    total = 0
    previews: list[tuple[str, str]] = []

    with args.output.open("w", encoding="utf-8") as fout:
        for t_idx, tpl in enumerate(TEMPLATES):
            for i in range(args.variants):
                seed = args.seed_base + t_idx * 10_000 + i
                s = tpl.generate(seed)
                # pick one of 3 prompts based on seed
                rnd = random.Random(seed + 1)
                prompt = rnd.choice(s.prompts)
                record = sample_to_sharegpt(s, prompt)
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                total += 1
                by_category[s.category] = by_category.get(s.category, 0) + 1
                by_complexity[s.complexity] = by_complexity.get(s.complexity, 0) + 1
                if len(previews) < 3 and i == 0:
                    previews.append((prompt, s.code))

    print("=== Template generation stats ===")
    print(f"  templates : {len(TEMPLATES)}")
    print(f"  variants  : {args.variants}/template")
    print(f"  total     : {total}")
    print("  by category:")
    for k, v in sorted(by_category.items()):
        print(f"    {k:15s} {v}")
    print("  by complexity:")
    for k, v in sorted(by_complexity.items()):
        print(f"    {k}: {v}")
    print("\n--- previews ---")
    for p, c in previews:
        print(f"\nprompt: {p}")
        print("code (first 8 lines):")
        for line in c.splitlines()[:8]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
