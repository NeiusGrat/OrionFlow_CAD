"""Mutation: a Solid built from a Shell missing one face of a box. Single
body, so tier1.single_solid passes, but the shell is not closed -- must
fail tier1.watertight and nothing upstream of it.

This mutation is also the regression test for the bug it caught: build123d
0.10.0 exposes `Shape.is_valid` as a bool *property*, not a method. Calling
it as `shape.is_valid()` raises TypeError, which a naive try/except would
misreport as a crash rather than surfacing the real watertight=False."""

from orionflow_ofl import *
from build123d import Box, Shell, Solid

_box = Box(10, 10, 10)
_faces = list(_box.faces())
_open_shell = Shell(_faces[:-1])
part = Part(Solid(_open_shell))
