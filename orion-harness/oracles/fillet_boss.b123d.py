"""feature_coverage: fillet -- zero OFL training examples use build123d's
fillet() directly on a raw solid (OFL's Part.fillet() wraps it, but this
family exercises the build123d feature surface itself, kind='build123d')."""

from build123d import Axis, Rectangle, extrude, fillet

_block = extrude(Rectangle(40, 40), amount=10)
_vertical_edges = _block.edges().filter_by(Axis.Z)
part = fillet(_vertical_edges, radius=5)
