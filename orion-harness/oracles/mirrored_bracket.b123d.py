"""feature_coverage: mirror -- one half-bracket mirrored across the YZ
plane and unioned with itself, touching exactly at the mirror plane."""

from build123d import Plane, Pos, Rectangle, extrude, mirror

_half = extrude(Rectangle(20, 40), amount=5)
_half = Pos(10, 0, 0) * _half  # spans x=0..20, touches the mirror plane at x=0
_mirrored = mirror(_half, about=Plane.YZ)
part = _half + _mirrored
