"""Transpile CadQuery code from rumike7 dataset → OFL training pairs.

Usage:
    python scripts/cq_to_ofl.py                          # default paths
    python scripts/cq_to_ofl.py --input X.csv --output Y.jsonl
"""

from __future__ import annotations

import ast
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# AST-based CadQuery chain extractor
# ---------------------------------------------------------------------------

@dataclass
class MethodCall:
    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


def _eval_literal(node: ast.expr) -> Any:
    """Safely evaluate an AST node to a Python literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        # Try to recover variable names as strings
        if isinstance(node, ast.Name):
            return f"${node.id}"  # mark as variable ref
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = _eval_literal(node.operand)
            if isinstance(val, (int, float)):
                return -val
        return None


def _extract_chain(node: ast.expr) -> list[MethodCall] | None:
    """Walk a fluent method chain backwards from the outermost Call."""
    calls: list[MethodCall] = []
    current = node

    while isinstance(current, ast.Call):
        func = current.func
        if isinstance(func, ast.Attribute):
            method_name = func.attr
            args = [_eval_literal(a) for a in current.args]
            kwargs = {}
            for kw in current.keywords:
                kwargs[kw.arg] = _eval_literal(kw.value)
            calls.append(MethodCall(method_name, args, kwargs))
            current = func.value
        else:
            break

    calls.reverse()

    # The chain must start with Workplane
    if calls and calls[0].name == "Workplane":
        return calls

    return None


def extract_chains(code: str) -> list[list[MethodCall]]:
    """Parse CadQuery code and return all method chains found."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    chains: list[list[MethodCall]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = _extract_chain(node)
            if chain and len(chain) >= 2:
                chains.append(chain)

    # Deduplicate (inner chains are subsets of outer chains)
    # Keep only the longest chains
    if len(chains) > 1:
        chains.sort(key=len, reverse=True)
        kept = []
        for c in chains:
            methods = [m.name for m in c]
            is_subset = False
            for k in kept:
                k_methods = [m.name for m in k]
                if len(methods) < len(k_methods) and all(
                    m in k_methods for m in methods
                ):
                    is_subset = True
                    break
            if not is_subset:
                kept.append(c)
        chains = kept

    return chains


