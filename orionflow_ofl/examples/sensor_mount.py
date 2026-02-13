"""Sensor mount plate 30x20 with 2 M3 mounting holes — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Small sensor mounting plate
width = 30
height = 20
thickness = 3
hole_dia = 3.4  # M3 clearance
hole_spacing = 20

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Two M3 mounting holes
part -= (
    Hole(hole_dia)
    .at(-hole_spacing / 2, 0)
    .at(hole_spacing / 2, 0)
    .through()
    .label("mount_holes")
)

export(part, "sensor_mount.step")
print("OK  sensor_mount.step")
