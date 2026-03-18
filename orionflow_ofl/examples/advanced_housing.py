"""
OFL Example: Advanced Housing
Demonstrates fillet, chamfer, shell, and offset plane sketching.
"""
from orionflow_ofl import *

# 1. Base shape
housing = (
    Sketch(Plane.XY)
    .rect(80, 60)
    .extrude(30)
)

# 2. Fillet the 4 vertical corners
housing.fillet(5, edges="vertical")

# 3. Chamfer the top edge
housing.chamfer(2, edges="top")

# 4. Hollow it out from the bottom (wall thickness = 2mm)
housing.shell(2, open_face="bottom")

# 5. Add a mounting boss on top of the housing
boss = (
    Sketch(Plane.XY, offset=30)
    .circle(15)
    .extrude(10)
)
# Chamfer the top edge of the boss
boss.chamfer(1, edges="top")

# 6. Add the boss to the housing
housing += boss

# 7. Add a through hole down the middle of the boss
housing -= (
    Hole(10)
    .at(0, 0)
    .through()
)

export(housing, "advanced_housing.step")
