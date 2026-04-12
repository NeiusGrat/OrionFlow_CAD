"""Convert Fusion 360 Gallery-format JSONs (in data/deepcad_raw/) to
build123d-FTC training samples.

Note: the tree claims to be "DeepCAD" but the actual schema is the
Fusion 360 Gallery Reconstruction Dataset format, with:
    - entities: {id: Sketch | ExtrudeFeature | ...}
    - sequence: ordered references into entities
    - units: METERS (we scale x1000 for mm)
    - curves: Line3D / Circle3D / Arc3D in sketch-local coordinates

Filters:
    - sequence length 2..16
    - at least one Sketch and one ExtrudeFeature
    - every sketch must be axis-aligned (normal is ±X/Y/Z)
    - every sketch must be classifiable as a rectangle or a circle
    - at least 1 cut operation OR >=2 features total (not just a single block)
    - all extrude depths > 0
    - bounding dims in (0.5mm, 2000mm)

Usage:
    python scripts/convert_deepcad_to_b123d.py \
        --input data/deepcad_raw/cad_json \
        --output data/build123d_ftc/deepcad_raw.jsonl \
        --max-scan 15000 --target 3000
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any

SCALE = 1000.0  # meters -> mm

SYSTEM_PROMPT = (
    "You are OrionFlow, an AI mechanical design copilot. Given a part "
    "description, generate valid Build123d Python code following the Feature "
    "Tree Convention. Declare all dimensions as named parameters with units. "
    "Label each feature with a comment. The code must compile and produce a "
    "valid STEP file."
)


# ---------------------------------------------------------------------------
# Helpers: vector / plane math
# ---------------------------------------------------------------------------

def vec(d: dict) -> tuple[float, float, float]:
    return (float(d.get("x", 0.0)), float(d.get("y", 0.0)), float(d.get("z", 0.0)))


def is_unit_axis(v: tuple[float, float, float], tol: float = 1e-3) -> str | None:
    """Return 'X', 'Y', 'Z' (with sign) if v is close to a cardinal axis, else None."""
    x, y, z = v
    # check each axis
    axes = [("X", (1, 0, 0)), ("Y", (0, 1, 0)), ("Z", (0, 0, 1))]
    for name, (ax, ay, az) in axes:
        if abs(x - ax) < tol and abs(y - ay) < tol and abs(z - az) < tol:
            return f"+{name}"
        if abs(x + ax) < tol and abs(y + ay) < tol and abs(z + az) < tol:
            return f"-{name}"
    return None


def classify_plane(transform: dict) -> tuple[str, float] | None:
    """Map a sketch transform to a build123d plane name + signed offset.

    Returns None if the sketch is not aligned to a cardinal plane.
    """
    z_axis = vec(transform.get("z_axis", {}))
    origin = vec(transform.get("origin", {}))
    axis_name = is_unit_axis(z_axis)
    if axis_name is None:
        return None
    sign = 1.0 if axis_name.startswith("+") else -1.0
    letter = axis_name[1]
    # plane perpendicular to Z -> XY; perpendicular to Y -> XZ; to X -> YZ
    plane = {"Z": "Plane.XY", "Y": "Plane.XZ", "X": "Plane.YZ"}[letter]
    # offset is the component of origin along the sketch normal (scaled to mm)
    idx = {"X": 0, "Y": 1, "Z": 2}[letter]
    offset = origin[idx] * SCALE * sign
    return plane, offset


def project_to_sketch(
    point: tuple[float, float, float], transform: dict
) -> tuple[float, float]:
    """Project a 3D point into the sketch's 2D (u, v) basis (in meters)."""
    ox, oy, oz = vec(transform.get("origin", {}))
    x_ax = vec(transform.get("x_axis", {}))
    y_ax = vec(transform.get("y_axis", {}))
    dx = point[0] - ox
    dy = point[1] - oy
    dz = point[2] - oz
    u = dx * x_ax[0] + dy * x_ax[1] + dz * x_ax[2]
    v = dx * y_ax[0] + dy * y_ax[1] + dz * y_ax[2]
    return (u, v)


# ---------------------------------------------------------------------------
# Sketch classification
# ---------------------------------------------------------------------------

