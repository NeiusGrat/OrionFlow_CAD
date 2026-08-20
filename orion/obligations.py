"""What the part must actually contain, derived from what the user asked for.

The defect this exists for: a request stating ``hole_count = 4`` and
``hole_d = 5`` with no bolt circle built a **blank plate**, and it graded
VERIFIED. Every existing check agreed — the extents matched, the solid was
sound, and the closed-form volume matched the kernel exactly, because the volume
was computed from the same absent holes. ``blueprint_gen``'s consumption guard
did not fire either: the builder *read* ``hole_count`` and ``hole_r`` before
deciding it could not place them, so ``_Seen`` recorded them as used.

Presence of a parameter is not existence of a feature. Those are different
claims and this module is where they stop being conflated. Four states, kept
apart on purpose:

    requested      the user asked for it
    represented    the frozen contract carries a feature that claims to satisfy it
    instantiated   the built artifact carries that feature
    verified       the geometry independently agrees on count, size and placement

``hole_count = 4`` in the ledger establishes the first. It says nothing about
the other three, and the verdict must not treat it as if it did.

An obligation is derived **from the requirements**, never from the template the
builder produced. That direction is load-bearing: a builder that drops a feature
would also drop an obligation derived from its own output, and the check would
agree with the bug.

The rules are a table, one entry per feature a family can carry, because the
alternative is the same knowledge spread across eleven conditional blocks in
``blueprint_gen`` — which is exactly how the hole got there.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

#: Feature kinds. ``bore`` and ``hole_pattern`` are cylindrical voids and are
#: independently measurable in the built solid — a cylindrical face carries its
#: own radius and axis. ``pocket`` and ``slot`` are solid features whose
#: *existence* is checkable through feature attribution but whose dimensions are
#: not, and they say so rather than passing quietly.
BORE = "bore"
HOLE_PATTERN = "hole_pattern"
POCKET = "pocket"
SLOT = "slot"

#: Placement forms an obligation can carry. ``None`` means the request fixed a
#: size and a count but not a position, which is a real state: the count and the
#: diameter are still obligations even when nothing says where the holes go.
CENTRED = "centred"  # one axis, at the body's centre
BOLT_CIRCLE = "bolt_circle"  # n axes, all at radius r from the centre
GRID = "grid"  # n axes on a rectangular pitch
LINE = "line"  # n axes evenly spaced along an edge


@dataclass(frozen=True)
class Obligation:
    """One feature the built part is required to contain."""

    id: str
    kind: str
    label: str
    #: How many separate instances. ``None`` where the request fixed a size but
    #: not a number — the diameter is still owed even if the count is not.
    count: Optional[int] = None
    #: Cylindrical radius in mm, for ``bore`` and ``hole_pattern``.
    radius: Optional[float] = None
    #: ``{"form": ..., ...}`` or ``None`` when the request did not fix one.
    placement: Optional[dict] = None
    #: The requirement keys that created this obligation. Kept so a failure can
    #: name what the user said rather than what the schema calls it.
    source: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in asdict(self).items() if v not in (None, (), [])}
        out["source"] = list(self.source)
        return out


@dataclass(frozen=True)
class Rule:
    """When a set of requirements creates an obligation, and what it says."""

    id: str
    kind: str
    label: str
    #: Any one of these being present raises the obligation. Deliberately *any*
    #: rather than all: the defect case is ``hole_count`` and ``hole_r`` present
    #: with the bolt circle absent, and a rule that needed all three would go
    #: quiet exactly when the builder does.
    triggers: tuple[str, ...]
    build: Callable[[dict], dict] = field(repr=False, default=lambda _r: {})


def _f(req: dict, key: str) -> Optional[float]:
    value = req.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _i(req: dict, key: str) -> Optional[int]:
    value = _f(req, key)
    return int(value) if value is not None else None


def _bolt_circle(req: dict) -> dict:
    pcd_r = _f(req, "pcd_r")
    return {
        "count": _i(req, "hole_count"),
        "radius": _f(req, "hole_r"),
        "placement": (
            {"form": BOLT_CIRCLE, "radius": pcd_r} if pcd_r is not None else None
        ),
    }


def _square_pattern(req: dict) -> dict:
    square = _f(req, "bolt_square")
    return {
        # Four holes, because that is what a square pattern is and what
        # ``blueprint_gen.l_bracket`` builds from it.
        "count": 4 if square is not None else None,
        "radius": _f(req, "hole_r"),
        "placement": (
            {"form": GRID, "pitch": [square, square]} if square is not None else None
        ),
    }


def _grid_pattern(req: dict) -> dict:
    px, py = _f(req, "hole_pitch_x"), _f(req, "hole_pitch_y")
    return {
        "count": 4 if (px is not None and py is not None) else None,
        "radius": _f(req, "hole_r"),
        "placement": (
            {"form": GRID, "pitch": [px, py]}
            if (px is not None and py is not None)
            else None
        ),
    }


def _ports(req: dict) -> dict:
    return {
        "count": _i(req, "port_count"),
        "radius": _f(req, "port_r"),
        "placement": {"form": LINE} if _i(req, "port_count") else None,
    }


def _centred(key: str) -> Callable[[dict], dict]:
    def build(req: dict) -> dict:
        return {
            "count": 1,
            "radius": _f(req, key),
            "placement": {"form": CENTRED},
        }

    return build


def _sized(key: str) -> Callable[[dict], dict]:
    """A cylindrical feature with a stated size and no stated count or place."""

    def build(req: dict) -> dict:
        return {"count": None, "radius": _f(req, key), "placement": None}

    return build


#: Per family, every feature the request can ask for.
#:
#: Kept beside the schema it reads rather than inside the builders, because the
#: builders are where a requirement can go quiet — a rule that lived in the same
#: conditional block would go quiet with it.
RULES: dict[str, tuple[Rule, ...]] = {
    "rect_plate": (
        Rule("central_bore", BORE, "central bore", ("bore_r",), _centred("bore_r")),
        Rule("bolt_circle", HOLE_PATTERN, "mounting hole pattern",
             ("hole_count", "hole_r", "pcd_r"), _bolt_circle),
        Rule("pocket", POCKET, "pocket",
             ("pocket_l", "pocket_w", "pocket_depth")),
        Rule("slots", SLOT, "mounting slots",
             ("slot_length", "slot_width", "slot_edge_gap")),
    ),
    "l_bracket": (
        Rule("pilot_bore", BORE, "pilot bore", ("bore_r",), _centred("bore_r")),
        Rule("bolt_square", HOLE_PATTERN, "mounting hole pattern",
             ("hole_r", "bolt_square"), _square_pattern),
        Rule("counterbore", HOLE_PATTERN, "counterbore",
             ("cbore_r", "cbore_depth"), _sized("cbore_r")),
        Rule("slots", SLOT, "mounting slots",
             ("slot_length", "slot_width", "slot_count", "slot_edge_gap")),
    ),
    "bearing_housing": (
        Rule("bearing_seat", BORE, "bearing seat", ("bore_r",), _centred("bore_r")),
        Rule("flange_recess", HOLE_PATTERN, "flange recess",
             ("recess_r", "recess_depth"), _sized("recess_r")),
        Rule("mounting_holes", HOLE_PATTERN, "mounting hole pattern",
             ("hole_r", "hole_pitch_x", "hole_pitch_y"), _grid_pattern),
    ),
    "manifold": (
        Rule("main_passage", BORE, "main passage", ("passage_r",),
             _sized("passage_r")),
        Rule("ports", HOLE_PATTERN, "ports", ("port_count", "port_r"), _ports),
        Rule("mounting_holes", HOLE_PATTERN, "mounting hole pattern",
             ("hole_r", "hole_edge_gap"), _sized("hole_r")),
        Rule("counterbore", HOLE_PATTERN, "counterbore",
             ("cbore_r", "cbore_depth"), _sized("cbore_r")),
    ),
}


def derive(family: str, requirements: dict) -> list[Obligation]:
    """Every feature this request obliges the part to contain.

    Reads the *resolved* requirements — diameters already halved into radii by
    ``interview.resolve`` — because that is what the builder is handed and what
    the geometry will be measured against.
    """
    out: list[Obligation] = []
    for rule in RULES.get(family, ()):
        if not any(requirements.get(t) is not None for t in rule.triggers):
            continue
        spec = rule.build(requirements)
        out.append(
            Obligation(
                id=rule.id,
                kind=rule.kind,
                label=rule.label,
                count=spec.get("count"),
                radius=spec.get("radius"),
                placement=spec.get("placement"),
                source=tuple(t for t in rule.triggers if requirements.get(t) is not None),
            )
        )
    return out


def to_dicts(obligations: list[Obligation]) -> list[dict]:
    return [o.to_dict() for o in obligations]


def from_dicts(rows: Optional[list]) -> list[Obligation]:
    """Rehydrate obligations from a frozen Blueprint's ``design_plan``."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        out.append(
            Obligation(
                id=row.get("id", "?"),
                kind=row.get("kind", "?"),
                label=row.get("label", row.get("id", "?")),
                count=row.get("count"),
                radius=row.get("radius"),
                placement=row.get("placement"),
                source=tuple(row.get("source") or ()),
            )
        )
    return out
