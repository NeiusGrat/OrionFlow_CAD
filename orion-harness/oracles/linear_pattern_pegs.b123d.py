"""feature_coverage: linear pattern -- four cylindrical bosses standing on
a shared base plate, evenly spaced. build123d has no single "linear
pattern" call; a model must express it as a loop + boolean union against
the base, which is exactly the point of this family."""

from build123d import Cylinder, Pos, Rectangle, extrude

_base = extrude(Rectangle(100, 20), amount=4)
_bosses = [Pos(-30 + 20 * i, 0, 2) * Cylinder(6, 8) for i in range(4)]
part = _base
for _boss in _bosses:
    part = part + _boss
