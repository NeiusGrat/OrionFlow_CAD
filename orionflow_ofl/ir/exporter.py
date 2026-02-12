"""Offline AST → ofl_ir_v1 JSON exporter for dataset generation. Not runtime."""

import ast, json, sys
from pathlib import Path


def _val(node, vs):
    """Resolve an AST node to a Python literal using known *vs* (variables)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _val(node.operand, vs)
        return -v if isinstance(v, (int, float)) else None
    if isinstance(node, ast.Name) and node.id in vs:
        return vs[node.id]
    if isinstance(node, ast.Attribute):
        p = _name(node.value)
        full = f"{p}.{node.attr}" if p else None
        return vs.get(full)
    if isinstance(node, ast.BinOp):
        l, r = _val(node.left, vs), _val(node.right, vs)
        if l is not None and r is not None:
            ops = {ast.Add: l + r, ast.Sub: l - r, ast.Mult: l * r, ast.Div: l / r}
            return ops.get(type(node.op))
    return None


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        p = _name(node.value)
        return f"{p}.{node.attr}" if p else None
    return None


def _chain(node, vs):
    """Extract [(method, {args}), ...] from a chained call AST node."""
    if not isinstance(node, ast.Call):
        return []
    func = node.func
    kw = {f"_p{i}": _val(a, vs) for i, a in enumerate(node.args)}
    kw.update({k.arg: _val(k.value, vs) for k in node.keywords})
    if isinstance(func, ast.Attribute):
        return _chain(func.value, vs) + [(func.attr, kw)]
    if isinstance(func, ast.Name):
        return [(func.id, kw)]
    return []


def _sketch_op(ch, var):
    op = {"type": "sketch_extrude", "var": var}
    for m, kw in ch:
        if m == "Sketch":
            op["plane"] = "XY"
        elif m == "rect":
            op.update(profile="rect", width=kw.get("_p0"), height=kw.get("_p1"))
        elif m == "rounded_rect":
            op.update(profile="rounded_rect", width=kw.get("_p0"),
                      height=kw.get("_p1"), corner_radius=kw.get("_p2"))
        elif m == "circle":
            op.update(profile="circle", diameter=kw.get("_p0"))
        elif m == "extrude":
            op["thickness"] = kw.get("_p0")
    return op


def _hole_op(ch, target):
    op = {"type": "hole_subtract", "target": target}
    pts = []
    for m, kw in ch:
        if m == "Hole":
            op["diameter"] = kw.get("_p0")
        elif m == "at":
            pts.append({"x": kw.get("_p0"), "y": kw.get("_p1")})
        elif m == "at_circular":
            op["circular"] = {"radius": kw.get("_p0"),
                              "count": kw.get("count", kw.get("_p1")),
                              "start_angle": kw.get("start_angle", kw.get("_p2", 0))}
        elif m == "through":
            op["depth_mode"] = "through"
        elif m == "to_depth":
            op.update(depth_mode="blind", depth=kw.get("_p0"))
        elif m == "label":
            op["label"] = kw.get("_p0")
    if pts:
        op["positions"] = pts
    return op


def parse_ofl_source(source: str) -> dict:
    tree = ast.parse(source)
    vs, ops = {}, []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                v = _val(node.value, vs)
                if v is not None and isinstance(v, (int, float)):
                    vs[t.id] = v
                    continue
                ch = _chain(node.value, vs)
                if ch and ch[0][0] == "Sketch":
                    ops.append(_sketch_op(ch, t.id))
                    continue
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Sub):
            ch = _chain(node.value, vs)
            if ch and ch[0][0] == "Hole":
                ops.append(_hole_op(ch, _name(node.target)))
                continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if _name(node.value.func) == "export" and len(node.value.args) >= 2:
                a = node.value.args
                ops.append({"type": "export", "target": _name(a[0]),
                            "path": a[1].value if isinstance(a[1], ast.Constant) else None})
    return {"version": "ofl_ir_v1", "variables": vs, "operations": ops}


def export_ir(source_path: str) -> str:
    src = Path(source_path).read_text(encoding="utf-8")
    return json.dumps(parse_ofl_source(src), indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m orionflow_ofl.ir.exporter <script.py>", file=sys.stderr)
        sys.exit(1)
    print(export_ir(sys.argv[1]))
