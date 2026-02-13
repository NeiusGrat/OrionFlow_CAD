"""Parametric cover plate with n_bolts, cover_dia, bore_dia, thickness as variables — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
cover_dia = 100     # Cover outer diameter (mm)
bore_dia = 35       # Center bore diameter (mm)
n_bolts = 8         # Number of bolt holes
bolt_hole_dia = 7   # Bolt hole diameter (mm)
thickness = 6       # Cover thickness (mm)
# ====================================

# Calculate bolt PCD (pitch circle diameter) - 75% of cover diameter
bolt_pcd = cover_dia * 0.75

part = (
    Sketch(Plane.XY)
    .circle(cover_dia)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("center_bore")
)

part -= (
    Hole(bolt_hole_dia)
    .at_circular(bolt_pcd / 2, count=n_bolts, start_angle=0)
    .through()
    .label("bolt_holes")
)

export(part, "parametric_cover.step")
print("OK  parametric_cover.step")
