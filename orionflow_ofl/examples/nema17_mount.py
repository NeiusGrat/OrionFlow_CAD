"""NEMA 17 stepper-motor mounting plate — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

plate_size = 60
thickness = 6
bore_dia = 22
bolt_dia = 5.5
bolt_pcd = 31
corner_r = 3

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

export(part, "nema17_mount.step")
print("OK  nema17_mount.step")
