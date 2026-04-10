"""Convert OFL training data → Build123d training data.

Reads JSONL files with OFL code in assistant messages, converts the OFL code
to equivalent Build123d code, and writes parallel Build123d JSONL files.

Usage:
    python scripts/ofl_to_b123d.py
    python scripts/ofl_to_b123d.py --input data/training/synthetic_from_templates.jsonl
    python scripts/ofl_to_b123d.py --all   # convert all JSONL in data/training/
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# OFL → Build123d code converter
# ---------------------------------------------------------------------------

def convert_ofl_to_b123d(ofl_code: str) -> str | None:
    """Convert OFL Python code to Build123d Python code.

    Returns None if the code can't be converted (unrecognized pattern).
    """
    if "from orionflow_ofl import" not in ofl_code:
        return None

    # Join multi-line parenthesized expressions into logical lines
    blocks = _parse_blocks(ofl_code)
    if not blocks:
        return None

    b123d_lines: list[str] = []
    indent = "    "  # inside BuildPart
    part_var = "part"
    has_buildpart = False

    for block in blocks:
        btype = block["type"]

        if btype == "import":
            b123d_lines.append("from build123d import *")

        elif btype == "variable":
            b123d_lines.append(block["raw"])

        elif btype == "comment":
            if has_buildpart:
                b123d_lines.append(indent + block["raw"])
            else:
                b123d_lines.append(block["raw"])

        elif btype == "blank":
            b123d_lines.append("")

        elif btype == "sketch_extrude":
            if not has_buildpart:
                b123d_lines.append("")
                b123d_lines.append(f"with BuildPart() as {part_var}:")
                has_buildpart = True

            shape = block["shape"]  # rect, circle, rounded_rect
            args = block["args"]    # shape args as raw strings
            extrude = block.get("extrude")  # extrude arg
            plane = block.get("plane", "XY")
            offset = block.get("offset")

            if shape == "rect" and extrude:
                if offset:
                    b123d_lines.append(f"{indent}with Locations([(0, 0, {offset})]):")
                    b123d_lines.append(f"{indent}    Box({args[0]}, {args[1]}, {extrude})")
                else:
                    b123d_lines.append(f"{indent}Box({args[0]}, {args[1]}, {extrude})")

            elif shape == "circle" and extrude:
                diameter = args[0]
                radius = _halve_expr(diameter)
                if offset:
                    b123d_lines.append(f"{indent}with Locations([(0, 0, {offset})]):")
                    b123d_lines.append(f"{indent}    Cylinder({radius}, {extrude})")
                else:
                    b123d_lines.append(f"{indent}Cylinder({radius}, {extrude})")

            elif shape == "rounded_rect" and extrude:
                w, h, r = args[0], args[1], args[2]
                b123d_lines.append(f"{indent}with BuildSketch():")
                b123d_lines.append(f"{indent}    RectangleRounded({w}, {h}, {r})")
                b123d_lines.append(f"{indent}extrude(amount={extrude})")

            else:
                return None  # can't convert

        elif btype == "hole":
            if not has_buildpart:
                return None

            diameter = block["diameter"]
            radius = _halve_expr(diameter)
            positions = block.get("positions", [])
            circular = block.get("circular")
            depth = block.get("depth")

            if circular:
                r_circ = circular["radius"]
                count = circular["count"]
                start = circular.get("start_angle", "0")
                b123d_lines.append(f"{indent}with PolarLocations({r_circ}, {count}, {start}):")
                if depth:
                    b123d_lines.append(f"{indent}    CounterBoreHole({radius}, counter_bore_radius={radius}, counter_bore_depth={depth})")
                else:
                    b123d_lines.append(f"{indent}    Hole({radius})")
            elif positions:
                if len(positions) == 1:
                    x, y = positions[0]
                    if _is_zero(x) and _is_zero(y):
                        if depth:
                            b123d_lines.append(f"{indent}Hole({radius}, depth={depth})")
                        else:
                            b123d_lines.append(f"{indent}Hole({radius})")
                    else:
                        b123d_lines.append(f"{indent}with Locations([({x}, {y})]):")
                        if depth:
                            b123d_lines.append(f"{indent}    Hole({radius}, depth={depth})")
                        else:
                            b123d_lines.append(f"{indent}    Hole({radius})")
                else:
                    locs = ", ".join(f"({x}, {y})" for x, y in positions)
                    b123d_lines.append(f"{indent}with Locations([{locs}]):")
                    if depth:
                        b123d_lines.append(f"{indent}    Hole({radius}, depth={depth})")
                    else:
                        b123d_lines.append(f"{indent}    Hole({radius})")
            else:
                if depth:
                    b123d_lines.append(f"{indent}Hole({radius}, depth={depth})")
                else:
                    b123d_lines.append(f"{indent}Hole({radius})")

        elif btype == "fillet":
            if not has_buildpart:
                return None
            radius = block["radius"]
            edges = block.get("edges")
            if edges == "vertical":
                b123d_lines.append(f"{indent}fillet({part_var}.edges().filter_by(Axis.Z), {radius})")
            elif edges == "top":
                b123d_lines.append(f"{indent}fillet({part_var}.edges().group_by(Axis.Z)[-1], {radius})")
            elif edges == "bottom":
                b123d_lines.append(f"{indent}fillet({part_var}.edges().group_by(Axis.Z)[0], {radius})")
            else:
                b123d_lines.append(f"{indent}fillet({part_var}.edges(), {radius})")

        elif btype == "chamfer":
            if not has_buildpart:
                return None
            distance = block["distance"]
            edges = block.get("edges")
            if edges == "vertical":
                b123d_lines.append(f"{indent}chamfer({part_var}.edges().filter_by(Axis.Z), {distance})")
            elif edges == "top":
                b123d_lines.append(f"{indent}chamfer({part_var}.edges().group_by(Axis.Z)[-1], {distance})")
            elif edges == "bottom":
                b123d_lines.append(f"{indent}chamfer({part_var}.edges().group_by(Axis.Z)[0], {distance})")
            else:
                b123d_lines.append(f"{indent}chamfer({part_var}.edges(), {distance})")

        elif btype == "shell":
            if not has_buildpart:
                return None
            thickness = block["thickness"]
            face = block.get("open_face")
            if face == "top":
                b123d_lines.append(f"{indent}offset_3d(openings={part_var}.faces().sort_by(Axis.Z)[-1], amount=-{thickness})")
            elif face == "bottom":
                b123d_lines.append(f"{indent}offset_3d(openings={part_var}.faces().sort_by(Axis.Z)[0], amount=-{thickness})")
            else:
                b123d_lines.append(f"{indent}offset_3d(amount=-{thickness})")

        elif btype == "boolean_add":
            # In Build123d, shapes in the same BuildPart auto-union
            # So we just emit the shape directly
            sub = block.get("sub_blocks", [])
            for sb in sub:
                if sb["type"] == "sketch_extrude":
                    shape = sb["shape"]
                    args = sb["args"]
                    extrude = sb.get("extrude")
                    offset = sb.get("offset")
                    if shape == "rect" and extrude:
                        if offset:
                            b123d_lines.append(f"{indent}with Locations([(0, 0, {offset})]):")
                            b123d_lines.append(f"{indent}    Box({args[0]}, {args[1]}, {extrude})")
                        else:
                            b123d_lines.append(f"{indent}Box({args[0]}, {args[1]}, {extrude})")
                    elif shape == "circle" and extrude:
                        radius = _halve_expr(args[0])
                        if offset:
                            b123d_lines.append(f"{indent}with Locations([(0, 0, {offset})]):")
                            b123d_lines.append(f"{indent}    Cylinder({radius}, {extrude})")
                        else:
                            b123d_lines.append(f"{indent}Cylinder({radius}, {extrude})")

        elif btype == "export":
            filename = block.get("filename", "model.step")
            b123d_lines.append("")
            b123d_lines.append(f'export_step({part_var}.part, "{filename}")')

        elif btype == "unknown":
            # Skip unknown lines — best effort
            pass

    if not has_buildpart:
        return None

    return "\n".join(b123d_lines) + "\n"


# ---------------------------------------------------------------------------
# Block parser — splits OFL code into logical blocks
# ---------------------------------------------------------------------------

def _parse_blocks(code: str) -> list[dict]:
    """Parse OFL code into a list of typed blocks."""
    # First, join lines inside parentheses
    logical_lines = _join_parens(code)
    blocks: list[dict] = []

    i = 0
    while i < len(logical_lines):
        line = logical_lines[i]
        stripped = line.strip()

        # Blank
        if not stripped:
            blocks.append({"type": "blank"})
            i += 1
            continue

        # Comment
        if stripped.startswith("#"):
            blocks.append({"type": "comment", "raw": stripped})
            i += 1
            continue

        # Import
        if stripped.startswith("from orionflow_ofl import"):
            blocks.append({"type": "import"})
            i += 1
            continue

        # Variable assignment (simple: name = expr, no Sketch/Hole/export)
        if re.match(r'^[a-zA-Z_]\w*\s*=\s*', stripped) and not any(
            kw in stripped for kw in ("Sketch(", "Hole(", "export(")
        ) and "part" not in stripped.split("=")[0].strip():
            blocks.append({"type": "variable", "raw": stripped})
            i += 1
            continue

        # Sketch+extrude: part = (Sketch(Plane.XX).shape(...).extrude(...))
        sketch_match = re.search(
            r'Sketch\(Plane\.(\w+)(?:,\s*offset\s*=\s*(.+?))?\)\s*'
            r'\.(rect|circle|rounded_rect)\((.+?)\)\s*'
            r'(?:\.extrude\((.+?)\))?',
            stripped,
        )
        if sketch_match and ("part" in stripped.split("=")[0] if "=" in stripped else True):
            plane = sketch_match.group(1)
            offset = sketch_match.group(2)
            shape = sketch_match.group(3)
            shape_args_raw = sketch_match.group(4)
            extrude_arg = sketch_match.group(5)
            shape_args = [a.strip() for a in shape_args_raw.split(",")]

            block = {
                "type": "sketch_extrude",
                "shape": shape,
                "args": shape_args,
                "plane": plane,
            }
            if offset:
                block["offset"] = offset.strip()
            if extrude_arg:
                block["extrude"] = extrude_arg.strip()
            blocks.append(block)
            i += 1
            continue

        # Hole: part -= (Hole(d).at(...).through())
        hole_match = re.search(r'Hole\((.+?)\)', stripped)
        if hole_match and "-=" in stripped:
            diameter = hole_match.group(1).strip()
            block = {"type": "hole", "diameter": diameter}

            # Extract .at() positions
            positions = re.findall(r'\.at\((.+?)\)', stripped)
            pos_list = []
            for pos in positions:
                parts = [p.strip() for p in pos.split(",")]
                if len(parts) == 2:
                    pos_list.append((parts[0], parts[1]))
            if pos_list:
                block["positions"] = pos_list

            # Extract .at_circular()
            circ_match = re.search(
                r'\.at_circular\((.+?),\s*count\s*=\s*(\d+)'
                r'(?:,\s*start_angle\s*=\s*([^)]+))?\)',
                stripped,
            )
            if circ_match:
                block["circular"] = {
                    "radius": circ_match.group(1).strip(),
                    "count": circ_match.group(2).strip(),
                }
                if circ_match.group(3):
                    block["circular"]["start_angle"] = circ_match.group(3).strip()

            # Extract .to_depth()
            depth_match = re.search(r'\.to_depth\((.+?)\)', stripped)
            if depth_match:
                block["depth"] = depth_match.group(1).strip()

            blocks.append(block)
            i += 1
            continue

        # Fillet: part.fillet(r) or part = part.fillet(r, edges="...")
        fillet_match = re.search(
            r'\.fillet\(([^,)]+)(?:,\s*edges\s*=\s*["\'](\w+)["\'])?\)',
            stripped,
        )
        if fillet_match and "fillet" in stripped:
            blocks.append({
                "type": "fillet",
                "radius": fillet_match.group(1).strip(),
                "edges": fillet_match.group(2),
            })
            i += 1
            continue

        # Chamfer: part.chamfer(d) or part = part.chamfer(d, edges="...")
        chamfer_match = re.search(
            r'\.chamfer\(([^,)]+)(?:,\s*edges\s*=\s*["\'](\w+)["\'])?\)',
            stripped,
        )
        if chamfer_match and "chamfer" in stripped:
            blocks.append({
                "type": "chamfer",
                "distance": chamfer_match.group(1).strip(),
                "edges": chamfer_match.group(2),
            })
            i += 1
            continue

        # Shell: part.shell(t, open_face="...")
        shell_match = re.search(
            r'\.shell\(([^,)]+)(?:,\s*open_face\s*=\s*["\'](\w+)["\'])?\)',
            stripped,
        )
        if shell_match:
            blocks.append({
                "type": "shell",
                "thickness": shell_match.group(1).strip(),
                "open_face": shell_match.group(2),
            })
            i += 1
            continue

        # Boolean add: part += (Sketch(...).extrude(...))
        if "+=" in stripped and "Sketch(" in stripped:
            sub_sketch = re.search(
                r'Sketch\(Plane\.(\w+)(?:,\s*offset\s*=\s*(.+?))?\)\s*'
                r'\.(rect|circle|rounded_rect)\((.+?)\)\s*'
                r'(?:\.extrude\((.+?)\))?',
                stripped,
            )
            if sub_sketch:
                plane = sub_sketch.group(1)
                offset = sub_sketch.group(2)
                shape = sub_sketch.group(3)
                shape_args = [a.strip() for a in sub_sketch.group(4).split(",")]
                extrude_arg = sub_sketch.group(5)
                sb = {
                    "type": "sketch_extrude",
                    "shape": shape,
                    "args": shape_args,
                    "plane": plane,
                }
                if offset:
                    sb["offset"] = offset.strip()
                if extrude_arg:
                    sb["extrude"] = extrude_arg.strip()
                blocks.append({"type": "boolean_add", "sub_blocks": [sb]})
            i += 1
            continue

        # Export
        export_match = re.search(r'export\(\w+,\s*["\'](.+?)["\']\)', stripped)
        if export_match:
            blocks.append({"type": "export", "filename": export_match.group(1)})
            i += 1
            continue

        # Unknown — skip
        blocks.append({"type": "unknown", "raw": stripped})
        i += 1

    return blocks


def _join_parens(code: str) -> list[str]:
    """Join lines inside parentheses into single logical lines."""
    lines = code.splitlines()
    result: list[str] = []
    buf = ""
    depth = 0

    for line in lines:
        stripped = line.strip()
        if depth > 0:
            buf += " " + stripped
            depth += stripped.count("(") - stripped.count(")")
            if depth <= 0:
                result.append(buf)
                buf = ""
                depth = 0
        else:
            open_count = stripped.count("(")
            close_count = stripped.count(")")
            if open_count > close_count:
                buf = stripped
                depth = open_count - close_count
            else:
                result.append(line)

    if buf:
        result.append(buf)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _halve_expr(expr: str) -> str:
    """Convert a diameter expression to radius (divide by 2)."""
    expr = expr.strip()
    # If it's a simple number, halve it
    try:
        val = float(expr)
        if val == int(val):
            half = int(val) // 2 if int(val) % 2 == 0 else val / 2
        else:
            half = val / 2
        if isinstance(half, float) and half == int(half):
            return str(int(half))
        return str(half)
    except ValueError:
        pass
    # Variable — emit as expr / 2
    return f"{expr} / 2"


def _is_zero(expr: str) -> bool:
    expr = expr.strip()
    try:
        return float(expr) == 0.0
    except ValueError:
        return expr in ("0", "0.0", "center_x", "center_y")


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_B123D = (
    "You are OrionFlow, an AI mechanical design copilot. "
    "Given a part description, generate valid build123d Python code that "
    "creates a 3D STEP model. Use BuildPart context managers, descriptive "
    "variable names, and add comments for each feature."
)


# ---------------------------------------------------------------------------
# JSONL processing
# ---------------------------------------------------------------------------

def convert_jsonl(input_path: str, output_path: str) -> dict:
    """Convert a single JSONL file from OFL to Build123d format."""
    stats = {"total": 0, "converted": 0, "failed": 0}

    with (
        open(input_path, "r", encoding="utf-8") as fin,
        open(output_path, "w", encoding="utf-8") as fout,
    ):
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            stats["total"] += 1

            # Find and convert OFL code
            ofl_code = None
            code_key = None

            if "messages" in rec:
                for msg in rec["messages"]:
                    if msg.get("role") == "assistant":
                        ofl_code = msg["content"]
                        break
                code_key = "messages"
            elif "code" in rec:
                ofl_code = rec["code"]
                code_key = "code"
            elif "ofl_code" in rec:
                ofl_code = rec["ofl_code"]
                code_key = "ofl_code"

            if not ofl_code:
                stats["failed"] += 1
                continue

            b123d_code = convert_ofl_to_b123d(ofl_code)
            if not b123d_code:
                stats["failed"] += 1
                continue

            # Build output record
            out_rec = dict(rec)

            if code_key == "messages":
                new_msgs = []
                for msg in rec["messages"]:
                    if msg.get("role") == "system":
                        new_msgs.append({"role": "system", "content": SYSTEM_PROMPT_B123D})
                    elif msg.get("role") == "assistant":
                        new_msgs.append({"role": "assistant", "content": b123d_code})
                    else:
                        new_msgs.append(dict(msg))
                out_rec["messages"] = new_msgs
            elif code_key == "code":
                out_rec["code"] = b123d_code
            elif code_key == "ofl_code":
                out_rec["b123d_code"] = b123d_code

            out_rec["source"] = rec.get("source", "unknown") + "_b123d"

            fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
            stats["converted"] += 1

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OFL -> Build123d converter")
    parser.add_argument("--input", help="Single JSONL file to convert")
    parser.add_argument(
        "--all", action="store_true",
        help="Convert all JSONL files in data/training/",
    )
    parser.add_argument(
        "--output-dir",
        default="caddata/processed/b123d",
        help="Output directory for Build123d JSONL files",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.input:
        files = [args.input]
    elif args.all:
        data_dir = Path("data/training")
        files = sorted(str(p) for p in data_dir.glob("*.jsonl") if p.stat().st_size > 0)
    else:
        parser.error("Specify --input FILE or --all")
        return

    grand_total = 0
    grand_converted = 0

    for fpath in files:
        fname = Path(fpath).stem
        out_path = out_dir / f"{fname}_b123d.jsonl"
        print(f"  {Path(fpath).name} -> {out_path.name} ... ", end="", flush=True)
        stats = convert_jsonl(fpath, str(out_path))
        print(f"{stats['converted']}/{stats['total']} converted")
        grand_total += stats["total"]
        grand_converted += stats["converted"]

    print(f"\nTotal: {grand_converted}/{grand_total} converted "
          f"({grand_converted/grand_total*100:.1f}%)")
    print(f"Output directory: {args.output_dir}/")


if __name__ == "__main__":
    main()
