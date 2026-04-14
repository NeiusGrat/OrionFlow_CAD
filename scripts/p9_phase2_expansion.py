# ============================================================
# Phase 2 Dataset Expansion — p9_phase2_expansion.py
# ============================================================
# Generates ~6000 Build123d-FTC training samples across 10
# mechanical categories + gear templates, with inline
# validation, augmentation, and reasoning injection.
#
# Usage:
#   python scripts/p9_phase2_expansion.py
#   python scripts/p9_phase2_expansion.py --workers 4
#   python scripts/p9_phase2_expansion.py --categories flanges gears
#   python scripts/p9_phase2_expansion.py --dry-run
# ============================================================

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_GEN = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)

SYSTEM_PROMPT_EDIT = (
    "You are OrionFlow, an AI mechanical design copilot. The user will show "
    "you existing Build123d code and request a modification. Generate the "
    "complete modified code preserving the Feature Tree Convention structure. "
    "Only change what the user requested."
)

HOLE_SIZES = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 8.0, 10.0, 12.0]

METRIC_CLEARANCE = {
    "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6,
    "M8": 9.0, "M10": 11.0, "M12": 13.5,
}

ISO_BOLT_DIMS = {
    "M6":  {"head_af": 10.0, "head_h": 4.0,  "shaft_d": 6.0,  "nut_af": 10.0, "nut_h": 5.0,  "washer_od": 12.5, "washer_t": 1.6},
    "M8":  {"head_af": 13.0, "head_h": 5.3,  "shaft_d": 8.0,  "nut_af": 13.0, "nut_h": 6.5,  "washer_od": 17.0, "washer_t": 1.6},
    "M10": {"head_af": 16.0, "head_h": 6.4,  "shaft_d": 10.0, "nut_af": 16.0, "nut_h": 8.0,  "washer_od": 21.0, "washer_t": 2.0},
    "M12": {"head_af": 18.0, "head_h": 7.5,  "shaft_d": 12.0, "nut_af": 18.0, "nut_h": 10.0, "washer_od": 24.0, "washer_t": 2.5},
}

OUTPUT_DIR = Path("data/phase2_expansion")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def snap(val: float, step: float) -> float:
    return round(val / step) * step

def rand_len(lo: float, hi: float, step: float = 5) -> float:
    return float(snap(random.uniform(lo, hi), step))

def rand_thickness(lo: int = 2, hi: int = 20) -> float:
    return float(random.randint(lo, hi))

def rand_hole(min_dia: float = 3.0, max_dia: float = 12.0) -> float:
    choices = [d for d in HOLE_SIZES if min_dia <= d <= max_dia]
    return float(random.choice(choices))

def fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"

def code_hash(code: str) -> str:
    return "sha256:" + hashlib.sha256(code.encode()).hexdigest()[:16]

def build_code(params, body_lines, filename="output.step"):
    out = ["from build123d import *", "", "# --- Parameters ---"]
    for name, val, comment in params:
        c = f"  # {comment}" if comment else ""
        out.append(f"{name} = {fmt(val)}{c}")
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
# Validation
# ---------------------------------------------------------------------------

_VAL_SUFFIX = '''
import json
try:
    shape = part.part
    vol = shape.volume
    valid = shape.is_valid
    bb = shape.bounding_box()
    dims = [round(bb.max.X - bb.min.X, 2), round(bb.max.Y - bb.min.Y, 2), round(bb.max.Z - bb.min.Z, 2)]
    n_faces = len(shape.faces())
    n_edges = len(shape.edges())
    n_verts = len(shape.vertices())
    result = {
        "passed": valid and vol > 0,
        "volume": round(vol, 4),
        "is_valid": valid,
        "watertight": valid,
        "faces": n_faces,
        "edges": n_edges,
        "vertices": n_verts,
        "bbox": dims,
    }
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({"passed": False, "error": str(e)[:200]}))
'''

def validate_code(code: str, timeout: int = 60) -> dict:
    """Execute build123d code in a subprocess via temp file."""
    # Strip export / result lines
    clean_lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("export_step(") or s.startswith("export_stl("):
            continue
        if s.startswith("result = part.part"):
            continue
        clean_lines.append(line)

    script_content = "\n".join(clean_lines) + "\n" + _VAL_SUFFIX

    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
            dir=str(Path.cwd()),
        )
        tmp.write(script_content)
        tmp.close()

        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(Path.cwd()),
        )
        if result.returncode == 0 and result.stdout.strip():
            # Take last line that looks like JSON
            for line in reversed(result.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    return json.loads(line)
        return {"passed": False, "error": (result.stderr or "no output")[:200]}
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "timeout"}
    except Exception as e:
        return {"passed": False, "error": str(e)[:200]}
    finally:
        if tmp:
            try: os.unlink(tmp.name)
            except: pass


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
    prompt: str
    sub_type: str = ""

class CADTemplate(ABC):
    name: str = ""
    category: str = ""
    complexity: int = 2
    sub_type: str = ""

    def generate(self, seed: int) -> TemplateSample:
        random.seed(seed)
        params = self.randomize_params()
        code = self.generate_code(params)
        prompts = self.generate_prompts(params)
        prompt = prompts[seed % len(prompts)]
        return TemplateSample(
            name=self.name, category=self.category,
            complexity=self.complexity, params=params,
            code=code, prompt=prompt, sub_type=self.sub_type,
        )

    @abstractmethod
    def randomize_params(self) -> dict: ...
    @abstractmethod
    def generate_code(self, p: dict) -> str: ...
    @abstractmethod
    def generate_prompts(self, p: dict) -> list[str]: ...


# ===========================================================================
# CATEGORY 1: FLANGES
# ===========================================================================

class BoltedFlange(CADTemplate):
    name = "bolted_flange"
    category = "flange"
    complexity = 3

    def randomize_params(self):
        od = rand_len(80, 200)
        bore = float(snap(random.uniform(od * 0.2, od * 0.45), 1))
        t = rand_thickness(6, 16)
        n = random.choice([4, 6, 8, 12])
        pcd = float(snap((od + bore) / 2, 1))
        bd = rand_hole(4.0, 10.0)
        return {"outer_dia": od, "bore_dia": bore, "thickness": t, "n_bolts": n, "pcd": pcd, "bolt_dia": bd}

    def generate_code(self, p):
        return build_code([
            ("outer_dia", p["outer_dia"], "mm - flange OD"),
            ("bore_dia", p["bore_dia"], "mm - central bore"),
            ("thickness", p["thickness"], "mm"),
            ("n_bolts", p["n_bolts"], "bolt count"),
            ("pcd", p["pcd"], "mm - bolt circle diameter"),
            ("bolt_dia", p["bolt_dia"], "mm - bolt clearance hole"),
        ], [
            "# Feature 1: Flange disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Bolt hole pattern",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(pcd / 2, int(n_bolts)):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Create a bolted flange with {fmt(p['outer_dia'])}mm OD, {fmt(p['bore_dia'])}mm bore, "
            f"{fmt(p['thickness'])}mm thick, {p['n_bolts']} bolt holes on {fmt(p['pcd'])}mm PCD.",
            f"I need a pipe flange with {p['n_bolts']} bolt holes around a center bore.",
            f"Design a circular flange plate for a DN{int(p['bore_dia'])} pipe connection.",
        ]


class HubFlange(CADTemplate):
    name = "hub_flange"
    category = "flange"
    complexity = 4

    def randomize_params(self):
        od = rand_len(80, 180)
        bore = float(snap(random.uniform(od * 0.15, od * 0.35), 1))
        t = rand_thickness(6, 14)
        hub_d = float(snap(bore * 2.2, 1))
        hub_h = rand_len(15, 40)
        n = random.choice([4, 6, 8])
        pcd = float(snap((od + hub_d) / 2, 1))
        bd = rand_hole(4.0, 8.0)
        cham = float(random.choice([0.5, 1.0, 1.5, 2.0]))
        return {"outer_dia": od, "bore_dia": bore, "thickness": t, "hub_dia": hub_d,
                "hub_height": hub_h, "n_bolts": n, "pcd": pcd, "bolt_dia": bd, "chamfer": cham}

    def generate_code(self, p):
        return build_code([
            ("outer_dia", p["outer_dia"], "mm - flange OD"),
            ("bore_dia", p["bore_dia"], "mm - shaft bore"),
            ("thickness", p["thickness"], "mm - flange plate thickness"),
            ("hub_dia", p["hub_dia"], "mm - hub OD"),
            ("hub_height", p["hub_height"], "mm - hub length"),
            ("n_bolts", p["n_bolts"], "bolt count"),
            ("pcd", p["pcd"], "mm - bolt circle diameter"),
            ("bolt_dia", p["bolt_dia"], "mm"),
            ("chamfer_size", p["chamfer"], "mm - hub end chamfer"),
        ], [
            "# Feature 1: Flange disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Hub boss",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    Circle(hub_dia / 2)",
            "extrude(amount=hub_height)",
            "",
            "# Feature 3: Shaft bore (through flange + hub)",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=thickness + hub_height, mode=Mode.SUBTRACT)",
            "",
            "# Feature 4: Bolt pattern",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(pcd / 2, int(n_bolts)):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 5: Hub end chamfer",
            "chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=chamfer_size)",
        ])

    def generate_prompts(self, p):
        return [
            f"Hub flange: {fmt(p['outer_dia'])}mm OD disc with a {fmt(p['hub_dia'])}mm hub extending "
            f"{fmt(p['hub_height'])}mm, {fmt(p['bore_dia'])}mm bore, {p['n_bolts']} bolts on {fmt(p['pcd'])}mm PCD, "
            f"{fmt(p['chamfer'])}mm chamfer on hub end.",
            f"Design a flanged coupling hub with bolt holes and a chamfered shaft bore.",
            f"I need a flange with an integral hub boss for a {fmt(p['bore_dia'])}mm shaft.",
        ]


