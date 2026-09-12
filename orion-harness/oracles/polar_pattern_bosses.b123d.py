"""feature_coverage: polar pattern -- six bosses arranged radially around a
central disk, each overlapping the disk so the union stays one body."""

from build123d import Circle, Cylinder, Pos, Rot, extrude

_disk = extrude(Circle(10), amount=8)
_boss = Pos(9, 0, 0) * Cylinder(2, 8)
_bosses = [Rot(0, 0, 60 * i) * _boss for i in range(6)]
part = _disk
for _b in _bosses:
    part = part + _b
