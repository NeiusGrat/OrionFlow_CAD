"""20 parametric part templates for synthetic OFL training data."""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod

# ---------------------------------------------------------------------------
# engineering constants
# ---------------------------------------------------------------------------
METRIC_CLEARANCE = {
    "M2": 2.4, "M2.5": 2.8, "M3": 3.4, "M4": 4.5, "M5": 5.5,
    "M6": 6.6, "M8": 8.4, "M10": 10.5, "M12": 13.0, "M16": 17.5,
}
COMMON_THICKNESS = [1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12]
NEMA17 = {"pcd": 31.04, "bolt": "M3", "bore": 22, "size": 42.3}
NEMA23 = {"pcd": 47.14, "bolt": "M5", "bore": 38.1, "size": 56.4}


def _rc(choices):
    return random.choice(choices)


def _ru(lo, hi, decimals=1):
    return round(random.uniform(lo, hi), decimals)


def _ri(lo, hi):
    return random.randint(lo, hi)


# ---------------------------------------------------------------------------
# base class
# ---------------------------------------------------------------------------
class PartTemplate(ABC):
    name: str = ""
    complexity: int = 1

    def generate(self) -> tuple[str, str]:
        params = self.randomize_params()
        text = self.generate_description(params)
        code = self.generate_code(params)
        return text, code

    @abstractmethod
    def randomize_params(self) -> dict:
        ...

    @abstractmethod
    def generate_description(self, params: dict) -> str:
        ...

    @abstractmethod
    def generate_code(self, params: dict) -> str:
        ...


def _header():
    return "from orionflow_ofl import *\n"