class BlindFlange(CADTemplate):
    name = "blind_flange"
    category = "flange"
    complexity = 3

    def randomize_params(self):
        od = rand_len(60, 200)
        t = rand_thickness(8, 20)
        n = random.choice([4, 6, 8])
        pcd = float(snap(od * 0.7, 1))
        bd = rand_hole(4.0, 10.0)
        raised = float(random.choice([0, 2, 3]))
        rf_dia = float(snap(pcd * 0.75, 1)) if raised > 0 else 0
        return {"outer_dia": od, "thickness": t, "n_bolts": n, "pcd": pcd,
                "bolt_dia": bd, "raised_face_h": raised, "raised_face_dia": rf_dia}

    def generate_code(self, p):
        body = [
            "# Feature 1: Flange disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Bolt pattern",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(pcd / 2, int(n_bolts)):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        params = [
            ("outer_dia", p["outer_dia"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("n_bolts", p["n_bolts"], "bolt count"),
            ("pcd", p["pcd"], "mm - bolt circle"),
            ("bolt_dia", p["bolt_dia"], "mm"),
        ]
        if p["raised_face_h"] > 0:
            params.append(("raised_face_h", p["raised_face_h"], "mm - raised face height"))
            params.append(("raised_face_dia", p["raised_face_dia"], "mm - raised face diameter"))
            body.extend([
                "",
                "# Feature 3: Raised face",
                "with BuildSketch(Plane.XY.offset(thickness)):",
                "    Circle(raised_face_dia / 2)",
                "extrude(amount=raised_face_h)",
            ])
        return build_code(params, body)

    def generate_prompts(self, p):
        rf = f" with {fmt(p['raised_face_h'])}mm raised face" if p["raised_face_h"] > 0 else ""
        return [
            f"Blind flange {fmt(p['outer_dia'])}mm OD, {fmt(p['thickness'])}mm thick, "
            f"{p['n_bolts']} bolts on {fmt(p['pcd'])}mm PCD{rf}.",
            f"I need a blank flange to cap off a pipe — no center bore.",
            f"Design a blind flange plate for pressure testing a pipeline.",
        ]


# ===========================================================================
# CATEGORY 2: BRACKETS
# ===========================================================================

class SlottedLBracket(CADTemplate):
    name = "slotted_l_bracket"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        w = rand_len(40, 100)
        f1 = rand_len(30, 80)
        f2 = rand_len(30, 80)
        t = rand_thickness(3, 8)
        sw = rand_len(15, 40)
        sh = rand_hole(5.0, 8.0)
        return {"width": w, "flange1": f1, "flange2": f2, "thickness": t, "slot_w": sw, "slot_h": sh}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("flange1", p["flange1"], "mm - horizontal leg"),
            ("flange2", p["flange2"], "mm - vertical leg"),
            ("thickness", p["thickness"], "mm"),
            ("slot_w", p["slot_w"], "mm - slot length"),
            ("slot_h", p["slot_h"], "mm - slot width"),
        ], [
            "# Feature 1: Horizontal leg",
            "with BuildSketch(Plane.XY):",
            "    with Locations((flange1 / 2, 0)):",
            "        Rectangle(flange1, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Vertical leg",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, flange2 / 2)):",
            "        Rectangle(width, flange2)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Adjustment slot in horizontal leg",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((flange1 * 0.6, 0)):",
            "        SlotOverall(slot_w, slot_h)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"L-bracket with slotted hole: {fmt(p['width'])}mm wide, {fmt(p['flange1'])}mm horizontal, "
            f"{fmt(p['flange2'])}mm vertical, {fmt(p['thickness'])}mm thick, {fmt(p['slot_w'])}mm adjustment slot.",
            f"I need an L-bracket with a slot for adjustable mounting.",
            f"Design an angle bracket with a slot instead of a round hole for position adjustment.",
        ]


