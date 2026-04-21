"""Text2CAD Dataset → Build123d translator.

Input:  Text2CAD dataset files:
        - DeepCAD-format JSON files (sketch + extrude sequences)
        - Text annotations CSV with 4 abstraction levels per model:
          abstract, beginner, intermediate, expert
        - Optionally: minimal_json format (processed by CadSeqProc)
Output: Validated Build123d code preserving all 4 text description levels.

Text2CAD (NeurIPS 2024) uses the DeepCAD JSON schema:
  - sequence: list of {type: "ExtrudeFeature", entity: uuid, ...}
  - entities: {uuid: Sketch | ExtrudeFeature}
  - Sketch entities have profiles → loops → curves (Line, Arc, Circle)
  - ExtrudeFeature has extent_one/extent_two + operation (New/Join/Cut/Intersect)
  - Coordinate system: normalized, with sketch_size for denormalization
  - Curves: Line (start_point, end_point), Arc (start_point, mid_point, end_point),
            Circle (center, radius)

The 4 text abstraction levels (from their CSV):
  - abstract:     High-level shape category ("A rectangular prism with holes")
  - beginner:     Simple description with basic dimensions
  - intermediate: More detailed with specific measurements and operations
  - expert:       Full CAD-level description with precise parameters

Strategy:
  1. Parse DeepCAD JSON → extract sketch-extrude pairs
  2. Resolve sketch profiles into 2D geometry (lines, arcs, circles)
  3. Classify sketch plane from coordinate system (euler angles → XY/XZ/YZ)
  4. Map extrude operations to Build123d modes
  5. Emit Build123d code in canonical Feature Tree style
  6. Preserve all 4 text descriptions in output for multi-level training

Usage:
    python scripts/translators/text2cad_to_b123d.py \
        --input path/to/deepcad_json \
        --annotations path/to/text_annotations.csv \
        --split-json path/to/train_test_val.json \
        --output data/translators/text2cad/translated.jsonl \
        [--max-scan 10000] [--validate]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)

TEXT_LEVELS = ["abstract", "beginner", "intermediate", "expert"]

# DeepCAD uses cm internally; we convert to mm
SCALE = 10.0  # cm → mm

# Extrude operation names (same as Fusion360 Gallery / DeepCAD)
EXTRUDE_OPS = [
    "NewBodyFeatureOperation",
    "JoinFeatureOperation",
    "CutFeatureOperation",
    "IntersectFeatureOperation",
]


# ---------------------------------------------------------------------------
# Vector math
# ---------------------------------------------------------------------------

def _vec3(d: dict | None) -> tuple[float, float, float]:
    if d is None:
        return (0.0, 0.0, 0.0)
    return (float(d.get("x", 0.0)), float(d.get("y", 0.0)), float(d.get("z", 0.0)))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _is_unit_axis(v: tuple[float, float, float], tol: float = 0.05) -> str | None:
    for name, ax in [("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))]:
        if all(abs(a - b) < tol for a, b in zip(v, ax)):
            return f"+{name}"
        if all(abs(a + b) < tol for a, b in zip(v, ax)):
            return f"-{name}"
    return None


# ---------------------------------------------------------------------------
# Sketch plane classification
# ---------------------------------------------------------------------------

def _classify_plane_from_transform(transform: dict) -> tuple[str, float] | None:
    """Classify sketch plane from transform dict → (plane_name, offset_mm)."""
    z_axis = _vec3(transform.get("z_axis"))
    origin = _vec3(transform.get("origin"))

    axis = _is_unit_axis(z_axis)
    if axis is None:
        return None

    sign = 1.0 if axis.startswith("+") else -1.0
    letter = axis[1]
    plane_map = {"Z": "Plane.XY", "Y": "Plane.XZ", "X": "Plane.YZ"}
    plane = plane_map[letter]
    idx = {"X": 0, "Y": 1, "Z": 2}[letter]
    offset = origin[idx] * SCALE * sign
    return plane, offset


def _classify_plane_from_ref(ref_plane: dict) -> tuple[str, float] | None:
    """Classify from reference_plane when transform isn't available."""
    ptype = ref_plane.get("type", "")
    name = ref_plane.get("name", "")

    if ptype == "ConstructionPlane":
        if "XY" in name:
            return ("Plane.XY", 0.0)
        if "XZ" in name:
            return ("Plane.XZ", 0.0)
        if "YZ" in name:
            return ("Plane.YZ", 0.0)

    # BRepFace reference: try to use point_on_face + type
    if ptype == "BRepFace":
        # We'll handle this with the transform if available
        pass

    return None


# ---------------------------------------------------------------------------
# Profile/curve extraction (DeepCAD JSON format)
# ---------------------------------------------------------------------------

