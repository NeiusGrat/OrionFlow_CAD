"""Small square plate 20x20x2mm — OFL v0.1 example."""

from orionflow_ofl import *

# Small square plate for shim or spacer use
width = 20
height = 20
thickness = 2

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
