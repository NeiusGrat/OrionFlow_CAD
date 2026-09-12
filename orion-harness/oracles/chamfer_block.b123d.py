"""feature_coverage: chamfer on the vertical edges of a block."""

from build123d import Axis, Rectangle, chamfer, extrude

_block = extrude(Rectangle(40, 40), amount=10)
_vertical_edges = _block.edges().filter_by(Axis.Z)
part = chamfer(_vertical_edges, length=3)
