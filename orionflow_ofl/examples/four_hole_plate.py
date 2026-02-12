"""Rectangular plate with four corner mounting holes — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .rect(80, 60)
    .extrude(4)
)

part -= (
    Hole(6)
    .at(30, 20)
    .at(-30, 20)
    .at(-30, -20)
    .at(30, -20)
    .through()
    .label("corner_holes")
)

export(part, "four_hole_plate.step")
print("OK  four_hole_plate.step")
