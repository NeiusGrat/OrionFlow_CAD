"""Phase 5 v1: CadQuery -> build123d transpiler (clean subset, AST-based).

Supported patterns:
  * Single-statement: result = cq.Workplane("XY").box(w, d, h)...
  * Two-body with subtraction: a = ...; b = ...; result = a.cut(b)
  * Two-body with union:       a = ...; b = ...; result = a.union(b)
  * box / cylinder bases
  * hole / cboreHole / cskHole (treated as simple holes)
  * pushPoints([...]) location arrays
  * fillet / chamfer with simple-or-no edge selectors
  * translate for secondary bodies
  * cutBlind for symmetric pockets (rect at center)

Out of scope (skipped with reason):
  * moveTo/lineTo/polyline/spline/threePointArc/radiusArc custom profiles
  * revolve / sweep / loft / shell
  * complex face selectors (e.g. ">Z and <Y")
  * three or more body composition
  * for-loops, comprehensions, conditionals

Output: build123d code using BuildPart context manager + algebraic Mode.
Each transpilation is wrapped with `result = part.part` for downstream use.

Run:
    python phase5_transpile.py [splits...]   -> writes b123d/<split>.jsonl
"""
from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "raw"
OUT_DIR = ROOT / "b123d"

# --- supported ops -----------------------------------------------------------

SIMPLE_HOLE_OPS = {"hole", "cboreHole", "cskHole"}
EDGE_OPS = {"fillet", "chamfer"}
BASE_SOLIDS = {"box", "cylinder"}
SKIP_PROFILE_OPS = {"moveTo", "lineTo", "threePointArc", "spline", "polyline",
                    "polygon", "radiusArc", "sagittaArc", "ellipse"}
SKIP_COMPLEX_OPS = {"revolve", "sweep", "loft", "shell", "transformed", "mirror", "rotate"}


# --- AST helpers -------------------------------------------------------------

