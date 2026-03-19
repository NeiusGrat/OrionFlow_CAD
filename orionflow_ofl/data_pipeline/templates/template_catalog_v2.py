"""Expanded 50-template catalog for OrionFlow synthetic data generation.

This module keeps the implementation compact by using a small number of
template factories that emit concrete template classes with the required API:
``randomize_params()``, ``generate_code()``, ``generate_descriptions()``,
plus backward-compatible ``generate_description()`` and ``supported_variants()``.
"""

from __future__ import annotations

import random


STANDARD_KNOWLEDGE = {
    "bolt_clearance": {
        "M2": 2.4,
        "M2.5": 2.9,
        "M3": 3.4,
        "M4": 4.5,
        "M5": 5.3,
        "M6": 6.6,
        "M8": 9.0,
        "M10": 11.0,
        "M12": 13.5,
    },
    "nema": {
        "NEMA14": {"frame": 35.2, "pilot": 22.0, "pcd": 26.0, "bolt": "M3"},
        "NEMA17": {"frame": 42.3, "pilot": 22.0, "pcd": 31.0, "bolt": "M3"},
        "NEMA23": {"frame": 56.4, "pilot": 38.1, "pcd": 47.14, "bolt": "M5"},
        "NEMA34": {"frame": 86.0, "pilot": 73.0, "pcd": 69.6, "bolt": "M6"},
    },
    "bearings": {
        "608": (8, 22, 7),
        "6001": (12, 28, 8),
        "6200": (10, 30, 9),
        "6201": (12, 32, 10),
        "6205": (25, 52, 15),
        "6206": (30, 62, 16),
    },
    "pcb": {
        "RPi4": {
            "holes": [(3.5, 3.5), (3.5, 52.5), (61.5, 3.5), (61.5, 52.5)],
            "dia": 2.7,
            "board": (85, 56),
        },
        "Arduino_Uno": {
            "holes": [(14, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56)],
            "dia": 3.2,
            "board": (68.6, 53.4),
        },
    },
}

COMMON_THICKNESS = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]
THIN_THICKNESS = [1.5, 2.0, 2.5, 3.0, 4.0]
BOX_THICKNESS = [3.0, 4.0, 5.0, 6.0, 8.0]


class ModernTemplateBase:
    name: str = ""
    complexity: int = 1
    COMPLEXITY_VARIANTS = ["basic", "filleted"]

    def supported_variants(self) -> list[str]:
        return list(self.COMPLEXITY_VARIANTS)

    def generate_description(self, params: dict) -> str:
        return self.generate_descriptions(params, self.supported_variants()[0])[1]


def _rc(choices):
    return random.choice(choices)


def _ru(lo: float, hi: float, decimals: int = 1) -> float:
    return round(random.uniform(lo, hi), decimals)


def _ri(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


def _safe_fillet(*dims: float) -> float:
    positive = [d for d in dims if d > 0]
    smallest = min(positive) if positive else 6.0
    return round(min(max(smallest * 0.02, 0.4), 1.2), 1)


def _safe_chamfer(*dims: float) -> float:
    positive = [d for d in dims if d > 0]
    smallest = min(positive) if positive else 6.0
    return round(min(max(smallest * 0.015, 0.3), 0.8), 1)


def _safe_wall(*dims: float) -> float:
    positive = [d for d in dims if d > 0]
    smallest = min(positive) if positive else 20.0
    return round(min(max(smallest * 0.12, 1.5), max(1.5, smallest / 4.5)), 1)


def _fmt(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:.1f}"
        return f"{value}"
    return str(value)


def _render_code(assignments: list[tuple[str, object]], sections: list[str]) -> str:
    lines = ["from orionflow_ofl import *", ""]
    for name, value in assignments:
        lines.append(f"{name} = {_fmt(value)}")
    lines.append("")
    for section in sections:
        if not section:
            continue
        lines.extend(section.rstrip().splitlines())
        lines.append("")
    lines.append('export(part, "model.step")')
    lines.append("")
    return "\n".join(lines)


def _rect_part(
    width_var: str,
    height_var: str,
    thickness_var: str,
    corner_radius_var: str | None = None,
    plane_expr: str = "Plane.XY",
    offset_var: str | None = None,
    part_name: str = "part",
    comment: str = "Base feature",
) -> str:
    sketch_line = f"    Sketch({plane_expr}"
    if offset_var is not None:
        sketch_line += f", offset={offset_var}"
    sketch_line += ")"
    profile_line = (
        f"    .rounded_rect({width_var}, {height_var}, {corner_radius_var})"
        if corner_radius_var
        else f"    .rect({width_var}, {height_var})"
    )
    return (
        f"# {comment}\n"
        f"{part_name} = (\n"
        f"{sketch_line}\n"
        f"{profile_line}\n"
        f"    .extrude({thickness_var})\n"
        f")"
    )


def _circle_part(
    diameter_var: str,
    thickness_var: str,
    plane_expr: str = "Plane.XY",
    offset_var: str | None = None,
    part_name: str = "part",
    comment: str = "Base feature",
) -> str:
    sketch_line = f"    Sketch({plane_expr}"
    if offset_var is not None:
        sketch_line += f", offset={offset_var}"
    sketch_line += ")"
    return (
        f"# {comment}\n"
        f"{part_name} = (\n"
        f"{sketch_line}\n"
        f"    .circle({diameter_var})\n"
        f"    .extrude({thickness_var})\n"
        f")"
    )


def _manual_hole_block(
    diameter_var: str,
    positions: list[tuple[str, str]],
    label: str,
    through: bool = True,
    depth_var: str | None = None,
) -> str:
    lines = ["part -= (", f"    Hole({diameter_var})"]
    for x_expr, y_expr in positions:
        lines.append(f"    .at({x_expr}, {y_expr})")
    if through:
        lines.append("    .through()")
    else:
        lines.append(f"    .to_depth({depth_var})")
    lines.append(f'    .label("{label}")')
    lines.append(")")
    return "\n".join(lines)


def _circular_hole_block(
    diameter_var: str,
    radius_var: str,
    count_var: str,
    start_angle_var: str,
    label: str,
    through: bool = True,
    depth_var: str | None = None,
) -> str:
    lines = [
        "part -= (",
        f"    Hole({diameter_var})",
        f"    .at_circular({radius_var}, count={count_var}, start_angle={start_angle_var})",
    ]
    if through:
        lines.append("    .through()")
    else:
        lines.append(f"    .to_depth({depth_var})")
    lines.append(f'    .label("{label}")')
    lines.append(")")
    return "\n".join(lines)


def _variant_lines(variant: str, fillet_var: str = "fillet_radius", chamfer_var: str = "chamfer_distance") -> list[str]:
    lines: list[str] = []
    if "fillet" in variant:
        lines.append(f'# Variant feature: fillet outer edges\npart = part.fillet({fillet_var}, edges="vertical")')
    if "chamfer" in variant:
        lines.append(f'# Variant feature: chamfer top edges\npart = part.chamfer({chamfer_var}, edges="top")')
    return lines


def _top_bottom_fillet_lines(fillet_var: str = "fillet_radius") -> list[str]:
    return [
        f'# Variant feature: fillet top perimeter\npart = part.fillet({fillet_var}, edges="top")',
        f'# Variant feature: fillet bottom perimeter\npart = part.fillet({fillet_var}, edges="bottom")',
    ]


def _long_plate_descriptions(
    casual: str,
    engineering: str,
    natural: str,
) -> list[str]:
    return [casual, engineering, natural]


def _make_template_class(
    class_name: str,
    template_name: str,
    complexity: int,
    variants: list[str],
    randomize_fn,
    code_fn,
    descriptions_fn,
):
    class _Template(ModernTemplateBase):
        def randomize_params(self, variant: str = "basic") -> dict:
            return randomize_fn(variant)

        def generate_code(self, params: dict, variant: str = "basic") -> str:
            return code_fn(params, variant)

        def generate_descriptions(self, params: dict, variant: str = "basic") -> list[str]:
            return descriptions_fn(params, variant)

    _Template.__name__ = class_name
    _Template.name = template_name
    _Template.complexity = complexity
    _Template.COMPLEXITY_VARIANTS = variants
    return _Template


# ---------------------------------------------------------------------------
# Category 1 - Mounting Plates
# ---------------------------------------------------------------------------
def _flat_plate_params(variant: str) -> dict:
    plate_width = _ru(60, 180)
    plate_height = _ru(40, 140)
    edge_margin = round(min(plate_width, plate_height) * _ru(0.12, 0.18), 1)
    mounting_hole_diameter = _rc([3.4, 4.5, 5.3, 6.6])
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(COMMON_THICKNESS),
        "mounting_hole_diameter": mounting_hole_diameter,
        "edge_margin": edge_margin,
        "fillet_radius": _safe_fillet(plate_width, plate_height),
    }