def classify_loop(loop: dict, transform: dict) -> dict | None:
    """Classify a single loop as a circle, rectangle, or None.

    Returns dict with keys:
        - {"kind": "circle", "cx": mm, "cy": mm, "r": mm}
        - {"kind": "rect",   "cx": mm, "cy": mm, "w": mm, "h": mm}
    """
    curves = loop.get("profile_curves") or []
    if not curves:
        return None

    # Case 1: single circle curve
    if len(curves) == 1 and curves[0].get("type") == "Circle3D":
        c = curves[0]
        cp = vec(c.get("center_point", {}))
        u, v = project_to_sketch(cp, transform)
        r = float(c.get("radius", 0.0)) * SCALE
        if r <= 0:
            return None
        return {"kind": "circle", "cx": u * SCALE, "cy": v * SCALE, "r": r}

    # Case 2: exactly 4 lines forming an axis-aligned rectangle
    if len(curves) == 4 and all(c.get("type") == "Line3D" for c in curves):
        pts: list[tuple[float, float]] = []
        for c in curves:
            s = vec(c.get("start_point", {}))
            pts.append(project_to_sketch(s, transform))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        w = (x_max - x_min) * SCALE
        h = (y_max - y_min) * SCALE
        if w < 0.5 or h < 0.5:
            return None
        # check each point hits one of the 4 corners
        corners = {(x_min, y_min), (x_min, y_max), (x_max, y_min), (x_max, y_max)}
        tol = 1e-5
        for p in pts:
            matched = any(
                abs(p[0] - cx) < tol and abs(p[1] - cy) < tol for cx, cy in corners
            )
            if not matched:
                return None
        cx = (x_min + x_max) / 2 * SCALE
        cy = (y_min + y_max) / 2 * SCALE
        return {"kind": "rect", "cx": cx, "cy": cy, "w": w, "h": h}

    return None


def classify_sketch(sketch: dict) -> list[dict] | None:
    """Return a list of classified loops for the sketch (outer loops only)."""
    transform = sketch.get("transform", {})
    profiles = sketch.get("profiles") or {}
    out: list[dict] = []
    for pid, prof in profiles.items():
        loops = prof.get("loops") or []
        # only use the outermost loop per profile
        outer = None
        for loop in loops:
            if loop.get("is_outer", True):
                outer = loop
                break
        if outer is None:
            continue
        clf = classify_loop(outer, transform)
        if clf is None:
            return None  # unclassifiable -> reject
        out.append(clf)
    return out if out else None


# ---------------------------------------------------------------------------
# Full model extraction
# ---------------------------------------------------------------------------

OP_MAP = {
    "NewBodyFeatureOperation": "new",
    "JoinFeatureOperation": "join",
    "CutFeatureOperation": "cut",
    "IntersectFeatureOperation": "intersect",
}


