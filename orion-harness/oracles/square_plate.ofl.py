"""Square plate 100x100x5mm — OFL v0.1 example."""

from orionflow_ofl import *

# Simple square plate
width = 100
height = 100
thickness = 5

part = (
    Sketch(Plane.XY)
    .rect(width, height)
    .extrude(thickness)
)
