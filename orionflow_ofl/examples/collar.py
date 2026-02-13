"""Collar OD=35, ID=25, t=10 with set screw hole — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Shaft collar with set screw hole
outer_dia = 35
inner_dia = 25
thickness = 10
set_screw_hole_dia = 5

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

# Set screw hole - positioned radially (from top, offset from center)
# Note: This is a simplified representation - actual radial hole would need side feature
part -= (
    Hole(set_screw_hole_dia)
    .at(12, 0)  # Offset to intersect with bore wall
    .to_depth(8)
    .label("set_screw_hole")
)

export(part, "collar.step")
print("OK  collar.step")
