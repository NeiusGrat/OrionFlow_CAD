"""PCB standoff plate with 4 M3 holes at 58x28mm spacing — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# PCB mounting plate - common Arduino-sized board
width = 75
height = 45
thickness = 4
hole_dia = 3.4  # M3 clearance
hole_spacing_x = 58
hole_spacing_y = 28

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# PCB mounting holes at standard spacing
part -= (
    Hole(hole_dia)
    .at(hole_spacing_x / 2, hole_spacing_y / 2)
    .at(-hole_spacing_x / 2, hole_spacing_y / 2)
    .at(-hole_spacing_x / 2, -hole_spacing_y / 2)
    .at(hole_spacing_x / 2, -hole_spacing_y / 2)
    .through()
    .label("pcb_mount_holes")
)

export(part, "pcb_standoff_plate.step")
print("OK  pcb_standoff_plate.step")