def _is_str_const(node: ast.AST, value: str | None = None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return value is None or node.value == value
    return False


def _attr_chain(node: ast.AST) -> list[ast.AST]:
    """Flatten a fluent chain back to a list of Call nodes (outermost last)."""
    chain: list[ast.AST] = []
    current = node
    while isinstance(current, ast.Call):
        chain.append(current)
        if isinstance(current.func, ast.Attribute):
            current = current.func.value
        else:
            break
    chain.reverse()
    return chain


def _root_call_target(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        # cq.Workplane(...) -> attr='Workplane', value=Name('cq')
        if isinstance(f.value, ast.Name):
            return f"{f.value.id}.{f.attr}"
        # foo.bar.Baz(...) -> 'bar.Baz' (strip outer)
        if isinstance(f.value, ast.Attribute) and isinstance(f.value.value, ast.Name):
            return f"{f.value.attr}.{f.attr}"
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _method_name(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


# --- numeric resolution / formatting -----------------------------------------

class DimEnv:
    """Resolves Name and m.attr references against a dim dictionary."""

    def __init__(self, dims: dict[str, float]):
        self.dims = dims

    def to_source(self, node: ast.AST) -> str | None:
        """Return a build123d-source-friendly Python expression for `node`,
        using bare variable names. Returns None on failure."""
        try:
            return ast.unparse(self._rewrite(node))
        except Exception:
            return None

    def _rewrite(self, node: ast.AST) -> ast.AST:
        if isinstance(node, ast.Constant):
            return node
        if isinstance(node, ast.Name):
            if node.id in self.dims or node.id == "math":
                return node
            raise ValueError(f"unknown name: {node.id}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            # m.foo -> foo
            if node.attr in self.dims:
                return ast.Name(id=node.attr, ctx=ast.Load())
            # math.pi etc — keep as-is
            if node.value.id == "math":
                return node
            raise ValueError(f"unknown attr: {node.value.id}.{node.attr}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return ast.UnaryOp(op=node.op, operand=self._rewrite(node.operand))
        if isinstance(node, ast.BinOp):
            return ast.BinOp(
                left=self._rewrite(node.left),
                op=node.op,
                right=self._rewrite(node.right),
            )
        if isinstance(node, ast.Tuple):
            return ast.Tuple(
                elts=[self._rewrite(e) for e in node.elts],
                ctx=ast.Load(),
            )
        if isinstance(node, ast.List):
            return ast.List(
                elts=[self._rewrite(e) for e in node.elts],
                ctx=ast.Load(),
            )
        if isinstance(node, ast.Call):
            # math.tan, math.radians, etc.
            return node
        raise ValueError(f"cannot rewrite node: {type(node).__name__}")


def _extract_dims(tree: ast.Module) -> dict[str, float]:
    """Top-level numeric assigns + Measures(...)/SimpleNamespace(...) kwargs."""
    dims: dict[str, float] = {}

    def _eval(node: ast.AST) -> float | None:
        try:
            v = ast.literal_eval(node)
            if isinstance(v, (int, float)):
                return float(v)
        except Exception:
            pass
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = _eval(node.operand)
            return -inner if inner is not None else None
        if isinstance(node, ast.BinOp):
            l = _eval(node.left)
            r = _eval(node.right)
            if l is None or r is None:
                return None
            if isinstance(node.op, ast.Add): return l + r
            if isinstance(node.op, ast.Sub): return l - r
            if isinstance(node.op, ast.Mult): return l * r
            if isinstance(node.op, ast.Div) and r != 0: return l / r
        if isinstance(node, ast.Name) and node.id in dims:
            return dims[node.id]
        if isinstance(node, ast.Attribute) and node.attr in dims:
            return dims[node.attr]
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = _eval(node.value)
            if v is not None:
                dims[node.targets[0].id] = v
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target_name = node.targets[0].id if (
                len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            ) else None
            ftgt = _root_call_target(node.value)
            if ftgt in ("Measures", "SimpleNamespace") or _method_name(node.value) in ("Measures", "SimpleNamespace"):
                for kw in node.value.keywords:
                    if kw.arg is None:
                        continue
                    val = _eval(kw.value)
                    if val is not None:
                        dims[kw.arg] = val
    return dims


# --- transpile model ---------------------------------------------------------

@dataclass
class HoleSpec:
    diameter_src: str
    locations: list[str] = field(default_factory=list)  # [(x, y), ...] python tuple sources


@dataclass
class PocketSpec:
    """Subtractive rectangular pocket cut from a face."""
    width_src: str
    height_src: str
    depth_src: str
    face_sel: str   # ">Z", "<Z", ">X", etc.
    center_x_src: str = "0"
    center_y_src: str = "0"
    through: bool = False  # True for cutThruAll


@dataclass
class CircularPocketSpec:
    """Subtractive circular pocket cut from a face."""
    radius_src: str
    depth_src: str
    face_sel: str
    center_x_src: str = "0"
    center_y_src: str = "0"
    through: bool = False


@dataclass
class EdgeOpSpec:
    value_src: str
    selector: str | None = None  # raw CadQuery selector e.g. "|Z", ">Z"


@dataclass
class Body:
    """A single base solid plus its post-ops, in order."""
    name: str = ""
    base_op: str = ""           # 'box' | 'cylinder'
    base_args: list[str] = field(default_factory=list)
    translate: str | None = None  # source for (x, y, z)
    centered_xy: bool = True      # whether base is centered in XY (CadQuery default)
    centered_z: bool = True       # whether base is centered in Z
    holes: list[HoleSpec] = field(default_factory=list)
    pockets: list[PocketSpec | CircularPocketSpec] = field(default_factory=list)
    fillets: list[EdgeOpSpec] = field(default_factory=list)
    chamfers: list[EdgeOpSpec] = field(default_factory=list)


@dataclass
class Composition:
    primary: Body | None = None
    operands: list[tuple[str, Body]] = field(default_factory=list)  # (op, body) where op in {add, sub}


class TranspileError(Exception):
    pass


def _chain_root_name(call: ast.Call) -> str | None:
    """If chain root is a bare Name (continuation chain), return that name."""
    chain = _attr_chain(call)
    if not chain:
        return None
    root = chain[0]
    # Root is a Call. The function being called could be a method on a Name.
    if isinstance(root.func, ast.Attribute) and isinstance(root.func.value, ast.Name):
        # E.g. base.faces(">Z") - root call is base.faces(...).
        # We treat 'base' as the continuation source.
        return root.func.value.id
    return None


def _parse_chain_to_body(
    call: ast.Call, env: DimEnv, name: str = "", existing: Body | None = None,
) -> Body:
    """Parse a fluent CadQuery chain.

    If `existing` is provided, the chain is treated as a CONTINUATION of that
    body (no new base solid expected). Otherwise the chain MUST start at
    cq.Workplane(...).
    """
    body = existing if existing is not None else Body(name=name)
    chain = _attr_chain(call)
    if not chain:
        raise TranspileError("empty chain")

    if existing is None:
        root = chain[0]
        if _root_call_target(root) not in ("cq.Workplane", "Workplane"):
            raise TranspileError(f"chain root not Workplane: {_root_call_target(root)}")

        plane = "XY"
        if root.args and _is_str_const(root.args[0]):
            plane = root.args[0].value
            if plane.upper() not in ("XY", "XZ", "YZ"):
                raise TranspileError(f"unsupported plane: {plane}")
        start_idx = 1
    else:
        # Continuation chain: chain[0] is the FIRST method call on the existing body.
        # We start consuming from index 0 — but root call's method is e.g. faces().
        start_idx = 0
    body_plane = "XY"

    # Pending sketch state for rect+extrude / circle+extrude patterns
    pending_sketch: tuple[str, list[str]] | None = None
    # Current face selector and center for sketch-on-face operations
    current_face_sel: str | None = None
    current_center_x: str = "0"
    current_center_y: str = "0"
    # Most-recent edges selector for fillet/chamfer
    current_edge_sel: str | None = None

    i = start_idx
    while i < len(chain):
        c = chain[i]
        m = _method_name(c)

        if m in SKIP_PROFILE_OPS:
            raise TranspileError(f"custom profile op: {m}")
        if m in SKIP_COMPLEX_OPS:
            raise TranspileError(f"complex op: {m}")

        if m in BASE_SOLIDS and not body.base_op:
            body.base_op = m
            args = []
            for a in c.args:
                src = env.to_source(a)
                if src is None:
                    raise TranspileError(f"unresolvable {m} arg")
                args.append(src)
            body.base_args = args
            i += 1
            continue

        # rect(w, h) sets pending sketch
        if m == "rect" and len(c.args) >= 2:
            args = []
            for a in c.args[:2]:
                src = env.to_source(a)
                if src is None:
                    raise TranspileError("unresolvable rect arg")
                args.append(src)
            pending_sketch = ("rect", args)
            i += 1
            continue

        # circle(r) sets pending sketch
        if m == "circle" and len(c.args) >= 1:
            src = env.to_source(c.args[0])
            if src is None:
                raise TranspileError("unresolvable circle arg")
            pending_sketch = ("circle", [src])
            i += 1
            continue

        # extrude(h) consumes pending sketch -> base or hole-pocket
        if m == "extrude" and len(c.args) >= 1:
            if pending_sketch is None:
                raise TranspileError("extrude without pending sketch")
            h_src = env.to_source(c.args[0])
            if h_src is None:
                raise TranspileError("unresolvable extrude arg")
            kind, sk_args = pending_sketch
            if not body.base_op:
                # First extrude becomes the base
                if kind == "rect":
                    body.base_op = "box"
                    body.base_args = [sk_args[0], sk_args[1], h_src]
                else:  # circle
                    body.base_op = "cylinder"
                    body.base_args = [sk_args[0], h_src]
                pending_sketch = None
                i += 1
                continue
            else:
                # Secondary extrude (additive feature) — too complex for v1
                raise TranspileError("multi-extrude single chain")

        # cutBlind / cutThruAll consume pending sketch -> SUBTRACT pocket
        if m in ("cutBlind", "cutThruAll"):
            if pending_sketch is None:
                raise TranspileError(f"{m} without pending sketch")
            if not body.base_op:
                raise TranspileError(f"{m} before base solid")
            face_sel = current_face_sel or ">Z"
            if face_sel not in (">Z", "<Z"):
                # Other faces require complex orientation we don't do in v1.5
                raise TranspileError(f"cut on non-Z face: {face_sel}")
            kind, sk_args = pending_sketch
            if m == "cutBlind":
                if not c.args:
                    raise TranspileError("cutBlind without depth")
                depth_src = env.to_source(c.args[0])
                if depth_src is None:
                    raise TranspileError("unresolvable cutBlind depth")
                # cutBlind(-d) cuts in the negative-Z direction relative to the face.
                # Use abs() in the emitted code so depth is always positive.
                depth_src = f"abs({depth_src})"
                through = False
            else:  # cutThruAll
                # depth must equal base height (we'll emit 'base_height' or actual value)
                if body.base_op == "box" and len(body.base_args) >= 3:
                    depth_src = body.base_args[2]
                else:
                    raise TranspileError("cutThruAll on non-box base")
                through = True

            if kind == "rect":
                body.pockets.append(PocketSpec(
                    width_src=sk_args[0],
                    height_src=sk_args[1],
                    depth_src=depth_src,
                    face_sel=face_sel,
                    center_x_src=current_center_x,
                    center_y_src=current_center_y,
                    through=through,
                ))
            elif kind == "circle":
                body.pockets.append(CircularPocketSpec(
                    radius_src=sk_args[0],
                    depth_src=depth_src,
                    face_sel=face_sel,
                    center_x_src=current_center_x,
                    center_y_src=current_center_y,
                    through=through,
                ))
            pending_sketch = None
            # Reset center but keep face context
            current_center_x = "0"
            current_center_y = "0"
            i += 1
            continue

        if m == "translate":
            if not c.args:
                raise TranspileError("translate without args")
            src = env.to_source(c.args[0])
            if src is None:
                raise TranspileError("unresolvable translate")
            body.translate = src
            i += 1
            continue

        if m == "faces":
            if c.args and _is_str_const(c.args[0]):
                sel = c.args[0].value
                if any(tok in sel for tok in (" and ", " or ", "<<", ">>")):
                    raise TranspileError(f"complex selector: {sel}")
                current_face_sel = sel
                # New face context resets center
                current_center_x = "0"
                current_center_y = "0"
            i += 1
            continue

        if m == "center" and len(c.args) >= 2:
            cx = env.to_source(c.args[0])
            cy = env.to_source(c.args[1])
            if cx is None or cy is None:
                raise TranspileError("unresolvable center args")
            current_center_x = cx
            current_center_y = cy
            i += 1
            continue

        if m == "edges":
            if c.args and _is_str_const(c.args[0]):
                sel = c.args[0].value
                if any(tok in sel for tok in (" and ", " or ", "<<", ">>")):
                    raise TranspileError(f"complex selector: {sel}")
                current_edge_sel = sel
            else:
                current_edge_sel = None
            i += 1
            continue

        if m in ("workplane", "vertices"):
            if c.args and _is_str_const(c.args[0]):
                sel = c.args[0].value
                if any(tok in sel for tok in (" and ", " or ", "<<", ">>")):
                    raise TranspileError(f"complex selector: {sel}")
            i += 1
            continue

        if m == "pushPoints":
            if not c.args:
                raise TranspileError("pushPoints without args")
            arg = c.args[0]
            if not isinstance(arg, ast.List):
                raise TranspileError("pushPoints non-literal list")
            pt_srcs = []
            for elt in arg.elts:
                src = env.to_source(elt)
                if src is None:
                    raise TranspileError("unresolvable pushPoint")
                pt_srcs.append(src)
            # The next op after pushPoints should be a hole-like op
            j = i + 1
            while j < len(chain) and _method_name(chain[j]) in ("workplane", "faces", "edges", "center"):
                j += 1
            if j >= len(chain) or _method_name(chain[j]) not in SIMPLE_HOLE_OPS:
                raise TranspileError("pushPoints not followed by hole")
            hole_call = chain[j]
            if not hole_call.args:
                raise TranspileError("hole without diameter")
            d_src = env.to_source(hole_call.args[0])
            if d_src is None:
                raise TranspileError("unresolvable hole diameter")
            body.holes.append(HoleSpec(diameter_src=d_src, locations=pt_srcs))
            i = j + 1
            continue

        if m in SIMPLE_HOLE_OPS:
            if not c.args:
                raise TranspileError("hole without diameter")
            d_src = env.to_source(c.args[0])
            if d_src is None:
                raise TranspileError("unresolvable hole diameter")
            body.holes.append(HoleSpec(diameter_src=d_src, locations=["(0, 0)"]))
            i += 1
            continue

        if m == "fillet":
            if not c.args:
                raise TranspileError("fillet without arg")
            src = env.to_source(c.args[0])
            if src is None:
                raise TranspileError("unresolvable fillet")
            body.fillets.append(EdgeOpSpec(value_src=src, selector=current_edge_sel))
            i += 1
            continue

        if m == "chamfer":
            if not c.args:
                raise TranspileError("chamfer without arg")
            src = env.to_source(c.args[0])
            if src is None:
                raise TranspileError("unresolvable chamfer")
            body.chamfers.append(EdgeOpSpec(value_src=src, selector=current_edge_sel))
            i += 1
            continue

        if m in ("union", "cut", "intersect", "combine", "close"):
            # These belong outside a single-body chain
            raise TranspileError(f"unsupported in single-body chain: {m}")

        # Harmless ops we can ignore (metadata, accessors, etc.)
        if m in ("tag", "val", "first", "firstSolid", "newObject", "Workplane",
                 "consolidateWires", "clean", "combine"):
            i += 1
            continue

        raise TranspileError(f"unknown op: {m}")

    if not body.base_op:
        raise TranspileError("no base solid found")
    return body


def _flatten_body(tree: ast.Module) -> list[ast.stmt]:
    """Return the list of statements to walk.

    If the module's last meaningful node is a class with a single build()
    method, or a single FunctionDef returning a Workplane chain, expand its
    body so transpile sees the actual operations.
    """
    stmts: list[ast.stmt] = []
    fn_bodies: list[list[ast.stmt]] = []

    for n in tree.body:
        stmts.append(n)
        if isinstance(n, ast.FunctionDef):
            fn_bodies.append(n.body)
        if isinstance(n, ast.ClassDef):
            for sub in n.body:
                if isinstance(sub, ast.FunctionDef):
                    fn_bodies.append(sub.body)

    # Append all function bodies AFTER top-level so dims/Measures resolve first
    for fb in fn_bodies:
        stmts.extend(fb)
    return stmts


def _parse_program(tree: ast.Module, env: DimEnv) -> Composition:
    """Walk top-level statements, producing a Composition (primary + ops)."""
    comp = Composition()
    bodies: dict[str, Body] = {}
    final_var: str | None = None

    walk_body = _flatten_body(tree)
    for node in walk_body:
        # Handle 'return some_expr' inside function bodies as final assignment
        if isinstance(node, ast.Return) and node.value is not None:
            rhs = node.value
            if isinstance(rhs, ast.Name) and rhs.id in bodies:
                final_var = rhs.id
            continue
        # Now treat the rest as Assign-like statements; the loop body below
        # takes Assign nodes; non-Assigns are skipped.
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id

        rhs = node.value

        # case 1: rhs is a Call -> a body chain
        if isinstance(rhs, ast.Call):
            # 1.0: skip non-CadQuery roots (Measures, SimpleNamespace, math.*, user funcs)
            chain = _attr_chain(rhs)
            if chain:
                root_target = _root_call_target(chain[0])
                cont_root = _chain_root_name(rhs)
                is_cq = root_target in ("cq.Workplane", "Workplane")
                is_continuation = cont_root is not None and cont_root in bodies
                if not is_cq and not is_continuation:
                    # Not a CadQuery operation - skip
                    continue
            m = _method_name(rhs)
            if m in ("cut", "union", "combine") and isinstance(rhs.func, ast.Attribute):
                base_node = rhs.func.value
                base_id = base_node.id if isinstance(base_node, ast.Name) else None
                if base_id and base_id in bodies and rhs.args and isinstance(rhs.args[0], ast.Name):
                    other_name = rhs.args[0].id
                    if other_name in bodies:
                        op = "sub" if m == "cut" else "add"
                        if comp.primary is None:
                            comp.primary = bodies[base_id]
                        comp.operands.append((op, bodies[other_name]))
                        bodies[name] = comp.primary
                        final_var = name
                        continue
                raise TranspileError("composition base not a known body")

            # 1b: continuation chain - root is a known body name
            cont_name = _chain_root_name(rhs)
            if cont_name and cont_name in bodies:
                existing = bodies[cont_name]
                body = _parse_chain_to_body(rhs, env, name=name, existing=existing)
                bodies[name] = body
                final_var = name
                continue

            # 1c: fresh chain rooted at cq.Workplane
            body = _parse_chain_to_body(rhs, env, name=name)
            bodies[name] = body
            final_var = name
            continue

        # case 2: rhs is a Name (alias)
        if isinstance(rhs, ast.Name) and rhs.id in bodies:
            bodies[name] = bodies[rhs.id]
            final_var = name
            continue

    if final_var is None:
        raise TranspileError("no shape variable found")

    if comp.primary is None:
        comp.primary = bodies[final_var]
    return comp


# --- emission ----------------------------------------------------------------

def _emit_body(body: Body, indent: str = "    ", mode: str = "ADD") -> list[str]:
    """Emit build123d operations to construct a body inside an existing BuildPart."""
    lines: list[str] = []
    loc_block = body.translate
    mode_kw = f", mode=Mode.{mode}" if mode != "ADD" else ""

    if loc_block:
        lines.append(f"{indent}with Locations(Location({loc_block})):")
        sub = indent + "    "
    else:
        sub = indent

    if body.base_op == "box" and len(body.base_args) >= 3:
        w, d, h = body.base_args[0], body.base_args[1], body.base_args[2]
        lines.append(f"{sub}Box({w}, {d}, {h}{mode_kw})")
    elif body.base_op == "cylinder" and len(body.base_args) >= 2:
        r, h = body.base_args[0], body.base_args[1]
        lines.append(f"{sub}Cylinder({r}, {h}{mode_kw})")
    else:
        raise TranspileError(f"emit: unsupported base {body.base_op}")

    return lines


def _emit_program(comp: Composition, dims: dict[str, float]) -> str:
    """Emit a complete build123d Python program."""
    used_dims = sorted(dims.keys())
    lines: list[str] = ["from build123d import *", ""]
    for k in used_dims:
        v = dims[k]
        if abs(v - round(v)) < 1e-9:
            lines.append(f"{k} = {int(round(v))}")
        else:
            lines.append(f"{k} = {v}")
    if used_dims:
        lines.append("")

    lines.append("with BuildPart() as part:")
    # Primary body
    primary = comp.primary
    assert primary is not None
    lines.extend(_emit_body(primary, indent="    ", mode="ADD"))

    # Operands
    for op, body in comp.operands:
        mode = "SUBTRACT" if op == "sub" else "ADD"
        lines.extend(_emit_body(body, indent="    ", mode=mode))

    # Pockets (subtract Box/Cylinder at right Z based on face selector)
    for p in primary.pockets:
        # Compute Z position of the pocket center.
        # CadQuery default centered=(True,True,False) means base Z extends 0..h.
        # build123d Box is centered at origin so it extends -h/2..+h/2.
        # We translated Box up by 0 (no translate) so it's centered.
        # For >Z: top face is at z = base_h/2; pocket extends from top down by depth
        #   pocket_center_z = base_h/2 - depth/2
        # For <Z: bottom face is at z = -base_h/2; pocket extends from bottom up
        #   pocket_center_z = -base_h/2 + depth/2
        if primary.base_op == "box" and len(primary.base_args) >= 3:
            base_h = primary.base_args[2]
        elif primary.base_op == "cylinder" and len(primary.base_args) >= 2:
            base_h = primary.base_args[1]
        else:
            continue  # can't position; skip
        depth = p.depth_src
        if p.face_sel == ">Z":
            z_expr = f"({base_h}) / 2 - ({depth}) / 2"
        else:  # <Z
            z_expr = f"-({base_h}) / 2 + ({depth}) / 2"

        if isinstance(p, PocketSpec):
            w, h_, d = p.width_src, p.height_src, p.depth_src
            lines.append(
                f"    with Locations(({p.center_x_src}, {p.center_y_src}, {z_expr})):"
            )
            lines.append(f"        Box({w}, {h_}, {d}, mode=Mode.SUBTRACT)")
        elif isinstance(p, CircularPocketSpec):
            r, d = p.radius_src, p.depth_src
            lines.append(
                f"    with Locations(({p.center_x_src}, {p.center_y_src}, {z_expr})):"
            )
            lines.append(f"        Cylinder({r}, {d}, mode=Mode.SUBTRACT)")

    # Holes (apply to primary at top face by default)
    for h in primary.holes:
        if len(h.locations) == 1:
            lines.append(f"    with Locations({h.locations[0]}):")
        else:
            lines.append(f"    with Locations({', '.join(h.locations)}):")
        lines.append(f"        Hole(({h.diameter_src}) / 2)")

    # Edge ops on primary
    def _edge_expr(sel: str | None) -> str:
        if not sel:
            return "part.edges()"
        s = sel.strip()
        if s == "|Z":
            return "part.edges().filter_by(Axis.Z)"
        if s == "|X":
            return "part.edges().filter_by(Axis.X)"
        if s == "|Y":
            return "part.edges().filter_by(Axis.Y)"
        if s == ">Z":
            return "part.faces().sort_by(Axis.Z)[-1].edges()"
        if s == "<Z":
            return "part.faces().sort_by(Axis.Z)[0].edges()"
        if s == ">X":
            return "part.faces().sort_by(Axis.X)[-1].edges()"
        if s == "<X":
            return "part.faces().sort_by(Axis.X)[0].edges()"
        if s == ">Y":
            return "part.faces().sort_by(Axis.Y)[-1].edges()"
        if s == "<Y":
            return "part.faces().sort_by(Axis.Y)[0].edges()"
        return "part.edges()"

    for f_op in primary.fillets:
        lines.append(f"    fillet({_edge_expr(f_op.selector)}, radius={f_op.value_src})")
    for c_op in primary.chamfers:
        lines.append(f"    chamfer({_edge_expr(c_op.selector)}, length={c_op.value_src})")

    lines.append("")
    lines.append("result = part.part")
    lines.append("")
    return "\n".join(lines)


# --- top-level transpile -----------------------------------------------------

def transpile(code: str) -> tuple[bool, str, str]:
    """Return (ok, b123d_code_or_empty, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, "", f"syntax_error: {e}"
    try:
        dims = _extract_dims(tree)
        env = DimEnv(dims)
        comp = _parse_program(tree, env)
        out = _emit_program(comp, dims)
        return True, out, ""
    except TranspileError as e:
        return False, "", str(e)
    except Exception as e:
        return False, "", f"internal: {type(e).__name__}: {e}"


# --- main --------------------------------------------------------------------

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
        n_in = n_ok = 0
        reason_hist: dict[str, int] = {}
        with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
            for line in fin:
                row = json.loads(line)
                n_in += 1
                ok, b123d_code, reason = transpile(row["code"])
                rec = {
                    "uuid": row["uuid"],
                    "split": row["split"],
                    "transpile_ok": ok,
                    "reason": reason,
                    "b123d_code": b123d_code,
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if ok:
                    n_ok += 1
                else:
                    bucket = reason.split(":", 1)[0] if ":" in reason else reason
                    reason_hist[bucket] = reason_hist.get(bucket, 0) + 1
        summary[split] = {
            "in": n_in, "ok": n_ok, "rate": round(n_ok / max(1, n_in), 3),
            "top_reasons": dict(sorted(reason_hist.items(), key=lambda kv: -kv[1])[:10]),
        }
        print(f"[{split}] {n_ok}/{n_in} ({100*n_ok/max(1,n_in):.1f}%) -> {out_path}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
