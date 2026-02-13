"""Parametric washer with OD/ID/T as variables — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
outer_dia = 30      # Outer diameter (mm)
inner_dia = 12      # Inner diameter (mm)
thickness = 2.5     # Thickness (mm)
# ====================================

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

export(part, "parametric_washer.step")
print("OK  parametric_washer.step")
