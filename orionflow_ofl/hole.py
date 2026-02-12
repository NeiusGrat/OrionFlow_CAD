"""OFL Hole — declarative subtractive cylinder specification."""

import math


class Hole:
    """Describe one or more cylindrical holes to subtract from a Part.

    Geometry is built only when applied via ``part -= hole``.
    """

    def __init__(self, diameter):
        self._diameter = diameter
        self._positions = []
        self._through = False
        self._depth = None
        self._label = None

    # ── positioning ──────────────────────────────────────────────

    def at(self, x, y):
        """Add a single hole position (XY relative to part center)."""
        self._positions.append((x, y))
        return self

    def at_circular(self, radius, count, start_angle=0):
        """Add *count* holes equally spaced on a circle of *radius* mm."""
        for i in range(count):
            angle = math.radians(start_angle + i * 360 / count)
            self._positions.append((radius * math.cos(angle), radius * math.sin(angle)))
        return self

    # ── depth ────────────────────────────────────────────────────

    def through(self):
        """Mark hole as through-all (depth derived from part bounding box)."""
        self._through = True
        self._depth = None
        return self

    def to_depth(self, depth):
        """Blind hole to *depth* mm from the top face."""
        self._through = False
        self._depth = depth
        return self

    # ── metadata ─────────────────────────────────────────────────

    def label(self, name):
        """Attach a human-readable label (stored, not used for geometry)."""
        self._label = name
        return self
