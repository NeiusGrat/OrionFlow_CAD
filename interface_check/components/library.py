"""Interface specs of bought parts, and matching placed instances to them.

Order of trust: the knowledge base (NEMA flange table, SKF bearings), then a
spec read from the vendor's STEP (pure geometry), then one read from a
datasheet (LLM, every number checked against the PDF text, user confirms).

A name match alone is never trusted. The instance's own geometry must show the
spec — the hole square and pilot for a motor, the bore and OD for a bearing —
or the match becomes a ``COMPONENT_UNCONFIRMED`` finding instead of a silent
assumption that the part is what its name says.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from ..models import Features
from ..rules import bearings

GEOM_TOL = 0.1      # mm, spec vs measured


@dataclass
class Component:
    name: str
    type: str                                   # motor | bearing | servo | other
    mount: dict = field(default_factory=dict)   # {pattern: rect|circle, a_mm, b_mm, pcd_mm, hole_count, thread}
    pilot_dia_mm: Optional[float] = None
    shaft_dia_mm: Optional[float] = None
    bore_mm: Optional[float] = None             # bearings
    od_mm: Optional[float] = None
    width_mm: Optional[float] = None
    mass_kg: Optional[float] = None
    aliases: list[str] = field(default_factory=list)   # regexes on normalised names
    source: dict = field(default_factory=dict)
    verified: bool = False
    needs_review: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


#: NEMA ICS 16 flange dimensions. Hole spacing is the square side.
NEMA: list[Component] = [
    Component("NEMA 11 stepper", "motor", {"pattern": "rect", "a_mm": 23.0, "b_mm": 23.0, "hole_count": 4, "thread": "M2.5"},
              pilot_dia_mm=22.0, shaft_dia_mm=5.0, aliases=[r"nema\s*-?\s*11\b", r"\bnema11"]),
    Component("NEMA 14 stepper", "motor", {"pattern": "rect", "a_mm": 26.0, "b_mm": 26.0, "hole_count": 4, "thread": "M3"},
              pilot_dia_mm=22.0, shaft_dia_mm=5.0, aliases=[r"nema\s*-?\s*14\b", r"\bnema14"]),
    Component("NEMA 17 stepper", "motor", {"pattern": "rect", "a_mm": 31.0, "b_mm": 31.0, "hole_count": 4, "thread": "M3"},
              pilot_dia_mm=22.0, shaft_dia_mm=5.0, aliases=[r"nema\s*-?\s*17\b", r"\bnema17", r"\b42\s*byg"]),
    Component("NEMA 23 stepper", "motor", {"pattern": "rect", "a_mm": 47.14, "b_mm": 47.14, "hole_count": 4, "thread": "through 5.0"},
              pilot_dia_mm=38.1, shaft_dia_mm=6.35, aliases=[r"nema\s*-?\s*23\b", r"\bnema23", r"\b57\s*byg"]),
]
for _c in NEMA:
    _c.source = {"kind": "knowledge_base", "ref": "NEMA ICS 16"}
    _c.verified = True


def library_path() -> Path:
    return Path(os.environ.get("INTERFACE_CHECK_LIBRARY", "data/interface_check/components.json"))


class Library:
    def __init__(self, extra: list[Component] | None = None, path: Path | None = None):
        self.path = path or library_path()
        self.user: list[Component] = list(extra or [])
        if self.path.exists():
            for row in json.loads(self.path.read_text()):
                self.user.append(Component(**row))

    def all(self) -> list[Component]:
        return self.user + NEMA

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([c.to_dict() for c in self.user], indent=2))

    def add(self, c: Component) -> None:
        self.user = [u for u in self.user if u.name != c.name] + [c]

    def by_name(self, name: str) -> Optional[Component]:
        """Library entry this instance name refers to (user entries win)."""
        low = name.lower().replace("_", " ")
        for c in self.all():
            for pat in c.aliases or [re.escape(c.name.lower())]:
                if re.search(pat, low):
                    return c
        hit = bearings.lookup(name)
        if hit:
            des, (d, D, B) = hit
            return Component(f"{des} bearing", "bearing", bore_mm=d, od_mm=D, width_mm=B,
                             source={"kind": "knowledge_base", "ref": "SKF deep groove / ISO 15"},
                             verified=True)
        return None


@dataclass
class Match:
    component: Component
    confirmed: bool
    measured: dict
    reason: str = ""
    axis: Optional[np.ndarray] = None       # motor shaft / bearing axis, assembly frame
    centre: Optional[np.ndarray] = None
    pattern: object = None


def confirm(c: Component, f: Features) -> Match:
    """Does this instance's geometry show the spec? (features in assembly frame)"""
    if c.type == "bearing":
        return _confirm_bearing(c, f)
    if c.mount.get("pattern"):
        return _confirm_mount(c, f)
    return Match(c, False, {}, "spec has no geometry to confirm")


