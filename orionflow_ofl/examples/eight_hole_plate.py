"""Rectangular plate with 8 holes on circular pattern — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Rectangular plate with 8 holes arranged in a circle
width = 120
height = 120
thickness = 6
hole_dia = 6
hole_pcd = 80

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at_circular(hole_pcd / 2, count=8, start_angle=0)
    .through()
    .label("mounting_holes")
)

export(part, "eight_hole_plate.step")
print("OK  eight_hole_plate.step")
