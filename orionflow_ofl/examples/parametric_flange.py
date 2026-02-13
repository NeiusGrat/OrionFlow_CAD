"""Parametric flange with bolt_count, pcd, bore, plate_dia as variables — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# ============ PARAMETERS ============
plate_dia = 80      # Flange outer diameter (mm)
bore_dia = 30       # Center bore diameter (mm)
bolt_count = 6      # Number of bolt holes
bolt_pcd = 60       # Bolt pitch circle diameter (mm)
bolt_hole_dia = 7   # Bolt hole diameter (mm)
thickness = 8       # Flange thickness (mm)
# ====================================

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
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
    .at_circular(bolt_pcd / 2, count=bolt_count, start_angle=0)
    .through()
    .label("bolt_holes")
)

export(part, "parametric_flange.step")
print("OK  parametric_flange.step")
