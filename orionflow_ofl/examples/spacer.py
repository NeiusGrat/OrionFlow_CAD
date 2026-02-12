"""Cylindrical spacer with center bore — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .circle(20)
    .extrude(10)
)

part -= (
    Hole(8)
    .at(0, 0)
    .through()
    .label("center_bore")
)

export(part, "spacer.step")
print("OK  spacer.step")