def _flat_plate_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("edge_margin", p["edge_margin"]),
        ("mounting_hole_x", "plate_width / 2 - edge_margin"),
        ("mounting_hole_y", "plate_height / 2 - edge_margin"),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Base mounting plate"),
        "# Corner mounting holes\n" + _manual_hole_block(
            "mounting_hole_diameter",
            [
                ("mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "-mounting_hole_y"),
                ("mounting_hole_x", "-mounting_hole_y"),
            ],
            "mounting_holes",
        ),
    ]
    sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _flat_plate_desc(p: dict, variant: str) -> list[str]:
    variant_text = " with filleted edges" if variant == "filleted" else ""
    return _long_plate_descriptions(
        f"Flat mounting plate, {p['plate_thickness']:.0f}mm thick{variant_text}",
        (
            f"Flat mounting plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, 4x {p['mounting_hole_diameter']:.1f}mm corner holes"
            + (f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else "")
        ),
        (
            f"I need a flat mounting plate about {p['plate_width']:.0f} by {p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, with four corner mounting holes"
            + (f" and a {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else "")
            + "."
        ),
    )


FlatPlate = _make_template_class(
    "FlatPlate",
    "flat_plate",
    2,
    ["basic", "filleted"],
    _flat_plate_params,
    _flat_plate_code,
    _flat_plate_desc,
)


def _motor_mount_params(frame_key: str, variant: str) -> dict:
    nema = STANDARD_KNOWLEDGE["nema"][frame_key]
    plate_size = round(nema["frame"] + _ru(10, 22), 1)
    pilot_recess_diameter = round(nema["pilot"] + _ru(4, 8), 1)
    return {
        "frame_key": frame_key,
        "plate_size": plate_size,
        "plate_thickness": _rc([4.0, 5.0, 6.0, 8.0]),
        "corner_radius": _ru(3, 6),
        "pilot_diameter": nema["pilot"],
        "bolt_pitch_circle_diameter": nema["pcd"],
        "bolt_size": nema["bolt"],
        "mounting_hole_diameter": STANDARD_KNOWLEDGE["bolt_clearance"][nema["bolt"]],
        "bolt_hole_count": 4,
        "bolt_start_angle": 45.0,
        "fillet_radius": _safe_fillet(plate_size, plate_size),
        "pilot_recess_diameter": pilot_recess_diameter,
        "pilot_recess_depth": 2.0,
    }


def _motor_mount_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_size", p["plate_size"]),
        ("plate_thickness", p["plate_thickness"]),
        ("corner_radius", p["corner_radius"]),
        ("pilot_diameter", p["pilot_diameter"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("bolt_pitch_circle_diameter", p["bolt_pitch_circle_diameter"]),
        ("bolt_circle_radius", "bolt_pitch_circle_diameter / 2"),
        ("bolt_hole_count", p["bolt_hole_count"]),
        ("bolt_start_angle", p["bolt_start_angle"]),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
        ("pilot_recess_diameter", p["pilot_recess_diameter"]),
        ("pilot_recess_depth", p["pilot_recess_depth"]),
    ]
    sections = [
        _rect_part(
            "plate_size",
            "plate_size",
            "plate_thickness",
            "corner_radius",
            comment=f"{p['frame_key']} motor mounting plate",
        ),
    ]
    if variant == "filleted":
        sections.extend(_top_bottom_fillet_lines())
    sections.extend(
        [
            "# Pilot bore\n" + _manual_hole_block(
                "pilot_diameter",
                [("center_x", "center_y")],
                "pilot_bore",
            ),
            "# Motor bolt pattern\n" + _circular_hole_block(
                "mounting_hole_diameter",
                "bolt_circle_radius",
                "bolt_hole_count",
                "bolt_start_angle",
                "motor_mount_holes",
            ),
        ]
    )
    if variant == "recessed":
        sections.append(
            "# Pilot recess for the motor boss\n"
            + _manual_hole_block(
                "pilot_recess_diameter",
                [("center_x", "center_y")],
                "pilot_recess",
                through=False,
                depth_var="pilot_recess_depth",
            )
        )
    return _render_code(assignments, sections)


def _motor_mount_desc(p: dict, variant: str) -> list[str]:
    extra = ""
    if variant == "filleted":
        extra = f", {p['fillet_radius']:.1f}mm edge fillet"
    elif variant == "recessed":
        extra = f", {p['pilot_recess_depth']:.1f}mm deep pilot recess"
    return _long_plate_descriptions(
        f"{p['frame_key']} motor mount, {p['plate_thickness']:.0f}mm thick",
        (
            f"{p['frame_key']} mounting plate: {p['plate_size']:.0f}x{p['plate_size']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, {p['pilot_diameter']:.1f}mm pilot bore, "
            f"4x {p['bolt_size']} holes on {p['bolt_pitch_circle_diameter']:.1f}mm PCD{extra}"
        ),
        (
            f"I need a {p['frame_key']} stepper mounting plate around {p['plate_size']:.0f}mm square, "
            f"{p['plate_thickness']:.0f}mm thick, with the standard 4-hole pattern and "
            f"a {p['pilot_diameter']:.1f}mm pilot bore{extra}."
        ),
    )


Nema17Mount = _make_template_class(
    "Nema17Mount",
    "nema17_mount",
    3,
    ["basic", "filleted", "recessed"],
    lambda variant: _motor_mount_params("NEMA17", variant),
    _motor_mount_code,
    _motor_mount_desc,
)

Nema23Mount = _make_template_class(
    "Nema23Mount",
    "nema23_mount",
    3,
    ["basic", "filleted"],
    lambda variant: _motor_mount_params("NEMA23", variant),
    _motor_mount_code,
    _motor_mount_desc,
)


def _pcb_mount_params(variant: str) -> dict:
    board_name = _rc(list(STANDARD_KNOWLEDGE["pcb"].keys()))
    board_data = STANDARD_KNOWLEDGE["pcb"][board_name]
    board_width, board_height = board_data["board"]
    plate_thickness = _rc(THIN_THICKNESS)
    return {
        "board_name": board_name,
        "board_width": board_width,
        "board_height": board_height,
        "plate_width": round(board_width + _ru(12, 24), 1),
        "plate_height": round(board_height + _ru(12, 24), 1),
        "plate_thickness": plate_thickness,
        "corner_radius": _ru(2, 5),
        "mounting_hole_diameter": board_data["dia"],
        "hole_positions": board_data["holes"],
        "fillet_radius": round(min(_safe_fillet(board_width, board_height), max(0.3, plate_thickness * 0.4)), 1),
    }


def _pcb_mount_code(p: dict, variant: str) -> str:
    positions = p["hole_positions"]
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("corner_radius", p["corner_radius"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("board_origin_x", round(-p["board_width"] / 2, 1)),
        ("board_origin_y", round(-p["board_height"] / 2, 1)),
        ("hole_1_x", round(positions[0][0] - p["board_width"] / 2, 1)),
        ("hole_1_y", round(positions[0][1] - p["board_height"] / 2, 1)),
        ("hole_2_x", round(positions[1][0] - p["board_width"] / 2, 1)),
        ("hole_2_y", round(positions[1][1] - p["board_height"] / 2, 1)),
        ("hole_3_x", round(positions[2][0] - p["board_width"] / 2, 1)),
        ("hole_3_y", round(positions[2][1] - p["board_height"] / 2, 1)),
        ("hole_4_x", round(positions[3][0] - p["board_width"] / 2, 1)),
        ("hole_4_y", round(positions[3][1] - p["board_height"] / 2, 1)),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [_rect_part("plate_width", "plate_height", "plate_thickness", "corner_radius", comment="PCB standoff plate")]
    if variant == "filleted":
        sections.extend(_top_bottom_fillet_lines())
    sections.append(
        "# PCB mounting holes\n"
        + _manual_hole_block(
            "mounting_hole_diameter",
            [
                ("hole_1_x", "hole_1_y"),
                ("hole_2_x", "hole_2_y"),
                ("hole_3_x", "hole_3_y"),
                ("hole_4_x", "hole_4_y"),
            ],
            "pcb_mount_holes",
        )
    )
    return _render_code(assignments, sections)


def _pcb_mount_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
    return _long_plate_descriptions(
        f"{p['board_name']} standoff plate, {p['plate_thickness']:.1f}mm thick",
        (
            f"{p['board_name']} PCB standoff plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.1f}mm thick, 4x {p['mounting_hole_diameter']:.1f}mm board mounting holes{extra}"
        ),
        (
            f"I need a standoff plate for a {p['board_name']} board, about "
            f"{p['plate_width']:.0f} by {p['plate_height']:.0f}mm, with the 4 standard board holes{extra}."
        ),
    )


PcbStandoffPlate = _make_template_class(
    "PcbStandoffPlate",
    "pcb_standoff_plate",
    2,
    ["basic", "filleted"],
    _pcb_mount_params,
    _pcb_mount_code,
    _pcb_mount_desc,
)


def _din_rail_plate_params(variant: str) -> dict:
    plate_width = _ru(110, 180)
    plate_height = _ru(35, 70)
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(THIN_THICKNESS),
        "rail_hole_diameter": _rc([4.5, 5.3, 6.6]),
        "rail_hole_spacing": round(plate_width * _ru(0.45, 0.65), 1),
        "chamfer_distance": _safe_chamfer(plate_width, plate_height),
    }


def _din_rail_plate_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("rail_hole_diameter", p["rail_hole_diameter"]),
        ("rail_hole_spacing", p["rail_hole_spacing"]),
        ("rail_hole_x", "rail_hole_spacing / 2"),
        ("center_y", 0.0),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="DIN rail adapter plate"),
        "# Rail mounting holes\n"
        + _manual_hole_block(
            "rail_hole_diameter",
            [("rail_hole_x", "center_y"), ("-rail_hole_x", "center_y")],
            "rail_mount_holes",
        ),
    ]
    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _din_rail_plate_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['chamfer_distance']:.1f}mm top chamfer" if variant == "chamfered" else ""
    return _long_plate_descriptions(
        f"DIN rail plate, {p['plate_thickness']:.1f}mm thick",
        (
            f"DIN rail mounting plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.1f}mm thick, 2x {p['rail_hole_diameter']:.1f}mm rail holes at "
            f"{p['rail_hole_spacing']:.0f}mm spacing{extra}"
        ),
        (
            f"I need a DIN rail mounting plate about {p['plate_width']:.0f} by {p['plate_height']:.0f}mm, "
            f"with two rail mounting holes spaced {p['rail_hole_spacing']:.0f}mm apart{extra}."
        ),
    )


DinRailPlate = _make_template_class(
    "DinRailPlate",
    "din_rail_plate",
    2,
    ["basic", "chamfered"],
    _din_rail_plate_params,
    _din_rail_plate_code,
    _din_rail_plate_desc,
)


def _sensor_mount_params(variant: str) -> dict:
    plate_width = _ru(35, 70)
    plate_height = _ru(25, 50)
    center_bore_diameter = _ru(8, min(plate_width, plate_height) * 0.45)
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(THIN_THICKNESS),
        "center_bore_diameter": round(center_bore_diameter, 1),
        "mounting_hole_diameter": _rc([2.9, 3.4, 4.5]),
        "mounting_hole_spacing": round(plate_width * _ru(0.4, 0.6), 1),
        "fillet_radius": _safe_fillet(plate_width, plate_height),
    }


