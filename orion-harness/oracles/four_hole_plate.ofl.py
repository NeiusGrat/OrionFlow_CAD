"""Rectangular plate with four corner mounting holes — OFL v0.1 example."""

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .rect(80, 60)
    .extrude(4)
)

part -= (
    Hole(6)
    .at(30, 20)
    .at(-30, 20)
    .at(-30, -20)
    .at(30, -20)
    .through()
    .label("corner_holes")
)
