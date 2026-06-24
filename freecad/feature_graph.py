"""Canonical FeatureGraph: assembly, validation, and measurement helpers.

Standalone — imports no FreeCAD and no heavy deps. Safe to import from the
orchestrator (system Python). ``fcstd_parser`` produces the raw graph (every
section except ``parameters``); the mapper fills ``parameters``; this module
merges and validates the result against ``feature_graph_schema.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import SCHEMA_PATH, SCHEMA_VERSION

EMPTY_SECTIONS = ("features", "sketches", "dependencies", "parameters", "constraints", "expressions")


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    return json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))


def empty_graph(source_id: str = "") -> dict[str, Any]:
    g: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_id": source_id,
        "document": {"name": "", "label": "", "object_count": 0},
    }
    for s in EMPTY_SECTIONS:
        g[s] = []
    return g


def build_graph(raw: dict[str, Any], parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge a raw extraction dict with recovered named parameters."""
    g = empty_graph(raw.get("source_id", ""))
    g["document"] = raw.get("document", g["document"])
    g["features"] = raw.get("features", [])
    g["sketches"] = raw.get("sketches", [])
    g["dependencies"] = raw.get("dependencies", [])
    g["constraints"] = raw.get("constraints", [])
    g["expressions"] = raw.get("expressions", [])
    g["parameters"] = parameters
    return g