def _sensor_mount_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("center_bore_diameter", p["center_bore_diameter"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("mounting_hole_spacing", p["mounting_hole_spacing"]),
        ("mounting_hole_x", "mounting_hole_spacing / 2"),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Sensor mounting plate"),
        "# Sensor clearance bore\n" + _manual_hole_block(
            "center_bore_diameter",
            [("center_x", "center_y")],
            "sensor_bore",
        ),
        "# Side mounting holes\n" + _manual_hole_block(
            "mounting_hole_diameter",
            [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
            "mounting_holes",
        ),
    ]
    if variant == "filleted":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _sensor_mount_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
    return _long_plate_descriptions(
        f"Sensor mount plate, {p['plate_thickness']:.1f}mm thick",
        (
            f"Sensor mounting plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.1f}mm thick, {p['center_bore_diameter']:.1f}mm center bore, "
            f"2x {p['mounting_hole_diameter']:.1f}mm side holes at {p['mounting_hole_spacing']:.0f}mm spacing{extra}"
        ),
        (
            f"I need a small sensor mounting plate around {p['plate_width']:.0f} by {p['plate_height']:.0f}mm, "
            f"with a {p['center_bore_diameter']:.1f}mm center opening and two side mounting holes{extra}."
        ),
    )


SensorMount = _make_template_class(
    "SensorMount",
    "sensor_mount",
    2,
    ["basic", "filleted"],
    _sensor_mount_params,
    _sensor_mount_code,
    _sensor_mount_desc,
)


def _baseplate_opening_params(variant: str) -> dict:
    plate_width = _ru(80, 180)
    plate_height = _ru(60, 140)
    opening_diameter = round(min(plate_width, plate_height) * _ru(0.22, 0.38), 1)
    edge_margin = round(min(plate_width, plate_height) * _ru(0.12, 0.16), 1)
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(COMMON_THICKNESS),
        "center_opening_diameter": opening_diameter,
        "mounting_hole_diameter": _rc([4.5, 5.3, 6.6, 9.0]),
        "edge_margin": edge_margin,
        "fillet_radius": _safe_fillet(plate_width, plate_height),
    }


def _baseplate_opening_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("center_opening_diameter", p["center_opening_diameter"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("edge_margin", p["edge_margin"]),
        ("mounting_hole_x", "plate_width / 2 - edge_margin"),
        ("mounting_hole_y", "plate_height / 2 - edge_margin"),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Base plate with central opening"),
        "# Central clearance opening\n" + _manual_hole_block(
            "center_opening_diameter",
            [("center_x", "center_y")],
            "central_opening",
        ),
        "# Corner mounting holes\n" + _manual_hole_block(
            "mounting_hole_diameter",
            [
                ("mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "-mounting_hole_y"),
                ("mounting_hole_x", "-mounting_hole_y"),
            ],
            "mounting_holes",
        ),
    ]
    if variant == "filleted":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _baseplate_opening_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
    return _long_plate_descriptions(
        f"Baseplate with center opening, {p['plate_thickness']:.0f}mm thick",
        (
            f"Baseplate with clearance opening: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, {p['center_opening_diameter']:.1f}mm center opening, "
            f"4x {p['mounting_hole_diameter']:.1f}mm corner holes{extra}"
        ),
        (
            f"I need a baseplate about {p['plate_width']:.0f} by {p['plate_height']:.0f}mm with "
            f"a {p['center_opening_diameter']:.1f}mm central clearance opening and four corner mounting holes{extra}."
        ),
    )


BaseplateWithCutout = _make_template_class(
    "BaseplateWithCutout",
    "baseplate_with_cutout",
    3,
    ["basic", "filleted"],
    _baseplate_opening_params,
    _baseplate_opening_code,
    _baseplate_opening_desc,
)


def _grid_plate_params(variant: str) -> dict:
    plate_width = _ru(90, 180)
    plate_height = _ru(70, 150)
    column_count = _ri(3, 6)
    row_count = _ri(2, 5)
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(COMMON_THICKNESS),
        "grid_hole_diameter": _rc([3.4, 4.5, 5.3, 6.6]),
        "column_count": column_count,
        "row_count": row_count,
        "grid_spacing_x": round(plate_width / (column_count + 1), 1),
        "grid_spacing_y": round(plate_height / (row_count + 1), 1),
        "chamfer_distance": _safe_chamfer(plate_width, plate_height),
    }


def _grid_plate_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("grid_hole_diameter", p["grid_hole_diameter"]),
        ("column_count", p["column_count"]),
        ("row_count", p["row_count"]),
        ("grid_spacing_x", p["grid_spacing_x"]),
        ("grid_spacing_y", p["grid_spacing_y"]),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    positions: list[tuple[str, str]] = []
    for column_index in range(p["column_count"]):
        x_value = round(-p["plate_width"] / 2 + (column_index + 1) * p["grid_spacing_x"], 1)
        assignments.append((f"grid_hole_x_{column_index + 1}", x_value))
        for row_index in range(p["row_count"]):
            y_value = round(-p["plate_height"] / 2 + (row_index + 1) * p["grid_spacing_y"], 1)
            name = f"grid_hole_y_{row_index + 1}"
            if (name, y_value) not in assignments:
                assignments.append((name, y_value))
            positions.append((f"grid_hole_x_{column_index + 1}", f"grid_hole_y_{row_index + 1}"))
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Multi-hole grid plate"),
        "# Grid mounting holes\n" + _manual_hole_block("grid_hole_diameter", positions, "grid_holes"),
    ]
    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _grid_plate_desc(p: dict, variant: str) -> list[str]:
    hole_count = p["column_count"] * p["row_count"]
    extra = f", {p['chamfer_distance']:.1f}mm top chamfer" if variant == "chamfered" else ""
    return _long_plate_descriptions(
        f"Grid plate with {hole_count} holes, {p['plate_thickness']:.0f}mm thick",
        (
            f"Multi-hole grid plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, {p['column_count']}x{p['row_count']} grid of "
            f"{p['grid_hole_diameter']:.1f}mm holes{extra}"
        ),
        (
            f"I need a rectangular plate around {p['plate_width']:.0f} by {p['plate_height']:.0f}mm "
            f"with a {p['column_count']} by {p['row_count']} grid of {p['grid_hole_diameter']:.1f}mm holes{extra}."
        ),
    )


MultiHoleGrid = _make_template_class(
    "MultiHoleGrid",
    "multi_hole_grid",
    3,
    ["basic", "chamfered"],
    _grid_plate_params,
    _grid_plate_code,
    _grid_plate_desc,
)


def _cover_plate_params(variant: str) -> dict:
    plate_width = _ru(80, 170)
    plate_height = _ru(60, 130)
    through_hole_diameter = _rc([3.4, 4.5, 5.3])
    relief_diameter = round(through_hole_diameter + _ru(2, 4), 1)
    edge_margin = round(min(plate_width, plate_height) * _ru(0.13, 0.18), 1)
    relief_depth = round(_rc([1.5, 2.0, 2.5]), 1)
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(COMMON_THICKNESS),
        "through_hole_diameter": through_hole_diameter,
        "relief_diameter": relief_diameter,
        "relief_depth": min(relief_depth, round(_rc(COMMON_THICKNESS) / 2, 1)),
        "edge_margin": edge_margin,
        "chamfer_distance": _safe_chamfer(plate_width, plate_height),
    }


def _cover_plate_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("through_hole_diameter", p["through_hole_diameter"]),
        ("relief_diameter", p["relief_diameter"]),
        ("relief_depth", p["relief_depth"]),
        ("edge_margin", p["edge_margin"]),
        ("mounting_hole_x", "plate_width / 2 - edge_margin"),
        ("mounting_hole_y", "plate_height / 2 - edge_margin"),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    positions = [
        ("mounting_hole_x", "mounting_hole_y"),
        ("-mounting_hole_x", "mounting_hole_y"),
        ("-mounting_hole_x", "-mounting_hole_y"),
        ("mounting_hole_x", "-mounting_hole_y"),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Cover plate"),
        "# Through mounting holes\n" + _manual_hole_block(
            "through_hole_diameter",
            positions,
            "mounting_through_holes",
        ),
        "# Shallow relief bores\n" + _manual_hole_block(
            "relief_diameter",
            positions,
            "mounting_relief_bores",
            through=False,
            depth_var="relief_depth",
        ),
    ]
    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _cover_plate_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['chamfer_distance']:.1f}mm top chamfer" if variant == "chamfered" else ""
    return _long_plate_descriptions(
        f"Cover plate with relief bores, {p['plate_thickness']:.0f}mm thick",
        (
            f"Cover plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, {p['plate_thickness']:.0f}mm thick, "
            f"4x {p['through_hole_diameter']:.1f}mm through holes with "
            f"{p['relief_diameter']:.1f}mm x {p['relief_depth']:.1f}mm relief bores{extra}"
        ),
        (
            f"I need a cover plate about {p['plate_width']:.0f} by {p['plate_height']:.0f}mm with four "
            f"mounting holes and shallow relief bores above them{extra}."
        ),
    )


CoverPlate = _make_template_class(
    "CoverPlate",
    "cover_plate",
    3,
    ["basic", "chamfered"],
    _cover_plate_params,
    _cover_plate_code,
    _cover_plate_desc,
)


def _adapter_plate_params(variant: str) -> dict:
    plate_width = _ru(90, 180)
    plate_height = _ru(90, 180)
    inner_bolt_size = _rc(["M3", "M4", "M5"])
    outer_bolt_size = _rc(["M5", "M6", "M8"])
    return {
        "plate_width": plate_width,
        "plate_height": plate_height,
        "plate_thickness": _rc(COMMON_THICKNESS),
        "center_bore_diameter": round(min(plate_width, plate_height) * _ru(0.16, 0.24), 1),
        "inner_bolt_size": inner_bolt_size,
        "outer_bolt_size": outer_bolt_size,
        "inner_hole_diameter": STANDARD_KNOWLEDGE["bolt_clearance"][inner_bolt_size],
        "outer_hole_diameter": STANDARD_KNOWLEDGE["bolt_clearance"][outer_bolt_size],
        "inner_pitch_circle_diameter": round(min(plate_width, plate_height) * _ru(0.34, 0.46), 1),
        "outer_pitch_circle_diameter": round(min(plate_width, plate_height) * _ru(0.56, 0.72), 1),
        "inner_hole_count": _rc([4, 6]),
        "outer_hole_count": _rc([6, 8]),
        "inner_start_angle": 0.0,
        "outer_start_angle": _rc([0.0, 22.5, 30.0]),
        "fillet_radius": _safe_fillet(plate_width, plate_height),
    }


