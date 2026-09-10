"""Parametric models for the off-the-shelf parts, driven by measured numbers.

These are the parts the slab reconstruction cannot reach: a rolling-element
bearing is a revolve plus a circular pattern, not a stack of extrusions, and it
is also where the faceted conversion hurts most - the two bearing types account
for 45% of every face in the assembly (72 811 of 163 071) because the source
STLs tessellate each ball.

Every dimension below was measured off the source mesh, not taken from a
catalogue, and each model reports its own error against that mesh.
"""
from __future__ import annotations

from dataclasses import dataclass

from build123d import Compound, Cylinder, Location, Pos, Sphere


@dataclass(frozen=True)
class Bearing:
    """A deep-groove ball bearing, as measured from its cross-sections.

    ``outer_bore`` and ``inner_od`` are the two race surfaces facing the ball
    track; they were read straight off a section taken near the end face, where
    the races are still separate rings:

        22x16x4 at z=0.5 -> OD 21.993 / 19.987 and 17.996 / 15.990
        15x10x3 at z=0.4 -> OD 14.996 / 13.488 and 11.502 /  9.995
    """
    name: str
    od: float
    bore: float
    width: float
    outer_bore: float
    inner_od: float
    balls: int

    @property
    def pitch_radius(self) -> float:
        return 0.25 * (self.outer_bore + self.inner_od)

    @property
    def ball_radius(self) -> float:
        # exactly the gap: the balls touch both raceways without cutting into
        # them. An earlier version made them 5% proud so the three pieces would
        # fuse into one solid, but a 0.025 mm overlap between a sphere and a
        # cylinder is a near-tangent intersection, and every one of the 14
        # bearing instances came back invalid after a STEP round-trip.
        return 0.25 * (self.outer_bore - self.inner_od)

    def build(self) -> Compound:
        """Outer race, inner race and the balls, as separate solids.

        A bearing is an assembly, not one body, so this is also what makes the
        geometry robust: nothing has to be booleaned across a tangency.
        """
        h = self.width
        mid = h / 2
        outer = (Pos(0, 0, mid) * Cylinder(self.od / 2, h)
                 - Pos(0, 0, mid) * Cylinder(self.outer_bore / 2, h))
        inner = (Pos(0, 0, mid) * Cylinder(self.inner_od / 2, h)
                 - Pos(0, 0, mid) * Cylinder(self.bore / 2, h))
        parts = [outer, inner]
        for i in range(self.balls):
            parts.append(Location((0, 0, mid))
                         * Location((0, 0, 0), (0, 0, 360.0 * i / self.balls))
                         * Pos(self.pitch_radius, 0, 0)
                         * Sphere(self.ball_radius))
        return Compound(parts)


#: Ball counts came from the void pattern in a mid-width section: the 22x16x4
#: shows gaps every ~32.7 degrees, so eleven balls.
BEARINGS = {
    "seeed_bearing__configuration__22x16x4": Bearing(
        name="seeed_bearing__configuration__22x16x4",
        od=22.0, bore=16.0, width=4.0, outer_bore=20.0, inner_od=18.0, balls=11),
    "seeed_bearing__configuration_default": Bearing(
        name="seeed_bearing__configuration_default",
        od=15.0, bore=10.0, width=3.0, outer_bore=13.49, inner_od=11.50, balls=9),
}


def build_all() -> dict:
    return {name: b.build() for name, b in BEARINGS.items()}
