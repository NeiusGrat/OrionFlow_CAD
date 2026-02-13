"""Thin washer OD=30, ID=16, t=1.5mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Thin washer - M8 washer dimensions approximately
outer_dia = 30
inner_dia = 16
thickness = 1.5

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("center_hole")
)

export(part, "thin_washer.step")
print("OK  thin_washer.step")
