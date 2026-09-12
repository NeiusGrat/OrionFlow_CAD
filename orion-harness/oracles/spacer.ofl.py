"""Cylindrical spacer with center bore — OFL v0.1 example."""

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .circle(20)
    .extrude(10)
)

part -= (
    Hole(8)
    .at(0, 0)
    .through()
    .label("center_bore")
)
