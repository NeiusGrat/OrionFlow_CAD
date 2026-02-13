"""Gearbox cover plate with center bore, 8 bolt holes, 2 dowel pins — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Gearbox cover plate
width = 150
height = 100
thickness = 10
bore_dia = 35
bolt_hole_dia = 8.5  # M8 clearance
dowel_hole_dia = 6

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

# Center bore for shaft
part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

# 8 bolt holes around perimeter
part -= (
    Hole(bolt_hole_dia)
    .at(60, 35)
    .at(60, -35)
    .at(-60, 35)
    .at(-60, -35)
    .at(20, 40)
    .at(-20, 40)
    .at(20, -40)
    .at(-20, -40)
    .through()
    .label("bolt_holes")
)

# 2 dowel pin holes for alignment
part -= (
    Hole(dowel_hole_dia)
    .at(50, 0)
    .at(-50, 0)
    .to_depth(6)
    .label("dowel_pins")
)

export(part, "gearbox_cover.step")
print("OK  gearbox_cover.step")
