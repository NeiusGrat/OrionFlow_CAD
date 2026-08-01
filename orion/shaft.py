"""Generate a stepped shaft from a resolved design, not from a wish.

A shaft is the part of a rotary joint where every other decision lands. Its
seats are the bearings' bores; its shoulders are the bearings' own abutment
diameters, which is what the constraint join in ``knowledge.abutment``
established; its keyed section is as long as the key the torque needed; its
overall length is the sum of everything the assembly asked for. Almost nothing
about it is chosen.

That is why it is generated from the resolved plan rather than beside it. A
shaft drawn independently and then checked against the bearings is a shaft that
disagrees with them roughly as often as someone mistypes, and the disagreement
looks like a drawing rather than an error. Here the bore *is* the seat, by
construction, and there is no step at which they could diverge.

**A shoulder is only as good as the number behind it.** Where a bearing carries
an attributed ``da min`` the shoulder is set to it. Where it does not, the
section is emitted without a shoulder and says so, because a shoulder invented
to make the drawing look finished is exactly the failure the abutment work
exists to prevent — the shaft looks right, the ring seats on its corner, and
the bearing fails early for a reason nothing in the model records.

The geometry is a revolved half-profile: a stepped shaft is a polyline of
radius and length, and every section contributes one rectangle to it. Volume
follows in closed form, so the build is checkable against arithmetic rather
than against a previous run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

#: A turned step needs a relief where it meets a shoulder, or the tool leaves a
#: radius the mating ring sits on. 0.5 mm is the usual undercut for this size
#: range and is stated rather than assumed silently.
UNDERCUT_MM = 0.5

BEARING_SEAT = "bearing_seat"
SHOULDER = "shoulder"
KEYED = "keyed_section"
SEAL_JOURNAL = "seal_journal"
PLAIN = "plain"
THREADED = "threaded_end"


@dataclass
class Section:
    """One cylinder of the shaft, and what decided its diameter."""

    name: str
    kind: str
    dia_mm: float
    length_mm: float
    why: str
    #: Features cut into this section rather than turned as part of it.
    features: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def radius_mm(self) -> float:
        return self.dia_mm / 2.0

    def volume_mm3(self) -> float:
        return math.pi * self.radius_mm**2 * self.length_mm

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "dia_mm": self.dia_mm,
            "length_mm": self.length_mm,
            "why": self.why,
        }
        if self.features:
            out["features"] = self.features
        if self.warnings:
            out["warnings"] = self.warnings
        return out


@dataclass
class Shaft:
    """A stepped shaft as an ordered run of sections."""

    sections: list[Section] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def length_mm(self) -> float:
        return sum(s.length_mm for s in self.sections)

    @property
    def max_dia_mm(self) -> float:
        return max((s.dia_mm for s in self.sections), default=0.0)

    def volume_mm3(self) -> float:
        return sum(s.volume_mm3() for s in self.sections)

    def mass_g(self, density: float = 7.85e-3) -> float:
        return self.volume_mm3() * density

    def runs(self) -> list[tuple[float, float]]:
        """Sections merged into distinct turned diameters.

        Adjacent sections of equal diameter are one cylinder. Emitting a step
        between them puts two identical points in the polyline — a zero-length
        edge the kernel is entitled to reject, and a shape that is wrong in a
        way volume would never reveal.
        """
        out: list[tuple[float, float]] = []
        for section in self.sections:
            if out and abs(out[-1][0] - section.radius_mm) < 1e-9:
                out[-1] = (out[-1][0], out[-1][1] + section.length_mm)
            else:
                out.append((section.radius_mm, section.length_mm))
        return out

    def variables(self) -> dict[str, float]:
        """One radius and one length per turned diameter.

        The Blueprint IR wants every dimension to be an expression over named
        variables, and it is right to: a literal in a profile is a number
        nothing can re-derive, which is the difference between a parametric
        model and a drawing that happens to have been computed once.
        """
        v: dict[str, float] = {}
        for i, (radius, length) in enumerate(self.runs(), 1):
            v[f"r{i}"], v[f"L{i}"] = radius, length
        return v

    def profile(self) -> list[list[str]]:
        """The revolved half-profile, as a closed polyline of (r, z).

        Starts and ends on the axis, so the revolve produces a solid rather
        than a tube. Each point is an expression over the run variables, and
        the z coordinates accumulate as sums of the lengths before them — so
        lengthening one section moves everything downstream of it without
        anything being recomputed here.
        """
        points: list[list[str]] = [["0", "0"]]
        reached: list[str] = []
        for i in range(1, len(self.runs()) + 1):
            here = " + ".join(reached) or "0"
            points.append([f"r{i}", here])
            reached.append(f"L{i}")
            points.append([f"r{i}", " + ".join(reached)])
        points.append(["0", " + ".join(reached)])
        return points

    def volume_expr(self) -> str:
        return " + ".join(f"pi*r{i}**2*L{i}" for i in range(1, len(self.runs()) + 1))

    def length_expr(self) -> str:
        return " + ".join(f"L{i}" for i in range(1, len(self.runs()) + 1))

    def widest(self) -> str:
        """The variable naming the largest turned diameter."""
        runs = self.runs()
        return f"r{max(range(len(runs)), key=lambda i: runs[i][0]) + 1}"

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "length_mm": round(self.length_mm, 3),
            "max_dia_mm": self.max_dia_mm,
            "volume_mm3": round(self.volume_mm3(), 3),
            "mass_g": round(self.mass_g(), 2),
            "citations": self.citations,
            "warnings": self.warnings,
        }

    def explain(self) -> str:
        lines = [
            f"SHAFT  {self.length_mm:g} mm long, "
            f"{self.max_dia_mm:g} mm max, {self.mass_g():.0f} g",
            "",
        ]
        z = 0.0
        for s in self.sections:
            lines.append(
                f"  {z:7.2f}..{z + s.length_mm:<7.2f} " f"dia {s.dia_mm:<7g} {s.name}"
            )
            lines.append(f"          {s.why}")
            for feature in s.features:
                lines.append(
                    f"          + {feature['kind']}: " f"{feature.get('detail', '')}"
                )
            for warning in s.warnings:
                lines.append(f"          NOTE: {warning}")
            z += s.length_mm
        if self.citations:
            lines += ["", "per: " + "; ".join(self.citations)]
        for w in self.warnings:
            lines.append(f"NOTE: {w}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
def from_plan(plan: Any, overhang_mm: float = 10.0) -> Shaft:
    """Build the shaft the resolved plan implies.

    Reads the bearing that was selected and the key that was sized, and lays
    out: an overhang to drive, the keyed section, a shoulder to locate the
    bearing against, and the bearing seat itself. Nothing here picks a
    diameter — every one of them was decided upstream and is quoted with the
    decision that made it.
    """
    from orion.knowledge import functions as F
    from orion.skills.bearing_seat import bearing as lookup

    shaft = Shaft()
    rotation = next(
        (
            r
            for r in plan.resolutions
            if r.function == F.SUPPORTS_ROTATION and r.resolved
        ),
        None,
    )
    if rotation is None:
        shaft.warnings.append(
            "no bearing was resolved, so there is no seat to build the shaft "
            "around; the shaft is what the assembly's numbers land on and "
            "there are none yet"
        )
        return shaft

    designation = rotation.summary.split()[0]
    spec = lookup(designation)
    bore = float(spec["d"])
    width = float(spec["B"])
    shaft.citations.append(
        f"ISO 15 boundary dimensions for {designation} "
        f"({bore:g} x {spec['D']:g} x {width:g} mm)"
    )

    # The drive end, and the key that was already sized against the torque.
    key = next(
        (
            r
            for r in plan.resolutions
            if r.function == F.TRANSMITS_TORQUE and r.resolved
        ),
        None,
    )
    if key is not None:
        key_len = key.provides.get("key_length_mm", 0.0)
        keyed = Section(
            name="keyed drive section",
            kind=KEYED,
            dia_mm=bore,
            length_mm=key_len + 2 * UNDERCUT_MM,
            why=f"the bearing bore {bore:g} mm carried through so the drive "
            f"and the seat are one turned diameter",
            features=[
                {
                    "kind": "keyway",
                    "detail": f"DIN 6885 "
                    f"{key.provides.get('key_width_mm', 0):g} x "
                    f"{key.provides.get('key_height_mm', 0):g}, "
                    f"{key_len:g} mm long",
                    "width_mm": key.provides.get("key_width_mm"),
                    "depth_mm": (key.provides.get("key_height_mm", 0) / 2.0),
                    "length_mm": key_len,
                }
            ],
        )
        shaft.sections.append(
            Section(
                name="drive overhang",
                kind=PLAIN,
                dia_mm=bore,
                length_mm=overhang_mm,
                why="free length beyond the key for the coupling to reach",
            )
        )
        shaft.sections.append(keyed)
        shaft.citations.extend(key.citations)

    # The shoulder the inner ring abuts. Only if a real number backs it.
    da_min = spec.get("da_min")
    if da_min is not None:
        shaft.sections.append(
            Section(
                name="locating shoulder",
                kind=SHOULDER,
                dia_mm=float(da_min),
                length_mm=max(2.0, (float(da_min) - bore) / 2.0),
                why=f"da min {da_min:g} mm — the abutment attributed to "
                f"{designation} by constraint satisfaction, so the ring seats "
                f"on its face rather than its chamfer",
                features=[
                    {
                        "kind": "undercut",
                        "detail": f"{UNDERCUT_MM:g} mm relief at the step, so "
                        f"the tool radius does not become the seat",
                    }
                ],
            )
        )
        conf = spec.get("abutment_confidence")
        if conf:
            shaft.warnings.append(
                f"the shoulder diameter is {conf}, not read against "
                f"{designation}'s own row — it was proved consistent with it"
            )
    else:
        shaft.warnings.append(
            f"no abutment diameter on file for {designation}, so the shaft "
            f"carries no locating shoulder. The inner ring has nothing to seat "
            f"against and needs a spacer or a retaining ring instead."
        )

    shaft.sections.append(
        Section(
            name=f"{designation} seat",
            kind=BEARING_SEAT,
            dia_mm=bore,
            length_mm=width,
            why=f"{designation} bore {bore:g} mm over its full {width:g} mm width, "
            f"interference so the inner ring cannot creep",
        )
    )
    return shaft


def blueprint(shaft: Shaft, part_class: str = "stepped_shaft") -> Any:
    """The shaft as a frozen Blueprint, ready for the same compiler and checks.

    Asserted on closed-form volume and both extents, so a build is checked
    against arithmetic rather than against whatever it produced last time.
    """
    from orion.blueprint import Blueprint

    features = [
        {"id": "Body", "type": "Body", "parameters": {}},
        {"id": "s_shaft", "type": "Sketch", "parameters": {}},
        {
            "id": "shaft",
            "type": "Revolution",
            "rationale": "stepped shaft: seats, shoulder and keyed "
            "section turned as one revolved profile",
            "parameters": {
                "Angle": "360",
                "Reversed": False,
                "_ReferenceAxis": {
                    "object": "s_shaft",
                    "is_sketch": True,
                    "subs": ["V_Axis"],
                },
            },
        },
    ]
    template = {
        "features": features,
        "sketches": [
            {
                "id": "s_shaft",
                "plane": "XZ",
                "z": "0",
                "profile": {"builder": "polyline", "args": {"points": shaft.profile()}},
            }
        ],
        "dependencies": [{"source": "s_shaft", "target": "shaft", "kind": "profile"}],
    }
    return Blueprint(
        part_class=part_class,
        variables=shaft.variables(),
        datums={},
        design_plan={
            "steps": [
                {
                    "step": i + 1,
                    "eq": f"dia {s.dia_mm:g} x {s.length_mm:g}",
                    "why": s.why,
                }
                for i, s in enumerate(shaft.sections)
            ]
        },
        assertions=[
            {
                "id": "body",
                "kind": "body_volume",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": shaft.volume_expr(),
            },
            {
                "id": "od_extent",
                "kind": "bbox_extent",
                "axis": "x",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": f"2*{shaft.widest()}",
            },
            {
                "id": "length_extent",
                "kind": "bbox_extent",
                "axis": "z",
                "tier": 1,
                "tol_rel": 1e-6,
                "target": shaft.length_expr(),
            },
        ],
        template=template,
    ).freeze()


def from_request(request: str) -> tuple[Shaft, Optional[Any]]:
    """End to end: requirements to a shaft, through the constraint solver."""
    from orion import resolve as RS

    result = RS.resolve(request)
    if result.chosen is None:
        empty = Shaft()
        empty.warnings.append(
            f"no design was resolved, so there is no shaft: " f"{result.explanation}"
        )
        return empty, None
    return from_plan(result.chosen.plan), result