def _adapter_plate_code(p: dict, variant: str) -> str:
    assignments = [
        ("plate_width", p["plate_width"]),
        ("plate_height", p["plate_height"]),
        ("plate_thickness", p["plate_thickness"]),
        ("center_bore_diameter", p["center_bore_diameter"]),
        ("inner_hole_diameter", p["inner_hole_diameter"]),
        ("outer_hole_diameter", p["outer_hole_diameter"]),
        ("inner_pitch_circle_diameter", p["inner_pitch_circle_diameter"]),
        ("outer_pitch_circle_diameter", p["outer_pitch_circle_diameter"]),
        ("inner_circle_radius", "inner_pitch_circle_diameter / 2"),
        ("outer_circle_radius", "outer_pitch_circle_diameter / 2"),
        ("inner_hole_count", p["inner_hole_count"]),
        ("outer_hole_count", p["outer_hole_count"]),
        ("inner_start_angle", p["inner_start_angle"]),
        ("outer_start_angle", p["outer_start_angle"]),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [
        _rect_part("plate_width", "plate_height", "plate_thickness", comment="Adapter plate"),
        "# Center bore\n" + _manual_hole_block("center_bore_diameter", [("center_x", "center_y")], "center_bore"),
        "# Inner bolt circle\n" + _circular_hole_block(
            "inner_hole_diameter",
            "inner_circle_radius",
            "inner_hole_count",
            "inner_start_angle",
            "inner_bolt_circle",
        ),
        "# Outer bolt circle\n" + _circular_hole_block(
            "outer_hole_diameter",
            "outer_circle_radius",
            "outer_hole_count",
            "outer_start_angle",
            "outer_bolt_circle",
        ),
    ]
    if variant == "filleted":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _adapter_plate_desc(p: dict, variant: str) -> list[str]:
    extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
    return _long_plate_descriptions(
        f"Adapter plate, {p['plate_thickness']:.0f}mm thick",
        (
            f"Adapter plate: {p['plate_width']:.0f}x{p['plate_height']:.0f}mm, "
            f"{p['plate_thickness']:.0f}mm thick, {p['center_bore_diameter']:.1f}mm center bore, "
            f"{p['inner_hole_count']}x {p['inner_hole_diameter']:.1f}mm holes on {p['inner_pitch_circle_diameter']:.0f}mm PCD, "
            f"{p['outer_hole_count']}x {p['outer_hole_diameter']:.1f}mm holes on {p['outer_pitch_circle_diameter']:.0f}mm PCD{extra}"
        ),
        (
            f"I need an adapter plate about {p['plate_width']:.0f} by {p['plate_height']:.0f}mm with "
            f"a center bore and two different bolt circles: an inner {p['inner_hole_count']}-hole pattern "
            f"and an outer {p['outer_hole_count']}-hole pattern{extra}."
        ),
    )


AdapterPlate = _make_template_class(
    "AdapterPlate",
    "adapter_plate",
    4,
    ["basic", "filleted"],
    _adapter_plate_params,
    _adapter_plate_code,
    _adapter_plate_desc,
)


# ---------------------------------------------------------------------------
# Category 2 - Brackets
# ---------------------------------------------------------------------------
def _bracket_params(kind: str, variant: str) -> dict:
    base_plate_width = _ru(70, 150)
    base_plate_depth = _ru(50, 110)
    upright_height = _ru(35, 90)
    upright_thickness = _rc([4.0, 5.0, 6.0, 8.0])
    base_plate_thickness = upright_thickness
    mounting_hole_diameter = _rc([4.5, 5.3, 6.6])
    edge_margin = round(min(base_plate_width, base_plate_depth) * _ru(0.14, 0.2), 1)
    params = {
        "base_plate_width": base_plate_width,
        "base_plate_depth": base_plate_depth,
        "base_plate_thickness": base_plate_thickness,
        "upright_height": upright_height,
        "upright_thickness": upright_thickness,
        "mounting_hole_diameter": mounting_hole_diameter,
        "edge_margin": edge_margin,
        "fillet_radius": _safe_fillet(base_plate_width, base_plate_depth, upright_height),
        "chamfer_distance": _safe_chamfer(base_plate_width, base_plate_depth),
    }
    if kind == "u_bracket":
        params["wall_spacing"] = round(base_plate_width * _ru(0.45, 0.62), 1)
    if kind in {"servo_bracket", "angle_bracket_slotted"}:
        params["servo_pattern_spacing_x"] = round(base_plate_width * _ru(0.45, 0.6), 1)
        params["servo_pattern_spacing_y"] = round(base_plate_depth * _ru(0.25, 0.4), 1)
    if kind == "z_bracket":
        params["upper_plate_width"] = round(base_plate_width * _ru(0.5, 0.7), 1)
        params["upper_plate_depth"] = round(base_plate_depth * _ru(0.45, 0.65), 1)
        params["step_height"] = round(upright_height * _ru(0.55, 0.7), 1)
    return params


def _bracket_code(kind: str, p: dict, variant: str) -> str:
    assignments = [
        ("base_plate_width", p["base_plate_width"]),
        ("base_plate_depth", p["base_plate_depth"]),
        ("base_plate_thickness", p["base_plate_thickness"]),
        ("upright_height", p["upright_height"]),
        ("upright_thickness", p["upright_thickness"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("edge_margin", p["edge_margin"]),
        ("base_plane_offset", "-base_plate_thickness / 2"),
        ("mounting_hole_x", "base_plate_width / 2 - edge_margin"),
        ("mounting_hole_y", "base_plate_depth / 2 - edge_margin"),
        ("rear_wall_offset", "base_plate_depth / 2 - upright_thickness / 2"),
        ("side_wall_offset", "base_plate_width / 2 - upright_thickness / 2"),
        ("fillet_radius", p["fillet_radius"]),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    sections = [
        _rect_part(
            "base_plate_width",
            "base_plate_depth",
            "base_plate_thickness",
            plane_expr="Plane.XY",
            offset_var="base_plane_offset",
            comment="Base bracket plate",
        )
    ]

    if kind in {"l_bracket", "gusset_triangle", "shelf_bracket", "angle_bracket_slotted"}:
        sections.append(
            _rect_part(
                "base_plate_width",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.XZ",
                offset_var="rear_wall_offset",
                part_name="upright_web",
                comment="Rear upright web",
            )
        )
        sections.append("# Join upright web\npart += upright_web")

    if kind == "u_bracket":
        assignments.append(("wall_spacing", p["wall_spacing"]))
        assignments.append(("left_wall_offset", "-wall_spacing / 2"))
        assignments.append(("right_wall_offset", "wall_spacing / 2"))
        sections.append(
            _rect_part(
                "base_plate_depth",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.YZ",
                offset_var="left_wall_offset",
                part_name="left_side_wall",
                comment="Left side wall",
            )
        )
        sections.append(
            _rect_part(
                "base_plate_depth",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.YZ",
                offset_var="right_wall_offset",
                part_name="right_side_wall",
                comment="Right side wall",
            )
        )
        sections.append("# Join side walls\npart += left_side_wall\npart += right_side_wall")

    if kind == "corner_bracket":
        sections.append(
            _rect_part(
                "base_plate_width",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.XZ",
                offset_var="rear_wall_offset",
                part_name="rear_wall",
                comment="Rear upright wall",
            )
        )
        sections.append(
            _rect_part(
                "base_plate_depth",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.YZ",
                offset_var="side_wall_offset",
                part_name="side_wall",
                comment="Side upright wall",
            )
        )
        sections.append("# Join upright walls\npart += rear_wall\npart += side_wall")

    if kind == "servo_bracket":
        assignments.extend(
            [
                ("servo_pattern_spacing_x", p["servo_pattern_spacing_x"]),
                ("servo_pattern_spacing_y", p["servo_pattern_spacing_y"]),
                ("servo_pattern_x", "servo_pattern_spacing_x / 2"),
                ("servo_pattern_y", "servo_pattern_spacing_y / 2"),
            ]
        )
        sections.append(
            _rect_part(
                "base_plate_width",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.XZ",
                offset_var="rear_wall_offset",
                part_name="support_web",
                comment="Support web",
            )
        )
        sections.append("# Join support web\npart += support_web")

    if kind == "shelf_bracket":
        assignments.append(("support_web_offset", "rear_wall_offset - upright_thickness"))
        sections.append(
            _rect_part(
                "base_plate_width",
                "upright_height",
                "upright_thickness",
                plane_expr="Plane.XZ",
                offset_var="support_web_offset",
                part_name="support_web",
                comment="Secondary support web",
            )
        )
        sections.append("# Join secondary support web\npart += support_web")

    if kind == "z_bracket":
        assignments.extend(
            [
                ("upper_plate_width", p["upper_plate_width"]),
                ("upper_plate_depth", p["upper_plate_depth"]),
                ("step_height", p["step_height"]),
            ]
        )
        sections.append(
            _rect_part(
                "upper_plate_width",
                "upper_plate_depth",
                "base_plate_thickness",
                plane_expr="Plane.XY",
                offset_var="step_height",
                part_name="upper_plate",
                comment="Upper stepped plate",
            )
        )
        sections.append(
            _rect_part(
                "upper_plate_depth",
                "step_height",
                "upright_thickness",
                plane_expr="Plane.YZ",
                offset_var="side_wall_offset",
                part_name="step_web",
                comment="Step web",
            )
        )
        sections.append("# Join stepped geometry\npart += upper_plate\npart += step_web")

    hole_positions = [
        ("mounting_hole_x", "mounting_hole_y"),
        ("-mounting_hole_x", "mounting_hole_y"),
    ]
    if kind not in {"servo_bracket", "angle_bracket_slotted"}:
        hole_positions.extend(
            [("-mounting_hole_x", "-mounting_hole_y"), ("mounting_hole_x", "-mounting_hole_y")]
        )

    if kind in {"servo_bracket", "angle_bracket_slotted"}:
        sections.append(
            "# Base mounting holes\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [
                    ("mounting_hole_x", "mounting_hole_y"),
                    ("-mounting_hole_x", "mounting_hole_y"),
                    ("mounting_hole_x", "-mounting_hole_y"),
                    ("-mounting_hole_x", "-mounting_hole_y"),
                ],
                "base_mount_holes",
            )
        )
    else:
        sections.append("# Base mounting holes\n" + _manual_hole_block("mounting_hole_diameter", hole_positions, "base_mount_holes"))

    if kind == "servo_bracket":
        sections.append(
            "# Servo mounting pattern\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [
                    ("servo_pattern_x", "servo_pattern_y"),
                    ("-servo_pattern_x", "servo_pattern_y"),
                    ("servo_pattern_x", "-servo_pattern_y"),
                    ("-servo_pattern_x", "-servo_pattern_y"),
                ],
                "servo_mount_pattern",
            )
        )

    if kind == "angle_bracket_slotted":
        assignments.extend(
            [
                ("slot_pair_offset", "mounting_hole_x / 2"),
                ("slot_pair_spacing", "mounting_hole_y / 3"),
            ]
        )
        sections.append(
            "# Paired clearance holes approximating slotted mounting\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [
                    ("slot_pair_offset", "slot_pair_spacing"),
                    ("slot_pair_offset", "-slot_pair_spacing"),
                    ("-slot_pair_offset", "slot_pair_spacing"),
                    ("-slot_pair_offset", "-slot_pair_spacing"),
                ],
                "paired_clearance_holes",
            )
        )

    if variant == "filleted":
        sections.extend(_variant_lines(variant))
    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _bracket_desc(kind: str, p: dict, variant: str) -> list[str]:
    variant_suffix = ""
    if variant == "filleted":
        variant_suffix = f", {p['fillet_radius']:.1f}mm edge fillet"
    elif variant == "chamfered":
        variant_suffix = f", {p['chamfer_distance']:.1f}mm top chamfer"

    if kind == "l_bracket":
        casual = f"L bracket body, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"L bracket body: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"{p['upright_height']:.0f}mm upright, 4x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )
    elif kind == "u_bracket":
        casual = f"U bracket body, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"U bracket body: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"{p['upright_height']:.0f}mm side walls, 4x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )
    elif kind == "gusset_triangle":
        casual = f"Gusset support bracket, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Gusset support bracket: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"{p['upright_height']:.0f}mm support web, 4x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )
    elif kind == "corner_bracket":
        casual = f"Corner bracket body, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Corner bracket body: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"two upright walls, 4x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )
    elif kind == "servo_bracket":
        casual = f"Servo bracket plate, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Servo bracket plate: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"4x base holes plus 4x servo pattern holes, support web{variant_suffix}"
        )
    elif kind == "shelf_bracket":
        casual = f"Shelf support bracket, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Shelf support bracket: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"dual support webs, 4x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )
    elif kind == "angle_bracket_slotted":
        casual = f"Angle bracket with paired holes, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Angle bracket: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm base, "
            f"upright web, base holes plus paired clearance holes{variant_suffix}"
        )
    else:
        casual = f"Stepped Z bracket, {p['base_plate_thickness']:.0f}mm thick"
        engineering = (
            f"Stepped Z bracket: {p['base_plate_width']:.0f}x{p['base_plate_depth']:.0f}mm lower plate, "
            f"{p['upper_plate_width']:.0f}x{p['upper_plate_depth']:.0f}mm upper plate, support web, "
            f"2x {p['mounting_hole_diameter']:.1f}mm base holes{variant_suffix}"
        )

    natural = f"I need a {engineering[0].lower() + engineering[1:]}"
    return _long_plate_descriptions(casual, engineering, natural + ".")


LBracket = _make_template_class(
    "LBracket",
    "l_bracket",
    3,
    ["basic", "filleted"],
    lambda variant: _bracket_params("l_bracket", variant),
    lambda params, variant: _bracket_code("l_bracket", params, variant),
    lambda params, variant: _bracket_desc("l_bracket", params, variant),
)

UBracket = _make_template_class(
    "UBracket",
    "u_bracket",
    4,
    ["basic", "filleted"],
    lambda variant: _bracket_params("u_bracket", variant),
    lambda params, variant: _bracket_code("u_bracket", params, variant),
    lambda params, variant: _bracket_desc("u_bracket", params, variant),
)

GussetTriangle = _make_template_class(
    "GussetTriangle",
    "gusset_triangle",
    3,
    ["basic", "filleted"],
    lambda variant: _bracket_params("gusset_triangle", variant),
    lambda params, variant: _bracket_code("gusset_triangle", params, variant),
    lambda params, variant: _bracket_desc("gusset_triangle", params, variant),
)

CornerBracket = _make_template_class(
    "CornerBracket",
    "corner_bracket",
    4,
    ["basic", "filleted"],
    lambda variant: _bracket_params("corner_bracket", variant),
    lambda params, variant: _bracket_code("corner_bracket", params, variant),
    lambda params, variant: _bracket_desc("corner_bracket", params, variant),
)

ServoBracket = _make_template_class(
    "ServoBracket",
    "servo_bracket",
    3,
    ["basic", "filleted"],
    lambda variant: _bracket_params("servo_bracket", variant),
    lambda params, variant: _bracket_code("servo_bracket", params, variant),
    lambda params, variant: _bracket_desc("servo_bracket", params, variant),
)

ShelfBracket = _make_template_class(
    "ShelfBracket",
    "shelf_bracket",
    4,
    ["basic", "filleted"],
    lambda variant: _bracket_params("shelf_bracket", variant),
    lambda params, variant: _bracket_code("shelf_bracket", params, variant),
    lambda params, variant: _bracket_desc("shelf_bracket", params, variant),
)

AngleBracketSlotted = _make_template_class(
    "AngleBracketSlotted",
    "angle_bracket_slotted",
    4,
    ["basic", "chamfered"],
    lambda variant: _bracket_params("angle_bracket_slotted", variant),
    lambda params, variant: _bracket_code("angle_bracket_slotted", params, variant),
    lambda params, variant: _bracket_desc("angle_bracket_slotted", params, variant),
)

ZBracket = _make_template_class(
    "ZBracket",
    "z_bracket",
    4,
    ["basic", "filleted"],
    lambda variant: _bracket_params("z_bracket", variant),
    lambda params, variant: _bracket_code("z_bracket", params, variant),
    lambda params, variant: _bracket_desc("z_bracket", params, variant),
)


