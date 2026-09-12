"""Flat washer — OFL v0.1 example."""

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .circle(24)
    .extrude(2)
)

part -= (
    Hole(12)
    .at(0, 0)
    .through()
    .label("center_hole")
)
