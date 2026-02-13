"""NEMA 23 stepper motor mounting plate — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# NEMA 23 motor mount - standard dimensions
# NEMA 23: 47.14mm PCD, M5 holes, center bore 38.1mm
plate_size = 70
thickness = 8
bore_dia = 38.1
bolt_dia = 5.5  # M5 clearance
bolt_pcd = 47.14
corner_r = 5

part = (
    Sketch(Plane.XY)
    .rounded_rect(plate_size, plate_size, corner_r)
    .extrude(thickness)
)

part -= (
    Hole(bore_dia)
    .at(0, 0)
    .through()
    .label("shaft_bore")
)

part -= (
    Hole(bolt_dia)
    .at_circular(bolt_pcd / 2, count=4, start_angle=45)
    .through()
    .label("mount_holes")
)

export(part, "nema23_mount.step")
print("OK  nema23_mount.step")
