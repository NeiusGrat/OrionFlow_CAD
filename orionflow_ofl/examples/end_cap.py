"""End cap with center bore and 6-hole pattern — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

# Circular end cap for tube or pipe
plate_dia = 90
thickness = 6
bore_dia = 25
bolt_hole_dia = 7
bolt_pcd = 70

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
    .at_circular(bolt_pcd / 2, count=6, start_angle=0)
    .through()
    .label("mount_holes")
)

export(part, "end_cap.step")
print("OK  end_cap.step")
