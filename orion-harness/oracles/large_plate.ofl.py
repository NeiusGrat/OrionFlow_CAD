"""Large plate 300x200x10mm — OFL v0.1 example."""

from orionflow_ofl import *

# Large rectangular plate for base or mounting surface
width = 300
height = 200
thickness = 10

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