class HeavyUBracket(CADTemplate):
    name = "heavy_u_bracket"
    category = "bracket"
    complexity = 4

    def randomize_params(self):
        bw = rand_len(50, 120)
        sh = rand_len(40, 80)
        depth = rand_len(40, 80)
        t = rand_thickness(4, 10)
        d = rand_hole(5.0, 10.0)
        fil = float(random.choice([0, 2, 3, 4]))
        return {"base_width": bw, "side_height": sh, "depth": depth, "thickness": t, "hole_dia": d, "fillet_r": fil}

    def generate_code(self, p):
        body = [
            "# Feature 1: Base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(base_width + 2 * thickness, depth)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Left wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations((-(base_width / 2 + thickness / 2), 0)):",
            "        Rectangle(thickness, depth)",
            "extrude(amount=side_height)",
            "",
            "# Feature 3: Right wall",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with Locations(((base_width / 2 + thickness / 2), 0)):",
            "        Rectangle(thickness, depth)",
            "extrude(amount=side_height)",
            "",
            "# Feature 4: Mounting holes in base",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(base_width * 0.6, depth * 0.6, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ]
        params = [
            ("base_width", p["base_width"], "mm - inner width"),
            ("side_height", p["side_height"], "mm - wall height"),
            ("depth", p["depth"], "mm - along Y"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
        ]
        if p["fillet_r"] > 0:
            params.append(("fillet_r", p["fillet_r"], "mm - inner fillet"))
            body.extend([
                "",
                "# Feature 5: Inner fillets at base-wall junction",
                "fillet(part.edges().filter_by(Axis.Y).sort_by(Axis.Z)[0:2], radius=fillet_r)",
            ])
        return build_code(params, body)

    def generate_prompts(self, p):
        fil_txt = f", {fmt(p['fillet_r'])}mm inner fillets" if p["fillet_r"] > 0 else ""
        return [
            f"Heavy U-bracket: {fmt(p['base_width'])}mm inner width, {fmt(p['side_height'])}mm walls, "
            f"{fmt(p['depth'])}mm deep, {fmt(p['thickness'])}mm thick, {fmt(p['hole_dia'])}mm mounting holes{fil_txt}.",
            f"I need a sturdy U-channel bracket to cradle a motor or actuator.",
            f"Design a U-shaped bracket with bolt holes in the base plate.",
        ]


class WallBracket(CADTemplate):
    name = "wall_bracket"
    category = "bracket"
    complexity = 3

    def randomize_params(self):
        w = rand_len(30, 80)
        h = rand_len(40, 100)
        proj = rand_len(30, 80)
        t = rand_thickness(3, 8)
        d = rand_hole(4.0, 8.0)
        return {"width": w, "height": h, "projection": proj, "thickness": t, "hole_dia": d}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm - wall plate height"),
            ("projection", p["projection"], "mm - shelf depth"),
            ("thickness", p["thickness"], "mm"),
            ("hole_dia", p["hole_dia"], "mm"),
        ], [
            "# Feature 1: Wall plate (vertical)",
            "with BuildSketch(Plane.YZ):",
            "    with Locations((0, height / 2)):",
            "        Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Shelf (horizontal)",
            "with BuildSketch(Plane.XY):",
            "    with Locations((projection / 2 + thickness, 0)):",
            "        Rectangle(projection, width)",
            "extrude(amount=thickness)",
            "",
            "# Feature 3: Wall mounting holes",
            "with BuildSketch(Plane.YZ.offset(thickness)):",
            "    with GridLocations(width * 0.5, height * 0.6, 2, 2):",
            "        Circle(hole_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Wall-mount bracket: {fmt(p['width'])}mm wide, {fmt(p['height'])}mm tall back plate, "
            f"{fmt(p['projection'])}mm shelf, {fmt(p['thickness'])}mm thick, {fmt(p['hole_dia'])}mm holes.",
            f"I need a shelf bracket to screw into a wall.",
            f"Design a wall-mounted support bracket with a horizontal shelf.",
        ]


# ===========================================================================
# CATEGORY 3: SHAFTS
# ===========================================================================

class KeywayShaft(CADTemplate):
    name = "keyway_shaft"
    category = "shaft"
    complexity = 4

    def randomize_params(self):
        d = float(snap(random.uniform(12, 40), 1))
        l = rand_len(40, 120)
        kw = float(snap(d * 0.25, 0.5))
        kd = float(snap(d * 0.15, 0.5))
        kl = float(snap(l * 0.4, 1))
        cham = float(random.choice([0.5, 1.0, 1.5]))
        return {"shaft_dia": d, "shaft_length": l, "key_width": kw,
                "key_depth": kd, "key_length": kl, "chamfer": cham}

    def generate_code(self, p):
        return build_code([
            ("shaft_dia", p["shaft_dia"], "mm"),
            ("shaft_length", p["shaft_length"], "mm"),
            ("key_width", p["key_width"], "mm - keyway width"),
            ("key_depth", p["key_depth"], "mm - keyway depth"),
            ("key_length", p["key_length"], "mm - keyway length"),
            ("chamfer_size", p["chamfer"], "mm - end chamfer"),
        ], [
            "# Feature 1: Main shaft cylinder",
            "with BuildSketch(Plane.XY):",
            "    Circle(shaft_dia / 2)",
            "extrude(amount=shaft_length)",
            "",
            "# Feature 2: Keyway slot (rectangular cut along top)",
            "with BuildSketch(Plane.XY.offset(shaft_length / 2 - key_length / 2)):",
            "    with Locations((0, shaft_dia / 2 - key_depth / 2)):",
            "        Rectangle(key_width, key_depth)",
            "extrude(amount=key_length, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: End chamfers",
            "chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=chamfer_size)",
            "chamfer(part.faces().sort_by(Axis.Z)[0].edges(), length=chamfer_size)",
        ])

    def generate_prompts(self, p):
        return [
            f"Shaft {fmt(p['shaft_dia'])}mm diameter, {fmt(p['shaft_length'])}mm long with a "
            f"{fmt(p['key_width'])}x{fmt(p['key_depth'])}mm keyway, {fmt(p['key_length'])}mm long, "
            f"chamfered ends.",
            f"Design a keyed shaft for a gear or pulley coupling.",
            f"I need a shaft with a keyway cut for power transmission.",
        ]


class SteppedShaftV2(CADTemplate):
    name = "stepped_shaft_v2"
    category = "shaft"
    complexity = 3

    def randomize_params(self):
        d1 = float(snap(random.uniform(15, 40), 1))
        d2 = float(snap(d1 * 0.7, 1))
        d3 = float(snap(d2 * 0.7, 1))
        h1 = rand_len(10, 30)
        h2 = rand_len(15, 40)
        h3 = rand_len(10, 25)
        cham = float(random.choice([0.5, 1.0]))
        return {"d1": d1, "d2": d2, "d3": d3, "h1": h1, "h2": h2, "h3": h3, "chamfer": cham}

    def generate_code(self, p):
        return build_code([
            ("d1", p["d1"], "mm - shoulder diameter"),
            ("d2", p["d2"], "mm - bearing journal"),
            ("d3", p["d3"], "mm - shaft end"),
            ("h1", p["h1"], "mm - shoulder length"),
            ("h2", p["h2"], "mm - journal length"),
            ("h3", p["h3"], "mm - end length"),
            ("chamfer_size", p["chamfer"], "mm"),
        ], [
            "# Feature 1: Shoulder section",
            "with BuildSketch(Plane.XY):",
            "    Circle(d1 / 2)",
            "extrude(amount=h1)",
            "",
            "# Feature 2: Bearing journal",
            "with BuildSketch(Plane.XY.offset(h1)):",
            "    Circle(d2 / 2)",
            "extrude(amount=h2)",
            "",
            "# Feature 3: Shaft end",
            "with BuildSketch(Plane.XY.offset(h1 + h2)):",
            "    Circle(d3 / 2)",
            "extrude(amount=h3)",
            "",
            "# Feature 4: End chamfer",
            "chamfer(part.faces().sort_by(Axis.Z)[-1].edges(), length=chamfer_size)",
        ])

    def generate_prompts(self, p):
        total = p["h1"] + p["h2"] + p["h3"]
        return [
            f"Three-step shaft: {fmt(p['d1'])}mm shoulder, {fmt(p['d2'])}mm journal, "
            f"{fmt(p['d3'])}mm end. Lengths {fmt(p['h1'])}/{fmt(p['h2'])}/{fmt(p['h3'])}mm.",
            f"Design a stepped shaft about {fmt(total)}mm total length, decreasing diameter.",
            f"I need a shaft with bearing journal step-downs for press-fit assembly.",
        ]


class GroovedShaft(CADTemplate):
    name = "grooved_shaft"
    category = "shaft"
    complexity = 4

    def randomize_params(self):
        d = float(snap(random.uniform(15, 35), 1))
        l = rand_len(50, 100)
        gw = float(random.choice([1.5, 2.0, 2.5]))
        gd = float(snap(d * 0.08, 0.25))
        gpos = float(snap(l * 0.2, 1))
        return {"shaft_dia": d, "shaft_length": l, "groove_width": gw,
                "groove_depth": gd, "groove_position": gpos}

    def generate_code(self, p):
        return build_code([
            ("shaft_dia", p["shaft_dia"], "mm"),
            ("shaft_length", p["shaft_length"], "mm"),
            ("groove_width", p["groove_width"], "mm - snap ring groove width"),
            ("groove_depth", p["groove_depth"], "mm - groove depth"),
            ("groove_pos", p["groove_position"], "mm - distance from end"),
        ], [
            "# Feature 1: Main shaft",
            "with BuildSketch(Plane.XY):",
            "    Circle(shaft_dia / 2)",
            "extrude(amount=shaft_length)",
            "",
            "# Feature 2: Snap ring groove (annular cut)",
            "with BuildSketch(Plane.XY.offset(groove_pos)):",
            "    Circle(shaft_dia / 2)",
            "    Circle(shaft_dia / 2 - groove_depth, mode=Mode.SUBTRACT)",
            "extrude(amount=groove_width, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Shaft {fmt(p['shaft_dia'])}mm x {fmt(p['shaft_length'])}mm with a snap ring groove "
            f"({fmt(p['groove_width'])}mm wide, {fmt(p['groove_depth'])}mm deep) at {fmt(p['groove_position'])}mm from end.",
            f"I need a shaft with a retaining ring groove near one end.",
            f"Design a shaft with a circlip groove for axial retention.",
        ]


# ===========================================================================
# CATEGORY 4: BUSHINGS / HOUSINGS
# ===========================================================================

class PressFitBushing(CADTemplate):
    name = "press_fit_bushing"
    category = "bushing"
    complexity = 3

    def randomize_params(self):
        od = float(snap(random.uniform(12, 35), 0.5))
        nominal_bore = float(snap(random.uniform(od * 0.35, od * 0.6), 0.5))
        bore = nominal_bore - 0.025  # press fit interference
        h = rand_len(10, 40)
        flange = random.choice([True, False])
        fl_d = float(snap(od * 1.6, 1)) if flange else 0
        fl_h = float(random.choice([2, 3, 4])) if flange else 0
        return {"outer_dia": od, "bore_dia": bore, "nominal_bore": nominal_bore,
                "height": h, "has_flange": flange, "flange_dia": fl_d, "flange_h": fl_h}

    def generate_code(self, p):
        params = [
            ("outer_dia", p["outer_dia"], "mm - press-fit OD"),
            ("bore_dia", p["bore_dia"], f"mm - bore (nominal {fmt(p['nominal_bore'])}mm - 0.025 interference)"),
            ("height", p["height"], "mm"),
        ]
        body = [
            "# Feature 1: Bushing body",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Through bore (press-fit tolerance)",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ]
        if p["has_flange"]:
            params.append(("flange_dia", p["flange_dia"], "mm - flange OD"))
            params.append(("flange_h", p["flange_h"], "mm - flange thickness"))
            body = [
                "# Feature 1: Flange disc",
                "with BuildSketch(Plane.XY):",
                "    Circle(flange_dia / 2)",
                "extrude(amount=flange_h)",
                "",
                "# Feature 2: Bushing body",
                "with BuildSketch(Plane.XY.offset(flange_h)):",
                "    Circle(outer_dia / 2)",
                "extrude(amount=height)",
                "",
                "# Feature 3: Through bore",
                "with BuildSketch(Plane.XY):",
                "    Circle(bore_dia / 2)",
                "extrude(amount=flange_h + height, mode=Mode.SUBTRACT)",
            ]
        return build_code(params, body)

    def generate_prompts(self, p):
        flg = " with retention flange" if p["has_flange"] else ""
        return [
            f"Press-fit bushing: {fmt(p['outer_dia'])}mm OD, {fmt(p['bore_dia'])}mm bore "
            f"(0.025mm interference), {fmt(p['height'])}mm long{flg}.",
            f"Design a bushing with press-fit tolerance for a {fmt(p['nominal_bore'])}mm shaft.",
            f"I need a plain bearing bushing that presses into a housing bore.",
        ]


class SlidingFitBushing(CADTemplate):
    name = "sliding_fit_bushing"
    category = "bushing"
    complexity = 3

    def randomize_params(self):
        od = float(snap(random.uniform(12, 35), 0.5))
        nominal_bore = float(snap(random.uniform(od * 0.35, od * 0.6), 0.5))
        bore = nominal_bore + 0.025  # sliding fit clearance
        h = rand_len(10, 40)
        return {"outer_dia": od, "bore_dia": bore, "nominal_bore": nominal_bore, "height": h}

    def generate_code(self, p):
        return build_code([
            ("outer_dia", p["outer_dia"], "mm"),
            ("bore_dia", p["bore_dia"], f"mm - bore (nominal {fmt(p['nominal_bore'])}mm + 0.025 clearance)"),
            ("height", p["height"], "mm"),
        ], [
            "# Feature 1: Bushing body",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Sliding-fit bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Sliding-fit bushing: {fmt(p['outer_dia'])}mm OD, {fmt(p['bore_dia'])}mm bore "
            f"(0.025mm clearance), {fmt(p['height'])}mm long.",
            f"Design a free-running bushing for a {fmt(p['nominal_bore'])}mm shaft.",
            f"I need a guide bushing with sliding fit tolerance.",
        ]


class FlangedHousing(CADTemplate):
    name = "flanged_housing"
    category = "bushing"
    complexity = 4

    def randomize_params(self):
        od = rand_len(40, 80)
        bore = float(snap(od * 0.4, 1))
        h = rand_len(20, 50)
        fl_w = rand_len(od + 20, od + 60)
        fl_h_ = rand_len(od + 10, od + 40)
        fl_t = rand_thickness(4, 10)
        bd = rand_hole(4.0, 8.0)
        return {"housing_od": od, "bore_dia": bore, "housing_height": h,
                "flange_width": fl_w, "flange_height": fl_h_, "flange_thickness": fl_t, "bolt_dia": bd}

    def generate_code(self, p):
        return build_code([
            ("housing_od", p["housing_od"], "mm - cylinder OD"),
            ("bore_dia", p["bore_dia"], "mm - bearing bore"),
            ("housing_height", p["housing_height"], "mm"),
            ("flange_width", p["flange_width"], "mm"),
            ("flange_height", p["flange_height"], "mm"),
            ("flange_thickness", p["flange_thickness"], "mm"),
            ("bolt_dia", p["bolt_dia"], "mm"),
        ], [
            "# Feature 1: Flange base plate",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(flange_width, flange_height)",
            "extrude(amount=flange_thickness)",
            "",
            "# Feature 2: Cylindrical housing body",
            "with BuildSketch(Plane.XY.offset(flange_thickness)):",
            "    Circle(housing_od / 2)",
            "extrude(amount=housing_height)",
            "",
            "# Feature 3: Bearing bore (blind — leave 3mm base)",
            "with BuildSketch(Plane.XY.offset(flange_thickness + housing_height)):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=-(housing_height - 3), mode=Mode.SUBTRACT)",
            "",
            "# Feature 4: Mounting bolts (4 corners)",
            "with BuildSketch(Plane.XY.offset(flange_thickness)):",
            "    with GridLocations(flange_width - 20, flange_height - 20, 2, 2):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-flange_thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Flanged bearing housing: {fmt(p['housing_od'])}mm OD cylinder, {fmt(p['bore_dia'])}mm blind bore, "
            f"on a {fmt(p['flange_width'])}x{fmt(p['flange_height'])}mm base with 4 bolt holes.",
            f"Design a pillow-block style bearing housing with a mounting flange.",
            f"I need a housing to mount a bearing with bolt-down capability.",
        ]


# ===========================================================================
# CATEGORY 5: BOLTS / NUTS / WASHERS
# ===========================================================================

class HexBolt(CADTemplate):
    name = "hex_bolt"
    category = "fastener"
    complexity = 3

    def randomize_params(self):
        size = random.choice(["M6", "M8", "M10", "M12"])
        dims = ISO_BOLT_DIMS[size]
        grip = float(random.choice([15, 20, 25, 30, 40, 50]))
        return {"size": size, "head_af": dims["head_af"], "head_h": dims["head_h"],
                "shaft_d": dims["shaft_d"], "grip_length": grip}

    def generate_code(self, p):
        return build_code([
            ("head_af", p["head_af"], f"mm - {p['size']} hex across-flats"),
            ("head_h", p["head_h"], "mm - head height"),
            ("shaft_dia", p["shaft_d"], "mm - shank diameter"),
            ("grip_length", p["grip_length"], "mm - shank length"),
        ], [
            "# Feature 1: Hex head",
            "with BuildSketch(Plane.XY):",
            "    RegularPolygon(head_af / 2, side_count=6)",
            "extrude(amount=head_h)",
            "",
            "# Feature 2: Cylindrical shank",
            "with BuildSketch(Plane.XY.offset(-grip_length)):",
            "    Circle(shaft_dia / 2)",
            "extrude(amount=grip_length)",
        ], f"{p['size'].lower()}_bolt.step")

    def generate_prompts(self, p):
        return [
            f"{p['size']} hex bolt, {fmt(p['grip_length'])}mm grip length.",
            f"Create a {p['size']} hex head bolt with a {fmt(p['grip_length'])}mm shank.",
            f"I need a standard {p['size']} hex bolt model.",
        ]


class HexNut(CADTemplate):
    name = "hex_nut"
    category = "fastener"
    complexity = 2

    def randomize_params(self):
        size = random.choice(["M6", "M8", "M10", "M12"])
        dims = ISO_BOLT_DIMS[size]
        return {"size": size, "nut_af": dims["nut_af"], "nut_h": dims["nut_h"], "bore_d": dims["shaft_d"]}

    def generate_code(self, p):
        return build_code([
            ("nut_af", p["nut_af"], f"mm - {p['size']} across-flats"),
            ("nut_h", p["nut_h"], "mm - nut height"),
            ("bore_dia", p["bore_d"], "mm - thread bore"),
        ], [
            "# Feature 1: Hex body",
            "with BuildSketch(Plane.XY):",
            "    RegularPolygon(nut_af / 2, side_count=6)",
            "extrude(amount=nut_h)",
            "",
            "# Feature 2: Thread bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=nut_h, mode=Mode.SUBTRACT)",
        ], f"{p['size'].lower()}_nut.step")

    def generate_prompts(self, p):
        return [
            f"Standard {p['size']} hex nut.",
            f"Create a hex nut for an {p['size']} bolt.",
            f"I need an {p['size']} nut model with the correct across-flats dimension.",
        ]


class FlatWasher(CADTemplate):
    name = "flat_washer"
    category = "fastener"
    complexity = 2

    def randomize_params(self):
        size = random.choice(["M6", "M8", "M10", "M12"])
        dims = ISO_BOLT_DIMS[size]
        return {"size": size, "washer_od": dims["washer_od"],
                "washer_t": dims["washer_t"], "bore_d": dims["shaft_d"] + 0.5}

    def generate_code(self, p):
        return build_code([
            ("washer_od", p["washer_od"], f"mm - {p['size']} washer OD"),
            ("washer_t", p["washer_t"], "mm - thickness"),
            ("bore_dia", p["bore_d"], "mm - clearance hole"),
        ], [
            "# Feature 1: Washer disc",
            "with BuildSketch(Plane.XY):",
            "    Circle(washer_od / 2)",
            "extrude(amount=washer_t)",
            "",
            "# Feature 2: Center hole",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=washer_t, mode=Mode.SUBTRACT)",
        ], f"{p['size'].lower()}_washer.step")

    def generate_prompts(self, p):
        return [
            f"Standard flat washer for {p['size']}: {fmt(p['washer_od'])}mm OD, {fmt(p['washer_t'])}mm thick.",
            f"Create a flat washer for an {p['size']} bolt.",
            f"I need a plain washer model for {p['size']} fasteners.",
        ]


# ===========================================================================
# CATEGORY 6: ENCLOSURES
# ===========================================================================

class ShellEnclosure(CADTemplate):
    name = "shell_enclosure"
    category = "enclosure"
    complexity = 4

    def randomize_params(self):
        w = rand_len(50, 140)
        d = rand_len(40, 100)
        h = rand_len(25, 60)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        return {"width": w, "depth": d, "height": h, "wall": wall}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm - wall thickness"),
        ], [
            "# Feature 1: Solid block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Shell out (remove top face)",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
        ])

    def generate_prompts(self, p):
        return [
            f"Open-top enclosure {fmt(p['width'])}x{fmt(p['depth'])}x{fmt(p['height'])}mm, "
            f"{fmt(p['wall'])}mm walls, hollowed using shell operation.",
            f"I need a project box with an open top for an electronics board.",
            f"Design a hollow enclosure using shell() to create uniform wall thickness.",
        ]


class BossEnclosure(CADTemplate):
    name = "boss_enclosure"
    category = "enclosure"
    complexity = 5

    def randomize_params(self):
        w = rand_len(60, 140)
        d = rand_len(50, 110)
        h = rand_len(25, 50)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        boss_d = float(random.choice([6.0, 8.0]))
        boss_hole = float(random.choice([2.5, 3.0]))
        boss_h = float(snap(h * 0.6, 1))
        return {"width": w, "depth": d, "height": h, "wall": wall,
                "boss_d": boss_d, "boss_hole": boss_hole, "boss_h": boss_h}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm"),
            ("boss_d", p["boss_d"], "mm - PCB boss OD"),
            ("boss_hole", p["boss_hole"], "mm - screw pilot"),
            ("boss_h", p["boss_h"], "mm - boss height"),
        ], [
            "# Feature 1: Solid block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Shell",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
            "",
            "# Feature 3: PCB mounting bosses (4 corners)",
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
        ])

    def generate_prompts(self, p):
        return [
            f"Electronics enclosure {fmt(p['width'])}x{fmt(p['depth'])}x{fmt(p['height'])}mm with "
            f"{fmt(p['wall'])}mm walls, shelled, 4 PCB mounting bosses with pilot holes.",
            f"Design a project enclosure with screw bosses for mounting a circuit board.",
            f"I need a shelled box with standoff bosses inside for a PCB.",
        ]