# ---------------------------------------------------------------------------
# Category 3 and 6 - Cylindrical parts, shafts, and pins
# ---------------------------------------------------------------------------
def _cyl_params(kind: str, variant: str) -> dict:
    if kind == "washer":
        inner_diameter = _rc([3.4, 4.5, 5.3, 6.6, 9.0])
        outer_diameter = round(inner_diameter * _ru(2.0, 2.8), 1)
        thickness = _rc([1.0, 1.5, 2.0, 2.5, 3.0])
        return {
            "outer_diameter": outer_diameter,
            "inner_diameter": inner_diameter,
            "part_thickness": thickness,
            "chamfer_distance": _safe_chamfer(outer_diameter - inner_diameter, thickness),
        }
    if kind in {"spacer_ring", "adapter_sleeve", "adapter_sleeve_long"}:
        inner_diameter = _rc([6.6, 9.0, 11.0, 13.5])
        wall_thickness = _ru(2.5, 6.0)
        return {
            "outer_diameter": round(inner_diameter + wall_thickness * 2, 1),
            "inner_diameter": inner_diameter,
            "part_thickness": _ru(6, 20) if kind == "spacer_ring" else (_ru(16, 50) if kind == "adapter_sleeve" else _ru(40, 90)),
            "chamfer_distance": _safe_chamfer(inner_diameter, wall_thickness),
        }
    if kind in {"flanged_bushing", "shoulder_spacer", "stepped_shaft"}:
        shaft_diameter = _ru(10, 24)
        shoulder_diameter = round(shaft_diameter + _ru(6, 14), 1)
        flange_diameter = round(shoulder_diameter + _ru(6, 14), 1)
        return {
            "shaft_diameter": round(shaft_diameter, 1),
            "shoulder_diameter": shoulder_diameter,
            "flange_diameter": flange_diameter,
            "bore_diameter": round(max(shaft_diameter - _ru(2, 5), 4.0), 1),
            "body_length": _ru(12, 40),
            "shoulder_length": _ru(5, 16),
            "flange_thickness": _ru(4, 10),
            "chamfer_distance": _safe_chamfer(shaft_diameter, shoulder_diameter),
        }
    if kind == "threaded_standoff":
        clearance_diameter = _rc([3.4, 4.5, 5.3, 6.6])
        return {
            "outer_diameter": round(clearance_diameter + _ru(5, 10), 1),
            "inner_diameter": clearance_diameter,
            "part_thickness": _ru(10, 35),
            "chamfer_distance": _safe_chamfer(clearance_diameter, 10.0),
        }
    if kind == "dowel_pin":
        pin_diameter = _rc([4.0, 5.0, 6.0, 8.0, 10.0])
        return {
            "outer_diameter": pin_diameter,
            "part_thickness": _ru(20, 80),
            "chamfer_distance": _safe_chamfer(pin_diameter, pin_diameter),
        }
    if kind == "shaft_collar":
        shaft_diameter = _rc([12.0, 16.0, 20.0, 25.0])
        outer_diameter = round(shaft_diameter + _ru(10, 18), 1)
        return {
            "outer_diameter": outer_diameter,
            "inner_diameter": shaft_diameter,
            "part_thickness": _ru(8, 18),
            "set_screw_hole_diameter": _rc([3.4, 4.5, 5.3]),
            "set_screw_hole_offset_x": round(outer_diameter * 0.25, 1),
            "set_screw_hole_offset_y": 0.0,
            "chamfer_distance": _safe_chamfer(outer_diameter, shaft_diameter),
        }
    raise ValueError(f"Unsupported cylindrical template kind: {kind}")


def _cyl_code(kind: str, p: dict, variant: str) -> str:
    assignments: list[tuple[str, object]] = []
    sections: list[str] = []

    if kind in {"washer", "spacer_ring", "adapter_sleeve", "adapter_sleeve_long", "threaded_standoff"}:
        assignments.extend(
            [
                ("outer_diameter", p["outer_diameter"]),
                ("inner_diameter", p["inner_diameter"]),
                ("part_thickness", p["part_thickness"]),
                ("center_x", 0.0),
                ("center_y", 0.0),
                ("chamfer_distance", p["chamfer_distance"]),
            ]
        )
        sections.append(_circle_part("outer_diameter", "part_thickness", comment="Cylindrical body"))
        sections.append("# Through bore\n" + _manual_hole_block("inner_diameter", [("center_x", "center_y")], "center_bore"))

    elif kind in {"flanged_bushing", "shoulder_spacer"}:
        assignments.extend(
            [
                ("shaft_diameter", p["shaft_diameter"]),
                ("shoulder_diameter", p["shoulder_diameter"]),
                ("flange_diameter", p["flange_diameter"]),
                ("bore_diameter", p["bore_diameter"]),
                ("body_length", p["body_length"]),
                ("shoulder_length", p["shoulder_length"]),
                ("flange_thickness", p["flange_thickness"]),
                ("center_x", 0.0),
                ("center_y", 0.0),
                ("chamfer_distance", p["chamfer_distance"]),
            ]
        )
        sections.append(_circle_part("shoulder_diameter", "body_length", comment="Main cylindrical body"))
        sections.append(
            _circle_part(
                "flange_diameter" if kind == "flanged_bushing" else "shaft_diameter",
                "flange_thickness" if kind == "flanged_bushing" else "shoulder_length",
                offset_var="body_length",
                part_name="upper_step",
                comment="Upper stepped feature",
            )
        )
        sections.append("# Join stepped feature\npart += upper_step")
        sections.append("# Through bore\n" + _manual_hole_block("bore_diameter", [("center_x", "center_y")], "center_bore"))

    elif kind == "stepped_shaft":
        assignments.extend(
            [
                ("shaft_diameter", p["shaft_diameter"]),
                ("shoulder_diameter", p["shoulder_diameter"]),
                ("body_length", p["body_length"]),
                ("shoulder_length", p["shoulder_length"]),
                ("chamfer_distance", p["chamfer_distance"]),
            ]
        )
        sections.append(_circle_part("shoulder_diameter", "shoulder_length", comment="Primary shaft section"))
        sections.append(
            _circle_part(
                "shaft_diameter",
                "body_length",
                offset_var="shoulder_length",
                part_name="upper_shaft",
                comment="Secondary shaft step",
            )
        )
        sections.append("# Join shaft step\npart += upper_shaft")

    elif kind == "dowel_pin":
        assignments.extend(
            [
                ("outer_diameter", p["outer_diameter"]),
                ("part_thickness", p["part_thickness"]),
                ("chamfer_distance", p["chamfer_distance"]),
            ]
        )
        sections.append(_circle_part("outer_diameter", "part_thickness", comment="Dowel pin body"))

    elif kind == "shaft_collar":
        assignments.extend(
            [
                ("outer_diameter", p["outer_diameter"]),
                ("inner_diameter", p["inner_diameter"]),
                ("part_thickness", p["part_thickness"]),
                ("set_screw_hole_diameter", p["set_screw_hole_diameter"]),
                ("set_screw_hole_offset_x", p["set_screw_hole_offset_x"]),
                ("set_screw_hole_offset_y", p["set_screw_hole_offset_y"]),
                ("center_x", 0.0),
                ("center_y", 0.0),
                ("chamfer_distance", p["chamfer_distance"]),
            ]
        )
        sections.append(_circle_part("outer_diameter", "part_thickness", comment="Shaft collar body"))
        sections.append("# Shaft bore\n" + _manual_hole_block("inner_diameter", [("center_x", "center_y")], "shaft_bore"))
        sections.append(
            "# Top set-screw hole\n"
            + _manual_hole_block(
                "set_screw_hole_diameter",
                [("set_screw_hole_offset_x", "set_screw_hole_offset_y")],
                "set_screw_hole",
            )
        )

    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _cyl_desc(kind: str, p: dict, variant: str) -> list[str]:
    extra = f", {p['chamfer_distance']:.1f}mm chamfer" if variant == "chamfered" else ""
    if kind == "washer":
        casual = f"Washer, {p['part_thickness']:.1f}mm thick"
        engineering = f"Washer: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm ID, {p['part_thickness']:.1f}mm thick{extra}"
    elif kind == "spacer_ring":
        casual = f"Spacer ring, {p['part_thickness']:.0f}mm long"
        engineering = f"Spacer ring: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm ID, {p['part_thickness']:.1f}mm long{extra}"
    elif kind == "flanged_bushing":
        casual = f"Flanged bushing, {p['body_length']:.0f}mm long"
        engineering = (
            f"Flanged bushing: {p['shoulder_diameter']:.1f}mm body diameter, {p['flange_diameter']:.1f}mm flange, "
            f"{p['bore_diameter']:.1f}mm bore, {p['body_length']:.1f}mm body length{extra}"
        )
    elif kind == "shoulder_spacer":
        casual = f"Shoulder spacer, {p['body_length']:.0f}mm long"
        engineering = (
            f"Shoulder spacer: {p['shoulder_diameter']:.1f}mm body diameter, {p['shaft_diameter']:.1f}mm upper step, "
            f"{p['bore_diameter']:.1f}mm bore, {p['body_length']:.1f}mm body length{extra}"
        )
    elif kind == "threaded_standoff":
        casual = f"Threaded standoff blank, {p['part_thickness']:.0f}mm long"
        engineering = f"Threaded standoff blank: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm through bore, {p['part_thickness']:.1f}mm long{extra}"
    elif kind == "adapter_sleeve":
        casual = f"Adapter sleeve, {p['part_thickness']:.0f}mm long"
        engineering = f"Adapter sleeve: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm ID, {p['part_thickness']:.1f}mm long{extra}"
    elif kind == "adapter_sleeve_long":
        casual = f"Long adapter sleeve, {p['part_thickness']:.0f}mm long"
        engineering = f"Long adapter sleeve: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm ID, {p['part_thickness']:.1f}mm long{extra}"
    elif kind == "stepped_shaft":
        casual = f"Stepped shaft, {p['body_length'] + p['shoulder_length']:.0f}mm overall"
        engineering = f"Stepped shaft: {p['shoulder_diameter']:.1f}mm lower step, {p['shaft_diameter']:.1f}mm upper step, {p['body_length'] + p['shoulder_length']:.1f}mm overall{extra}"
    elif kind == "dowel_pin":
        casual = f"Dowel pin, {p['part_thickness']:.0f}mm long"
        engineering = f"Dowel pin: {p['outer_diameter']:.1f}mm diameter, {p['part_thickness']:.1f}mm long{extra}"
    else:
        casual = f"Shaft collar, {p['part_thickness']:.0f}mm thick"
        engineering = f"Shaft collar: {p['outer_diameter']:.1f}mm OD, {p['inner_diameter']:.1f}mm bore, {p['set_screw_hole_diameter']:.1f}mm top set-screw hole{extra}"
    natural = f"I need a {engineering[0].lower() + engineering[1:]}."
    return _long_plate_descriptions(casual, engineering, natural)


SpacerRing = _make_template_class(
    "SpacerRing",
    "spacer_ring",
    2,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("spacer_ring", variant),
    lambda params, variant: _cyl_code("spacer_ring", params, variant),
    lambda params, variant: _cyl_desc("spacer_ring", params, variant),
)

WasherTemplate = _make_template_class(
    "WasherTemplate",
    "washer",
    2,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("washer", variant),
    lambda params, variant: _cyl_code("washer", params, variant),
    lambda params, variant: _cyl_desc("washer", params, variant),
)

FlangedBushing = _make_template_class(
    "FlangedBushing",
    "flanged_bushing",
    3,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("flanged_bushing", variant),
    lambda params, variant: _cyl_code("flanged_bushing", params, variant),
    lambda params, variant: _cyl_desc("flanged_bushing", params, variant),
)

