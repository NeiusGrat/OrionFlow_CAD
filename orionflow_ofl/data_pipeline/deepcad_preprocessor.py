"""
Preprocess raw DeepCAD / Fusion 360 JSON → simplified format for DeepCADConverter.

The real DeepCAD dataset uses the Fusion 360 API schema:
  - entities: dict of entity_id → {type: "Sketch"/"ExtrudeFeature", ...}
  - sequence: list of {index, type, entity} references

The DeepCADConverter expects a simplified schema:
  - sequence: list of {type: "sketch"/"extrude", plane: {...}, loops: [...], ...}

This module bridges the gap.
"""

from __future__ import annotations

import math
from typing import Any


# ── Operation mapping ────────────────────────────────────────
_OP_MAP = {
    "NewBodyFeatureOperation": "new",
    "JoinFeatureOperation": "join",
    "CutFeatureOperation": "cut",
    "IntersectFeatureOperation": "intersect",
}


def preprocess_deepcad(raw: dict) -> dict | None:
    """Convert raw Fusion 360 JSON → simplified sequence format.
    
    Returns {"sequence": [...]} or None if not convertible.
    """
    entities = raw.get("entities", {})
    seq_refs = raw.get("sequence", [])
    
    if not entities or not seq_refs:
        return None
    
    simplified_seq: list[dict] = []
    
    for ref in sorted(seq_refs, key=lambda r: r.get("index", 0)):
        entity_id = ref.get("entity", "")
        entity = entities.get(entity_id)
        if entity is None:
            return None
        
        etype = ref.get("type", entity.get("type", ""))
        
        if etype == "Sketch":
            sketch = _convert_sketch(entity, entities)
            if sketch is None:
                return None
            simplified_seq.append(sketch)
            
        elif etype == "ExtrudeFeature":
            extrude = _convert_extrude(entity, entities)
            if extrude is None:
                return None
            simplified_seq.append(extrude)
        else:
            # Unknown feature type — skip entire model
            return None
    
    if not simplified_seq:
        return None
    
    return {"sequence": simplified_seq}


def _convert_sketch(entity: dict, all_entities: dict) -> dict | None:
    """Convert a Sketch entity → simplified sketch dict."""
    transform = entity.get("transform", {})
    plane = _extract_plane(transform)
    if plane is None:
        return None
    
    # Extract loops from profiles
    profiles = entity.get("profiles", {})
    loops: list[dict] = []
    
    for prof_name, prof_data in profiles.items():
        raw_loops = prof_data.get("loops", [])
        for raw_loop in raw_loops:
            raw_curves = raw_loop.get("profile_curves", [])
            converted_curves = []
            for rc in raw_curves:
                curve = _convert_curve(rc, transform)
                if curve is not None:
                    converted_curves.append(curve)
            
            if converted_curves:
                loops.append({"curves": converted_curves})
    
    if not loops:
        return None
    
    return {
        "type": "sketch",
        "plane": plane,
        "loops": loops,
    }


def _convert_extrude(entity: dict, all_entities: dict) -> dict | None:
    """Convert an ExtrudeFeature entity → simplified extrude dict."""
    operation = entity.get("operation", "")
    boolean = _OP_MAP.get(operation)
    if boolean is None:
        return None
    
    # Extract extent values
    e1 = entity.get("extent_one", {})
    e2 = entity.get("extent_two", {})
    
    dist1 = _get_extent_value(e1)
    dist2 = _get_extent_value(e2)
    
    if dist1 is None:
        return None
    
    result: dict[str, Any] = {
        "type": "extrude",
        "extent_one": abs(dist1),
        "boolean": boolean,
    }
    
    if dist2 is not None and dist2 != 0:
        result["extent_two"] = abs(dist2)
    
    return result


def _extract_plane(transform: dict) -> dict | None:
    """Extract plane normal from sketch transform."""
    origin = transform.get("origin", {})
    z_axis = transform.get("z_axis", {})
    
    nx = z_axis.get("x", 0)
    ny = z_axis.get("y", 0)
    nz = z_axis.get("z", 0)
    
    ox = origin.get("x", 0)
    oy = origin.get("y", 0)
    oz = origin.get("z", 0)
    
    return {
        "x": ox, "y": oy, "z": oz,
        "nx": nx, "ny": ny, "nz": nz,
    }


def _convert_curve(raw_curve: dict, transform: dict) -> dict | None:
    """Convert a Fusion 360 curve → simplified curve dict."""
    ctype = raw_curve.get("type", "")
    
    if ctype == "Line3D":
        sp = raw_curve.get("start_point", {})
        ep = raw_curve.get("end_point", {})
        return {
            "type": "line",
            "start": _point_2d(sp, transform),
            "end": _point_2d(ep, transform),
        }
    
    elif ctype == "Circle3D":
        cp = raw_curve.get("center_point", {})
        radius = raw_curve.get("radius", 0)
        return {
            "type": "circle",
            "center": _point_2d(cp, transform),
            "radius": radius,
        }
    
    elif ctype == "Arc3D":
        sp = raw_curve.get("start_point", {})
        ep = raw_curve.get("end_point", {})
        cp = raw_curve.get("center_point", {})
        return {
            "type": "arc",
            "start": _point_2d(sp, transform),
            "end": _point_2d(ep, transform),
            "center": _point_2d(cp, transform) if cp else None,
        }
    
    # Unsupported curve type
    return None


def _point_2d(point_3d: dict, transform: dict) -> list[float]:
    """Project a 3D point to 2D sketch coordinates using the transform.
    
    The sketch transform defines a local coordinate system:
      origin, x_axis, y_axis, z_axis
    
    We project the 3D point onto the sketch plane to get 2D coords.
    """
    origin = transform.get("origin", {"x": 0, "y": 0, "z": 0})
    x_axis = transform.get("x_axis", {"x": 1, "y": 0, "z": 0})
    y_axis = transform.get("y_axis", {"x": 0, "y": 1, "z": 0})
    
    # Vector from origin to point
    dx = point_3d.get("x", 0) - origin.get("x", 0)
    dy = point_3d.get("y", 0) - origin.get("y", 0)
    dz = point_3d.get("z", 0) - origin.get("z", 0)
    
    # Project onto x_axis and y_axis
    u = dx * x_axis.get("x", 0) + dy * x_axis.get("y", 0) + dz * x_axis.get("z", 0)
    v = dx * y_axis.get("x", 0) + dy * y_axis.get("y", 0) + dz * y_axis.get("z", 0)
    
    return [u, v]


def _get_extent_value(extent: dict) -> float | None:
    """Extract distance value from extent definition."""
    if not extent:
        return 0.0
    distance = extent.get("distance", {})
    if isinstance(distance, dict):
        return distance.get("value", 0.0)
    return None
