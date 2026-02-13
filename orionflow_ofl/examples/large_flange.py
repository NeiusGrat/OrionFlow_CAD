"""Large flange OD=100, ID=50, t=8 with 6 bolt holes — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Large pipe flange with bolt circle
outer_dia = 100
inner_dia = 50
thickness = 8
bolt_hole_dia = 10
bolt_pcd = 80

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

part -= (
    Hole(bolt_hole_dia)
    .at_circular(bolt_pcd / 2, count=6, start_angle=0)
    .through()
    .label("bolt_holes")
)

export(part, "large_flange.step")
print("OK  large_flange.step")