def _confirm_bearing(c: Component, f: Features) -> Match:
    od = _closest([b for b in f.bosses], c.od_mm)
    bore = _closest([h for h in f.holes], c.bore_mm)
    measured = {"od_mm": od.diameter if od else None, "bore_mm": bore.diameter if bore else None}
    ok = (od is not None and bore is not None and abs(od.diameter - c.od_mm) <= GEOM_TOL
          and abs(bore.diameter - c.bore_mm) <= GEOM_TOL)
    if ok and c.width_mm:
        measured["width_mm"] = od.length
        ok = abs(od.length - c.width_mm) <= max(GEOM_TOL, 0.02 * c.width_mm)
    reason = "" if ok else (f"expected bore Ø{c.bore_mm} / OD Ø{c.od_mm} x {c.width_mm}, "
                            f"measured bore {_fmt(measured['bore_mm'])} / OD {_fmt(measured['od_mm'])}")
    return Match(c, ok, measured, reason, axis=od.axis if od else None, centre=od.center if od else None)


def _confirm_mount(c: Component, f: Features) -> Match:
    m = c.mount
    best, err = None, 1e9
    for p in f.patterns:
        if len(p.holes) != m.get("hole_count", len(p.holes)):
            continue
        if m["pattern"] == "rect" and p.kind == "rect":
            e = abs(p.a - min(m["a_mm"], m["b_mm"])) + abs(p.b - max(m["a_mm"], m["b_mm"]))
        elif m["pattern"] == "circle" and p.kind == "circle":
            e = abs(p.pcd - m["pcd_mm"])
        else:
            continue
        if e < err:
            best, err = p, e
    measured = {"pattern": best.describe() if best else None}
    if best is None or err > GEOM_TOL * 2:
        return Match(c, False, measured, f"no {m['pattern']} hole pattern matching the spec "
                     f"({_spec_pattern(c)}) on the part", pattern=best)
    pilot = None
    if c.pilot_dia_mm:
        pilot = _closest([b for b in f.bosses if _coaxial(b, best)], c.pilot_dia_mm)
        measured["pilot_dia_mm"] = pilot.diameter if pilot else None
        if pilot is None or abs(pilot.diameter - c.pilot_dia_mm) > GEOM_TOL:
            return Match(c, False, measured, f"hole pattern matches but pilot Ø{c.pilot_dia_mm} "
                         f"not found (measured {_fmt(measured['pilot_dia_mm'])})", pattern=best)
    return Match(c, True, measured, axis=best.axis, centre=pilot.center if pilot else best.centroid,
                 pattern=best)


def _spec_pattern(c: Component) -> str:
    m = c.mount
    if m["pattern"] == "rect":
        return f"{m['hole_count']} holes on {m['a_mm']} x {m['b_mm']}"
    return f"{m['hole_count']} holes on PCD {m['pcd_mm']}"


def _coaxial(b, p) -> bool:
    from ..features import axis_offset, parallel
    return parallel(b.axis, p.axis) and axis_offset(b, p.centroid) < 0.5


def _closest(items, target):
    if target is None or not items:
        return None
    return min(items, key=lambda x: abs(x.diameter - target))


def _fmt(v) -> str:
    return "none" if v is None else f"Ø{v:.2f}"
