"""Plate with center bore and two bolt circles — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Complex flange with center bore + inner + outer bolt circles
plate_dia = 120
thickness = 10
bore_dia = 40
inner_bolt_dia = 6
inner_pcd = 55
outer_bolt_dia = 8
outer_pcd = 95

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
    .extrude(thickness)
)

# Center bore
part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

# Inner bolt circle - 6 holes
part -= (
    Hole(inner_bolt_dia)
    .at_circular(inner_pcd / 2, count=6, start_angle=0)
    .through()
    .label("inner_bolts")
)

# Outer bolt circle - 8 holes
part -= (
    Hole(outer_bolt_dia)
    .at_circular(outer_pcd / 2, count=8, start_angle=22.5)
    .through()
    .label("outer_bolts")
)

export(part, "multi_pattern.step")
print("OK  multi_pattern.step")
