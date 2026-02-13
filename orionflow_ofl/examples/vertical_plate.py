"""Vertical plate on YZ plane 80x120x4mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate oriented on YZ plane (standing upright along X-axis)
width = 80
height = 120
thickness = 4

part = (
    Sketch(Plane.YZ)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "vertical_plate.step")
print("OK  vertical_plate.step")