def extract_features(doc: dict) -> list[dict] | None:
    """Walk the sequence and build a flat feature list.

    Returns None if anything is unsupported.
    Each feature: {"plane": str, "offset": mm, "profiles": [classified], "depth": mm, "op": str}
    """
    entities = doc.get("entities") or {}
    seq = doc.get("sequence") or []
    if not (2 <= len(seq) <= 16):
        return None

    # last-seen sketch id, its classified profiles, and its transform metadata
    sketch_cache: dict[str, dict] = {}

    features: list[dict] = []
    for step in seq:
        t = step.get("type")
        eid = step.get("entity")
        ent = entities.get(eid, {})
        if t == "Sketch":
            transform = ent.get("transform", {})
            plane = classify_plane(transform)
            if plane is None:
                return None
            profiles = classify_sketch(ent)
            if profiles is None:
                return None
            sketch_cache[eid] = {
                "plane": plane[0],
                "offset": plane[1],
                "profiles": profiles,
            }
        elif t == "ExtrudeFeature":
            op_raw = ent.get("operation")
            op = OP_MAP.get(op_raw)
            if op not in ("new", "cut", "join"):
                return None
            extent = ent.get("extent_one", {}).get("distance", {}).get("value", 0.0)
            depth = float(extent) * SCALE
            if abs(depth) < 0.1:
                return None
            depth = abs(depth)
            if depth > 2000:
                return None
            # find the referenced sketch
            refs = ent.get("profiles") or []
            if not refs:
                return None
            sketch_id = refs[0].get("sketch")
            cached = sketch_cache.get(sketch_id)
            if not cached:
                return None
            features.append(
                {
                    "plane": cached["plane"],
                    "offset": cached["offset"],
                    "profiles": cached["profiles"],
                    "depth": depth,
                    "op": op,
                }
            )
        else:
            # unsupported feature type
            return None

    if not features:
        return None

    # Must have at least one "new" feature as the base
    if features[0]["op"] != "new":
        return None

    # Range check on all dims
    for f in features:
        for prof in f["profiles"]:
            if prof["kind"] == "circle":
                if prof["r"] < 0.25 or prof["r"] > 1000:
                    return None
            else:
                if prof["w"] < 0.5 or prof["w"] > 2000:
                    return None
                if prof["h"] < 0.5 or prof["h"] > 2000:
                    return None

    return features


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def fmt(x: float) -> str:
    x = round(x, 3)
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x))}.0"
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def generate_code(features: list[dict]) -> tuple[str, dict]:
    """Build the FTC code string. Return (code, summary) where summary is a
    dict used to derive the prompt."""
    param_lines: list[str] = []
    body: list[str] = []
    params_seen: dict[str, float] = {}

    def add_param(name: str, val: float, comment: str) -> str:
        # ensure unique names
        base = name
        i = 1
        while name in params_seen and abs(params_seen[name] - val) > 1e-6:
            i += 1
            name = f"{base}_{i}"
        params_seen[name] = val
        param_lines.append(f"{name} = {fmt(val)}  # {comment}")
        return name

    summary = {
        "op_counts": {"new": 0, "cut": 0, "join": 0},
        "dims": [],  # list of (w, h, d) for plate-ish shapes
        "circles": [],  # list of radii (holes/bosses)
    }

    for idx, f in enumerate(features, start=1):
        summary["op_counts"][f["op"]] = summary["op_counts"].get(f["op"], 0) + 1
        plane = f["plane"]
        offset = f["offset"]
        depth = f["depth"]
        op = f["op"]

        # signed depth in code for cut = negative
        if op == "cut":
            mode_suffix = ", mode=Mode.SUBTRACT"
            depth_expr_sign = "-"
        else:
            mode_suffix = ""
            depth_expr_sign = ""

        depth_name = add_param(f"depth_{idx}", depth, f"mm - feature {idx} depth")

        plane_expr = plane if abs(offset) < 1e-6 else f"{plane}.offset({fmt(offset)})"

        feature_label = {
            "new": "Base body",
            "join": "Join feature",
            "cut": "Cut feature",
        }[op]
        body.append(f"# Feature {idx}: {feature_label}")
        body.append(f"with BuildSketch({plane_expr}):")

        for pi, prof in enumerate(f["profiles"]):
            if prof["kind"] == "circle":
                rname = add_param(f"r_{idx}_{pi + 1}", prof["r"], "mm - circle radius")
                summary["circles"].append(prof["r"])
                if abs(prof["cx"]) < 1e-6 and abs(prof["cy"]) < 1e-6:
                    body.append(f"    Circle({rname})")
                else:
                    cx = add_param(f"cx_{idx}_{pi + 1}", prof["cx"], "mm")
                    cy = add_param(f"cy_{idx}_{pi + 1}", prof["cy"], "mm")
                    body.append(f"    with Locations(({cx}, {cy})):")
                    body.append(f"        Circle({rname})")
            else:  # rect
                wname = add_param(f"w_{idx}_{pi + 1}", prof["w"], "mm - rect width")
                hname = add_param(f"h_{idx}_{pi + 1}", prof["h"], "mm - rect height")
                summary["dims"].append((prof["w"], prof["h"], depth))
                if abs(prof["cx"]) < 1e-6 and abs(prof["cy"]) < 1e-6:
                    body.append(f"    Rectangle({wname}, {hname})")
                else:
                    cx = add_param(f"cx_{idx}_{pi + 1}", prof["cx"], "mm")
                    cy = add_param(f"cy_{idx}_{pi + 1}", prof["cy"], "mm")
                    body.append(f"    with Locations(({cx}, {cy})):")
                    body.append(f"        Rectangle({wname}, {hname})")

        body.append(f"extrude(amount={depth_expr_sign}{depth_name}{mode_suffix})")
        body.append("")

    code_lines = ["from build123d import *", "", "# --- Parameters ---"]
    code_lines.extend(param_lines)
    code_lines.append("")
    code_lines.append("# --- Feature Tree ---")
    code_lines.append("with BuildPart() as part:")
    for line in body:
        code_lines.append("    " + line if line else "")
    code_lines.append("")
    code_lines.append("# --- Export ---")
    code_lines.append("result = part.part")
    code_lines.append('export_step(result, "output.step")')
    return "\n".join(code_lines), summary


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

