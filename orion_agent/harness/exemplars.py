"""Curated FeatureGraph exemplars — the retrieval side of Generate.

A small library of worked (request -> compact FeatureGraph) pairs, every one of
which is compile-verified against real FreeCAD (see the integration test).
``retrieve`` picks the most relevant ones for a user request by keyword score;
the ContextPacker injects them into the Generate/Reconstruct system prompt so
the model imitates known-good structure instead of inventing shape from scratch.

Deliberately not embeddings: at this library size a transparent keyword score
is deterministic, debuggable, and free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Exemplar:
    name: str
    request: str                    # the user-style request it answers
    keywords: set[str]
    graph: dict
    notes: str = ""                 # one-line teaching point
    _score: float = field(default=0.0, repr=False)

    def render(self) -> str:
        return (f'Request: "{self.request}"' +
                (f"  ({self.notes})" if self.notes else "") + "\n"
                "FeatureGraph: " + json.dumps(self.graph, separators=(",", ":")))


def _rect(w: float, h: float) -> list[dict]:
    x, y = w / 2.0, h / 2.0
    return [
        {"type": "LineSegment", "sx": -x, "sy": -y, "ex": x, "ey": -y},
        {"type": "LineSegment", "sx": x, "sy": -y, "ex": x, "ey": y},
        {"type": "LineSegment", "sx": x, "sy": y, "ex": -x, "ey": y},
        {"type": "LineSegment", "sx": -x, "sy": y, "ex": -x, "ey": -y},
    ]


def _poly(points: list[tuple]) -> list[dict]:
    out = []
    for i, (sx, sy) in enumerate(points):
        ex, ey = points[(i + 1) % len(points)]
        out.append({"type": "LineSegment", "sx": sx, "sy": sy, "ex": ex, "ey": ey})
    return out


LIBRARY: list[Exemplar] = [
    Exemplar(
        name="plate_with_holes",
        request="a 100x60x8 mm mounting plate with four 6mm corner holes, 10mm from the edges",
        keywords={"plate", "holes", "mounting", "rectangular", "corner", "base"},
        notes="several circles in ONE sketch cut in one Pocket",
        graph={
            "features": [
                {"id": "sk_plate", "type": "Sketch"},
                {"id": "pad_plate", "type": "Pad", "parameters": {"Length": 8}},
                {"id": "sk_holes", "type": "Sketch"},
                {"id": "cut_holes", "type": "Pocket", "parameters": {"Length": 8}},
            ],
            "sketches": [
                {"id": "sk_plate", "plane": "XY", "geometry": _rect(100, 60)},
                {"id": "sk_holes", "plane": "XY", "geometry": [
                    {"type": "Circle", "cx": x, "cy": y, "radius": 3}
                    for x in (-40, 40) for y in (-20, 20)
                ]},
            ],
            "dependencies": [
                {"source": "sk_plate", "target": "pad_plate", "kind": "profile"},
                {"source": "sk_holes", "target": "cut_holes", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="flange_bolt_circle",
        request="a flange, 120mm outer diameter, 30mm centre bore, 10mm thick, "
                "with 8 M8 holes on a 90mm bolt circle",
        keywords={"flange", "bolt", "bore", "disc", "hub", "ring", "bolt circle"},
        notes="one bolt hole + PolarPattern makes the circle",
        graph={
            "features": [
                {"id": "sk_disc", "type": "Sketch"},
                {"id": "pad_disc", "type": "Pad", "parameters": {"Length": 10}},
                {"id": "sk_bore", "type": "Sketch"},
                {"id": "cut_bore", "type": "Pocket", "parameters": {"Length": 10}},
                {"id": "sk_bolt", "type": "Sketch"},
                {"id": "cut_bolt", "type": "Pocket", "parameters": {"Length": 10}},
                {"id": "pattern_bolts", "type": "PolarPattern",
                 "parameters": {"Occurrences": 8, "Angle": 360,
                                "_Axis": {"role": "Z_Axis"},
                                "_Originals": ["cut_bolt"]}},
            ],
            "sketches": [
                {"id": "sk_disc", "plane": "XY",
                 "geometry": [{"type": "Circle", "cx": 0, "cy": 0, "radius": 60}]},
                {"id": "sk_bore", "plane": "XY",
                 "geometry": [{"type": "Circle", "cx": 0, "cy": 0, "radius": 15}]},
                {"id": "sk_bolt", "plane": "XY",
                 "geometry": [{"type": "Circle", "cx": 45, "cy": 0, "radius": 4}]},
            ],
            "dependencies": [
                {"source": "sk_disc", "target": "pad_disc", "kind": "profile"},
                {"source": "sk_bore", "target": "cut_bore", "kind": "profile"},
                {"source": "sk_bolt", "target": "cut_bolt", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="rounded_block",
        request="a 80x50x20 block with 8mm rounded vertical corners and a 2mm "
                "chamfer on the top edges",
        keywords={"fillet", "rounded", "chamfer", "bevel", "block", "corners", "round"},
        notes="dressups select edges semantically, never by edge number",
        graph={
            "features": [
                {"id": "sk_block", "type": "Sketch"},
                {"id": "pad_block", "type": "Pad", "parameters": {"Length": 20}},
                {"id": "fillet_corners", "type": "Fillet",
                 "parameters": {"Radius": 8, "_Edges": "vertical"}},
                {"id": "chamfer_top", "type": "Chamfer",
                 "parameters": {"Size": 2, "_Edges": "top"}},
            ],
            "sketches": [
                {"id": "sk_block", "plane": "XY", "geometry": _rect(80, 50)},
            ],
            "dependencies": [
                {"source": "sk_block", "target": "pad_block", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="stepped_shaft",
        request="a stepped shaft: 30mm diameter for 20mm, then 20mm diameter for 30mm",
        keywords={"shaft", "cylinder", "stepped", "axle", "rod", "pin", "revolve",
                  "turned", "spindle"},
        notes="closed half-profile on XZ revolved 360 about the Z axis",
        graph={
            "features": [
                {"id": "sk_profile", "type": "Sketch"},
                {"id": "rev_shaft", "type": "Revolution",
                 "parameters": {"Angle": 360,
                                "_ReferenceAxis": {"role": "Z_Axis"}}},
            ],
            "sketches": [
                {"id": "sk_profile", "plane": "XZ", "geometry": _poly([
                    (0, 0), (15, 0), (15, 20), (10, 20), (10, 50), (0, 50),
                ])},
            ],
            "dependencies": [
                {"source": "sk_profile", "target": "rev_shaft", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="l_bracket",
        request="an L-bracket, 60mm base, 40mm upright, 8mm thick, 30mm wide",
        keywords={"bracket", "angle", "l-shaped", "l bracket", "upright", "leg"},
        notes="L profile drawn on XZ, padded to width",
        graph={
            "features": [
                {"id": "sk_l", "type": "Sketch"},
                {"id": "pad_l", "type": "Pad", "parameters": {"Length": 30}},
            ],
            "sketches": [
                {"id": "sk_l", "plane": "XZ", "geometry": _poly([
                    (0, 0), (60, 0), (60, 8), (8, 8), (8, 40), (0, 40),
                ])},
            ],
            "dependencies": [
                {"source": "sk_l", "target": "pad_l", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="hole_row",
        request="a 100x40x8 bar with a row of five 6mm holes, 20mm apart",
        keywords={"row", "array", "grid", "linear", "pattern", "series", "spaced",
                  "bar", "rail"},
        notes="one hole + LinearPattern; Length is the total span",
        graph={
            "features": [
                {"id": "sk_bar", "type": "Sketch"},
                {"id": "pad_bar", "type": "Pad", "parameters": {"Length": 8}},
                {"id": "sk_hole", "type": "Sketch"},
                {"id": "cut_hole", "type": "Pocket", "parameters": {"Length": 8}},
                {"id": "pattern_row", "type": "LinearPattern",
                 "parameters": {"Occurrences": 5, "Length": 80,
                                "_Direction": {"role": "X_Axis"},
                                "_Originals": ["cut_hole"]}},
            ],
            "sketches": [
                {"id": "sk_bar", "plane": "XY", "geometry": _rect(100, 40)},
                {"id": "sk_hole", "plane": "XY",
                 "geometry": [{"type": "Circle", "cx": -40, "cy": 0, "radius": 3}]},
            ],
            "dependencies": [
                {"source": "sk_bar", "target": "pad_bar", "kind": "profile"},
                {"source": "sk_hole", "target": "cut_hole", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="lofted_transition",
        request="a lofted transition 40mm tall from an 80x50 rectangular base "
                "to a 30x20 rectangular top",
        keywords={"loft", "lofted", "transition", "taper", "tapered", "funnel",
                  "hopper", "adapter", "morph"},
        notes='profile = bottom section; each section sketch has its own "z"',
        graph={
            "features": [
                {"id": "sk_base", "type": "Sketch"},
                {"id": "sk_top", "type": "Sketch"},
                {"id": "loft1", "type": "Loft",
                 "parameters": {"_Sections": ["sk_top"]}},
            ],
            "sketches": [
                {"id": "sk_base", "plane": "XY", "geometry": _rect(80, 50)},
                {"id": "sk_top", "plane": "XY", "z": 40, "geometry": _rect(30, 20)},
            ],
            "dependencies": [
                {"source": "sk_base", "target": "loft1", "kind": "profile"},
            ],
        },
    ),
    Exemplar(
        name="swept_elbow_tube",
        request="a solid 8mm-diameter rod swept along an L-path: 20mm up, a "
                "10mm-radius elbow, then 20mm horizontal",
        keywords={"sweep", "swept", "pipe", "tube", "elbow", "bend", "bent",
                  "rod", "path", "spine"},
        notes="profile on XY at path start; OPEN spine sketch on XZ (line-arc-line)",
        graph={
            "features": [
                {"id": "sk_prof", "type": "Sketch"},
                {"id": "sk_path", "type": "Sketch"},
                {"id": "sweep1", "type": "Sweep",
                 "parameters": {"_Spine": "sk_path"}},
            ],
            "sketches": [
                {"id": "sk_prof", "plane": "XY", "geometry": [
                    {"type": "Circle", "cx": 0, "cy": 0, "radius": 4}]},
                {"id": "sk_path", "plane": "XZ", "geometry": [
                    {"type": "LineSegment", "sx": 0, "sy": 0, "ex": 0, "ey": 20},
                    {"type": "ArcOfCircle", "cx": 10, "cy": 20, "radius": 10,
                     "first": 1.5707963268, "last": 3.1415926536},
                    {"type": "LineSegment", "sx": 10, "sy": 30, "ex": 30, "ey": 30}]},
            ],
            "dependencies": [
                {"source": "sk_prof", "target": "sweep1", "kind": "profile"},
            ],
        },
    ),
]


def retrieve(message: str, k: int = 2) -> list[Exemplar]:
    """Top-k exemplars for a request by transparent keyword scoring.

    Always returns at least one (the generic plate) so Generate is never
    zero-shot on graph structure.
    """
    words = set(message.lower().replace(",", " ").replace(".", " ").split())
    text = message.lower()
    scored = []
    for ex in LIBRARY:
        score = sum(2.0 if " " in kw and kw in text else float(kw in words)
                    for kw in ex.keywords)
        scored.append((score, ex))
    scored.sort(key=lambda p: -p[0])
    picked = [ex for score, ex in scored[:k] if score > 0]
    if not picked:
        picked = [LIBRARY[0]]
    return picked


def render_examples(message: str, k: int = 2) -> str:
    """The prompt block the ContextPacker appends for Generate/Reconstruct."""
    picked = retrieve(message, k=k)
    return "\n\n".join(ex.render() for ex in picked)