class RibbedEnclosure(CADTemplate):
    name = "ribbed_enclosure"
    category = "enclosure"
    complexity = 5

    def randomize_params(self):
        w = rand_len(60, 120)
        d = rand_len(50, 100)
        h = rand_len(25, 50)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        rib_t = float(random.choice([1.5, 2.0]))
        rib_h = float(snap(h * 0.5, 1))
        n_ribs = random.choice([2, 3])
        return {"width": w, "depth": d, "height": h, "wall": wall,
                "rib_t": rib_t, "rib_h": rib_h, "n_ribs": n_ribs}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("depth", p["depth"], "mm"),
            ("height", p["height"], "mm"),
            ("wall", p["wall"], "mm"),
            ("rib_t", p["rib_t"], "mm - rib thickness"),
            ("rib_h", p["rib_h"], "mm - rib height"),
            ("n_ribs", p["n_ribs"], "number of internal ribs"),
        ], [
            "# Feature 1: Solid block",
            "Box(width, depth, height)",
            "",
            "# Feature 2: Shell open top",
            "top = part.faces().sort_by(Axis.Z)[-1]",
            "offset(amount=-wall, openings=top)",
            "",
            "# Feature 3: Internal stiffening ribs",
            "with BuildSketch(Plane.XY.offset(wall)):",
            "    with Locations(*[(0, (i - (n_ribs - 1) / 2) * depth / (n_ribs + 1)) for i in range(int(n_ribs))]):",
            "        Rectangle(width - 2 * wall - 1, rib_t)",
            "extrude(amount=rib_h)",
        ])

    def generate_prompts(self, p):
        return [
            f"Enclosure {fmt(p['width'])}x{fmt(p['depth'])}x{fmt(p['height'])}mm with {fmt(p['wall'])}mm walls, "
            f"shelled, {p['n_ribs']} internal stiffening ribs.",
            f"Design a sturdy enclosure with internal ribs for rigidity.",
            f"I need a shelled box with reinforcement ribs running across the inside.",
        ]


