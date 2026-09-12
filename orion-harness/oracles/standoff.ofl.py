"""Standoff OD=10, ID=4.2 (M4 clearance), t=15mm — OFL v0.1 example."""

from orionflow_ofl import *

# Standoff for M4 bolt - clearance hole
outer_dia = 10
inner_dia = 4.2  # M4 clearance hole
thickness = 15

part = (
    Sketch(Plane.XY)
    .circle(outer_dia)
    .extrude(thickness)
)

part -= (
    Hole(inner_dia)
    .at(0, 0)
    .through()
    .label("m4_clearance")
)
