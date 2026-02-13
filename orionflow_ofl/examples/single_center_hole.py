"""Plate with single center hole — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Rectangular plate with one centered hole
width = 100
height = 60
thickness = 5
hole_dia = 15

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

export(part, "single_center_hole.step")
print("OK  single_center_hole.step")
