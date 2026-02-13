"""Thick spacer OD=40, ID=20, t=25mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Thick spacer for structural support
outer_dia = 40
inner_dia = 20
thickness = 25

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

export(part, "thick_spacer.step")
print("OK  thick_spacer.step")
