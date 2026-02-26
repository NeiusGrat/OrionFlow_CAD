"""5 curated few-shot examples that teach the model OFL syntax.

These cover the key patterns: simple plate, washer, NEMA mount,
spacer, and circular flange.
"""

SYSTEM_PROMPT = """\
You are OrionFlow, a CAD code generator. Given a description of a mechanical part,
output executable Python code using the orionflow_ofl library.

Rules:
- Always start with: from orionflow_ofl import *
- Define all dimensions as named variables at the top
- Use Sketch(Plane.XY).rect(w, h).extrude(t) for rectangular plates
- Use Sketch(Plane.XY).circle(diameter).extrude(t) for circular parts
- Use Sketch(Plane.XY).rounded_rect(w, h, r).extrude(t) for rounded plates
- Use Hole(diameter).at(x, y).through().label("name") for holes
- Use Hole(diameter).at_circular(radius, count=N, start_angle=A).through() for bolt patterns
- Use part -= hole for boolean subtraction
- Always end with: export(part, "part_name.step")
- Output ONLY the Python code, nothing else."""

FEW_SHOT_EXAMPLES = [
    {
        "text": "Simple rectangular plate, 100mm by 60mm, 5mm thick",
        "code": """from orionflow_ofl import *

width = 100
height = 60
thickness = 5

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "rect_plate.step")""",
    },
    {
        "text": "Flat washer, 24mm outer diameter, 13mm center hole, 2.5mm thick",
        "code": """from orionflow_ofl import *

od = 24
hole_dia = 13
thickness = 2.5

part = (
    Sketch(Plane.XY)
    .circle(od)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

export(part, "washer.step")""",
    },
    {
        "text": (
            "NEMA-17 motor mounting plate. 60mm square, 6mm thick, 3mm corner "
            "radius. Center bore 22mm. Four M5 mounting holes on 31mm bolt "
            "circle at 45 degree offset."
        ),
        "code": """from orionflow_ofl import *

plate_size = 60
thickness = 6
corner_r = 3
bore_dia = 22
bolt_dia = 5.5
bolt_pcd = 31

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
    .label("M5_mount")
)

export(part, "nema17_mount.step")""",
    },
    {
        "text": "Cylindrical spacer. 20mm outer diameter, 10mm bore, 15mm long.",
        "code": """from orionflow_ofl import *

od = 20
bore_dia = 10
length = 15

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

export(part, "spacer.step")""",
    },
    {
        "text": (
            "Circular flange plate. 100mm diameter, 8mm thick. Center bore "
            "50mm. Six M8 bolt holes equally spaced on 75mm bolt circle."
        ),
        "code": """from orionflow_ofl import *

plate_dia = 100
thickness = 8
bore_dia = 50
bolt_dia = 8.4
bolt_pcd = 75
bolt_count = 6

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
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
    .at_circular(bolt_pcd / 2, count=bolt_count, start_angle=0)
    .through()
    .label("M8_mount")
)

export(part, "flange.step")""",
    },
]