def validate(graph: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid).

    Uses ``jsonschema`` when available; otherwise falls back to a structural check.
    """
    try:
        import jsonschema  # type: ignore

        validator = jsonschema.Draft7Validator(load_schema())
        errs = sorted(validator.iter_errors(graph), key=lambda e: list(e.path))
        return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs]
    except ImportError:
        return _structural_validate(graph)


def _structural_validate(graph: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for key in ("schema_version", "document", *EMPTY_SECTIONS):
        if key not in graph:
            errs.append(f"<root>: missing '{key}'")
    doc = graph.get("document", {})
    for k in ("name", "label", "object_count"):
        if k not in doc:
            errs.append(f"document: missing '{k}'")
    for i, f in enumerate(graph.get("features", [])):
        for k in ("id", "type", "type_id", "label", "parameters"):
            if k not in f:
                errs.append(f"features[{i}]: missing '{k}'")
    return errs


# ---------------------------------------------------------------------------
# Measurement helpers (consumed by parameter_mapper)
# ---------------------------------------------------------------------------

def iter_measurements(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the graph into matchable numeric measurements.

    Each measurement: {value, kind, target, property, relation}. ``kind`` is one
    of: diameter, radius, length, distance_from_origin, bolt_circle_diameter,
    count. These are what named key-parameters get value-matched against.
    """
    out: list[dict[str, Any]] = []

    # Feature lengths (Pad / Pocket depth / thickness / height)
    for f in graph.get("features", []):
        params = f.get("parameters", {})
        if "Length" in params and isinstance(params["Length"], (int, float)):
            out.append({
                "value": float(params["Length"]),
                "kind": "length",
                "target": f["id"],
                "property": "Length",
                "relation": "value",
            })
        if "Occurrences" in params and isinstance(params["Occurrences"], (int, float)):
            out.append({
                "value": float(params["Occurrences"]),
                "kind": "count",
                "target": f["id"],
                "property": "Occurrences",
                "relation": "value",
            })
        if "Radius" in params and isinstance(params["Radius"], (int, float)):
            out.append({
                "value": float(params["Radius"]),
                "kind": "radius",
                "target": f["id"],
                "property": "Radius",
                "relation": "value",
            })

    # Sketch geometry
    for sk in graph.get("sketches", []):
        geoms = sk.get("geometry", [])
        circles = [g for g in geoms if g.get("type") == "Circle"]
        lines = [g for g in geoms if g.get("type") == "LineSegment"]

        # Line-segment lengths (step riser/depth, slot lengths, edge sizes).
        for g in lines:
            dx = float(g.get("ex", 0.0)) - float(g.get("sx", 0.0))
            dy = float(g.get("ey", 0.0)) - float(g.get("sy", 0.0))
            ln = (dx * dx + dy * dy) ** 0.5
            if ln > 1e-6:
                out.append({"value": ln, "kind": "length",
                            "target": f"{sk['id']}:geo{g['index']}",
                            "property": "EdgeLength", "relation": "value"})

        # Sketch bounding-box spans (across-flats, width, overall sizes).
        # Prefer the parser's true edge bbox (covers BSpline/arc gear profiles);
        # fall back to primitive endpoints when absent.
        bbox = sk.get("bbox")
        if bbox:
            span_x, span_y = float(bbox["span_x"]), float(bbox["span_y"])
        else:
            xs, ys = [], []
            for g in geoms:
                t = g.get("type")
                if t == "Circle":
                    r = float(g.get("radius", 0.0))
                    xs += [float(g.get("cx", 0.0)) - r, float(g.get("cx", 0.0)) + r]
                    ys += [float(g.get("cy", 0.0)) - r, float(g.get("cy", 0.0)) + r]
                elif t == "LineSegment":
                    xs += [float(g.get("sx", 0.0)), float(g.get("ex", 0.0))]
                    ys += [float(g.get("sy", 0.0)), float(g.get("ey", 0.0))]
                elif t == "ArcOfCircle":
                    r = float(g.get("radius", 0.0))
                    xs += [float(g.get("cx", 0.0)) - r, float(g.get("cx", 0.0)) + r]
                    ys += [float(g.get("cy", 0.0)) - r, float(g.get("cy", 0.0)) + r]
            span_x = (max(xs) - min(xs)) if xs else 0.0
            span_y = (max(ys) - min(ys)) if ys else 0.0
        if span_x > 1e-6 or span_y > 1e-6:
            for axis, span in (("SpanX", span_x), ("SpanY", span_y)):
                if span > 1e-6:
                    # exposed as both length and diameter so width/size/dia/length names match
                    out.append({"value": span, "kind": "length", "target": sk["id"],
                                "property": axis, "relation": "bbox_span"})
                    out.append({"value": span, "kind": "diameter", "target": sk["id"],
                                "property": axis, "relation": "bbox_span"})

        # Edge count (polygon sides / segment count).
        if lines:
            out.append({"value": float(len(lines)), "kind": "count", "target": sk["id"],
                        "property": "EdgeCount", "relation": "len(lines)"})

        # Per-circle radius/diameter and distance from sketch origin
        for g in geoms:
            if g.get("type") == "Circle":
                r = float(g.get("radius", 0.0))
                cx, cy = float(g.get("cx", 0.0)), float(g.get("cy", 0.0))
                tgt = f"{sk['id']}:geo{g['index']}"
                out.append({"value": r, "kind": "radius", "target": tgt,
                            "property": "Radius", "relation": "value"})
                out.append({"value": 2.0 * r, "kind": "diameter", "target": tgt,
                            "property": "Diameter", "relation": "diameter=2*radius"})
                dist = (cx * cx + cy * cy) ** 0.5
                if dist > 1e-6:
                    out.append({"value": 2.0 * dist, "kind": "bolt_circle_diameter",
                                "target": sk["id"], "property": "BoltCircleDiameter",
                                "relation": "bcd=2*hypot(cx,cy)"})
                    out.append({"value": dist, "kind": "distance_from_origin",
                                "target": tgt, "property": "CenterDistance",
                                "relation": "hypot(cx,cy)"})
            elif g.get("type") == "ArcOfCircle":
                r = float(g.get("radius", 0.0))
                tgt = f"{sk['id']}:geo{g['index']}"
                out.append({"value": r, "kind": "radius", "target": tgt,
                            "property": "Radius", "relation": "value"})
        # Counts: number of circles in the sketch (bolt-hole arrays etc.)
        if circles:
            out.append({
                "value": float(len(circles)),
                "kind": "count",
                "target": sk["id"],
                "property": "CircleCount",
                "relation": "len(circles)",
            })

    return out
