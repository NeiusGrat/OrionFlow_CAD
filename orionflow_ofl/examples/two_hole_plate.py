"""Plate with two holes spaced apart — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Rectangular plate with two mounting holes
width = 120
height = 50
thickness = 6
hole_dia = 8
hole_spacing = 80

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at(-hole_spacing / 2, 0)
    .at(hole_spacing / 2, 0)
    .through()
    .label("mounting_holes")
)

export(part, "two_hole_plate.step")
print("OK  two_hole_plate.step")
