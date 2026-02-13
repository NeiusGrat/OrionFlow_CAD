"""Bearing housing cap with center bore and bolt circle — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Bearing housing cap - for 6205 bearing (25mm ID, 52mm OD)
plate_dia = 70
thickness = 8
bore_dia = 52  # Bearing OD press fit
bolt_hole_dia = 7  # M6 clearance
bolt_pcd = 58

part = (
    Sketch(Plane.XY)
    .circle(plate_dia)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("bearing_bore")
)

part -= (
    Hole(bolt_hole_dia)
    .at_circular(bolt_pcd / 2, count=4, start_angle=45)
    .through()
    .label("mount_bolts")
)

export(part, "bearing_housing_cap.step")
print("OK  bearing_housing_cap.step")