def generate_prompt(summary: dict, rng: random.Random) -> str:
    dims = summary["dims"]
    circles = summary["circles"]
    ops = summary["op_counts"]
    n_cuts = ops.get("cut", 0)

    # base shape
    if dims:
        w, h, d = dims[0]
        shape = "block" if abs(w - h) < 5 and d > 5 else "plate"
        base_desc = (
            f"{shape} measuring {fmt(w)}mm x {fmt(h)}mm x {fmt(d)}mm"
        )
    elif circles:
        r = circles[0]
        base_desc = f"cylindrical part with an outer diameter of {fmt(r * 2)}mm"
    else:
        base_desc = "solid part"

    feature_desc = ""
    if n_cuts == 1:
        feature_desc = " with a single through-hole or pocket cut out of it"
    elif n_cuts == 2:
        feature_desc = " with two cut features (holes or pockets)"
    elif n_cuts >= 3:
        feature_desc = f" with {n_cuts} cut features"

    templates = [
        f"Create a {base_desc}{feature_desc}.",
        f"Design a {base_desc}{feature_desc}.",
        f"Model a {base_desc}{feature_desc}.",
    ]
    return rng.choice(templates)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scan_files(input_dir: Path) -> list[Path]:
    return list(input_dir.rglob("*.json"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True, help="DeepCAD JSON dir")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-scan", type=int, default=15000)
    ap.add_argument("--target", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"Scanning {args.input}...")
    all_files = scan_files(args.input)
    print(f"  found {len(all_files)} files")
    rng = random.Random(args.seed)
    rng.shuffle(all_files)
    pick = all_files[: args.max_scan]
    print(f"  picking {len(pick)} (max-scan)")

    stats = {
        "scanned": 0,
        "converted": 0,
        "json_error": 0,
        "filter_len": 0,
        "filter_plane": 0,
        "filter_shape": 0,
        "filter_op": 0,
        "filter_extent": 0,
        "filter_base": 0,
        "filter_no_cut": 0,
        "filter_dims": 0,
        "exception": 0,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_fp = args.output.open("w", encoding="utf-8")
    converted = 0

    for path in pick:
        stats["scanned"] += 1
        if converted >= args.target:
            break
        try:
            with path.open("r", encoding="utf-8") as fp:
                doc = json.load(fp)
        except Exception:
            stats["json_error"] += 1
            continue

        try:
            features = extract_features(doc)
        except Exception:
            stats["exception"] += 1
            continue

        if features is None:
            # we lost the reason — but re-run with quick sanity for coarse breakdown
            seq = doc.get("sequence") or []
            if not (2 <= len(seq) <= 16):
                stats["filter_len"] += 1
            else:
                stats["filter_shape"] += 1
            continue

        # require at least one "new" AND (at least one cut OR 2+ features)
        ops = [f["op"] for f in features]
        if ops[0] != "new":
            stats["filter_base"] += 1
            continue
        if "cut" not in ops and len(ops) < 2:
            stats["filter_no_cut"] += 1
            continue

        code, summary = generate_code(features)
        prompt = generate_prompt(summary, rng)

        record = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": code},
            ],
            "source": "deepcad",
            "origin_file": path.name,
            "n_features": len(features),
            "op_counts": summary["op_counts"],
            "complexity": min(5, max(2, len(features))),
        }
        out_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        converted += 1
        stats["converted"] += 1

    out_fp.close()

    print("=== DeepCAD conversion stats ===")
    for k, v in stats.items():
        print(f"  {k:18s} {v}")
    print(f"  wrote {converted} samples to {args.output}")
    if stats["scanned"]:
        rate = stats["converted"] / stats["scanned"] * 100
        print(f"  pass rate: {rate:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
