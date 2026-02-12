"""Simple flat rectangular plate — OFL v0.1 example."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orionflow_ofl import *

part = (
    Sketch(Plane.XY)
    .rect(100, 50)
    .extrude(3)
)

export(part, "flat_plate.step")
print("OK  flat_plate.step")
