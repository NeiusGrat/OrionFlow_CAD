"""Round flange with 6 holes on circular pattern — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Circular flange with 6 bolt holes
plate_dia = 80
thickness = 8
hole_dia = 7
hole_pcd = 60

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
    .extrude(thickness)
)

part -= (
    Hole(hole_dia)
    .at_circular(hole_pcd / 2, count=6, start_angle=0)
    .through()
    .label("bolt_holes")
)

export(part, "six_hole_flange.step")
print("OK  six_hole_flange.step")
