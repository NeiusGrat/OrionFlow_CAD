"""Diamond orientation plate on XZ plane 60x60x5mm — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate oriented on XZ plane (standing upright along Y-axis)
width = 60
height = 60
thickness = 5

part = (
    Sketch(Plane.XZ)
    .rect(width, height)
    .extrude(thickness)
)

export(part, "diamond_orientation.step")
print("OK  diamond_orientation.step")
