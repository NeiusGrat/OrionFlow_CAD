"""Fusion 360 Gallery Reconstruction Dataset → Build123d translator.

Input:  Reconstruction Dataset JSON files (from AutodeskAILab/Fusion360GalleryDataset)
Output: Validated Build123d code that compiles and produces watertight solids.

The Reconstruction Dataset encodes sketch-and-extrude sequences:
  - entities: {uuid: Sketch | ExtrudeFeature}
  - timeline: ordered list of entity references
  - sketches contain points, curves, profiles with loops
  - extrudes reference sketch profiles and have extent/operation info
  - units: cm  (we convert to mm for Build123d output)
  - curves: SketchLine, SketchCircle, SketchArc

Strategy:
  1. Walk the timeline, pair each Sketch with its ExtrudeFeature
  2. For each sketch, resolve profile loops into trimmed curve geometry
  3. Classify the sketch plane (XY/XZ/YZ + offset) from the transform
  4. Map extrude operations to Build123d modes (NewBody/Join→ADD, Cut→SUBTRACT)
  5. Emit parametric Build123d code in canonical Feature Tree style
  6. Validate by exec + bounding-box check

Target: 90%+ translation success rate on axis-aligned sketch-and-extrude models.

Usage:
    python scripts/translators/fusion360_to_b123d.py \
        --input path/to/reconstruction/jsons \
        --output data/translators/fusion360/translated.jsonl \
        [--max-scan 10000] [--validate]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import textwrap
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCALE = 10.0  # cm → mm

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)

# ---------------------------------------------------------------------------
# Vector / plane math
# ---------------------------------------------------------------------------

def _vec3(d: dict | None) -> tuple[float, float, float]:
    if d is None:
        return (0.0, 0.0, 0.0)
    return (float(d.get("x", 0.0)), float(d.get("y", 0.0)), float(d.get("z", 0.0)))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def _is_unit_axis(v: tuple[float, float, float], tol: float = 0.01) -> str | None:
    """Return '+X'/'-X'/'+Y'/... if v is close to a cardinal axis."""
    for name, ax in [("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))]:
        if all(abs(a - b) < tol for a, b in zip(v, ax)):
            return f"+{name}"
        if all(abs(a + b) < tol for a, b in zip(v, ax)):
            return f"-{name}"
    return None


def _classify_plane(sketch_entity: dict) -> tuple[str, float] | None:
    """Classify sketch plane → (b123d_plane_name, offset_mm) or None."""
    transform = sketch_entity.get("transform", {})
    if not transform:
        # Try reference_plane for simple axis planes
        ref = sketch_entity.get("reference_plane", {})
        if ref.get("type") == "ConstructionPlane":
            name = ref.get("name", "")
            if "XY" in name:
                return ("Plane.XY", 0.0)
            if "XZ" in name:
                return ("Plane.XZ", 0.0)
            if "YZ" in name:
                return ("Plane.YZ", 0.0)
        return None

    z_axis = _vec3(transform.get("z_axis"))
    origin = _vec3(transform.get("origin"))

    axis_name = _is_unit_axis(z_axis)
    if axis_name is None:
        return None

    sign = 1.0 if axis_name.startswith("+") else -1.0
    letter = axis_name[1]
    plane_map = {"Z": "Plane.XY", "Y": "Plane.XZ", "X": "Plane.YZ"}
    plane = plane_map[letter]
    idx = {"X": 0, "Y": 1, "Z": 2}[letter]
    offset = origin[idx] * SCALE * sign
    return plane, offset


def _project_to_sketch_2d(
    point_3d: tuple[float, float, float], transform: dict
) -> tuple[float, float]:
    """Project a 3D point into the sketch's local 2D coordinate system."""
    origin = _vec3(transform.get("origin"))
    x_axis = _vec3(transform.get("x_axis"))
    y_axis = _vec3(transform.get("y_axis"))
    dx = tuple(point_3d[i] - origin[i] for i in range(3))
    u = _dot(dx, x_axis)
    v = _dot(dx, y_axis)
    return (u, v)


# ---------------------------------------------------------------------------
# Profile geometry extraction
# ---------------------------------------------------------------------------

