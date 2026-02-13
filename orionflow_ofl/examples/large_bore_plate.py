"""Plate with large bore >60% of plate width — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Plate with large center bore - tests thin wall conditions
width = 80
height = 80
thickness = 6
bore_dia = 55  # 68.75% of plate width

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("large_bore")
)

export(part, "large_bore_plate.step")
print("OK  large_bore_plate.step")
