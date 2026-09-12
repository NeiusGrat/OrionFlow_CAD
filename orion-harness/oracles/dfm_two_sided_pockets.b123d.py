"""dfm_machinable: a plate with one pocket on top and one pocket on its
-Y side. Two setups are required -- a model that places both pockets on
the same face would score better on tier4.setups but wrongly (this task
doesn't attempt to catch that; it only checks the declared part is
buildable and machinable in the setups the spec allows)."""

from build123d import Box, Pos, Rectangle, extrude

_plate = extrude(Rectangle(100, 50), amount=10)
_top_pocket = Pos(20, 0, 7) * Box(10, 10, 6)  # floor at z=4
_side_pocket = Pos(0, -22, 3) * Box(10, 6, 10)  # floor at y=-19
part = _plate - _top_pocket - _side_pocket
