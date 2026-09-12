"""feature_coverage: loft -- a nozzle transitioning from a 10mm-radius
circle to a 20mm-radius circle over 20mm of height."""

from build123d import Circle, Pos, loft

_bottom = Pos(0, 0, 0) * Circle(10)
_top = Pos(0, 0, 20) * Circle(20)
part = loft(sections=[_bottom, _top])