ShoulderSpacer = _make_template_class(
    "ShoulderSpacer",
    "shoulder_spacer",
    3,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("shoulder_spacer", variant),
    lambda params, variant: _cyl_code("shoulder_spacer", params, variant),
    lambda params, variant: _cyl_desc("shoulder_spacer", params, variant),
)

ThreadedStandoff = _make_template_class(
    "ThreadedStandoff",
    "threaded_standoff",
    2,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("threaded_standoff", variant),
    lambda params, variant: _cyl_code("threaded_standoff", params, variant),
    lambda params, variant: _cyl_desc("threaded_standoff", params, variant),
)

AdapterSleeve = _make_template_class(
    "AdapterSleeve",
    "adapter_sleeve",
    2,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("adapter_sleeve", variant),
    lambda params, variant: _cyl_code("adapter_sleeve", params, variant),
    lambda params, variant: _cyl_desc("adapter_sleeve", params, variant),
)

SteppedShaft = _make_template_class(
    "SteppedShaft",
    "stepped_shaft",
    3,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("stepped_shaft", variant),
    lambda params, variant: _cyl_code("stepped_shaft", params, variant),
    lambda params, variant: _cyl_desc("stepped_shaft", params, variant),
)

DowelPin = _make_template_class(
    "DowelPin",
    "dowel_pin",
    1,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("dowel_pin", variant),
    lambda params, variant: _cyl_code("dowel_pin", params, variant),
    lambda params, variant: _cyl_desc("dowel_pin", params, variant),
)

AdapterSleeveLong = _make_template_class(
    "AdapterSleeveLong",
    "adapter_sleeve_long",
    2,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("adapter_sleeve_long", variant),
    lambda params, variant: _cyl_code("adapter_sleeve_long", params, variant),
    lambda params, variant: _cyl_desc("adapter_sleeve_long", params, variant),
)

ShaftCollar = _make_template_class(
    "ShaftCollar",
    "shaft_collar",
    3,
    ["basic", "chamfered"],
    lambda variant: _cyl_params("shaft_collar", variant),
    lambda params, variant: _cyl_code("shaft_collar", params, variant),
    lambda params, variant: _cyl_desc("shaft_collar", params, variant),
)


# ---------------------------------------------------------------------------
# Category 4 - Flanges
# ---------------------------------------------------------------------------
def _flange_params(kind: str, variant: str) -> dict:
    outer_diameter = _ru(80, 180)
    bolt_size = _rc(["M4", "M5", "M6", "M8"])
    params = {
        "outer_diameter": outer_diameter,
        "part_thickness": _rc([6.0, 8.0, 10.0, 12.0]),
        "bolt_hole_diameter": STANDARD_KNOWLEDGE["bolt_clearance"][bolt_size],
        "bolt_hole_count": _rc([4, 6, 8]),
        "bolt_pitch_circle_diameter": round(outer_diameter * _ru(0.58, 0.78), 1),
        "bolt_start_angle": _rc([0.0, 22.5, 30.0]),
        "fillet_radius": _safe_fillet(outer_diameter, outer_diameter),
        "chamfer_distance": _safe_chamfer(outer_diameter, outer_diameter),
        "bolt_size": bolt_size,
    }
    if kind == "pipe_flange":
        params["center_bore_diameter"] = round(outer_diameter * _ru(0.25, 0.45), 1)
    elif kind == "bearing_retainer":
        bearing_code = _rc(list(STANDARD_KNOWLEDGE["bearings"].keys()))
        bore, outer, width = STANDARD_KNOWLEDGE["bearings"][bearing_code]
        params["bearing_code"] = bearing_code
        params["center_bore_diameter"] = float(outer)
        params["outer_diameter"] = round(outer + _ru(18, 40), 1)
        params["bolt_pitch_circle_diameter"] = round((params["outer_diameter"] + outer) / 2, 1)
        params["bearing_width"] = float(width)
    elif kind == "motor_adapter_flange":
        inner_frame = STANDARD_KNOWLEDGE["nema"][_rc(["NEMA17", "NEMA23"])]
        params["center_bore_diameter"] = round(inner_frame["pilot"] * _ru(1.0, 1.2), 1)
        params["inner_hole_diameter"] = STANDARD_KNOWLEDGE["bolt_clearance"][inner_frame["bolt"]]
        params["inner_hole_count"] = 4
        params["inner_pitch_circle_diameter"] = inner_frame["pcd"]
        params["inner_start_angle"] = 45.0
    elif kind == "blind_flange":
        params["center_bore_diameter"] = 0.0
    elif kind == "reducing_flange":
        params["center_bore_diameter"] = round(outer_diameter * _ru(0.22, 0.4), 1)
        params["hub_diameter"] = round(params["center_bore_diameter"] + _ru(14, 24), 1)
        params["hub_height"] = _ru(6, 14)
    elif kind == "coupler_flange":
        params["center_bore_diameter"] = round(outer_diameter * _ru(0.22, 0.34), 1)
        params["inner_hole_diameter"] = _rc([3.4, 4.5, 5.3])
        params["inner_hole_count"] = _rc([3, 4, 6])
        params["inner_pitch_circle_diameter"] = round(outer_diameter * _ru(0.32, 0.46), 1)
        params["inner_start_angle"] = 0.0
    return params


