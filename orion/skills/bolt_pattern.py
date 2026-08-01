"""create_bolt_pattern — holes that can actually be drilled and bolted.

Four numbers decide whether a bolt pattern is manufacturable, and three of them
are rules rather than choices: the clearance hole for the bolt (ISO 273), the
edge distance that stops the land tearing out, and the spacing that leaves room
for a socket. Only the bolt circle is really a design decision.

Every one of those was being left to the model, which is why the studio's bench
produced patterns whose holes sat outside their own plate.
"""

from __future__ import annotations

import math

from orion.skills.base import (
    Skill,
    SkillError,
    SkillGraph,
    SkillResult,
    registry,
)

#: ISO 273 clearance holes, medium series, in mm. The medium series is the
#: default for general assembly; fine is for dowelled/located joints and coarse
#: for weldments and structural work.
ISO_273_MEDIUM = {
    3.0: 3.4, 4.0: 4.5, 5.0: 5.5, 6.0: 6.6, 8.0: 9.0, 10.0: 11.0,
    12.0: 13.5, 16.0: 17.5, 20.0: 22.0, 24.0: 26.0,
}

#: Shop rules, stated as multiples of the bolt diameter. These are conventions
#: rather than a standard, and are labelled as such wherever they are quoted.
EDGE_DISTANCE_D = 1.5      # hole centre to a free edge
PITCH_D = 3.0              # hole centre to hole centre, socket access


def create_bolt_pattern(bolt_size_mm: float, count: int,
                        bolt_circle_dia_mm: float,
                        plate_thickness_mm: float = 0.0) -> SkillResult:
    """A circular bolt pattern, checked for clearance, edge distance and pitch."""
    if bolt_size_mm not in ISO_273_MEDIUM:
        raise SkillError(
            f"no ISO 273 clearance hole tabulated for M{bolt_size_mm:g}. "
            f"Available: {', '.join('M%g' % d for d in sorted(ISO_273_MEDIUM))}")
    if count < 2:
        raise SkillError("a bolt pattern needs at least two bolts")
    if bolt_circle_dia_mm <= 0:
        raise SkillError("the bolt circle diameter must be positive")

    hole_dia = ISO_273_MEDIUM[bolt_size_mm]
    hole_r = hole_dia / 2.0
    bc_r = bolt_circle_dia_mm / 2.0

    # Chord between adjacent holes on the circle — the real spacing, not the arc.
    pitch = 2.0 * bc_r * math.sin(math.pi / count)
    min_pitch = PITCH_D * bolt_size_mm
    if pitch < min_pitch:
        raise SkillError(
            f"{count} x M{bolt_size_mm:g} on a {bolt_circle_dia_mm:g} mm bolt "
            f"circle puts the holes {pitch:.1f} mm apart; {min_pitch:.1f} mm is "
            f"the practical minimum for socket access ({PITCH_D:g}d). Use a "
            f"larger circle or fewer bolts.")

    edge = EDGE_DISTANCE_D * bolt_size_mm
    min_outer_r = bc_r + hole_r + edge

    return SkillResult(
        part_class="bolt_pattern",
        variables={"hole_n": float(count), "hole_r": hole_r, "bc_r": bc_r},
        rationale={
            "hole_r": f"M{bolt_size_mm:g} clearance hole {hole_dia:g} mm "
                      f"(ISO 273 medium)",
            "hole_n": f"{count} bolts as requested",
            "bc_r": f"bolt circle {bolt_circle_dia_mm:g} mm as requested",
        },
        citations=[
            f"ISO 273 medium series: M{bolt_size_mm:g} clearance hole "
            f"{hole_dia:g} mm",
        ],
        derived={
            "clearance_hole_mm": hole_dia,
            "hole_pitch_mm": round(pitch, 2),
            "min_hole_pitch_mm": round(min_pitch, 2),
            "edge_distance_mm": round(edge, 2),
            "min_outer_radius_mm": round(min_outer_r, 2),
            "min_outer_diameter_mm": round(2 * min_outer_r, 2),
        },
        warnings=(
            [] if not plate_thickness_mm else
            [f"a {plate_thickness_mm:g} mm plate gives "
             f"{plate_thickness_mm / bolt_size_mm:.2f}d of thread engagement if "
             f"tapped rather than clearance-drilled; call "
             f"calc_thread_engagement to size it properly"]),
    )


registry.register(Skill(
    name="create_bolt_pattern",
    description=(
        "Resolve a circular bolt pattern: clearance hole from ISO 273, hole "
        "spacing checked for socket access, and the minimum outer diameter the "
        "part needs so the holes keep their edge distance. Refuses patterns "
        "that cannot be assembled. Use this instead of choosing hole sizes and "
        "spacing yourself."),
    parameters={
        "type": "object",
        "properties": {
            "bolt_size_mm": {"type": "number",
                             "description": "Nominal bolt diameter, e.g. 8 for M8."},
            "count": {"type": "integer", "description": "Number of bolts."},
            "bolt_circle_dia_mm": {"type": "number",
                                   "description": "Bolt circle diameter (PCD)."},
            "plate_thickness_mm": {
                "type": "number",
                "description": "Optional: plate thickness, to comment on thread "
                               "engagement if the holes are tapped.",
            },
        },
        "required": ["bolt_size_mm", "count", "bolt_circle_dia_mm"],
    },
    run=create_bolt_pattern,
    graph=SkillGraph(
        functions=["ProvidesClampForce", "LocatesPart"],
        inputs=["bolt_size_mm", "count", "bolt_circle_dia_mm"],
        calculators=["thread_engagement", "bolt_torque_nm"],
        standards=["ISO 273 clearance holes"],
        outputs=["hole count, radius and bolt circle",
                 "minimum outer diameter", "edge distance"],
    ),
))
