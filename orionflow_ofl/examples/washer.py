"""Flat washer — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .circle(24)
    .extrude(2)
)

part -= (
    Hole(12)
    .at(0, 0)
    .through()
    .label("center_hole")
)

export(part, "washer.step")
print("OK  washer.step")
