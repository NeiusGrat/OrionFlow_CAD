"""Plate with center bore and 4 bolt holes of different diameters — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate with mixed hole sizes: center bore + 4 corner bolt holes
width = 100
height = 100
thickness = 8
bore_dia = 30
bolt_hole_dia = 6
bolt_offset = 35

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Center bore
part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

# Four corner bolt holes
part -= (
    Hole(bolt_hole_dia)
    .at(bolt_offset, bolt_offset)
    .at(-bolt_offset, bolt_offset)
    .at(-bolt_offset, -bolt_offset)
    .at(bolt_offset, -bolt_offset)
    .through()
    .label("bolt_holes")
)

export(part, "mixed_holes.step")
print("OK  mixed_holes.step")
