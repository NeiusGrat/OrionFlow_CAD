"""Pipe segment OD=60, ID=52, t=40mm (thin wall tube) — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Thin wall pipe segment - 4mm wall thickness
outer_dia = 60
inner_dia = 52
thickness = 40

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("pipe_bore")
)

export(part, "pipe_segment.step")
print("OK  pipe_segment.step")