def _extract_profile_curves(
    sketch_entity: dict, profile_id: str
) -> list[dict]:
    """Extract trimmed curves from a profile in a sketch entity."""
    profiles = sketch_entity.get("profiles", {})
    profile = profiles.get(profile_id, {})
    curves = []
    for loop in profile.get("loops", []):
        for pc in loop.get("profile_curves", []):
            curves.append(pc)
    return curves


def _project_point(point_3d, transform):
    """Project 3D point to sketch 2D using transform axes."""
    if not transform:
        return (point_3d[0], point_3d[1])
    origin = _vec3(transform.get("origin"))
    x_axis = _vec3(transform.get("x_axis"))
    y_axis = _vec3(transform.get("y_axis"))
    dx = tuple(point_3d[i] - origin[i] for i in range(3))
    u = _dot(dx, x_axis)
    v = _dot(dx, y_axis)
    return (u, v)


def _classify_profile(curves: list[dict], transform: dict) -> dict | None:
    """Classify profile geometry into rect/circle/polygon.

    NOTE: Profile curves in both Fusion 360 and DeepCAD formats use
    sketch-local coordinates where x,y are the 2D sketch coords (z=0).
    """
    points_2d = []
    has_arc = False

    for pc in curves:
        ptype = pc.get("type", "")

        if ptype == "Circle3D":
            center = _vec3(pc.get("center"))
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

    # Deduplicate
    unique = []
    for p in points_2d:
        if not any(abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6 for q in unique):
            unique.append(p)

    if len(unique) < 3:
        return None

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

    # Rectangle check
    if not has_arc and len(unique) == 4:
        on_edges = all(
            (abs(p[0] - min_x) < 1e-5 or abs(p[0] - max_x) < 1e-5) and
            (abs(p[1] - min_y) < 1e-5 or abs(p[1] - max_y) < 1e-5)
            for p in unique
        )
        if on_edges:
            return {"shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h}

    if not has_arc:
        centroid_x = sum(p[0] for p in unique) / len(unique)
        centroid_y = sum(p[1] for p in unique) / len(unique)
        unique.sort(key=lambda p: math.atan2(p[1] - centroid_y, p[0] - centroid_x))
        scaled_pts = [(p[0] * SCALE, p[1] * SCALE) for p in unique]
        return {"shape": "polygon", "points": scaled_pts, "cx": cx, "cy": cy}

    return {"shape": "rect", "cx": cx, "cy": cy, "w": w, "h": h}


# ---------------------------------------------------------------------------
# Extract sketch-extrude pairs from DeepCAD JSON
# ---------------------------------------------------------------------------

def _extract_pairs(data: dict) -> list[dict]:
    """Walk the sequence and pair ExtrudeFeatures with their sketch profiles."""
    entities = data.get("entities", {})
    sequence = data.get("sequence", [])

    pairs = []
    for entry in sequence:
        if entry.get("type") != "ExtrudeFeature":
            continue

        eid = entry.get("entity", "")
        ext = entities.get(eid, {})
        if not ext or ext.get("type") != "ExtrudeFeature":
            continue

        ext_profiles = ext.get("profiles", [])
        if not ext_profiles:
            continue

        # Group by sketch
        sketch_groups = {}
        for pref in ext_profiles:
            sid = pref.get("sketch", "")
            pid = pref.get("profile", "")
            sketch_groups.setdefault(sid, []).append(pid)

        for sid, pids in sketch_groups.items():
            sketch = entities.get(sid)
            if not sketch or sketch.get("type") != "Sketch":
                continue

            transform = sketch.get("transform", {})

            # Classify plane
            plane_info = _classify_plane_from_transform(transform)
            if plane_info is None:
                ref = sketch.get("reference_plane", {})
                plane_info = _classify_plane_from_ref(ref)
            if plane_info is None:
                continue

            # Extract profile shapes
            profile_shapes = []
            for pid in pids:
                curves = _extract_profile_curves(sketch, pid)
                shape = _classify_profile(curves, transform)
                if shape:
                    profile_shapes.append(shape)

            if not profile_shapes:
                continue

            # Extrude parameters
            ext_one = ext.get("extent_one", {})
            ext_two = ext.get("extent_two", {})
            d1 = abs(float(ext_one.get("distance", {}).get("value", 0.0))) * SCALE
            d2 = abs(float(ext_two.get("distance", {}).get("value", 0.0))) * SCALE if ext_two else 0.0

            extent_type = ext.get("extent_type", "OneSideFeatureExtentType")
            if extent_type == "SymmetricFeatureExtentType":
                half = d1 / 2
                d1, d2 = half, half

            operation = ext.get("operation", "NewBodyFeatureOperation")

            # Check start extent for offsets
            start_ext = ext.get("start_extent", {})
            start_offset = 0.0
            if start_ext.get("type") == "OffsetStartDefinition":
                start_offset = abs(float(start_ext.get("offset", {}).get("value", 0.0))) * SCALE

            pairs.append({
                "plane": plane_info,
                "profiles": profile_shapes,
                "distance": d1 + d2 if d2 > 0.01 else d1,
                "distance_one": d1,
                "distance_two": d2,
                "extent_type": extent_type,
                "operation": operation,
                "start_offset": start_offset,
            })

    return pairs


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def _round(v: float, decimals: int = 3) -> float:
    return round(v, decimals)


def generate_b123d_code(pairs: list[dict]) -> str:
    """Generate Build123d code from sketch-extrude pairs."""
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

        depth_var = f"depth_{fi}"
        params.append(f"{depth_var} = {_round(dist)}  # mm - feature {fi} depth")

        if abs(plane_offset) < 0.01:
            plane_expr = plane_name
        else:
            plane_expr = f"{plane_name}.offset({_round(plane_offset)})"

        if op == "CutFeatureOperation":
            mode_str = ", mode=Mode.SUBTRACT"
        elif op == "IntersectFeatureOperation":
            mode_str = ", mode=Mode.INTERSECT"
        else:
            mode_str = ""

        extrude_expr = f"extrude(amount={depth_var}{mode_str})"

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
                    sketch_lines.append(f"        with Locations(({cx_var}, {cy_var})):")
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
                    sketch_lines.append(f"        with Locations(({cx_var}, {cy_var})):")
                    sketch_lines.append(f"            Rectangle({w_var}, {h_var})")

            elif shape == "polygon":
                pts = prof["points"]
                pts_str = ", ".join(f"({_round(p[0])}, {_round(p[1])})" for p in pts)
                sketch_lines.append(f"        Polygon([{pts_str}], align=None)")

        feature_code = []
        feature_code.append(f"    # Feature {fi}: {'Cut' if 'Cut' in op else 'Extrude'}")
        feature_code.append(f"    with BuildSketch({plane_expr}):")
        feature_code.extend(sketch_lines)
        feature_code.append(f"    {extrude_expr}")
        feature_blocks.append("\n".join(feature_code))

    code_lines = lines + params + ["", "# --- Feature Tree ---", "with BuildPart() as part:"]
    for block in feature_blocks:
        code_lines.append(block)
        code_lines.append("")

    code_lines.append("result = part.part")
    return "\n".join(code_lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_code(code: str) -> dict:
    """Execute generated code and verify it produces a valid solid."""
    try:
        ns = {}
        exec(code, ns)
        result = ns.get("result")
        if result is None:
            return {"valid": False, "error": "no result object", "bbox": None}

        try:
            bb = result.bounding_box()
            dims = (
                round(bb.max.X - bb.min.X, 3),
                round(bb.max.Y - bb.min.Y, 3),
                round(bb.max.Z - bb.min.Z, 3),
            )
            if all(d > 0.001 for d in dims):
                return {"valid": True, "error": None, "bbox": dims}
            else:
                return {"valid": False, "error": f"degenerate bbox {dims}", "bbox": dims}
        except Exception as e:
            return {"valid": False, "error": f"bbox failed: {e}", "bbox": None}
    except Exception as e:
        return {"valid": False, "error": str(e)[:500], "bbox": None}


# ---------------------------------------------------------------------------
# Text annotations loading
# ---------------------------------------------------------------------------

def load_annotations(csv_path: Path) -> dict[str, dict[str, str]]:
    """Load text annotations CSV → {uid: {abstract: ..., beginner: ..., ...}}."""
    annotations = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("uid", "").strip()
            if not uid:
                continue
            annot = {}
            for level in TEXT_LEVELS:
                text = row.get(level, "").strip()
                if text:
                    annot[level] = text
            if annot:
                annotations[uid] = annot
    return annotations


# ---------------------------------------------------------------------------
# Translate a single JSON
# ---------------------------------------------------------------------------

def translate_file(
    json_path: Path,
    annotations: dict[str, dict[str, str]] | None = None,
    uid: str = "",
    do_validate: bool = True,
) -> dict | None:
    """Translate one DeepCAD JSON file → training sample(s).

    Returns None if not translatable.
    Returns a dict with code, text_levels, valid, error, bbox, source.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    pairs = _extract_pairs(data)
    if not pairs:
        return None

    code = generate_b123d_code(pairs)
    if not code:
        return None

    # Get text descriptions
    text_levels = {}
    if annotations and uid:
        text_levels = annotations.get(uid, {})

    # Generate a fallback description if no annotations
    if not text_levels:
        desc = _generate_fallback_description(pairs)
        text_levels = {"beginner": desc}

    result = {
        "code": code,
        "text_levels": text_levels,
        "n_features": len(pairs),
        "source": uid or str(json_path.name),
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


def _generate_fallback_description(pairs: list[dict]) -> str:
    parts = []
    for i, pair in enumerate(pairs):
        op = pair["operation"]
        dist = _round(pair["distance"])
        prof = pair["profiles"][0] if pair["profiles"] else {}
        shape = prof.get("shape", "shape")

        if shape == "rect":
            desc = f"{_round(prof['w'])}x{_round(prof['h'])}mm rectangle"
        elif shape == "circle":
            desc = f"circle (r={_round(prof['radius'])}mm)"
        else:
            desc = shape

        if "Cut" in op:
            parts.append(f"cut a {desc}, {dist}mm deep")
        else:
            parts.append(f"extrude a {desc}, {dist}mm tall")

    return f"A {len(pairs)}-feature part: " + "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Format training samples (one per text level)
# ---------------------------------------------------------------------------

def format_training_samples(result: dict) -> list[dict]:
    """One training sample per text abstraction level."""
    samples = []
    for level, text in result["text_levels"].items():
        samples.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
                {"role": "assistant", "content": result["code"]},
            ],
            "source": f"text2cad:{result['source']}",
            "text_level": level,
            "n_features": result["n_features"],
            "_validation": {
                "valid": result["valid"],
                "error": result["error"],
                "bbox": result["bbox"],
            },
        })
    return samples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Text2CAD → Build123d translator"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Directory containing DeepCAD JSON files"
    )
    parser.add_argument(
        "--annotations", "-a", default="",
        help="Path to text annotations CSV (with uid, abstract, beginner, intermediate, expert columns)"
    )
    parser.add_argument(
        "--split-json", default="",
        help="Path to train/test/val split JSON"
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
        help="Validate generated code"
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

    # Load annotations if provided
    annotations = {}
    if args.annotations and Path(args.annotations).exists():
        print(f"Loading annotations from {args.annotations}...")
        annotations = load_annotations(Path(args.annotations))
        print(f"  Loaded {len(annotations)} annotated models")

    # Load split if provided
    uids_to_process = None
    if args.split_json and Path(args.split_json).exists():
        with open(args.split_json, "r") as f:
            splits = json.load(f)
        uids_to_process = []
        for key in ("train", "test", "validation"):
            uids_to_process.extend(splits.get(key, []))
        print(f"  Split has {len(uids_to_process)} UIDs")

    # Find JSON files
    if uids_to_process is not None:
        json_files = []
        for uid in uids_to_process:
            p = input_dir / (uid + ".json")
            if p.exists():
                json_files.append((p, uid))
    else:
        json_files = [(p, p.stem) for p in sorted(input_dir.rglob("*.json"))]

    if args.max_scan > 0:
        json_files = json_files[: args.max_scan]

    print(f"Found {len(json_files)} JSON files to process")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    translated = 0
    valid = 0
    total_samples = 0
    level_counts = {l: 0 for l in TEXT_LEVELS}

    with open(output_path, "w", encoding="utf-8") as out:
        for jf, uid in json_files:
            total += 1
            result = translate_file(jf, annotations, uid, do_validate)
            if result is None:
                continue

            translated += 1
            if result.get("valid", False):
                valid += 1
                samples = format_training_samples(result)
                for s in samples:
                    out.write(json.dumps(s, ensure_ascii=False) + "\n")
                    total_samples += 1
                    level = s.get("text_level", "")
                    if level in level_counts:
                        level_counts[level] += 1

            if total % 500 == 0:
                rate = valid / translated * 100 if translated > 0 else 0
                print(
                    f"  scanned {total}, translated {translated}, "
                    f"valid {valid} ({rate:.1f}%), samples {total_samples}"
                )

    rate = valid / translated * 100 if translated > 0 else 0
    print(f"\n{'='*60}")
    print(f"Text2CAD -> Build123d Translation Summary")
    print(f"{'='*60}")
    print(f"  Files scanned:      {total}")
    print(f"  Translatable:       {translated}")
    print(f"  Valid (compiled):    {valid}")
    print(f"  Success rate:       {rate:.1f}%")
    print(f"  Total samples:      {total_samples}")
    print(f"  Per text level:")
    for level, count in level_counts.items():
        print(f"    {level:15s}: {count}")
    print(f"  Output:             {output_path}")


if __name__ == "__main__":
    main()
