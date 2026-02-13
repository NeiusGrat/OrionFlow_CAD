"""Plate with blind holes (not through) — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate with blind holes - holes that don't go all the way through
width = 80
height = 60
thickness = 15
hole_dia = 8
hole_depth = 8

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Blind holes - only go partway through
part -= (
    Hole(hole_dia)
    .at(20, 15)
    .at(-20, 15)
    .at(0, -15)
    .to_depth(hole_depth)
    .label("blind_holes")
)

export(part, "blind_hole_plate.step")
print("OK  blind_hole_plate.step")