# ===========================================================================
# CATEGORY 7: STANDOFFS
# ===========================================================================

class RoundStandoff(CADTemplate):
    name = "round_standoff"
    category = "standoff"
    complexity = 2

    def randomize_params(self):
        od = float(snap(random.uniform(6, 16), 0.5))
        bore = float(snap(random.uniform(2.5, 4.5), 0.5))
        h = float(snap(random.uniform(5, 25), 1))
        return {"outer_dia": od, "bore_dia": bore, "height": h}

    def generate_code(self, p):
        return build_code([
            ("outer_dia", p["outer_dia"], "mm"),
            ("bore_dia", p["bore_dia"], "mm - screw hole"),
            ("height", p["height"], "mm"),
        ], [
            "# Feature 1: Outer cylinder",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Screw bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Round standoff: {fmt(p['outer_dia'])}mm OD, {fmt(p['bore_dia'])}mm bore, {fmt(p['height'])}mm tall.",
            f"I need a simple cylindrical PCB standoff.",
            f"Design a round spacer with a screw hole through the center.",
        ]


class HexStandoff(CADTemplate):
    name = "hex_standoff"
    category = "standoff"
    complexity = 2

    def randomize_params(self):
        af = float(snap(random.uniform(5, 12), 0.5))
        bore = float(snap(random.uniform(2.5, 4.5), 0.5))
        h = float(snap(random.uniform(5, 25), 1))
        return {"across_flats": af, "bore_dia": bore, "height": h}

    def generate_code(self, p):
        return build_code([
            ("across_flats", p["across_flats"], "mm - hex AF"),
            ("bore_dia", p["bore_dia"], "mm"),
            ("height", p["height"], "mm"),
        ], [
            "# Feature 1: Hex body",
            "with BuildSketch(Plane.XY):",
            "    RegularPolygon(across_flats / 2, side_count=6)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Through bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Hex standoff: {fmt(p['across_flats'])}mm AF, {fmt(p['bore_dia'])}mm bore, {fmt(p['height'])}mm tall.",
            f"I need a hexagonal standoff for PCB mounting.",
            f"Design a hex spacer that can be tightened with a wrench.",
        ]


class SquareStandoff(CADTemplate):
    name = "square_standoff"
    category = "standoff"
    complexity = 2

    def randomize_params(self):
        side = float(snap(random.uniform(6, 14), 0.5))
        bore = float(snap(random.uniform(2.5, 4.5), 0.5))
        h = float(snap(random.uniform(5, 25), 1))
        return {"side_length": side, "bore_dia": bore, "height": h}

    def generate_code(self, p):
        return build_code([
            ("side_length", p["side_length"], "mm - square side"),
            ("bore_dia", p["bore_dia"], "mm"),
            ("height", p["height"], "mm"),
        ], [
            "# Feature 1: Square body",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(side_length, side_length)",
            "extrude(amount=height)",
            "",
            "# Feature 2: Through bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=height, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Square standoff: {fmt(p['side_length'])}mm side, {fmt(p['bore_dia'])}mm bore, {fmt(p['height'])}mm tall.",
            f"Design a square cross-section standoff for tight-space mounting.",
            f"I need a square-body PCB spacer.",
        ]


# ===========================================================================
# CATEGORY 8: GASKETS
# ===========================================================================

class RoundGasket(CADTemplate):
    name = "round_gasket"
    category = "gasket"
    complexity = 2

    def randomize_params(self):
        od = rand_len(60, 180)
        id_ = float(snap(od * random.uniform(0.3, 0.55), 1))
        t = float(random.choice([1.0, 1.5, 2.0, 3.0]))
        n = random.choice([4, 6, 8])
        pcd = float(snap((od + id_) / 2, 1))
        bd = rand_hole(4.0, 8.0)
        return {"outer_dia": od, "inner_dia": id_, "thickness": t, "n_bolts": n, "pcd": pcd, "bolt_dia": bd}

    def generate_code(self, p):
        return build_code([
            ("outer_dia", p["outer_dia"], "mm"),
            ("inner_dia", p["inner_dia"], "mm - center opening"),
            ("thickness", p["thickness"], "mm - gasket material"),
            ("n_bolts", p["n_bolts"], "bolt holes"),
            ("pcd", p["pcd"], "mm - bolt circle"),
            ("bolt_dia", p["bolt_dia"], "mm"),
        ], [
            "# Feature 1: Gasket ring",
            "with BuildSketch(Plane.XY):",
            "    Circle(outer_dia / 2)",
            "    Circle(inner_dia / 2, mode=Mode.SUBTRACT)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Bolt holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with PolarLocations(pcd / 2, int(n_bolts)):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Round gasket: {fmt(p['outer_dia'])}mm OD, {fmt(p['inner_dia'])}mm ID, "
            f"{fmt(p['thickness'])}mm thick, {p['n_bolts']} bolt holes on {fmt(p['pcd'])}mm PCD.",
            f"Design a flange gasket with bolt holes matching a {p['n_bolts']}-bolt pattern.",
            f"I need a ring gasket for a pipe flange connection.",
        ]


class RectGasket(CADTemplate):
    name = "rect_gasket"
    category = "gasket"
    complexity = 3

    def randomize_params(self):
        w = rand_len(60, 160)
        h = rand_len(50, 140)
        t = float(random.choice([1.0, 1.5, 2.0, 3.0]))
        cutout_w = float(snap(w * random.uniform(0.4, 0.65), 1))
        cutout_h = float(snap(h * random.uniform(0.4, 0.65), 1))
        bd = rand_hole(4.0, 6.0)
        margin = float(snap(random.uniform(8, 15), 1))
        return {"width": w, "height": h, "thickness": t, "cutout_w": cutout_w,
                "cutout_h": cutout_h, "bolt_dia": bd, "margin": margin}

    def generate_code(self, p):
        return build_code([
            ("width", p["width"], "mm"),
            ("height", p["height"], "mm"),
            ("thickness", p["thickness"], "mm"),
            ("cutout_w", p["cutout_w"], "mm - opening width"),
            ("cutout_h", p["cutout_h"], "mm - opening height"),
            ("bolt_dia", p["bolt_dia"], "mm"),
            ("margin", p["margin"], "mm - bolt inset from edge"),
        ], [
            "# Feature 1: Gasket body",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(width, height)",
            "extrude(amount=thickness)",
            "",
            "# Feature 2: Central opening",
            "with BuildSketch(Plane.XY):",
            "    Rectangle(cutout_w, cutout_h)",
            "extrude(amount=thickness, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Corner bolt holes",
            "with BuildSketch(Plane.XY.offset(thickness)):",
            "    with GridLocations(width - 2 * margin, height - 2 * margin, 2, 2):",
            "        Circle(bolt_dia / 2)",
            "extrude(amount=-thickness, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Rectangular gasket: {fmt(p['width'])}x{fmt(p['height'])}x{fmt(p['thickness'])}mm with a "
            f"{fmt(p['cutout_w'])}x{fmt(p['cutout_h'])}mm center opening and 4 bolt holes.",
            f"Design a flat gasket for a rectangular manifold cover.",
            f"I need a gasket with a window cutout and corner bolt holes.",
        ]


# ===========================================================================
# CATEGORY 9: PIPE FITTINGS (simplified — no sweep, use boolean)
# ===========================================================================

class PipeReducer(CADTemplate):
    name = "pipe_reducer"
    category = "pipe_fitting"
    complexity = 3

    def randomize_params(self):
        d1 = rand_len(25, 60)
        d2 = float(snap(d1 * random.uniform(0.5, 0.75), 1))
        wall = float(random.choice([2.0, 2.5, 3.0]))
        h1 = rand_len(15, 30)
        h2 = rand_len(15, 30)
        return {"large_dia": d1, "small_dia": d2, "wall": wall, "large_h": h1, "small_h": h2}

    def generate_code(self, p):
        return build_code([
            ("large_od", p["large_dia"], "mm - large end OD"),
            ("small_od", p["small_dia"], "mm - small end OD"),
            ("wall", p["wall"], "mm - pipe wall thickness"),
            ("large_h", p["large_h"], "mm - large end length"),
            ("small_h", p["small_h"], "mm - small end length"),
        ], [
            "# Feature 1: Large end tube",
            "with BuildSketch(Plane.XY):",
            "    Circle(large_od / 2)",
            "extrude(amount=large_h)",
            "",
            "# Feature 2: Bore large end",
            "with BuildSketch(Plane.XY):",
            "    Circle(large_od / 2 - wall)",
            "extrude(amount=large_h, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Small end tube",
            "with BuildSketch(Plane.XY.offset(large_h)):",
            "    Circle(small_od / 2)",
            "extrude(amount=small_h)",
            "",
            "# Feature 4: Bore small end",
            "with BuildSketch(Plane.XY.offset(large_h)):",
            "    Circle(small_od / 2 - wall)",
            "extrude(amount=small_h, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Pipe reducer: {fmt(p['large_dia'])}mm to {fmt(p['small_dia'])}mm, {fmt(p['wall'])}mm wall.",
            f"Design a concentric reducer for joining two pipe sizes.",
            f"I need a reducing coupling from DN{int(p['large_dia'])} to DN{int(p['small_dia'])}.",
        ]


class PipeTee(CADTemplate):
    name = "pipe_tee"
    category = "pipe_fitting"
    complexity = 4

    def randomize_params(self):
        d = rand_len(20, 50)
        wall = float(random.choice([2.0, 2.5, 3.0]))
        h = rand_len(30, 60)
        branch_h = rand_len(15, 35)
        return {"pipe_od": d, "wall": wall, "run_height": h, "branch_height": branch_h}

    def generate_code(self, p):
        return build_code([
            ("pipe_od", p["pipe_od"], "mm"),
            ("wall", p["wall"], "mm"),
            ("run_height", p["run_height"], "mm - main run length"),
            ("branch_height", p["branch_height"], "mm - branch length"),
        ], [
            "# Feature 1: Main run tube (outer)",
            "with BuildSketch(Plane.XY):",
            "    Circle(pipe_od / 2)",
            "extrude(amount=run_height)",
            "",
            "# Feature 2: Branch tube (outer) — perpendicular at midpoint",
            "with BuildSketch(Plane.XZ.offset(-pipe_od / 2)):",
            "    with Locations((0, run_height / 2)):",
            "        Circle(pipe_od / 2)",
            "extrude(amount=branch_height)",
            "",
            "# Feature 3: Bore main run",
            "with BuildSketch(Plane.XY):",
            "    Circle(pipe_od / 2 - wall)",
            "extrude(amount=run_height, mode=Mode.SUBTRACT)",
            "",
            "# Feature 4: Bore branch",
            "with BuildSketch(Plane.XZ.offset(-pipe_od / 2)):",
            "    with Locations((0, run_height / 2)):",
            "        Circle(pipe_od / 2 - wall)",
            "extrude(amount=branch_height, mode=Mode.SUBTRACT)",
        ])

    def generate_prompts(self, p):
        return [
            f"Pipe tee: {fmt(p['pipe_od'])}mm OD, {fmt(p['wall'])}mm wall, {fmt(p['run_height'])}mm run, "
            f"{fmt(p['branch_height'])}mm branch.",
            f"Design a tee fitting where a branch pipe meets a main run at 90 degrees.",
            f"I need a T-junction pipe fitting for plumbing or pneumatics.",
        ]


# ===========================================================================
# CATEGORY 10: GEARS (inspired by py_gearworks — pure build123d only)
# ===========================================================================

class SpurGearBlank(CADTemplate):
    name = "spur_gear"
    category = "gear"
    sub_type = "spur_single"
    complexity = 4

    def randomize_params(self):
        m = float(random.choice([1.0, 1.5, 2.0, 2.5, 3.0]))
        z = random.choice([12, 14, 16, 18, 20, 24, 28, 32])
        h = float(snap(random.uniform(6, 20), 1))
        pa = 20.0  # pressure angle
        bore = float(snap(random.uniform(4, 12), 0.5))
        pitch_r = m * z / 2
        addendum_r = pitch_r + m
        dedendum_r = pitch_r - 1.25 * m
        tooth_gap_r = m * 0.45
        return {"module": m, "teeth": z, "height": h, "pressure_angle": pa,
                "bore_dia": bore, "pitch_radius": pitch_r, "addendum_radius": addendum_r,
                "dedendum_radius": dedendum_r, "tooth_gap_radius": tooth_gap_r}

    def generate_code(self, p):
        return build_code([
            ("module_m", p["module"], "mm - gear module"),
            ("num_teeth", p["teeth"], "tooth count"),
            ("gear_height", p["height"], "mm"),
            ("pressure_angle", p["pressure_angle"], "degrees"),
            ("bore_dia", p["bore_dia"], "mm - shaft bore"),
            ("addendum_r", p["addendum_radius"], "mm - tip circle radius"),
            ("dedendum_r", p["dedendum_radius"], "mm - root circle radius"),
            ("pitch_r", p["pitch_radius"], "mm - pitch circle radius"),
            ("tooth_gap_r", p["tooth_gap_radius"], "mm - gap approximation radius"),
        ], [
            "# Feature 1: Gear blank at addendum diameter",
            "with BuildSketch(Plane.XY):",
            "    Circle(addendum_r)",
            "extrude(amount=gear_height)",
            "",
            "# Feature 2: Cut tooth gaps (circular approximation at pitch circle)",
            "with BuildSketch(Plane.XY):",
            "    with PolarLocations(pitch_r, int(num_teeth)):",
            "        Circle(tooth_gap_r)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Shaft bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
        ], "spur_gear.step")

    def generate_prompts(self, p):
        return [
            f"Spur gear: module {fmt(p['module'])}mm, {p['teeth']} teeth, {fmt(p['height'])}mm face width, "
            f"{fmt(p['pressure_angle'])}deg pressure angle, {fmt(p['bore_dia'])}mm bore.",
            f"Design a {p['teeth']}-tooth spur gear with module {fmt(p['module'])} and a keyable bore.",
            f"I need a spur gear for a simple gear train, module {fmt(p['module'])}, {p['teeth']} teeth.",
        ]


class HelicalGearBlank(CADTemplate):
    name = "helical_gear"
    category = "gear"
    sub_type = "helical_single"
    complexity = 5

    def randomize_params(self):
        m = float(random.choice([1.5, 2.0, 2.5, 3.0]))
        z = random.choice([13, 16, 20, 24, 31])
        h = float(snap(random.uniform(10, 25), 1))
        helix = float(random.choice([10, 15, 20, 25]))
        bore = float(snap(random.uniform(5, 12), 0.5))
        pitch_r = m * z / 2
        addendum_r = pitch_r + m
        tooth_gap_r = m * 0.45
        return {"module": m, "teeth": z, "height": h, "helix_angle": helix,
                "bore_dia": bore, "pitch_radius": pitch_r, "addendum_radius": addendum_r,
                "tooth_gap_radius": tooth_gap_r}

    def generate_code(self, p):
        # Twist degrees = helix_angle * height / (pitch_radius * pi) approximately
        twist_approx = p["helix_angle"] * p["height"] / (p["pitch_radius"] * math.pi)
        return build_code([
            ("module_m", p["module"], "mm - gear module"),
            ("num_teeth", p["teeth"], "tooth count"),
            ("gear_height", p["height"], "mm - face width"),
            ("helix_angle", p["helix_angle"], "degrees"),
            ("bore_dia", p["bore_dia"], "mm - shaft bore"),
            ("addendum_r", p["addendum_radius"], "mm - tip radius"),
            ("pitch_r", p["pitch_radius"], "mm - pitch radius"),
            ("tooth_gap_r", p["tooth_gap_radius"], "mm - gap radius"),
            ("twist_deg", round(twist_approx, 2), "degrees - extrude twist"),
        ], [
            "# Feature 1: Helical gear blank",
            "with BuildSketch(Plane.XY):",
            "    Circle(addendum_r)",
            "extrude(amount=gear_height)",
            "",
            "# Feature 2: Cut tooth gaps with twist (helical approximation)",
            "with BuildSketch(Plane.XY):",
            "    with PolarLocations(pitch_r, int(num_teeth)):",
            "        Circle(tooth_gap_r)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Shaft bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
        ], "helical_gear.step")

    def generate_prompts(self, p):
        return [
            f"Helical gear: module {fmt(p['module'])}mm, {p['teeth']} teeth, {fmt(p['height'])}mm face width, "
            f"{fmt(p['helix_angle'])}deg helix angle, {fmt(p['bore_dia'])}mm bore.",
            f"Design a helical gear with {p['teeth']} teeth and {fmt(p['helix_angle'])} degree helix.",
            f"I need a helical gear for a quiet-running drive, module {fmt(p['module'])}.",
        ]


class BevelGearBlank(CADTemplate):
    name = "bevel_gear"
    category = "gear"
    sub_type = "bevel_single"
    complexity = 5

    def randomize_params(self):
        m = float(random.choice([2.0, 2.5, 3.0]))
        z = random.choice([16, 20, 24])
        h = float(snap(random.uniform(10, 20), 1))
        bore = float(snap(random.uniform(5, 10), 0.5))
        pitch_r = m * z / 2
        addendum_r = pitch_r + m
        tooth_gap_r = m * 0.45
        return {"module": m, "teeth": z, "height": h, "bore_dia": bore,
                "pitch_radius": pitch_r, "addendum_radius": addendum_r,
                "tooth_gap_radius": tooth_gap_r}

    def generate_code(self, p):
        return build_code([
            ("module_m", p["module"], "mm - gear module"),
            ("num_teeth", p["teeth"], "tooth count"),
            ("gear_height", p["height"], "mm - face width"),
            ("bore_dia", p["bore_dia"], "mm - shaft bore"),
            ("addendum_r", p["addendum_radius"], "mm"),
            ("pitch_r", p["pitch_radius"], "mm"),
            ("tooth_gap_r", p["tooth_gap_radius"], "mm"),
        ], [
            "# Feature 1: Gear cone (frustum approximation)",
            "with BuildSketch(Plane.XY):",
            "    Circle(addendum_r)",
            "extrude(amount=gear_height, taper=10)",
            "",
            "# Feature 2: Tooth gap cuts",
            "with BuildSketch(Plane.XY):",
            "    with PolarLocations(pitch_r, int(num_teeth)):",
            "        Circle(tooth_gap_r)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
            "",
            "# Feature 3: Shaft bore",
            "with BuildSketch(Plane.XY):",
            "    Circle(bore_dia / 2)",
            "extrude(amount=gear_height, mode=Mode.SUBTRACT)",
        ], "bevel_gear.step")

    def generate_prompts(self, p):
        return [
            f"Bevel gear: module {fmt(p['module'])}mm, {p['teeth']} teeth, {fmt(p['height'])}mm face width, "
            f"{fmt(p['bore_dia'])}mm bore, 10deg cone angle.",
            f"Design a straight bevel gear for a right-angle drive.",
            f"I need a bevel gear with {p['teeth']} teeth, module {fmt(p['module'])}.",
        ]


# ===========================================================================
# Template Registry
# ===========================================================================

ALL_TEMPLATES: dict[str, list[CADTemplate]] = {
    "flanges":      [BoltedFlange(), HubFlange(), BlindFlange()],
    "brackets":     [SlottedLBracket(), HeavyUBracket(), WallBracket()],
    "shafts":       [KeywayShaft(), SteppedShaftV2(), GroovedShaft()],
    "bushings":     [PressFitBushing(), SlidingFitBushing(), FlangedHousing()],
    "fasteners":    [HexBolt(), HexNut(), FlatWasher()],
    "enclosures":   [ShellEnclosure(), BossEnclosure(), RibbedEnclosure()],
    "standoffs":    [RoundStandoff(), HexStandoff(), SquareStandoff()],
    "gaskets":      [RoundGasket(), RectGasket()],
    "pipe_fittings": [PipeReducer(), PipeTee()],
    "gears":        [SpurGearBlank(), HelicalGearBlank(), BevelGearBlank()],
}

# Complexity budget per category: 40 easy + 40 medium + 20 hard = 100 base
COMPLEXITY_BUDGET = {2: 20, 3: 40, 4: 30, 5: 10}


# ===========================================================================
# Reasoning Layer
# ===========================================================================

REASONING_TEMPLATES = [
    "<think>\n1. Start with {shape_desc}\n2. {feature_2}\n3. {feature_3}\n4. Add {finishing} for manufacturing\n</think>\n\n",
    "<think>\nDesign approach:\n- Base geometry: {shape_desc}\n- Key feature: {feature_2}\n- Secondary: {feature_3}\n- Finish: {finishing}\n</think>\n\n",
]

def generate_reasoning_prefix(sample: TemplateSample) -> str:
    """Generate a reasoning trace for complexity 4-5 samples."""
    if sample.complexity < 4:
        return ""

    shape_map = {
        "flange": "circular disc at outer diameter",
        "bracket": "L/U shaped structural profile",
        "shaft": "cylindrical rod as base",
        "bushing": "hollow cylinder with tolerance bore",
        "fastener": "hex polygon head + cylindrical shank",
        "enclosure": "solid box then shell to hollow",
        "standoff": "small prismatic body with bore",
        "gasket": "flat ring profile with bolt holes",
        "pipe_fitting": "concentric cylinders with wall thickness",
        "gear": "gear blank at addendum diameter with tooth gaps",
    }

    feature_descs = [
        "Add mounting holes / bolt pattern",
        "Cut central bore or pocket",
        "Add reinforcement ribs or bosses",
        "Apply fillets/chamfers for deburring",
        "Create keyway or slot feature",
        "Shell for uniform wall thickness",
    ]

    finishing = random.choice(["chamfers on edges", "fillets at intersections",
                               "deburring chamfers", "surface finish considerations"])

    tmpl = random.choice(REASONING_TEMPLATES)
    return tmpl.format(
        shape_desc=shape_map.get(sample.category, "base solid"),
        feature_2=random.choice(feature_descs),
        feature_3=random.choice(feature_descs),
        finishing=finishing,
    )


# ===========================================================================
# Worker function (must be top-level for multiprocessing)
# ===========================================================================

def _generate_one(args: tuple) -> Optional[dict]:
    """Generate and validate a single sample. Returns record dict or None."""
    template_cls_name, category, seed, add_reasoning = args

    # Re-instantiate the template class
    for templates in ALL_TEMPLATES.values():
        for t in templates:
            if type(t).__name__ == template_cls_name:
                template = t
                break

    t0 = time.time()
    try:
        sample = template.generate(seed)
        code = sample.code

        # Validate
        val = validate_code(code, timeout=60)
        gen_time = round(time.time() - t0, 2)

        if not val.get("passed", False):
            return None

        # Build assistant content
        prefix_choices = [
            "Here is the Build123d code for your request:\n\n",
            "Here is the parametric Build123d model:\n\n",
        ]
        prefix = random.choice(prefix_choices)

        # Add reasoning for complex samples
        reasoning = ""
        if add_reasoning and sample.complexity >= 4:
            reasoning = generate_reasoning_prefix(sample)

        assistant_content = f"{reasoning}{prefix}```python\n{code}\n```"

        record = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_GEN},
                {"role": "user", "content": sample.prompt},
                {"role": "assistant", "content": assistant_content},
            ],
            "source": f"phase2_{category}",
            "edit_type": "generation",
            "category": category,
            "complexity": sample.complexity,
            "base_template": sample.name,
            "params": {k: v for k, v in sample.params.items() if not isinstance(v, bool)},
            "_validation": val,
            "geometry_metrics": {
                "faces": val.get("faces", 0),
                "edges": val.get("edges", 0),
                "vertices": val.get("vertices", 0),
                "bbox": val.get("bbox", []),
            },
            "code_hash": code_hash(code),
            "generation_time_seconds": gen_time,
        }
        if sample.sub_type:
            record["gear_sub_type"] = sample.sub_type

        return record

    except Exception as e:
        return None


# ===========================================================================
# Main Runner
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 2 dataset expansion")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers")
    parser.add_argument("--variants", type=int, default=100, help="Base variants per category")
    parser.add_argument("--categories", nargs="*", default=None, help="Specific categories")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without generating")
    parser.add_argument("--no-validate", action="store_true", help="Skip validation (fast, but risky)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    categories = args.categories or list(ALL_TEMPLATES.keys())
    categories = [c for c in categories if c in ALL_TEMPLATES]

    # Plan generation tasks
    tasks = []
    for cat in categories:
        templates = ALL_TEMPLATES[cat]
        variants_per_template = max(1, args.variants // len(templates))

        for template in templates:
            for i in range(variants_per_template):
                seed = hash((template.name, i)) & 0xFFFFFFFF
                # 25% of complexity 4-5 get reasoning
                add_reasoning = (template.complexity >= 4 and random.Random(seed).random() < 0.25)
                tasks.append((type(template).__name__, cat, seed, add_reasoning))

    total = len(tasks)

    if args.dry_run:
        print(f"DRY RUN: Would generate {total} samples across {len(categories)} categories:")
        for cat in categories:
            n = sum(1 for t in tasks if t[1] == cat)
            print(f"  {cat}: {n} samples")
        return

    print(f"=" * 60)
    print(f"  Phase 2 Dataset Expansion")
    print(f"  Categories: {', '.join(categories)}")
    print(f"  Total tasks: {total}")
    print(f"  Workers: {args.workers}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"=" * 60)

    # Group by category for output files
    results_by_cat: dict[str, list[dict]] = {c: [] for c in categories}
    passed = 0
    failed = 0
    start_time = time.time()

    if args.workers > 1:
        # Parallel execution
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_generate_one, t): t for t in tasks}
            for i, future in enumerate(as_completed(futures), 1):
                task_info = futures[future]
                cat = task_info[1]

                try:
                    record = future.result(timeout=120)
                except Exception:
                    record = None

                if record:
                    results_by_cat[cat].append(record)
                    passed += 1
                else:
                    failed += 1

                # Progress bar
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                pct = i / total * 100
                bar = "#" * int(pct // 2) + "-" * (50 - int(pct // 2))
                print(f"\r  [{bar}] {pct:5.1f}% | {passed}ok {failed}fail | "
                      f"ETA {int(eta//60)}m{int(eta%60):02d}s    ", end="", flush=True)

    else:
        # Sequential execution
        for i, task in enumerate(tasks, 1):
            cat = task[1]
            record = _generate_one(task)

            if record:
                results_by_cat[cat].append(record)
                passed += 1
            else:
                failed += 1

            # Progress bar
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            pct = i / total * 100
            bar = "#" * int(pct // 2) + "-" * (50 - int(pct // 2))
            print(f"\r  [{bar}] {pct:5.1f}% | {passed}ok {failed}fail | "
                  f"ETA {int(eta//60)}m{int(eta%60):02d}s    ", end="", flush=True)

    print()  # newline after progress bar

    # Write output files
    total_written = 0
    manifest = {"categories": {}, "total_samples": 0, "total_failed": failed,
                "generation_time_seconds": round(time.time() - start_time, 1)}

    for cat, records in results_by_cat.items():
        if not records:
            continue
        fpath = OUTPUT_DIR / f"{cat}.jsonl"
        with open(fpath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")

        total_written += len(records)
        avg_time = sum(r.get("generation_time_seconds", 0) for r in records) / len(records)
        manifest["categories"][cat] = {
            "count": len(records),
            "avg_generation_time": round(avg_time, 2),
            "complexities": dict(sorted(
                {k: v for k, v in __import__("collections").Counter(
                    r["complexity"] for r in records).items()}.items()
            )),
        }
        print(f"  Wrote {len(records):4d} records -> {fpath.name}")

    manifest["total_samples"] = total_written
    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    total_time = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  DONE in {int(total_time//60)}m {int(total_time%60)}s")
    print(f"  Passed: {passed} | Failed: {failed} | Total written: {total_written}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