# ---------------------------------------------------------------------------
# 1. RectangularPlate
# ---------------------------------------------------------------------------
class RectangularPlate(PartTemplate):
    name = "rectangular_plate"
    complexity = 1

    def randomize_params(self) -> dict:
        return {
            "width": _ru(20, 300),
            "height": _ru(20, 300),
            "thickness": _rc(COMMON_THICKNESS),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        w = random.choice(["plate", "panel", "sheet"])
        if level <= 2:
            return f"A flat rectangular {w}"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm rectangular {w}"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm {w}, {p['thickness']}mm thick"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm rectangular {w}, 6061-T6 aluminum, CNC machinable"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "rectangular_plate.step")
"""


# ---------------------------------------------------------------------------
# 2. RoundedRectPlate
# ---------------------------------------------------------------------------
class RoundedRectPlate(PartTemplate):
    name = "rounded_rect_plate"
    complexity = 1

    def randomize_params(self) -> dict:
        w = _ru(30, 250)
        h = _ru(30, 250)
        max_r = min(w, h) / 2 - 1
        return {
            "width": w,
            "height": h,
            "thickness": _rc(COMMON_THICKNESS),
            "corner_r": round(min(_ru(2, 15), max_r), 1),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A plate with rounded corners"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate with rounded corners"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate, {p['thickness']}mm thick, {p['corner_r']}mm corner radius"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm rounded rectangle, R{p['corner_r']}mm corners, mild steel"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
corner_r = {p['corner_r']}

part = (
    Sketch(Plane.XY)
    .rounded_rect(width, height, corner_r)
    .extrude(thickness)
)

export(part, "rounded_rect_plate.step")
"""


# ---------------------------------------------------------------------------
# 3. CircularDisc
# ---------------------------------------------------------------------------
class CircularDisc(PartTemplate):
    name = "circular_disc"
    complexity = 1

    def randomize_params(self) -> dict:
        return {
            "diameter": _ru(15, 200),
            "thickness": _rc(COMMON_THICKNESS),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        w = random.choice(["disc", "disk", "round plate"])
        if level <= 2:
            return f"A circular {w}"
        if level == 3:
            return f"{p['diameter']:.0f}mm {w}, {p['thickness']}mm thick"
        if level == 4:
            return f"\u00d8{p['diameter']:.0f}mm {w}, {p['thickness']}mm thick"
        return f"\u00d8{p['diameter']:.0f}x{p['thickness']}mm {w}, 304 stainless steel"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
diameter = {p['diameter']}
thickness = {p['thickness']}

part = (
    Sketch(Plane.XY)
    .circle(diameter)
    .extrude(thickness)
)

export(part, "circular_disc.step")
"""


# ---------------------------------------------------------------------------
# 4. PlateWithCenterHole
# ---------------------------------------------------------------------------
class PlateWithCenterHole(PartTemplate):
    name = "plate_with_center_hole"
    complexity = 2

    def randomize_params(self) -> dict:
        w = _ru(40, 200)
        h = _ru(40, 200)
        max_hole = min(w, h) - 10
        return {
            "width": w,
            "height": h,
            "thickness": _rc(COMMON_THICKNESS),
            "hole_dia": round(min(_ru(5, 50), max_hole), 1),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A plate with a center hole"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate with center hole"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate, {p['thickness']}mm thick, \u00d8{p['hole_dia']:.1f}mm center through hole"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm plate, \u00d8{p['hole_dia']:.1f}mm center bore, CNC machinable"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
hole_dia = {p['hole_dia']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(0, 0)
    .through()
    .label("center_hole")
)

export(part, "plate_with_center_hole.step")
"""


# ---------------------------------------------------------------------------
# 5. PlateWithBoltPattern
# ---------------------------------------------------------------------------
class PlateWithBoltPattern(PartTemplate):
    name = "plate_with_bolt_pattern"
    complexity = 3

    def randomize_params(self) -> dict:
        w = _ru(60, 250)
        h = _ru(60, 250)
        bolt = _rc(["M3", "M4", "M5", "M6", "M8"])
        count = _rc([4, 6, 8])
        pcd = round(min(w, h) * _ru(0.4, 0.7), 1)
        return {
            "width": w,
            "height": h,
            "thickness": _rc(COMMON_THICKNESS),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "count": count,
            "pcd": pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A plate with bolt holes in a circle"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate with {p['count']} bolt holes"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate, {p['thickness']}mm thick, {p['count']}x {p['bolt']} holes on {p['pcd']:.0f}mm PCD"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm plate, {p['count']}x {p['bolt']} clearance ({p['bolt_dia']}mm) on \u00d8{p['pcd']:.0f}mm PCD"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

export(part, "plate_with_bolt_pattern.step")
"""


# ---------------------------------------------------------------------------
# 6. CircularFlange
# ---------------------------------------------------------------------------
class CircularFlange(PartTemplate):
    name = "circular_flange"
    complexity = 3

    def randomize_params(self) -> dict:
        od = _ru(50, 200)
        bore = round(od * _ru(0.2, 0.4), 1)
        bolt = _rc(["M4", "M5", "M6", "M8"])
        pcd = round(od * _ru(0.55, 0.8), 1)
        return {
            "od": od,
            "thickness": _rc(COMMON_THICKNESS),
            "bore": bore,
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "bolt_count": _rc([4, 6, 8]),
            "pcd": pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A circular flange with bore and bolt holes"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm flange with center bore and {p['bolt_count']} bolt holes"
        if level == 4:
            return f"\u00d8{p['od']:.0f}mm flange, {p['thickness']}mm thick, \u00d8{p['bore']:.1f}mm bore, {p['bolt_count']}x {p['bolt']} on {p['pcd']:.0f}mm PCD"
        return f"\u00d8{p['od']:.0f}x{p['thickness']}mm flange, \u00d8{p['bore']:.1f}mm center bore, {p['bolt_count']}x {p['bolt']} clearance on \u00d8{p['pcd']:.0f}mm PCD, 304 SS"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
bore_dia = {p['bore']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['bolt_count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

export(part, "circular_flange.step")
"""


# ---------------------------------------------------------------------------
# 7. MotorMountPlate
# ---------------------------------------------------------------------------
class MotorMountPlate(PartTemplate):
    name = "motor_mount_plate"
    complexity = 3

    def randomize_params(self) -> dict:
        nema = _rc([NEMA17, NEMA23])
        size = round(nema["size"] + _ru(8, 20), 1)
        return {
            "size": size,
            "thickness": _rc([4, 5, 6, 8]),
            "bore": nema["bore"],
            "pcd": nema["pcd"],
            "bolt": nema["bolt"],
            "bolt_dia": METRIC_CLEARANCE[nema["bolt"]],
            "corner_r": _rc([2, 3, 4, 5]),
            "nema": "NEMA-17" if nema is NEMA17 else "NEMA-23",
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A motor mounting plate"
        if level == 3:
            return f"{p['nema']} motor mount plate, {p['size']:.0f}mm square"
        if level == 4:
            return f"{p['nema']} mount, {p['size']:.0f}mm square, {p['thickness']}mm thick, \u00d8{p['bore']}mm bore, 4x {p['bolt']} on {p['pcd']}mm PCD at 45\u00b0"
        return f"{p['size']:.0f}x{p['size']:.0f}x{p['thickness']}mm {p['nema']} mount, R{p['corner_r']}mm corners, \u00d8{p['bore']}mm shaft bore, 4x {p['bolt']} clearance on {p['pcd']}mm PCD"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
plate_size = {p['size']}
thickness = {p['thickness']}
bore_dia = {p['bore']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}
corner_r = {p['corner_r']}

part = (
    Sketch(Plane.XY)
    .rounded_rect(plate_size, plate_size, corner_r)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count=4, start_angle=45)
    .through()
    .label("mount_holes")
)

export(part, "motor_mount_plate.step")
"""


# ---------------------------------------------------------------------------
# 8. Washer
# ---------------------------------------------------------------------------
class Washer(PartTemplate):
    name = "washer"
    complexity = 2

    def randomize_params(self) -> dict:
        bolt = _rc(["M3", "M4", "M5", "M6", "M8", "M10", "M12"])
        bore = METRIC_CLEARANCE[bolt]
        od = round(bore * _ru(2.0, 3.0), 1)
        return {
            "od": od,
            "thickness": _rc([0.5, 0.8, 1, 1.5, 2, 3]),
            "bore": bore,
            "bolt": bolt,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A flat washer"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm washer for {p['bolt']} bolt"
        if level == 4:
            return f"\u00d8{p['od']:.1f}mm washer, {p['thickness']}mm thick, \u00d8{p['bore']}mm bore for {p['bolt']}"
        return f"\u00d8{p['od']:.1f}x{p['thickness']}mm flat washer, \u00d8{p['bore']}mm ID ({p['bolt']} clearance), zinc-plated steel"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
bore_dia = {p['bore']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("bore")
)

export(part, "washer.step")
"""


# ---------------------------------------------------------------------------
# 9. Spacer
# ---------------------------------------------------------------------------
class Spacer(PartTemplate):
    name = "spacer"
    complexity = 2

    def randomize_params(self) -> dict:
        bore = _rc([3.4, 4.5, 5.5, 6.6, 8.4])
        od = round(bore + _ru(3, 12), 1)
        return {
            "od": od,
            "length": _ru(5, 50),
            "bore": bore,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A cylindrical spacer"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm spacer, {p['length']:.0f}mm long"
        if level == 4:
            return f"\u00d8{p['od']:.1f}mm spacer, {p['length']:.1f}mm long, \u00d8{p['bore']}mm through bore"
        return f"\u00d8{p['od']:.1f}x{p['length']:.1f}mm spacer, \u00d8{p['bore']}mm ID, aluminum"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
length = {p['length']}
bore_dia = {p['bore']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(length)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("bore")
)

export(part, "spacer.step")
"""


# ---------------------------------------------------------------------------
# 10. Bushing
# ---------------------------------------------------------------------------
class Bushing(PartTemplate):
    name = "bushing"
    complexity = 2

    def randomize_params(self) -> dict:
        bore = _ru(6, 40)
        wall = _ru(3, 10)
        od = round(bore + 2 * wall, 1)
        return {
            "od": od,
            "length": _ru(8, 60),
            "bore": round(bore, 1),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A bushing"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm bushing, {p['length']:.0f}mm long"
        if level == 4:
            return f"\u00d8{p['od']:.1f}mm OD bushing, \u00d8{p['bore']:.1f}mm bore, {p['length']:.1f}mm length"
        return f"\u00d8{p['od']:.1f}x{p['length']:.1f}mm bushing, \u00d8{p['bore']:.1f}mm ID, bronze or Oilite bearing"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
length = {p['length']}
bore_dia = {p['bore']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(length)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("bearing_surface")
)

export(part, "bushing.step")
"""


# ---------------------------------------------------------------------------
# 11. EndCap
# ---------------------------------------------------------------------------
class EndCap(PartTemplate):
    name = "end_cap"
    complexity = 3

    def randomize_params(self) -> dict:
        od = _ru(40, 150)
        bolt = _rc(["M3", "M4", "M5", "M6"])
        pcd = round(od * _ru(0.6, 0.85), 1)
        return {
            "od": od,
            "thickness": _rc([3, 4, 5, 6, 8]),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "bolt_count": _rc([4, 6, 8]),
            "pcd": pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A circular end cap with bolt holes"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm end cap with {p['bolt_count']} bolt holes"
        if level == 4:
            return f"\u00d8{p['od']:.0f}mm end cap, {p['thickness']}mm thick, {p['bolt_count']}x {p['bolt']} on {p['pcd']:.0f}mm PCD"
        return f"\u00d8{p['od']:.0f}x{p['thickness']}mm end cap, {p['bolt_count']}x {p['bolt']} clearance on \u00d8{p['pcd']:.0f}mm PCD, 6061-T6"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['bolt_count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

export(part, "end_cap.step")
"""


# ---------------------------------------------------------------------------
# 12. MountingBracketBase
# ---------------------------------------------------------------------------
class MountingBracketBase(PartTemplate):
    name = "mounting_bracket_base"
    complexity = 2

    def randomize_params(self) -> dict:
        w = _ru(40, 150)
        h = _ru(30, 120)
        bolt = _rc(["M3", "M4", "M5", "M6"])
        bolt_dia = METRIC_CLEARANCE[bolt]
        count = _rc([2, 4])
        margin = max(bolt_dia, 6)
        return {
            "width": w,
            "height": h,
            "thickness": _rc(COMMON_THICKNESS),
            "bolt": bolt,
            "bolt_dia": bolt_dia,
            "count": count,
            "margin": round(margin, 1),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A mounting bracket base plate"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm bracket with {p['count']} mounting holes"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm bracket base, {p['thickness']}mm thick, {p['count']}x {p['bolt']} holes"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm bracket base, {p['count']}x {p['bolt']} clearance at edges, mild steel"

    def generate_code(self, p: dict) -> str:
        w2 = round(p["width"] / 2 - p["margin"], 1)
        h2 = round(p["height"] / 2 - p["margin"], 1)
        if p["count"] == 2:
            at_lines = f"    .at({w2}, 0)\n    .at(-{w2}, 0)"
        else:
            at_lines = f"    .at({w2}, {h2})\n    .at(-{w2}, {h2})\n    .at(-{w2}, -{h2})\n    .at({w2}, -{h2})"
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
{at_lines}
    .through()
    .label("mount_holes")
)

export(part, "mounting_bracket_base.step")
"""


# ---------------------------------------------------------------------------
# 13. SensorMountPlate
# ---------------------------------------------------------------------------
class SensorMountPlate(PartTemplate):
    name = "sensor_mount_plate"
    complexity = 2

    def randomize_params(self) -> dict:
        w = _ru(20, 60)
        h = _ru(15, 50)
        bolt = _rc(["M2", "M2.5", "M3"])
        spacing = round(min(w, h) * _ru(0.4, 0.7), 1)
        return {
            "width": w,
            "height": h,
            "thickness": _rc([1, 1.5, 2, 3]),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "spacing": spacing,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A small sensor mounting plate"
        if level == 3:
            return f"Small {p['width']:.0f}x{p['height']:.0f}mm sensor mount with 2 holes"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm sensor mount, {p['thickness']}mm thick, 2x {p['bolt']} holes at {p['spacing']:.0f}mm spacing"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm sensor mount, 2x {p['bolt']} clearance, {p['spacing']:.0f}mm apart, FR4 or aluminum"

    def generate_code(self, p: dict) -> str:
        half_sp = round(p["spacing"] / 2, 1)
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
    .at({half_sp}, 0)
    .at(-{half_sp}, 0)
    .through()
    .label("sensor_mount")
)

export(part, "sensor_mount_plate.step")
"""


# ---------------------------------------------------------------------------
# 14. PCBStandoffPlate
# ---------------------------------------------------------------------------
class PCBStandoffPlate(PartTemplate):
    name = "pcb_standoff_plate"
    complexity = 2

    def randomize_params(self) -> dict:
        # common PCB sizes
        presets = [(100, 60), (80, 50), (70, 40), (120, 80), (50, 50)]
        w, h = _rc(presets)
        bolt = _rc(["M2.5", "M3"])
        inset = _ru(3, 8)
        return {
            "width": w,
            "height": h,
            "thickness": _rc(COMMON_THICKNESS),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "inset": round(inset, 1),
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A PCB mounting plate with standoff holes"
        if level == 3:
            return f"{p['width']}x{p['height']}mm PCB plate with 4 corner holes"
        if level == 4:
            return f"{p['width']}x{p['height']}mm PCB standoff plate, {p['thickness']}mm thick, 4x {p['bolt']} at corners ({p['inset']}mm inset)"
        return f"{p['width']}x{p['height']}x{p['thickness']}mm PCB mount, 4x {p['bolt']} standoff holes at ({p['inset']}mm, {p['inset']}mm) from edges, aluminum"

    def generate_code(self, p: dict) -> str:
        cx = round(p["width"] / 2 - p["inset"], 1)
        cy = round(p["height"] / 2 - p["inset"], 1)
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
    .at({cx}, {cy})
    .at(-{cx}, {cy})
    .at(-{cx}, -{cy})
    .at({cx}, -{cy})
    .through()
    .label("standoff_holes")
)

export(part, "pcb_standoff_plate.step")
"""


# ---------------------------------------------------------------------------
# 15. BearingHousingCap
# ---------------------------------------------------------------------------
class BearingHousingCap(PartTemplate):
    name = "bearing_housing_cap"
    complexity = 3

    def randomize_params(self) -> dict:
        bearing_od = _rc([22, 32, 42, 47, 52, 62, 72])
        od = round(bearing_od + _ru(15, 40), 1)
        bolt = _rc(["M4", "M5", "M6", "M8"])
        pcd = round((bearing_od + od) / 2, 1)
        return {
            "od": od,
            "thickness": _rc([5, 6, 8, 10]),
            "bearing_bore": bearing_od,
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "bolt_count": _rc([4, 6]),
            "pcd": pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A bearing housing cap"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm bearing cap with bore and bolt holes"
        if level == 4:
            return f"\u00d8{p['od']:.0f}mm bearing housing cap, \u00d8{p['bearing_bore']}mm bearing bore, {p['bolt_count']}x {p['bolt']} on {p['pcd']:.0f}mm PCD"
        return f"\u00d8{p['od']:.0f}x{p['thickness']}mm bearing cap, \u00d8{p['bearing_bore']}mm bore, {p['bolt_count']}x {p['bolt']} clearance on \u00d8{p['pcd']:.0f}mm PCD"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
bearing_bore = {p['bearing_bore']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(bearing_bore)
    .at(0, 0)
    .through()
    .label("bearing_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['bolt_count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

export(part, "bearing_housing_cap.step")
"""


# ---------------------------------------------------------------------------
# 16. GearboxCover
# ---------------------------------------------------------------------------
class GearboxCover(PartTemplate):
    name = "gearbox_cover"
    complexity = 4

    def randomize_params(self) -> dict:
        od = _ru(100, 250)
        bore = round(od * _ru(0.15, 0.25), 1)
        bolt = _rc(["M5", "M6", "M8"])
        pcd = round(od * _ru(0.65, 0.85), 1)
        dowel_pcd = round(od * _ru(0.5, 0.6), 1)
        return {
            "od": od,
            "thickness": _rc([6, 8, 10, 12]),
            "bore": bore,
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "bolt_count": _rc([6, 8, 12]),
            "pcd": pcd,
            "dowel_dia": _rc([4, 5, 6, 8]),
            "dowel_count": 2,
            "dowel_pcd": dowel_pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A gearbox cover plate"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm gearbox cover with bolts and dowel pins"
        if level == 4:
            return f"\u00d8{p['od']:.0f}mm gearbox cover, \u00d8{p['bore']:.0f}mm bore, {p['bolt_count']}x {p['bolt']} bolts, 2 dowel pins"
        return f"\u00d8{p['od']:.0f}x{p['thickness']}mm cover, \u00d8{p['bore']:.0f}mm shaft bore, {p['bolt_count']}x {p['bolt']} on \u00d8{p['pcd']:.0f}mm PCD, 2x \u00d8{p['dowel_dia']}mm dowels on \u00d8{p['dowel_pcd']:.0f}mm"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
bore_dia = {p['bore']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}
dowel_dia = {p['dowel_dia']}
dowel_pcd = {p['dowel_pcd']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['bolt_count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

part -= (
    Hole(dowel_dia)
    .at_circular(dowel_pcd / 2, count=2, start_angle=0)
    .to_depth({round(p['thickness'] * 0.6, 1)})
    .label("dowel_pins")
)

export(part, "gearbox_cover.step")
"""


# ---------------------------------------------------------------------------
# 17. HeatSinkBase
# ---------------------------------------------------------------------------
class HeatSinkBase(PartTemplate):
    name = "heat_sink_base"
    complexity = 3

    def randomize_params(self) -> dict:
        w = _ru(80, 200)
        h = _ru(30, 80)
        bolt = _rc(["M3", "M4"])
        cols = _ri(3, 6)
        rows = _ri(2, 3)
        col_sp = round(w / (cols + 1), 1)
        row_sp = round(h / (rows + 1), 1)
        return {
            "width": w,
            "height": h,
            "thickness": _rc([5, 6, 8, 10]),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "cols": cols,
            "rows": rows,
            "col_sp": col_sp,
            "row_sp": row_sp,
        }

    def generate_description(self, p: dict) -> str:
        n = p["cols"] * p["rows"]
        level = _ri(1, 5)
        if level <= 2:
            return "A heat sink base with grid of holes"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm heat sink base with {n} holes"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm heat sink base, {p['thickness']}mm thick, {p['cols']}x{p['rows']} grid of {p['bolt']} holes"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm heat sink base, {n}x {p['bolt']} clearance in {p['cols']}x{p['rows']} grid, 6063-T5 aluminum"

    def generate_code(self, p: dict) -> str:
        at_lines = []
        for c in range(p["cols"]):
            for r in range(p["rows"]):
                x = round(-p["width"] / 2 + (c + 1) * p["col_sp"], 1)
                y = round(-p["height"] / 2 + (r + 1) * p["row_sp"], 1)
                at_lines.append(f"    .at({x}, {y})")
        at_block = "\n".join(at_lines)
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bolt_dia = {p['bolt_dia']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bolt_dia)
{at_block}
    .through()
    .label("mounting_holes")
)

export(part, "heat_sink_base.step")
"""


# ---------------------------------------------------------------------------
# 18. PipeFlange
# ---------------------------------------------------------------------------
class PipeFlange(PartTemplate):
    name = "pipe_flange"
    complexity = 3

    def randomize_params(self) -> dict:
        pipe_od = _rc([21.3, 26.9, 33.7, 42.4, 48.3, 60.3, 73.0, 88.9])
        od = round(pipe_od + _ru(30, 60), 1)
        bolt = _rc(["M6", "M8", "M10", "M12"])
        pcd = round((pipe_od + od) / 2, 1)
        return {
            "od": od,
            "thickness": _rc([8, 10, 12, 15]),
            "pipe_bore": round(pipe_od, 1),
            "bolt": bolt,
            "bolt_dia": METRIC_CLEARANCE[bolt],
            "bolt_count": _rc([4, 6, 8]),
            "pcd": pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A pipe flange"
        if level == 3:
            return f"\u00d8{p['od']:.0f}mm pipe flange with bore and bolts"
        if level == 4:
            return f"\u00d8{p['od']:.0f}mm flange, \u00d8{p['pipe_bore']:.1f}mm pipe bore, {p['bolt_count']}x {p['bolt']} on {p['pcd']:.0f}mm PCD"
        return f"\u00d8{p['od']:.0f}x{p['thickness']}mm pipe flange, \u00d8{p['pipe_bore']:.1f}mm bore, {p['bolt_count']}x {p['bolt']} clearance on \u00d8{p['pcd']:.0f}mm PCD, carbon steel"

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
od = {p['od']}
thickness = {p['thickness']}
pipe_bore = {p['pipe_bore']}
bolt_dia = {p['bolt_dia']}
bolt_pcd = {p['pcd']}

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(pipe_bore)
    .at(0, 0)
    .through()
    .label("pipe_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count={p['bolt_count']}, start_angle=0)
    .through()
    .label("{p['bolt']}_bolts")
)

export(part, "pipe_flange.step")
"""


# ---------------------------------------------------------------------------
# 19. BlindHolePlate
# ---------------------------------------------------------------------------
class BlindHolePlate(PartTemplate):
    name = "blind_hole_plate"
    complexity = 2

    def randomize_params(self) -> dict:
        w = _ru(50, 150)
        h = _ru(40, 120)
        t = _rc([8, 10, 12, 15, 20])
        hole_dia = _ru(4, 12)
        depth = round(t * _ru(0.3, 0.7), 1)
        count = _ri(2, 4)
        return {
            "width": w,
            "height": h,
            "thickness": t,
            "hole_dia": round(hole_dia, 1),
            "depth": depth,
            "count": count,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A plate with blind holes"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate with {p['count']} blind holes"
        if level == 4:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate, {p['thickness']}mm thick, {p['count']}x \u00d8{p['hole_dia']:.1f}mm blind holes {p['depth']:.0f}mm deep"
        return f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm plate, {p['count']}x \u00d8{p['hole_dia']:.1f}mm blind holes to {p['depth']:.1f}mm depth, CNC milled"

    def generate_code(self, p: dict) -> str:
        # place holes distributed along width
        at_lines = []
        spacing = round(p["width"] / (p["count"] + 1), 1)
        for i in range(p["count"]):
            x = round(-p["width"] / 2 + (i + 1) * spacing, 1)
            at_lines.append(f"    .at({x}, 0)")
        at_block = "\n".join(at_lines)
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
hole_dia = {p['hole_dia']}
hole_depth = {p['depth']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
{at_block}
    .to_depth(hole_depth)
    .label("blind_holes")
)

export(part, "blind_hole_plate.step")
"""


# ---------------------------------------------------------------------------
# 20. MultiPatternPlate
# ---------------------------------------------------------------------------
class MultiPatternPlate(PartTemplate):
    name = "multi_pattern_plate"
    complexity = 5

    def randomize_params(self) -> dict:
        w = _ru(80, 200)
        h = _ru(80, 200)
        bore = round(min(w, h) * _ru(0.15, 0.25), 1)
        inner_bolt = _rc(["M3", "M4", "M5"])
        outer_bolt = _rc(["M5", "M6", "M8"])
        inner_pcd = round(min(w, h) * _ru(0.3, 0.45), 1)
        outer_pcd = round(min(w, h) * _ru(0.55, 0.75), 1)
        return {
            "width": w,
            "height": h,
            "thickness": _rc([6, 8, 10, 12]),
            "bore": bore,
            "inner_bolt": inner_bolt,
            "inner_bolt_dia": METRIC_CLEARANCE[inner_bolt],
            "inner_count": _rc([4, 6]),
            "inner_pcd": inner_pcd,
            "outer_bolt": outer_bolt,
            "outer_bolt_dia": METRIC_CLEARANCE[outer_bolt],
            "outer_count": _rc([6, 8]),
            "outer_pcd": outer_pcd,
        }

    def generate_description(self, p: dict) -> str:
        level = _ri(1, 5)
        if level <= 2:
            return "A plate with center bore and two bolt circles"
        if level == 3:
            return f"{p['width']:.0f}x{p['height']:.0f}mm plate with bore, inner and outer bolt circles"
        if level == 4:
            return (
                f"{p['width']:.0f}x{p['height']:.0f}mm plate, {p['thickness']}mm thick, "
                f"\u00d8{p['bore']:.0f}mm bore, "
                f"{p['inner_count']}x {p['inner_bolt']} on {p['inner_pcd']:.0f}mm PCD, "
                f"{p['outer_count']}x {p['outer_bolt']} on {p['outer_pcd']:.0f}mm PCD"
            )
        return (
            f"{p['width']:.0f}x{p['height']:.0f}x{p['thickness']}mm multi-pattern plate, "
            f"\u00d8{p['bore']:.0f}mm center bore, "
            f"{p['inner_count']}x {p['inner_bolt']} clearance inner circle \u00d8{p['inner_pcd']:.0f}mm, "
            f"{p['outer_count']}x {p['outer_bolt']} clearance outer circle \u00d8{p['outer_pcd']:.0f}mm"
        )

    def generate_code(self, p: dict) -> str:
        return f"""{_header()}
width = {p['width']}
height = {p['height']}
thickness = {p['thickness']}
bore_dia = {p['bore']}
inner_bolt_dia = {p['inner_bolt_dia']}
inner_pcd = {p['inner_pcd']}
outer_bolt_dia = {p['outer_bolt_dia']}
outer_pcd = {p['outer_pcd']}

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

part -= (
    Hole(inner_bolt_dia)
    .at_circular(inner_pcd / 2, count={p['inner_count']}, start_angle=0)
    .through()
    .label("inner_bolts")
)

part -= (
    Hole(outer_bolt_dia)
    .at_circular(outer_pcd / 2, count={p['outer_count']}, start_angle={round(180 / p['outer_count'], 1)})
    .through()
    .label("outer_bolts")
)

export(part, "multi_pattern_plate.step")
"""


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
ALL_TEMPLATES: list[type[PartTemplate]] = [
    RectangularPlate,
    RoundedRectPlate,
    CircularDisc,
    PlateWithCenterHole,
    PlateWithBoltPattern,
    CircularFlange,
    MotorMountPlate,
    Washer,
    Spacer,
    Bushing,
    EndCap,
    MountingBracketBase,
    SensorMountPlate,
    PCBStandoffPlate,
    BearingHousingCap,
    GearboxCover,
    HeatSinkBase,
    PipeFlange,
    BlindHolePlate,
    MultiPatternPlate,
]
