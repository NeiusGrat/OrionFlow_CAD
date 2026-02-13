"""Bushing OD=25, ID=12, t=30mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Bushing - long cylindrical bearing surface
outer_dia = 25
inner_dia = 12
thickness = 30

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("bearing_surface")
)

export(part, "bushing.step")
print("OK  bushing.step")
