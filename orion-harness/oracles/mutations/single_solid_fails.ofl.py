"""Mutation: two boxes 1000mm apart, wrapped directly as a Part around a raw
Compound -- bypassing OFL's own `+` operator, which already refuses to
produce a disconnected union (see orionflow_ofl/part.py Part.__iadd__).
Must fail tier1.single_solid and nothing upstream of it."""

from orionflow_ofl import *
from build123d import Box, Compound, Pos

s1 = Pos(0, 0, 0) * Box(10, 10, 10)
s2 = Pos(1000, 0, 0) * Box(10, 10, 10)
part = Part(Compound(children=[s1, s2]))