def extract_variables(code: str) -> dict[str, Any]:
    """Extract top-level variable assignments (name = literal)."""
    variables: dict[str, Any] = {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return variables

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                val = _eval_literal(node.value)
                if val is not None:
                    variables[target.id] = val
    return variables


# ---------------------------------------------------------------------------
# CadQuery → OFL transpiler
# ---------------------------------------------------------------------------

CQ_PLANE_MAP = {
    "XY": "XY", "xy": "XY",
    "XZ": "XZ", "xz": "XZ",
    "YZ": "YZ", "yz": "YZ",
    "front": "XY", "back": "XY",
    "top": "XZ", "bottom": "XZ",
    "right": "YZ", "left": "YZ",
}


@dataclass
class TranspileResult:
    ok: bool
    ofl_code: str = ""
    b123d_code: str = ""
    skip_reason: str = ""
    complexity: int = 1


def _resolve(val: Any, variables: dict[str, Any]) -> Any:
    """Resolve a $variable reference, or return the literal."""
    if isinstance(val, str) and val.startswith("$"):
        varname = val[1:]
        return variables.get(varname, val)
    return val


def _fmt(val: Any) -> str:
    """Format a value for OFL code emission."""
    if isinstance(val, str) and val.startswith("$"):
        return val[1:]  # variable name
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    return repr(val)


def _is_variable_ref(val: Any) -> bool:
    return isinstance(val, str) and val.startswith("$")


def transpile_chain(
    chain: list[MethodCall],
    variables: dict[str, Any],
) -> TranspileResult:
    """Convert a single CadQuery method chain to OFL code."""

    if not chain or chain[0].name != "Workplane":
        return TranspileResult(False, skip_reason="no Workplane root")

    plane_str = chain[0].args[0] if chain[0].args else "XY"
    ofl_plane = CQ_PLANE_MAP.get(str(plane_str), None)
    if ofl_plane is None:
        return TranspileResult(False, skip_reason=f"unsupported plane: {plane_str}")

    # Walk the chain and build OFL operations
    sketch_op = None       # "rect" or "circle"
    sketch_args = []       # args for the sketch op
    extrude_arg = None     # extrude height
    extrude_kwargs = {}
    holes: list[dict] = []
    fillets: list[str] = []
    chamfers: list[str] = []
    has_unsupported = False
    unsupported_reason = ""
    complexity = 1

    i = 1
    while i < len(chain):
        m = chain[i]

        if m.name == "box" and len(m.args) >= 3:
            # .box(l, w, h) → rect(l, w) + extrude(h)
            sketch_op = "rect"
            sketch_args = [m.args[0], m.args[1]]
            extrude_arg = m.args[2]

        elif m.name == "rect" and len(m.args) >= 2:
            sketch_op = "rect"
            sketch_args = [m.args[0], m.args[1]]

        elif m.name == "circle" and len(m.args) >= 1:
            # CadQuery .circle(radius) → OFL .circle(diameter)
            r = m.args[0]
            if _is_variable_ref(r):
                sketch_op = "circle_from_radius"
                sketch_args = [r]
            else:
                resolved = _resolve(r, variables)
                if isinstance(resolved, (int, float)):
                    sketch_op = "circle"
                    sketch_args = [resolved * 2]
                else:
                    sketch_op = "circle_from_radius"
                    sketch_args = [r]

        elif m.name == "extrude" and len(m.args) >= 1:
            extrude_arg = m.args[0]
            if "taper" in m.kwargs:
                extrude_kwargs["taper"] = m.kwargs["taper"]

        elif m.name in ("faces", "workplane", "edges", "vertices"):
            pass  # context selectors — we handle the operations after them

        elif m.name == "hole" and len(m.args) >= 1:
            holes.append({"diameter": m.args[0]})
            complexity = max(complexity, 2)

        elif m.name == "cboreHole" and len(m.args) >= 3:
            holes.append({"diameter": m.args[0]})
            complexity = max(complexity, 3)

        elif m.name == "cskHole" and len(m.args) >= 3:
            holes.append({"diameter": m.args[0]})
            complexity = max(complexity, 3)

        elif m.name == "fillet" and len(m.args) >= 1:
            fillets.append(m.args[0])
            complexity = max(complexity, 2)

        elif m.name == "chamfer" and len(m.args) >= 1:
            chamfers.append(m.args[0])
            complexity = max(complexity, 2)

        elif m.name == "cutThruAll":
            pass  # handled implicitly with holes

        elif m.name in ("export", "close", "add", "val", "tag"):
            pass  # ignore

        elif m.name in ("pushPoints", "transformed", "center"):
            # positioning — skip records with complex positioning for now
            has_unsupported = True
            unsupported_reason = f"complex positioning: .{m.name}()"
            break

        elif m.name in (
            "polygon", "polyline", "spline", "ellipse",
            "sphere", "revolve", "sweep", "loft", "shell",
            "threePointArc", "sagittaArc", "radiusArc",
            "moveTo", "lineTo",
        ):
            has_unsupported = True
            unsupported_reason = f"unsupported op: .{m.name}()"
            break

        elif m.name in ("translate", "rotate", "mirror"):
            pass  # skip positioning for now

        elif m.name == "cutBlind" and len(m.args) >= 1:
            # .cutBlind() is like extrude-subtract
            pass  # skip — requires sketch context we can't recover

        elif m.name in ("union", "cut", "intersect"):
            has_unsupported = True
            unsupported_reason = f"boolean op: .{m.name}()"
            break

        elif m.name == "sketch":
            has_unsupported = True
            unsupported_reason = f"new-style sketch API"
            break

        else:
            has_unsupported = True
            unsupported_reason = f"unknown: .{m.name}()"
            break

        i += 1

    if has_unsupported:
        return TranspileResult(False, skip_reason=unsupported_reason)

    if sketch_op is None:
        return TranspileResult(False, skip_reason="no sketch operation found")

    if extrude_arg is None and sketch_op != "rect":
        # box already has extrude built in
        return TranspileResult(False, skip_reason="no extrude found")

    if extrude_kwargs.get("taper"):
        return TranspileResult(False, skip_reason="taper extrude not supported in OFL")

    # --- Collect variable references ---
    used_vars = set()

    def _collect_vars(val):
        if _is_variable_ref(val):
            used_vars.add(val[1:])

    for a in sketch_args:
        _collect_vars(a)
    if extrude_arg is not None:
        _collect_vars(extrude_arg)
    for h in holes:
        _collect_vars(h["diameter"])
    for f in fillets:
        _collect_vars(f)

    var_lines = []
    for vname in sorted(used_vars):
        if vname in variables:
            var_lines.append(f"{vname} = {_fmt(variables[vname])}")

    # --- Emit OFL code ---
    ofl = _emit_ofl(
        ofl_plane, sketch_op, sketch_args, extrude_arg,
        holes, fillets, chamfers, var_lines,
    )

    # --- Emit Build123d code ---
    b123d = _emit_b123d(
        ofl_plane, sketch_op, sketch_args, extrude_arg,
        holes, fillets, chamfers, var_lines, variables,
    )

    return TranspileResult(
        True, ofl_code=ofl, b123d_code=b123d, complexity=complexity,
    )


def _emit_ofl(
    plane, sketch_op, sketch_args, extrude_arg,
    holes, fillets, chamfers, var_lines,
) -> str:
    lines = ["from orionflow_ofl import *", ""]
    if var_lines:
        lines.extend(var_lines)
        lines.append("")

    if sketch_op == "rect":
        lines.append("part = (")
        lines.append(f"    Sketch(Plane.{plane})")
        lines.append(f"    .rect({_fmt(sketch_args[0])}, {_fmt(sketch_args[1])})")
        if extrude_arg is not None:
            lines.append(f"    .extrude({_fmt(extrude_arg)})")
        lines.append(")")
    elif sketch_op == "circle":
        lines.append("part = (")
        lines.append(f"    Sketch(Plane.{plane})")
        lines.append(f"    .circle({_fmt(sketch_args[0])})")
        if extrude_arg is not None:
            lines.append(f"    .extrude({_fmt(extrude_arg)})")
        lines.append(")")
    elif sketch_op == "circle_from_radius":
        varname = _fmt(sketch_args[0])
        lines.append(f"diameter = {varname} * 2")
        lines.append("")
        lines.append("part = (")
        lines.append(f"    Sketch(Plane.{plane})")
        lines.append("    .circle(diameter)")
        if extrude_arg is not None:
            lines.append(f"    .extrude({_fmt(extrude_arg)})")
        lines.append(")")

    for h in holes:
        lines.extend(["", "part -= (", f"    Hole({_fmt(h['diameter'])})",
                       "    .at(0, 0)", "    .through()", ")"])
    for f in fillets:
        lines.extend(["", f"part.fillet({_fmt(f)})"])
    for c in chamfers:
        lines.extend(["", f"part.chamfer({_fmt(c)})"])

    lines.extend(["", 'export(part, "model.step")', ""])
    return "\n".join(lines)


def _emit_b123d(
    plane, sketch_op, sketch_args, extrude_arg,
    holes, fillets, chamfers, var_lines, variables,
) -> str:
    lines = ["from build123d import *", ""]
    if var_lines:
        lines.extend(var_lines)
        lines.append("")

    lines.append("with BuildPart() as part:")

    if sketch_op == "rect":
        w, h = _fmt(sketch_args[0]), _fmt(sketch_args[1])
        if extrude_arg is not None:
            lines.append(f"    Box({w}, {h}, {_fmt(extrude_arg)})")
        else:
            lines.append(f"    with BuildSketch():")
            lines.append(f"        Rectangle({w}, {h})")
    elif sketch_op in ("circle", "circle_from_radius"):
        if sketch_op == "circle_from_radius":
            varname = _fmt(sketch_args[0])
            # Insert diameter variable before BuildPart
            lines.insert(len(lines) - 1, f"diameter = {varname} * 2")
            lines.insert(len(lines) - 1, "")
            r_expr = "diameter / 2"
        else:
            val = sketch_args[0]
            if isinstance(val, (int, float)):
                r_expr = _fmt(val / 2)
            else:
                r_expr = f"{_fmt(val)} / 2"

        if extrude_arg is not None:
            lines.append(f"    Cylinder({r_expr}, {_fmt(extrude_arg)})")
        else:
            lines.append(f"    with BuildSketch():")
            lines.append(f"        Circle({r_expr})")

    # Holes
    for h_item in holes:
        d = h_item["diameter"]
        if _is_variable_ref(d):
            r_expr = f"{_fmt(d)} / 2"
        else:
            resolved = _resolve(d, variables)
            if isinstance(resolved, (int, float)):
                r_expr = _fmt(resolved / 2)
            else:
                r_expr = f"{_fmt(d)} / 2"
        lines.append(f"    Hole({r_expr})")

    # Fillets
    for f in fillets:
        lines.append(f"    fillet(part.edges(), {_fmt(f)})")

    # Chamfers
    for c in chamfers:
        lines.append(f"    chamfer(part.edges(), {_fmt(c)})")

    lines.extend(["", 'export_step(part.part, "model.step")', ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comment / description extraction
# ---------------------------------------------------------------------------

# Lines to ignore when extracting descriptions
_IGNORE_PATTERNS = [
    re.compile(r"^#\s*export", re.IGNORECASE),
    re.compile(r"^#\s*-\*-"),
    re.compile(r"^#!/"),
    re.compile(r"^#\s*import"),
    re.compile(r"^#\s*$"),
]


def extract_description(code: str) -> str | None:
    """Extract a natural-language description from comments in the code."""
    descriptions = []
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        comment = stripped.lstrip("#").strip()
        if not comment:
            continue
        if any(p.match(stripped) for p in _IGNORE_PATTERNS):
            continue
        # Skip implementation comments
        if comment.startswith("The dimensions") or comment.startswith("Create a"):
            continue
        descriptions.append(comment)

    if not descriptions:
        return None

    # Take the first meaningful comment as the description
    desc = descriptions[0]

    # Clean up
    desc = desc.strip().rstrip(".")

    # Too short or too generic?
    if len(desc) < 5 or desc.lower() in ("code", "result", "output"):
        return None

    return desc


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_OFL = (
    "You are OrionFlow, an AI mechanical design copilot. "
    "Given a part description, generate valid OFL Python code that compiles "
    "to a 3D STEP model. Use descriptive variable names and add comments "
    "for each feature. Always include from orionflow_ofl import * and "
    "export(part, 'model.step')."
)

SYSTEM_PROMPT_B123D = (
    "You are OrionFlow, an AI mechanical design copilot. "
    "Given a part description, generate valid build123d Python code that "
    "creates a 3D STEP model. Use BuildPart context managers, descriptive "
    "variable names, and add comments for each feature."
)


def process_csv(
    input_path: str,
    output_dir: str,
    *,
    max_records: int = 0,
) -> dict:
    """Process rumike7 CSV and write training pairs as JSONL (both formats)."""

    stats = {
        "total": 0,
        "transpiled": 0,
        "unique": 0,
        "skipped_no_chain": 0,
        "skipped_unsupported": 0,
        "skipped_no_description": 0,
        "skipped_duplicate": 0,
        "skip_reasons": {},
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ofl_path = out / "rumike7_ofl.jsonl"
    b123d_path = out / "rumike7_b123d.jsonl"
    text_code_path = out / "rumike7_text_code.jsonl"

    seen_descriptions: set[str] = set()

    with (
        open(input_path, "r", encoding="utf-8") as fin,
        open(ofl_path, "w", encoding="utf-8") as f_ofl,
        open(b123d_path, "w", encoding="utf-8") as f_b123d,
        open(text_code_path, "w", encoding="utf-8") as f_txt,
    ):
        reader = csv.reader(fin)
        header = next(reader)
        content_idx = header.index("content")

        for row in reader:
            stats["total"] += 1
            if max_records and stats["total"] > max_records:
                break

            code = row[content_idx]

            chains = extract_chains(code)
            if not chains:
                stats["skipped_no_chain"] += 1
                continue

            variables = extract_variables(code)
            result = transpile_chain(chains[0], variables)

            if not result.ok:
                stats["skipped_unsupported"] += 1
                reason = result.skip_reason
                stats["skip_reasons"][reason] = stats["skip_reasons"].get(reason, 0) + 1
                continue

            description = extract_description(code)
            if not description:
                stats["skipped_no_description"] += 1
                continue

            # Deduplicate by description
            desc_key = description.lower().strip()
            if desc_key in seen_descriptions:
                stats["skipped_duplicate"] += 1
                continue
            seen_descriptions.add(desc_key)

            stats["transpiled"] += 1
            stats["unique"] += 1

            # --- OFL format (chat messages) ---
            ofl_rec = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_OFL},
                    {"role": "user", "content": description},
                    {"role": "assistant", "content": result.ofl_code},
                ],
                "source": "rumike7_transpiled",
                "complexity": result.complexity,
            }
            f_ofl.write(json.dumps(ofl_rec, ensure_ascii=False) + "\n")

            # --- Build123d format (chat messages) ---
            b123d_rec = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT_B123D},
                    {"role": "user", "content": description},
                    {"role": "assistant", "content": result.b123d_code},
                ],
                "source": "rumike7_transpiled",
                "complexity": result.complexity,
            }
            f_b123d.write(json.dumps(b123d_rec, ensure_ascii=False) + "\n")

            # --- Simple text+code pairs (both formats) ---
            txt_rec = {
                "text": description,
                "ofl_code": result.ofl_code,
                "b123d_code": result.b123d_code,
                "source": "rumike7_transpiled",
                "complexity": result.complexity,
            }
            f_txt.write(json.dumps(txt_rec, ensure_ascii=False) + "\n")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CadQuery -> OFL + Build123d transpiler")
    parser.add_argument(
        "--input",
        default="caddata/raw/rumike7/dataset_metadata.csv",
        help="Input CSV from rumike7 dataset",
    )
    parser.add_argument(
        "--output-dir",
        default="caddata/processed",
        help="Output directory for JSONL files",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Max records to process (0 = all)",
    )
    args = parser.parse_args()

    print(f"Processing {args.input} ...")
    stats = process_csv(args.input, args.output_dir, max_records=args.max_records)

    print(f"\nResults:")
    print(f"  Total records scanned: {stats['total']}")
    print(f"  Successfully transpiled: {stats['transpiled']}")
    print(f"  Unique (after dedup): {stats['unique']}")
    print(f"  Skipped (no chain): {stats['skipped_no_chain']}")
    print(f"  Skipped (unsupported): {stats['skipped_unsupported']}")
    print(f"  Skipped (no description): {stats['skipped_no_description']}")
    print(f"  Skipped (duplicate): {stats['skipped_duplicate']}")

    if stats["skip_reasons"]:
        print(f"\n  Top skip reasons:")
        sorted_reasons = sorted(
            stats["skip_reasons"].items(), key=lambda x: -x[1]
        )
        for reason, cnt in sorted_reasons[:15]:
            print(f"    {cnt:5d}  {reason}")

    print(f"\nOutputs in {args.output_dir}/:")
    print(f"  rumike7_ofl.jsonl     — OFL chat format")
    print(f"  rumike7_b123d.jsonl   — Build123d chat format")
    print(f"  rumike7_text_code.jsonl — text + both codes (flat)")


if __name__ == "__main__":
    main()
