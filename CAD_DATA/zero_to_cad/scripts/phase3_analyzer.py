"""Phase 3: Extract structured features from CadQuery code + ops_json.

Input  : raw/<split>.jsonl rows (each has 'code' and 'ops_json')
Output : features dict per row, written to analyzed/<split>.jsonl

Features captured per row:
  dims          : {name: float} resolved numeric dimensions
  base_solid    : 'box' | 'cylinder' | 'sphere' | 'cone' | 'extrude' | 'revolve' | 'sweep' | 'mixed'
  base_dims     : list[float]  args of the first base solid call (best-effort)
  op_counts     : {op_name: count}  histogram of all CadQuery op_name values
  holes         : {'simple': n, 'cbore': n, 'csk': n, 'patterns': n}
  edges         : {'fillet': [radii], 'chamfer': [dists]}
  pockets       : count of cutBlind operations
  extrusions    : count of extrude operations (excluding base)
  revolutions   : count of revolve operations
  multi_body    : True if union/combine count >= 1
  cuts          : count of boolean cut/subtract operations
  custom_profiles: count of moveTo/lineTo/threePointArc sketches
  selectors     : {selector_str: count}  e.g. {">Z": 4, "|Z": 1}
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw"
OUT_DIR = ROOT / "analyzed"

BASE_SOLIDS = {"box", "cylinder", "sphere", "cone", "wedge", "torus"}
HOLE_OPS = {"hole", "cboreHole", "cskHole", "cboreCounterSink"}
EDGE_OPS = {"fillet", "chamfer"}
CUT_OPS = {"cut", "cutBlind", "cutThruAll"}
COMBINE_OPS = {"union", "combine"}
SKETCH_PRIMITIVES = {"moveTo", "lineTo", "threePointArc", "spline", "close"}

SELECTOR_RE = re.compile(r'\.faces\(\s*[\'"]([^\'"]+)[\'"]\s*\)|\.edges\(\s*[\'"]([^\'"]+)[\'"]\s*\)')


def _extract_numeric_constants(tree: ast.AST) -> dict[str, float]:
    """Top-level `x = 1.5` and Measures(x=1.5, ...) -> {name: value}."""
    dims: dict[str, float] = {}
    for node in ast.walk(tree):
        # Top-level: x = literal-or-arith
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _try_eval_numeric(node.value, dims)
            if value is not None:
                dims[node.targets[0].id] = value
        # Measures(name=value, ...) and SimpleNamespace(name=value, ...)
        if isinstance(node, ast.Call):
            func_name = _call_target(node)
            if func_name in ("Measures", "SimpleNamespace"):
                for kw in node.keywords:
                    if kw.arg is None:
                        continue
                    value = _try_eval_numeric(kw.value, dims)
                    if value is not None:
                        dims[kw.arg] = value
    return dims


def _call_target(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _try_eval_numeric(node: ast.AST, env: dict[str, float]) -> float | None:
    try:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = _try_eval_numeric(node.operand, env)
            return -inner if inner is not None else None
        if isinstance(node, ast.BinOp):
            left = _try_eval_numeric(node.left, env)
            right = _try_eval_numeric(node.right, env)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right if right else None
            if isinstance(node.op, ast.Pow):
                return left ** right
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return env.get(node.attr)
    except Exception:
        return None
    return None


def _find_base_solid(tree: ast.AST, ops_list: list[dict], dims: dict[str, float]) -> tuple[str, list[float]]:
    """Identify the first primitive solid call. Returns (op_name, [resolved args])."""
    for op in ops_list:
        name = op.get("op_name", "")
        if name in BASE_SOLIDS:
            args = []
            for arg_str in op.get("args", []):
                # arg_str is either "70.0" or AST repr like "Name(id='width', ...)"
                val = _resolve_arg_str(arg_str, dims)
                if val is not None:
                    args.append(val)
            return name, args
    # Fallback: extrude/revolve treated as base
    for op in ops_list:
        if op.get("op_name") in {"extrude", "revolve"}:
            return op["op_name"], []
    return "mixed", []


_NAME_RE = re.compile(r"Name\(id='([^']+)'")
_CONST_RE = re.compile(r"Constant\(value=([\-0-9eE\.]+)\)")
_ATTR_RE = re.compile(r"attr='([^']+)'")
_BARE_DOTTED_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_BARE_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


def _resolve_arg_str(arg_str: str, dims: dict[str, float]) -> float | None:
    """Best-effort numeric resolution of an arg string from ops_json."""
    s = arg_str.strip()
    # Plain numeric
    try:
        return float(s)
    except ValueError:
        pass
    # Bare identifier: width
    if _BARE_IDENT_RE.match(s) and s in dims:
        return dims[s]
    # Bare dotted: m.plate_width  (use last segment)
    if _BARE_DOTTED_RE.match(s):
        last = s.rsplit(".", 1)[-1]
        if last in dims:
            return dims[last]
    # Try Python eval on simple arithmetic of dims (e.g. "width / 2.0", "m.foo + 1")
    try:
        from types import SimpleNamespace
        env = dict(dims)
        env["m"] = SimpleNamespace(**dims)
        env["__builtins__"] = {}
        val = eval(s, env)  # noqa: S307 - sandboxed env
        if isinstance(val, (int, float)):
            return float(val)
    except Exception:
        pass
    # AST-repr fallback patterns
    m = _NAME_RE.search(s)
    if m and m.group(1) in dims:
        return dims[m.group(1)]
    m = _ATTR_RE.search(s)
    if m and m.group(1) in dims:
        return dims[m.group(1)]
    m = _CONST_RE.search(s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _selectors_from_code(code: str) -> Counter:
    sels: Counter = Counter()
    for m in SELECTOR_RE.finditer(code):
        token = m.group(1) or m.group(2)
        if token:
            sels[token] += 1
    return sels


def analyze(code: str, ops_json_str: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = ast.parse("")
    try:
        ops_list = json.loads(ops_json_str) if ops_json_str else []
    except Exception:
        ops_list = []

    dims = _extract_numeric_constants(tree)
    base_solid, base_dims = _find_base_solid(tree, ops_list, dims)

    op_counts: Counter = Counter()
    fillet_radii: list[float] = []
    chamfer_dists: list[float] = []
    holes = {"simple": 0, "cbore": 0, "csk": 0, "patterns": 0}

    for op in ops_list:
        name = op.get("op_name", "")
        if not name:
            continue
        op_counts[name] += 1
        if name == "hole":
            holes["simple"] += 1
        elif name in ("cboreHole", "cboreCounterSink"):
            holes["cbore"] += 1
        elif name == "cskHole":
            holes["csk"] += 1
        elif name == "pushPoints":
            holes["patterns"] += 1
        if name == "fillet":
            for arg_str in op.get("args", []):
                v = _resolve_arg_str(arg_str, dims)
                if v is not None:
                    fillet_radii.append(round(v, 3))
        if name == "chamfer":
            for arg_str in op.get("args", []):
                v = _resolve_arg_str(arg_str, dims)
                if v is not None:
                    chamfer_dists.append(round(v, 3))

    pockets = op_counts.get("cutBlind", 0)
    extrusions = max(0, op_counts.get("extrude", 0) - (1 if base_solid == "extrude" else 0))
    revolutions = max(0, op_counts.get("revolve", 0) - (1 if base_solid == "revolve" else 0))
    multi_body = sum(op_counts.get(op, 0) for op in COMBINE_OPS) >= 1
    cuts = sum(op_counts.get(op, 0) for op in CUT_OPS)
    custom_profiles = sum(op_counts.get(op, 0) for op in SKETCH_PRIMITIVES)
    selectors = _selectors_from_code(code)

    return {
        "dims": {k: round(v, 3) for k, v in dims.items()},
        "base_solid": base_solid,
        "base_dims": [round(d, 3) for d in base_dims],
        "op_counts": dict(op_counts),
        "holes": holes,
        "edges": {
            "fillet": fillet_radii,
            "chamfer": chamfer_dists,
        },
        "pockets": pockets,
        "extrusions": extrusions,
        "revolutions": revolutions,
        "multi_body": multi_body,
        "cuts": cuts,
        "custom_profiles": custom_profiles,
        "selectors": dict(selectors),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    splits = sys.argv[1:] or ["train", "validation", "test"]
    summary = {}
    for split in splits:
        in_path = RAW_DIR / f"{split}.jsonl"
        if not in_path.exists():
            print(f"[{split}] missing {in_path}, skip")
            continue
        out_path = OUT_DIR / f"{split}.jsonl"
        n = 0
        with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                feats = analyze(row["code"], row.get("ops_json", "[]"))
                out = {
                    "uuid": row["uuid"],
                    "split": row["split"],
                    "num_faces": row["num_faces"],
                    "ops_count": row["ops_count"],
                    "score": row["score"],
                    "image_path": row["image_path"],
                    "features": feats,
                }
                fout.write(json.dumps(out, ensure_ascii=False) + "\n")
                n += 1
        summary[split] = n
        print(f"[{split}] analyzed {n} rows -> {out_path}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
