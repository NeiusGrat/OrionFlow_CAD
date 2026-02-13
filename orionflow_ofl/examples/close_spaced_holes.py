"""Plate with closely spaced holes 15mm apart — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate with holes in close proximity - tests minimum spacing
width = 100
height = 50
thickness = 5
hole_dia = 6
spacing = 15

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# 5 holes in a row, 15mm apart
part -= (
    Hole(hole_dia)
    .at(-30, 0)
    .at(-15, 0)
    .at(0, 0)
    .at(15, 0)
    .at(30, 0)
    .through()
    .label("close_holes")
)

export(part, "close_spaced_holes.step")
print("OK  close_spaced_holes.step")
