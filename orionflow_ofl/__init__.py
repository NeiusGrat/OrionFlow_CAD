"""OrionFlow Language (OFL) — deterministic Python CAD DSL.

Public API:
    Plane       — XY, XZ, YZ
    Sketch      — .rect() / .rounded_rect() / .circle() / .slot() / .polygon()
                  → .extrude() → Part
    Part        — booleans (+, -; subtract Holes AND Parts), .rotate() /
                  .translate() / .at(), .fillet() / .chamfer() / .shell()
    Hole        — .at() / .at_circular() / .along("x"|"y"|"z") /
                  .through() / .to_depth() / .label()
    Axis        — X, Y, Z (re-exported from build123d for Part.rotate)
    export()    — write Part to .step or .stl
"""

from build123d import Axis

from .planes import Plane
from .sketch import Sketch
from .part import Part
from .hole import Hole
from .export import export

__all__ = ["Plane", "Sketch", "Part", "Hole", "Axis", "export"]
__version__ = "0.3.0"
