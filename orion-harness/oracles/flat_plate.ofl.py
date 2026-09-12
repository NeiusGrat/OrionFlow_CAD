"""Simple flat rectangular plate — OFL v0.1 example."""

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .rect(100, 50)
    .extrude(3)
)
