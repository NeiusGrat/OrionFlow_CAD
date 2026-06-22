"""Topology-summary serializer.

Turns a (potentially large) shape description into a compact, token-bounded
string for the model's context, plus an on-demand ``expand`` path so the model
can drill into one shape without dumping the whole B-rep.

Works on both the addon's ``inspect_topology`` result and the sandbox's result
topology (same shape of dict).
"""

from __future__ import annotations

from typing import Any


def _fmt_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "—"
    return ", ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def summarize_shape(shape: dict[str, Any]) -> str:
    """One-line-ish compact summary of a single shape dict."""
    name = shape.get("name") or shape.get("label") or "shape"
    parts = [
        f"{name}: {shape.get('solids', '?')} solid(s), "
        f"{shape.get('faces', '?')} faces / {shape.get('edges', '?')} edges / "
        f"{shape.get('vertices', '?')} verts"
    ]
    surf = shape.get("surface_types") or {}
    if surf:
        parts.append(f"surfaces[{_fmt_counts(surf)}]")
    cyl = shape.get("cylindrical_faces")
    if cyl:
        parts.append(f"cylindrical_faces={cyl}")
    bb = shape.get("bounding_box") or {}
    if bb.get("size"):
        sx, sy, sz = bb["size"]
        parts.append(f"bbox={sx}x{sy}x{sz}")
    if shape.get("volume") is not None:
        parts.append(f"vol={shape['volume']}")
    if shape.get("center_of_mass"):
        parts.append(f"com={shape['center_of_mass']}")
    return " | ".join(parts)


def summarize_topology(raw: dict[str, Any], max_shapes: int = 8) -> str:
    """Compact summary of an ``inspect_topology`` / sandbox topology result."""
    if "shapes" in raw:
        shapes = raw["shapes"]
        lines = [summarize_shape(s) for s in shapes[:max_shapes]]
        if len(shapes) > max_shapes:
            lines.append(f"... and {len(shapes) - max_shapes} more shape(s) (ask to expand)")
        return "\n".join(lines) if lines else "no shapes"
    # sandbox-style single topology
    return summarize_shape(raw)


def expand_shape(raw: dict[str, Any], name: str) -> str:
    """Full detail for one named shape (the on-demand drill-in path)."""
    shapes = raw.get("shapes", [])
    for s in shapes:
        if s.get("name") == name or s.get("label") == name:
            lines = [summarize_shape(s)]
            ct = s.get("curve_types") or {}
            if ct:
                lines.append(f"  curves: {_fmt_counts(ct)}")
            bb = s.get("bounding_box") or {}
            if bb:
                lines.append(f"  bbox min={bb.get('min')} max={bb.get('max')}")
            return "\n".join(lines)
    return f"no shape named {name!r}"


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) for budget accounting."""
    return max(1, len(text) // 4)
