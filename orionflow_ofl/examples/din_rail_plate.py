"""DIN rail mounting plate 35mm wide — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# DIN rail mounting plate - 35mm standard width
width = 80
height = 35
thickness = 4
mount_hole_dia = 5.5  # M5 clearance
slot_hole_dia = 6

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Mounting holes for attaching to DIN rail
part -= (
    Hole(mount_hole_dia)
    .at(30, 0)
    .at(-30, 0)
    .through()
    .label("rail_mount_holes")
)

# Slots approximated as holes for device mounting
part -= (
    Hole(slot_hole_dia)
    .at(10, 8)
    .at(-10, 8)
    .at(10, -8)
    .at(-10, -8)
    .through()
    .label("device_mount_holes")
)

export(part, "din_rail_plate.step")
print("OK  din_rail_plate.step")