def _flange_code(kind: str, p: dict, variant: str) -> str:
    assignments = [
        ("outer_diameter", p["outer_diameter"]),
        ("part_thickness", p["part_thickness"]),
        ("bolt_hole_diameter", p["bolt_hole_diameter"]),
        ("bolt_hole_count", p["bolt_hole_count"]),
        ("bolt_pitch_circle_diameter", p["bolt_pitch_circle_diameter"]),
        ("bolt_circle_radius", "bolt_pitch_circle_diameter / 2"),
        ("bolt_start_angle", p["bolt_start_angle"]),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    sections = [_circle_part("outer_diameter", "part_thickness", comment="Flange body")]

    if variant == "filleted":
        sections.extend(_top_bottom_fillet_lines())

    if kind != "blind_flange":
        assignments.append(("center_bore_diameter", p["center_bore_diameter"]))
        sections.append("# Center bore\n" + _manual_hole_block("center_bore_diameter", [("center_x", "center_y")], "center_bore"))

    sections.append(
        "# Outer bolt circle\n"
        + _circular_hole_block(
            "bolt_hole_diameter",
            "bolt_circle_radius",
            "bolt_hole_count",
            "bolt_start_angle",
            "outer_bolt_circle",
        )
    )

    if kind == "bearing_retainer":
        assignments.append(("bearing_width", p["bearing_width"]))
    if kind in {"motor_adapter_flange", "coupler_flange"}:
        assignments.extend(
            [
                ("inner_hole_diameter", p["inner_hole_diameter"]),
                ("inner_hole_count", p["inner_hole_count"]),
                ("inner_pitch_circle_diameter", p["inner_pitch_circle_diameter"]),
                ("inner_circle_radius", "inner_pitch_circle_diameter / 2"),
                ("inner_start_angle", p["inner_start_angle"]),
            ]
        )
        sections.append(
            "# Inner bolt circle\n"
            + _circular_hole_block(
                "inner_hole_diameter",
                "inner_circle_radius",
                "inner_hole_count",
                "inner_start_angle",
                "inner_bolt_circle",
            )
        )
    if kind == "reducing_flange":
        assignments.extend([("hub_diameter", p["hub_diameter"]), ("hub_height", p["hub_height"])])
        sections.append(
            _circle_part(
                "hub_diameter",
                "hub_height",
                offset_var="part_thickness",
                part_name="hub",
                comment="Raised reducing hub",
            )
        )
        sections.append("# Join hub feature\npart += hub")

    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _flange_desc(kind: str, p: dict, variant: str) -> list[str]:
    extra = ""
    if variant == "filleted":
        extra = f", {p['fillet_radius']:.1f}mm edge fillet"
    elif variant == "chamfered":
        extra = f", {p['chamfer_distance']:.1f}mm top chamfer"
    if kind == "pipe_flange":
        engineering = (
            f"Pipe flange: {p['outer_diameter']:.0f}mm OD, {p['part_thickness']:.0f}mm thick, "
            f"{p['center_bore_diameter']:.1f}mm bore, {p['bolt_hole_count']}x {p['bolt_size']} holes on "
            f"{p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    elif kind == "bearing_retainer":
        engineering = (
            f"Bearing retainer: {p['outer_diameter']:.0f}mm OD, {p['center_bore_diameter']:.1f}mm bearing bore "
            f"for bearing {p['bearing_code']}, {p['bolt_hole_count']}x bolt holes on {p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    elif kind == "motor_adapter_flange":
        engineering = (
            f"Motor adapter flange: {p['outer_diameter']:.0f}mm OD, {p['center_bore_diameter']:.1f}mm bore, "
            f"4x inner motor holes on {p['inner_pitch_circle_diameter']:.1f}mm PCD and "
            f"{p['bolt_hole_count']}x outer bolt holes on {p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    elif kind == "blind_flange":
        engineering = (
            f"Blind flange: {p['outer_diameter']:.0f}mm OD, {p['part_thickness']:.0f}mm thick, "
            f"{p['bolt_hole_count']}x bolt holes on {p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    elif kind == "reducing_flange":
        engineering = (
            f"Reducing flange: {p['outer_diameter']:.0f}mm OD, {p['center_bore_diameter']:.1f}mm bore, "
            f"{p['hub_diameter']:.1f}mm raised hub, {p['bolt_hole_count']}x bolt holes on "
            f"{p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    else:
        engineering = (
            f"Coupler flange: {p['outer_diameter']:.0f}mm OD, {p['center_bore_diameter']:.1f}mm bore, "
            f"{p['inner_hole_count']}x inner holes on {p['inner_pitch_circle_diameter']:.0f}mm PCD and "
            f"{p['bolt_hole_count']}x outer holes on {p['bolt_pitch_circle_diameter']:.0f}mm PCD{extra}"
        )
    casual = engineering.split(":")[0] + f", {p['part_thickness']:.0f}mm thick"
    natural = f"I need a {engineering[0].lower() + engineering[1:]}."
    return _long_plate_descriptions(casual, engineering, natural)


PipeFlangeTemplate = _make_template_class(
    "PipeFlangeTemplate",
    "pipe_flange",
    3,
    ["basic", "chamfered"],
    lambda variant: _flange_params("pipe_flange", variant),
    lambda params, variant: _flange_code("pipe_flange", params, variant),
    lambda params, variant: _flange_desc("pipe_flange", params, variant),
)

BearingRetainer = _make_template_class(
    "BearingRetainer",
    "bearing_retainer",
    4,
    ["basic", "filleted"],
    lambda variant: _flange_params("bearing_retainer", variant),
    lambda params, variant: _flange_code("bearing_retainer", params, variant),
    lambda params, variant: _flange_desc("bearing_retainer", params, variant),
)

MotorAdapterFlange = _make_template_class(
    "MotorAdapterFlange",
    "motor_adapter_flange",
    4,
    ["basic", "filleted"],
    lambda variant: _flange_params("motor_adapter_flange", variant),
    lambda params, variant: _flange_code("motor_adapter_flange", params, variant),
    lambda params, variant: _flange_desc("motor_adapter_flange", params, variant),
)

BlindFlange = _make_template_class(
    "BlindFlange",
    "blind_flange",
    2,
    ["basic", "chamfered"],
    lambda variant: _flange_params("blind_flange", variant),
    lambda params, variant: _flange_code("blind_flange", params, variant),
    lambda params, variant: _flange_desc("blind_flange", params, variant),
)

ReducingFlange = _make_template_class(
    "ReducingFlange",
    "reducing_flange",
    4,
    ["basic", "chamfered"],
    lambda variant: _flange_params("reducing_flange", variant),
    lambda params, variant: _flange_code("reducing_flange", params, variant),
    lambda params, variant: _flange_desc("reducing_flange", params, variant),
)

CouplerFlange = _make_template_class(
    "CouplerFlange",
    "coupler_flange",
    4,
    ["basic", "filleted"],
    lambda variant: _flange_params("coupler_flange", variant),
    lambda params, variant: _flange_code("coupler_flange", params, variant),
    lambda params, variant: _flange_desc("coupler_flange", params, variant),
)


# ---------------------------------------------------------------------------
# Category 5, 7, 8, 9, 10 - Shells, clamps, heat, structural, complex
# ---------------------------------------------------------------------------
def _shell_box_params(kind: str, variant: str) -> dict:
    body_width = _ru(60, 140)
    body_depth = _ru(45, 120)
    body_height = _ru(20, 70)
    wall_thickness = _safe_wall(body_width, body_depth, body_height)
    params = {
        "body_width": body_width,
        "body_depth": body_depth,
        "body_height": body_height,
        "wall_thickness": wall_thickness,
        "fillet_radius": _safe_fillet(body_width, body_depth, body_height),
        "mounting_hole_diameter": _rc([3.4, 4.5, 5.3]),
        "edge_margin": round(min(body_width, body_depth) * _ru(0.14, 0.18), 1),
    }
    if kind == "sensor_housing_round":
        params["outer_diameter"] = _ru(50, 110)
        params["body_height"] = _ru(25, 70)
        params["wall_thickness"] = _safe_wall(params["outer_diameter"], params["body_height"])
        params["wire_hole_diameter"] = _rc([3.4, 4.5, 5.3, 6.6])
    if kind == "display_bezel":
        params["window_diameter"] = round(min(body_width, body_depth) * _ru(0.35, 0.55), 1)
    if kind == "junction_box":
        params["cable_hole_diameter"] = _rc([5.3, 6.6, 9.0])
    if kind == "battery_compartment":
        params["contact_hole_diameter"] = _rc([3.4, 4.5])
        params["contact_spacing"] = round(body_width * _ru(0.25, 0.4), 1)
    return params


def _shell_box_code(kind: str, p: dict, variant: str) -> str:
    assignments: list[tuple[str, object]] = [
        ("body_width", p.get("body_width", 0.0)),
        ("body_depth", p.get("body_depth", 0.0)),
        ("body_height", p["body_height"]),
        ("wall_thickness", p["wall_thickness"]),
        ("fillet_radius", p["fillet_radius"]),
        ("mounting_hole_diameter", p.get("mounting_hole_diameter", 3.4)),
        ("edge_margin", p.get("edge_margin", 10.0)),
        ("mounting_hole_x", "body_width / 2 - edge_margin"),
        ("mounting_hole_y", "body_depth / 2 - edge_margin"),
        ("center_x", 0.0),
        ("center_y", 0.0),
    ]
    sections: list[str] = []
    if kind == "sensor_housing_round":
        assignments.extend(
            [
                ("outer_diameter", p["outer_diameter"]),
                ("wire_hole_diameter", p["wire_hole_diameter"]),
                ("wire_hole_x", "outer_diameter / 4"),
            ]
        )
        sections.append(_circle_part("outer_diameter", "body_height", comment="Round housing body"))
    else:
        sections.append(_rect_part("body_width", "body_depth", "body_height", comment="Housing body"))

    if variant == "filleted":
        if kind == "sensor_housing_round":
            sections.extend(_top_bottom_fillet_lines())
        else:
            sections.append('# Variant feature: fillet outer vertical edges\npart = part.fillet(fillet_radius, edges="vertical")')

    sections.append('# Shell the body\npart = part.shell(wall_thickness, open_face="top")')

    if kind == "electronics_enclosure":
        sections.append(
            "# Corner mounting holes\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [
                    ("mounting_hole_x", "mounting_hole_y"),
                    ("-mounting_hole_x", "mounting_hole_y"),
                    ("-mounting_hole_x", "-mounting_hole_y"),
                    ("mounting_hole_x", "-mounting_hole_y"),
                ],
                "corner_mount_holes",
            )
        )
    elif kind == "sensor_housing_round":
        sections.append(
            "# Wire exit hole\n"
            + _manual_hole_block("wire_hole_diameter", [("wire_hole_x", "center_y")], "wire_exit_hole")
        )
    elif kind == "junction_box":
        assignments.append(("cable_hole_diameter", p["cable_hole_diameter"]))
        sections.append(
            "# Cable entry holes in the base\n"
            + _manual_hole_block(
                "cable_hole_diameter",
                [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
                "cable_entry_holes",
            )
        )
    elif kind == "battery_compartment":
        assignments.extend(
            [
                ("contact_hole_diameter", p["contact_hole_diameter"]),
                ("contact_spacing", p["contact_spacing"]),
                ("contact_x", "contact_spacing / 2"),
            ]
        )
        sections.append(
            "# Contact pin holes\n"
            + _manual_hole_block(
                "contact_hole_diameter",
                [("contact_x", "center_y"), ("-contact_x", "center_y")],
                "contact_pin_holes",
            )
        )
    elif kind == "display_bezel":
        assignments.append(("window_diameter", p["window_diameter"]))
        sections.append(
            "# Viewing opening\n"
            + _manual_hole_block("window_diameter", [("center_x", "center_y")], "viewing_window")
        )
    return _render_code(assignments, sections)


def _shell_box_desc(kind: str, p: dict, variant: str) -> list[str]:
    extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
    if kind == "open_box":
        engineering = f"Open box: {p['body_width']:.0f}x{p['body_depth']:.0f}x{p['body_height']:.0f}mm, shelled with {p['wall_thickness']:.1f}mm walls{extra}"
    elif kind == "electronics_enclosure":
        engineering = f"Electronics enclosure: {p['body_width']:.0f}x{p['body_depth']:.0f}x{p['body_height']:.0f}mm, {p['wall_thickness']:.1f}mm walls, 4x corner mounting holes{extra}"
    elif kind == "sensor_housing_round":
        engineering = f"Round sensor housing: {p['outer_diameter']:.0f}mm OD, {p['body_height']:.0f}mm tall, {p['wall_thickness']:.1f}mm walls, {p['wire_hole_diameter']:.1f}mm wire exit hole{extra}"
    elif kind == "junction_box":
        engineering = f"Junction box: {p['body_width']:.0f}x{p['body_depth']:.0f}x{p['body_height']:.0f}mm, {p['wall_thickness']:.1f}mm walls, 2x cable entry holes{extra}"
    elif kind == "battery_compartment":
        engineering = f"Battery compartment: {p['body_width']:.0f}x{p['body_depth']:.0f}x{p['body_height']:.0f}mm, {p['wall_thickness']:.1f}mm walls, 2x contact pin holes{extra}"
    else:
        engineering = f"Display bezel body: {p['body_width']:.0f}x{p['body_depth']:.0f}x{p['body_height']:.0f}mm, {p['wall_thickness']:.1f}mm walls, {p['window_diameter']:.1f}mm viewing opening{extra}"
    casual = engineering.split(":")[0] + f", {p['body_height']:.0f}mm tall"
    natural = f"I need a {engineering[0].lower() + engineering[1:]}."
    return _long_plate_descriptions(casual, engineering, natural)


OpenBox = _make_template_class("OpenBox", "open_box", 3, ["basic", "filleted"], lambda variant: _shell_box_params("open_box", variant), lambda params, variant: _shell_box_code("open_box", params, variant), lambda params, variant: _shell_box_desc("open_box", params, variant))
ElectronicsEnclosure = _make_template_class("ElectronicsEnclosure", "electronics_enclosure", 4, ["basic", "filleted"], lambda variant: _shell_box_params("electronics_enclosure", variant), lambda params, variant: _shell_box_code("electronics_enclosure", params, variant), lambda params, variant: _shell_box_desc("electronics_enclosure", params, variant))
SensorHousingRound = _make_template_class("SensorHousingRound", "sensor_housing_round", 4, ["basic", "filleted"], lambda variant: _shell_box_params("sensor_housing_round", variant), lambda params, variant: _shell_box_code("sensor_housing_round", params, variant), lambda params, variant: _shell_box_desc("sensor_housing_round", params, variant))
JunctionBox = _make_template_class("JunctionBox", "junction_box", 4, ["basic", "filleted"], lambda variant: _shell_box_params("junction_box", variant), lambda params, variant: _shell_box_code("junction_box", params, variant), lambda params, variant: _shell_box_desc("junction_box", params, variant))
BatteryCompartment = _make_template_class("BatteryCompartment", "battery_compartment", 4, ["basic", "filleted"], lambda variant: _shell_box_params("battery_compartment", variant), lambda params, variant: _shell_box_code("battery_compartment", params, variant), lambda params, variant: _shell_box_desc("battery_compartment", params, variant))
DisplayBezel = _make_template_class("DisplayBezel", "display_bezel", 4, ["basic", "filleted"], lambda variant: _shell_box_params("display_bezel", variant), lambda params, variant: _shell_box_code("display_bezel", params, variant), lambda params, variant: _shell_box_desc("display_bezel", params, variant))


def _simple_block_params(kind: str, variant: str) -> dict:
    block_width = _ru(40, 120)
    block_depth = _ru(20, 70)
    block_height = _ru(10, 35)
    return {
        "block_width": block_width,
        "block_depth": block_depth,
        "block_height": block_height,
        "channel_diameter": round(min(block_width, block_depth) * _ru(0.25, 0.45), 1),
        "mounting_hole_diameter": _rc([3.4, 4.5, 5.3]),
        "hole_spacing": round(block_width * _ru(0.4, 0.6), 1),
        "fillet_radius": _safe_fillet(block_width, block_depth, block_height),
        "chamfer_distance": _safe_chamfer(block_width, block_depth),
    }


def _simple_block_code(kind: str, p: dict, variant: str) -> str:
    assignments = [
        ("block_width", p["block_width"]),
        ("block_depth", p["block_depth"]),
        ("block_height", p["block_height"]),
        ("channel_diameter", p["channel_diameter"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("hole_spacing", p["hole_spacing"]),
        ("mounting_hole_x", "hole_spacing / 2"),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
        ("chamfer_distance", p["chamfer_distance"]),
    ]
    sections = [_rect_part("block_width", "block_depth", "block_height", comment="Block body")]
    if kind in {"cable_clamp", "bar_clamp", "rail_clamp"}:
        sections.append(
            "# Central relief channel approximation\n"
            + _manual_hole_block(
                "channel_diameter",
                [("center_x", "center_y")],
                "relief_channel",
                through=False,
                depth_var="block_height",
            )
        )
        sections.append(
            "# Mounting holes\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
                "mounting_holes",
            )
        )
    elif kind == "heat_sink_base":
        hole_positions = [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")]
        sections.append("# Cooling vent holes\n" + _manual_hole_block("mounting_hole_diameter", hole_positions, "vent_holes"))
    elif kind == "thermal_standoff":
        sections.append("# Through mounting hole\n" + _manual_hole_block("mounting_hole_diameter", [("center_x", "center_y")], "mount_hole"))
    elif kind == "cross_brace":
        sections.append(
            "# End mounting holes\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
                "end_mount_holes",
            )
        )
    elif kind == "rib_plate":
        sections.append(
            _rect_part(
                "block_width",
                "block_height",
                "block_depth",
                plane_expr="Plane.XZ",
                part_name="center_rib",
                comment="Central rib web",
            )
        )
        sections.append("# Join rib web\npart += center_rib")
        if variant == "filleted":
            sections.extend(_variant_lines(variant))
        sections.append(
            "# Base mounting holes\n"
            + _manual_hole_block(
                "mounting_hole_diameter",
                [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
                "base_mount_holes",
            )
        )
    elif kind == "support_column":
        sections.append(
            _rect_part(
                "block_width / 2",
                "block_depth / 2",
                "block_height",
                offset_var="block_height",
                part_name="support_post",
                comment="Support post",
            )
        )
        sections.append("# Join support post\npart += support_post")

    if variant == "filleted" and kind != "rib_plate":
        sections.extend(_variant_lines(variant))
    if variant == "chamfered":
        sections.extend(_variant_lines(variant))
    return _render_code(assignments, sections)


def _simple_block_desc(kind: str, p: dict, variant: str) -> list[str]:
    extra = ""
    if variant == "filleted":
        extra = f", {p['fillet_radius']:.1f}mm edge fillet"
    elif variant == "chamfered":
        extra = f", {p['chamfer_distance']:.1f}mm top chamfer"
    engineering_map = {
        "cable_clamp": f"Cable clamp: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm block, central semicircular relief, 2x mounting holes{extra}",
        "bar_clamp": f"Bar clamp block: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, central relief channel, 2x mounting holes{extra}",
        "rail_clamp": f"Rail clamp block: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, relief channel, 2x mounting holes{extra}",
        "heat_sink_base": f"Heat sink base: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, twin vent holes{extra}",
        "thermal_standoff": f"Thermal standoff plate: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, single through mounting hole{extra}",
        "cross_brace": f"Cross brace: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, 2x end mounting holes{extra}",
        "rib_plate": f"Rib plate: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm base with central rib and 2x base holes{extra}",
        "support_column": f"Support column: {p['block_width']:.0f}x{p['block_depth']:.0f}mm base with raised support post{extra}",
    }
    engineering = engineering_map[kind]
    casual = engineering.split(":")[0] + f", {p['block_height']:.0f}mm tall"
    natural = f"I need a {engineering[0].lower() + engineering[1:]}."
    return _long_plate_descriptions(casual, engineering, natural)


CableClamp = _make_template_class("CableClamp", "cable_clamp", 3, ["basic", "filleted"], lambda variant: _simple_block_params("cable_clamp", variant), lambda params, variant: _simple_block_code("cable_clamp", params, variant), lambda params, variant: _simple_block_desc("cable_clamp", params, variant))
BarClamp = _make_template_class("BarClamp", "bar_clamp", 3, ["basic", "filleted"], lambda variant: _simple_block_params("bar_clamp", variant), lambda params, variant: _simple_block_code("bar_clamp", params, variant), lambda params, variant: _simple_block_desc("bar_clamp", params, variant))
RailClamp = _make_template_class("RailClamp", "rail_clamp", 3, ["basic", "filleted"], lambda variant: _simple_block_params("rail_clamp", variant), lambda params, variant: _simple_block_code("rail_clamp", params, variant), lambda params, variant: _simple_block_desc("rail_clamp", params, variant))
HeatSinkBaseTemplate = _make_template_class("HeatSinkBaseTemplate", "heat_sink_base", 2, ["basic", "chamfered"], lambda variant: _simple_block_params("heat_sink_base", variant), lambda params, variant: _simple_block_code("heat_sink_base", params, variant), lambda params, variant: _simple_block_desc("heat_sink_base", params, variant))
ThermalStandoff = _make_template_class("ThermalStandoff", "thermal_standoff", 2, ["basic", "chamfered"], lambda variant: _simple_block_params("thermal_standoff", variant), lambda params, variant: _simple_block_code("thermal_standoff", params, variant), lambda params, variant: _simple_block_desc("thermal_standoff", params, variant))
CrossBrace = _make_template_class("CrossBrace", "cross_brace", 2, ["basic", "filleted"], lambda variant: _simple_block_params("cross_brace", variant), lambda params, variant: _simple_block_code("cross_brace", params, variant), lambda params, variant: _simple_block_desc("cross_brace", params, variant))
RibPlate = _make_template_class("RibPlate", "rib_plate", 3, ["basic", "filleted"], lambda variant: _simple_block_params("rib_plate", variant), lambda params, variant: _simple_block_code("rib_plate", params, variant), lambda params, variant: _simple_block_desc("rib_plate", params, variant))
SupportColumn = _make_template_class("SupportColumn", "support_column", 3, ["basic", "filleted"], lambda variant: _simple_block_params("support_column", variant), lambda params, variant: _simple_block_code("support_column", params, variant), lambda params, variant: _simple_block_desc("support_column", params, variant))


def _complex_params(kind: str, variant: str) -> dict:
    if kind == "bearing_block":
        bearing_code = _rc(list(STANDARD_KNOWLEDGE["bearings"].keys()))
        bore_diameter, outer_diameter, _ = STANDARD_KNOWLEDGE["bearings"][bearing_code]
        block_width = round(outer_diameter + _ru(18, 36), 1)
        block_depth = round(outer_diameter + _ru(14, 28), 1)
        block_height = _ru(18, 40)
        return {
            "bearing_code": bearing_code,
            "block_width": block_width,
            "block_depth": block_depth,
            "block_height": block_height,
            "bearing_bore_diameter": float(outer_diameter),
            "mounting_hole_diameter": _rc([4.5, 5.3, 6.6]),
            "hole_spacing": round(block_width * _ru(0.45, 0.62), 1),
            "fillet_radius": _safe_fillet(block_width, block_depth, block_height),
            "chamfer_distance": _safe_chamfer(block_width, block_depth),
        }
    block_width = _ru(90, 170)
    block_depth = _ru(70, 130)
    block_height = _ru(18, 40)
    return {
        "block_width": block_width,
        "block_depth": block_depth,
        "block_height": block_height,
        "wall_thickness": _safe_wall(block_width, block_depth, block_height),
        "bearing_bore_diameter": round(min(block_width, block_depth) * _ru(0.2, 0.32), 1),
        "mounting_hole_diameter": _rc([4.5, 5.3, 6.6]),
        "hole_spacing_x": round(block_width * _ru(0.45, 0.6), 1),
        "hole_spacing_y": round(block_depth * _ru(0.35, 0.5), 1),
        "fillet_radius": _safe_fillet(block_width, block_depth, block_height),
    }


def _complex_code(kind: str, p: dict, variant: str) -> str:
    if kind == "bearing_block":
        assignments = [
            ("block_width", p["block_width"]),
            ("block_depth", p["block_depth"]),
            ("block_height", p["block_height"]),
            ("bearing_bore_diameter", p["bearing_bore_diameter"]),
            ("mounting_hole_diameter", p["mounting_hole_diameter"]),
            ("hole_spacing", p["hole_spacing"]),
            ("mounting_hole_x", "hole_spacing / 2"),
            ("center_x", 0.0),
            ("center_y", 0.0),
            ("fillet_radius", p["fillet_radius"]),
            ("chamfer_distance", p["chamfer_distance"]),
        ]
        sections = [
            _rect_part("block_width", "block_depth", "block_height", comment="Bearing block body"),
            "# Bearing bore\n" + _manual_hole_block("bearing_bore_diameter", [("center_x", "center_y")], "bearing_bore"),
            "# Mounting holes\n" + _manual_hole_block(
                "mounting_hole_diameter",
                [("mounting_hole_x", "center_y"), ("-mounting_hole_x", "center_y")],
                "mounting_holes",
            ),
        ]
        if variant == "filleted":
            sections.extend(_variant_lines(variant))
        if variant == "chamfered":
            sections.extend(_variant_lines(variant))
        return _render_code(assignments, sections)

    assignments = [
        ("block_width", p["block_width"]),
        ("block_depth", p["block_depth"]),
        ("block_height", p["block_height"]),
        ("wall_thickness", p["wall_thickness"]),
        ("bearing_bore_diameter", p["bearing_bore_diameter"]),
        ("mounting_hole_diameter", p["mounting_hole_diameter"]),
        ("hole_spacing_x", p["hole_spacing_x"]),
        ("hole_spacing_y", p["hole_spacing_y"]),
        ("mounting_hole_x", "hole_spacing_x / 2"),
        ("mounting_hole_y", "hole_spacing_y / 2"),
        ("center_x", 0.0),
        ("center_y", 0.0),
        ("fillet_radius", p["fillet_radius"]),
    ]
    sections = [_rect_part("block_width", "block_depth", "block_height", comment="Gearbox cover body")]
    if variant == "filleted":
        sections.append('# Variant feature: fillet outer vertical edges\npart = part.fillet(fillet_radius, edges="vertical")')
    sections.append('# Shell the cover body\npart = part.shell(wall_thickness, open_face="bottom")')
    sections.append("# Bearing bore\n" + _manual_hole_block("bearing_bore_diameter", [("center_x", "center_y")], "bearing_bore"))
    sections.append(
        "# Perimeter mounting holes\n"
        + _manual_hole_block(
            "mounting_hole_diameter",
            [
                ("mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "mounting_hole_y"),
                ("-mounting_hole_x", "-mounting_hole_y"),
                ("mounting_hole_x", "-mounting_hole_y"),
            ],
            "mounting_holes",
        )
    )
    return _render_code(assignments, sections)


def _complex_desc(kind: str, p: dict, variant: str) -> list[str]:
    if kind == "bearing_block":
        extra = ""
        if variant == "filleted":
            extra = f", {p['fillet_radius']:.1f}mm edge fillet"
        elif variant == "chamfered":
            extra = f", {p['chamfer_distance']:.1f}mm top chamfer"
        engineering = f"Bearing block: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, bearing {p['bearing_code']} bore, 2x mounting holes{extra}"
    else:
        extra = f", {p['fillet_radius']:.1f}mm edge fillet" if variant == "filleted" else ""
        engineering = f"Gearbox cover: {p['block_width']:.0f}x{p['block_depth']:.0f}x{p['block_height']:.0f}mm, shelled with {p['wall_thickness']:.1f}mm walls, center bearing bore, 4x perimeter mounting holes{extra}"
    casual = engineering.split(":")[0] + f", {p['block_height']:.0f}mm tall"
    natural = f"I need a {engineering[0].lower() + engineering[1:]}."
    return _long_plate_descriptions(casual, engineering, natural)


BearingBlock = _make_template_class("BearingBlock", "bearing_block", 4, ["basic", "filleted", "chamfered"], lambda variant: _complex_params("bearing_block", variant), lambda params, variant: _complex_code("bearing_block", params, variant), lambda params, variant: _complex_desc("bearing_block", params, variant))
GearboxCoverTemplate = _make_template_class("GearboxCoverTemplate", "gearbox_cover", 5, ["basic", "filleted"], lambda variant: _complex_params("gearbox_cover", variant), lambda params, variant: _complex_code("gearbox_cover", params, variant), lambda params, variant: _complex_desc("gearbox_cover", params, variant))


EXPANDED_TEMPLATES = [
    FlatPlate,
    Nema17Mount,
    Nema23Mount,
    PcbStandoffPlate,
    DinRailPlate,
    SensorMount,
    BaseplateWithCutout,
    MultiHoleGrid,
    CoverPlate,
    AdapterPlate,
    LBracket,
    UBracket,
    GussetTriangle,
    CornerBracket,
    ServoBracket,
    ShelfBracket,
    AngleBracketSlotted,
    ZBracket,
    SpacerRing,
    WasherTemplate,
    FlangedBushing,
    ShoulderSpacer,
    ThreadedStandoff,
    AdapterSleeve,
    PipeFlangeTemplate,
    BearingRetainer,
    MotorAdapterFlange,
    BlindFlange,
    ReducingFlange,
    CouplerFlange,
    OpenBox,
    ElectronicsEnclosure,
    SensorHousingRound,
    JunctionBox,
    BatteryCompartment,
    DisplayBezel,
    SteppedShaft,
    DowelPin,
    AdapterSleeveLong,
    ShaftCollar,
    CableClamp,
    BarClamp,
    RailClamp,
    HeatSinkBaseTemplate,
    ThermalStandoff,
    CrossBrace,
    RibPlate,
    SupportColumn,
    BearingBlock,
    GearboxCoverTemplate,
]