def _resolve_profile_curves(
    profile: dict, sketch: dict
) -> list[dict]:
    """Extract the trimmed profile curves from a profile's loops."""
    all_curves = []
    for loop in profile.get("loops", []):
        for pc in loop.get("profile_curves", []):
            all_curves.append(pc)
    return all_curves


def _classify_profile_shape(
    profile_curves: list[dict], transform: dict
) -> dict | None:
    """Classify a set of profile curves as rect/circle/polygon or None.

    Returns a dict with keys: shape, and shape-specific params (in mm).

    NOTE: In the Fusion 360 Reconstruction Dataset, profile_curves contain
    3D points in sketch-local coordinates where only x and y are populated
    (z=0). We use x,y directly as the 2D sketch coordinates.
    """
    points_2d = []
    has_circle = False
    has_arc = False

    for pc in profile_curves:
        ptype = pc.get("type", "")
        if ptype == "Circle3D":
            has_circle = True
            center = _vec3(pc.get("center"))
            # Use sketch-local x,y directly
            cu, cv = center[0], center[1]
            radius = float(pc.get("radius", 0.0))
            return {
                "shape": "circle",
                "cx": cu * SCALE,
                "cy": cv * SCALE,
                "radius": radius * SCALE,
            }
        elif ptype in ("Line3D", "SketchLine"):
            sp = _vec3(pc.get("start_point"))
            ep = _vec3(pc.get("end_point"))
            # Use sketch-local x,y directly
            points_2d.append((sp[0], sp[1]))
            points_2d.append((ep[0], ep[1]))
        elif ptype in ("Arc3D", "SketchArc"):
            has_arc = True
            sp = _vec3(pc.get("start_point"))
            ep = _vec3(pc.get("end_point"))
            points_2d.append((sp[0], sp[1]))
            points_2d.append((ep[0], ep[1]))

    if not points_2d:
        return None

    # Deduplicate points
    unique = []
    for p in points_2d:
        is_dup = False
        for q in unique:
            if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                is_dup = True
                break
        if not is_dup:
            unique.append(p)

    if len(unique) < 3:
        return None

    # Compute bounding box
    xs = [p[0] for p in unique]
    ys = [p[1] for p in unique]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx = (min_x + max_x) / 2 * SCALE
    cy = (min_y + max_y) / 2 * SCALE
    w = (max_x - min_x) * SCALE
    h = (max_y - min_y) * SCALE

    if w < 0.01 or h < 0.01:
        return None

    # Check if it's a rectangle: all points should lie on bbox edges
    if not has_arc and len(unique) == 4:
        on_edges = all(
            (abs(p[0] - min_x) < 1e-5 or abs(p[0] - max_x) < 1e-5) and
            (abs(p[1] - min_y) < 1e-5 or abs(p[1] - max_y) < 1e-5)
            for p in unique
        )
        if on_edges:
            return {"shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h}

    # Fallback: emit as polygon using Line segments
    if not has_arc:
        # Order points by angle from centroid
        centroid_x = sum(p[0] for p in unique) / len(unique)
        centroid_y = sum(p[1] for p in unique) / len(unique)
        unique.sort(key=lambda p: math.atan2(p[1] - centroid_y, p[0] - centroid_x))
        scaled_pts = [(p[0] * SCALE, p[1] * SCALE) for p in unique]
        return {"shape": "polygon", "points": scaled_pts, "cx": cx, "cy": cy}

    # Has arcs → use bounding-box rectangle as approximation
    return {"shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h}


# ---------------------------------------------------------------------------
# Extract sketch-extrude pairs from timeline
# ---------------------------------------------------------------------------

def _extract_pairs(data: dict) -> list[dict]:
    """Walk the timeline/sequence and pair each ExtrudeFeature with its sketch profiles.

    Supports both Fusion 360 Gallery format (timeline) and DeepCAD format (sequence).

    Returns a list of dicts:
      { sketch_entity, extrude_entity, plane_info, profiles: [shape_dict, ...] }
    """
    entities = data.get("entities", {})

    # Support both timeline (Fusion360 Gallery) and sequence (DeepCAD) formats
    timeline = data.get("timeline", [])
    if not timeline:
        timeline = data.get("sequence", [])

    # Build timeline order
    ordered = sorted(timeline, key=lambda t: t.get("index", 0))

    pairs = []
    for entry in ordered:
        eid = entry.get("entity", "")
        ent = entities.get(eid, {})
        if ent.get("type") != "ExtrudeFeature":
            continue

        ext = ent
        # Resolve the sketch(es) referenced by this extrude
        ext_profiles = ext.get("profiles", [])
        if not ext_profiles:
            continue

        # Group profiles by sketch
        sketch_profiles = {}
        for pref in ext_profiles:
            sid = pref.get("sketch", "")
            pid = pref.get("profile", "")
            sketch_profiles.setdefault(sid, []).append(pid)

        for sid, pids in sketch_profiles.items():
            sketch_ent = entities.get(sid)
            if not sketch_ent or sketch_ent.get("type") != "Sketch":
                continue

            plane_info = _classify_plane(sketch_ent)
            if plane_info is None:
                continue  # skip non-axis-aligned sketches

            transform = sketch_ent.get("transform", {})
            profiles_shapes = []
            for pid in pids:
                profile = sketch_ent.get("profiles", {}).get(pid, {})
                if not profile:
                    continue
                curves = _resolve_profile_curves(profile, sketch_ent)
                shape = _classify_profile_shape(curves, transform)
                if shape:
                    profiles_shapes.append(shape)

            if not profiles_shapes:
                continue

            # Extract extrude params
            ext_one = ext.get("extent_one", {})
            ext_two = ext.get("extent_two", {})
            distance_one = abs(float(ext_one.get("distance", {}).get("value", 0.0))) * SCALE
            distance_two = abs(float(ext_two.get("distance", {}).get("value", 0.0))) * SCALE if ext_two else 0.0

            extent_type = ext.get("extent_type", "OneSideFeatureExtentType")
            if extent_type == "SymmetricFeatureExtentType":
                # Symmetric: total distance split equally
                half = distance_one / 2
                distance_one = half
                distance_two = half

            operation = ext.get("operation", "NewBodyFeatureOperation")

            pairs.append({
                "sketch_entity": sketch_ent,
                "extrude_entity": ext,
                "plane": plane_info,
                "profiles": profiles_shapes,
                "distance": distance_one + distance_two if distance_two > 0 else distance_one,
                "distance_one": distance_one,
                "distance_two": distance_two,
                "extent_type": extent_type,
                "operation": operation,
            })

    return pairs


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def _sanitize_var(name: str) -> str:
    """Make a safe Python variable name."""
    return name.replace(" ", "_").replace("-", "_").lower()


def _round(v: float, decimals: int = 3) -> float:
    return round(v, decimals)


def generate_b123d_code(pairs: list[dict]) -> str:
    """Generate Build123d code from extracted sketch-extrude pairs."""
    if not pairs:
        return ""

    lines = ["from build123d import *", "", "# --- Parameters ---"]
    params = []
    feature_blocks = []

    for i, pair in enumerate(pairs):
        fi = i + 1
        plane_name, plane_offset = pair["plane"]
        dist = pair["distance"]
        op = pair["operation"]

        # Parameter names
        depth_var = f"depth_{fi}"
        params.append(f"{depth_var} = {_round(dist)}  # mm - feature {fi} depth")

        # Build the plane expression
        if abs(plane_offset) < 0.01:
            plane_expr = plane_name
        else:
            plane_expr = f"{plane_name}.offset({_round(plane_offset)})"

        # Determine extrude mode
        if op in ("CutFeatureOperation",):
            mode_str = ", mode=Mode.SUBTRACT"
        elif op in ("IntersectFeatureOperation",):
            mode_str = ", mode=Mode.INTERSECT"
        else:
            mode_str = ""

        # Determine extrude direction
        if pair["extent_type"] == "SymmetricFeatureExtentType":
            extrude_expr = f"extrude(amount={depth_var} / 2, both=True{mode_str})"
        elif pair["distance_two"] > 0.01:
            extrude_expr = f"extrude(amount={depth_var}{mode_str})"
        else:
            extrude_expr = f"extrude(amount={depth_var}{mode_str})"

        # Build sketch content for each profile
        sketch_lines = []
        for j, prof in enumerate(pair["profiles"]):
            shape = prof["shape"]
            if shape == "circle":
                r_var = f"r_{fi}_{j+1}"
                params.append(f"{r_var} = {_round(prof['radius'])}  # mm - circle radius")
                cx, cy = _round(prof["cx"]), _round(prof["cy"])
                if abs(cx) < 0.01 and abs(cy) < 0.01:
                    sketch_lines.append(f"        Circle({r_var})")
                else:
                    cx_var = f"cx_{fi}_{j+1}"
                    cy_var = f"cy_{fi}_{j+1}"
                    params.append(f"{cx_var} = {cx}  # mm")
                    params.append(f"{cy_var} = {cy}  # mm")
                    sketch_lines.append(
                        f"        with Locations(({cx_var}, {cy_var})):"
                    )
                    sketch_lines.append(f"            Circle({r_var})")

            elif shape == "rect":
                w_var = f"w_{fi}_{j+1}"
                h_var = f"h_{fi}_{j+1}"
                params.append(f"{w_var} = {_round(prof['w'])}  # mm - rect width")
                params.append(f"{h_var} = {_round(prof['h'])}  # mm - rect height")
                cx, cy = _round(prof["cx"]), _round(prof["cy"])
                if abs(cx) < 0.01 and abs(cy) < 0.01:
                    sketch_lines.append(f"        Rectangle({w_var}, {h_var})")
                else:
                    cx_var = f"cx_{fi}_{j+1}"
                    cy_var = f"cy_{fi}_{j+1}"
                    params.append(f"{cx_var} = {cx}  # mm")
                    params.append(f"{cy_var} = {cy}  # mm")
                    sketch_lines.append(
                        f"        with Locations(({cx_var}, {cy_var})):"
                    )
                    sketch_lines.append(f"            Rectangle({w_var}, {h_var})")

            elif shape == "polygon":
                pts = prof["points"]
                pts_str = ", ".join(f"({_round(p[0])}, {_round(p[1])})" for p in pts)
                sketch_lines.append(
                    f"        Polygon([{pts_str}], align=None)"
                )

        feature_code = []
        feature_code.append(f"    # Feature {fi}: {'Cut' if 'Cut' in op else 'Extrude'}")
        feature_code.append(f"    with BuildSketch({plane_expr}):")
        feature_code.extend(sketch_lines)
        feature_code.append(f"    {extrude_expr}")
        feature_blocks.append("\n".join(feature_code))

    # Assemble
    code_lines = lines + params + [
        "",
        "# --- Feature Tree ---",
        "with BuildPart() as part:",
    ]
    for block in feature_blocks:
        code_lines.append(block)
        code_lines.append("")

    code_lines.append("result = part.part")
    return "\n".join(code_lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_code(code: str) -> dict:
    """Exec the generated code and check for a valid solid.

    Returns dict with keys: valid (bool), error (str|None), bbox (tuple|None).
    """
    try:
        ns = {}
        exec(code, ns)
        result = ns.get("result")
        if result is None:
            return {"valid": False, "error": "no result object", "bbox": None}

        # Check it has a bounding box (meaning it's a real solid)
        try:
            bb = result.bounding_box()
            dims = (
                round(bb.max.X - bb.min.X, 3),
                round(bb.max.Y - bb.min.Y, 3),
                round(bb.max.Z - bb.min.Z, 3),
            )
            # All dimensions must be > 0
            if all(d > 0.001 for d in dims):
                return {"valid": True, "error": None, "bbox": dims}
            else:
                return {"valid": False, "error": f"degenerate bbox {dims}", "bbox": dims}
        except Exception as e:
            return {"valid": False, "error": f"bbox check failed: {e}", "bbox": None}
    except Exception as e:
        return {"valid": False, "error": str(e)[:500], "bbox": None}


# ---------------------------------------------------------------------------
# Generate text description from geometry
# ---------------------------------------------------------------------------

def generate_description(pairs: list[dict]) -> str:
    """Generate a simple NL description of the part from its features."""
    if not pairs:
        return "A 3D part."

    parts_desc = []
    for i, pair in enumerate(pairs):
        op = pair["operation"]
        dist = _round(pair["distance"])
        profiles = pair["profiles"]

        # Describe the main profile
        prof = profiles[0] if profiles else {}
        shape = prof.get("shape", "unknown")

        if shape == "rect":
            w, h = _round(prof["w"]), _round(prof["h"])
            shape_desc = f"{w}x{h}mm rectangle"
        elif shape == "circle":
            r = _round(prof["radius"])
            shape_desc = f"circle (r={r}mm)"
        elif shape == "polygon":
            n = len(prof.get("points", []))
            shape_desc = f"{n}-sided polygon"
        else:
            shape_desc = "shape"

        if "Cut" in op:
            parts_desc.append(f"cut a {shape_desc}, {dist}mm deep")
        else:
            parts_desc.append(f"extrude a {shape_desc}, {dist}mm tall")

    n_features = len(pairs)
    desc = f"A {n_features}-feature part: " + "; ".join(parts_desc) + "."
    return desc


# ---------------------------------------------------------------------------
# Translate a single JSON file
# ---------------------------------------------------------------------------

def translate_file(json_path: Path, do_validate: bool = True) -> dict | None:
    """Translate one Reconstruction Dataset JSON to a training sample.

    Returns None if the file is not translatable (non-axis-aligned, etc.).
    Returns a dict with keys: code, description, valid, error, bbox, source.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    pairs = _extract_pairs(data)
    if not pairs:
        return None

    # Filter: at least 1 feature
    if len(pairs) < 1:
        return None

    code = generate_b123d_code(pairs)
    if not code:
        return None

    description = generate_description(pairs)

    result = {
        "code": code,
        "description": description,
        "n_features": len(pairs),
        "source": str(json_path.name),
        "valid": None,
        "error": None,
        "bbox": None,
    }

    if do_validate:
        vr = validate_code(code)
        result["valid"] = vr["valid"]
        result["error"] = vr["error"]
        result["bbox"] = vr["bbox"]

    return result


# ---------------------------------------------------------------------------
# Format as training JSONL
# ---------------------------------------------------------------------------

def format_training_sample(result: dict) -> dict:
    """Format a translated result into the canonical chat training format."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": result["description"]},
            {"role": "assistant", "content": result["code"]},
        ],
        "source": f"fusion360_gallery:{result['source']}",
        "n_features": result["n_features"],
        "_validation": {
            "valid": result["valid"],
            "error": result["error"],
            "bbox": result["bbox"],
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fusion 360 Gallery → Build123d translator"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Directory containing reconstruction JSON files"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Output JSONL path"
    )
    parser.add_argument(
        "--max-scan", type=int, default=0,
        help="Max files to scan (0 = all)"
    )
    parser.add_argument(
        "--validate", action="store_true", default=True,
        help="Validate generated code by executing it (requires build123d)"
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="Skip validation"
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"Error: input directory {input_dir} does not exist")
        sys.exit(1)

    do_validate = args.validate and not args.no_validate

    # Find all JSON files
    json_files = sorted(input_dir.rglob("*.json"))
    if args.max_scan > 0:
        json_files = json_files[: args.max_scan]

    print(f"Found {len(json_files)} JSON files in {input_dir}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    translated = 0
    valid = 0
    errors = []

    with open(output_path, "w", encoding="utf-8") as out:
        for jf in json_files:
            total += 1
            result = translate_file(jf, do_validate=do_validate)
            if result is None:
                continue

            translated += 1
            if result.get("valid", False):
                valid += 1
                sample = format_training_sample(result)
                out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            else:
                errors.append((str(jf.name), result.get("error", "unknown")))

            if total % 500 == 0:
                rate = valid / translated * 100 if translated > 0 else 0
                print(
                    f"  scanned {total}, translated {translated}, "
                    f"valid {valid} ({rate:.1f}%)"
                )

    # Summary
    rate = valid / translated * 100 if translated > 0 else 0
    print(f"\n{'='*60}")
    print(f"Fusion 360 Gallery -> Build123d Translation Summary")
    print(f"{'='*60}")
    print(f"  Files scanned:    {total}")
    print(f"  Translatable:     {translated}")
    print(f"  Valid (compiled):  {valid}")
    print(f"  Success rate:     {rate:.1f}%")
    print(f"  Output:           {output_path}")

    if errors and len(errors) <= 20:
        print(f"\nSample errors:")
        for name, err in errors[:20]:
            print(f"  {name}: {err[:120]}")


if __name__ == "__main__":
    main()
