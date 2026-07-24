"""Safe arithmetic expressions over named blueprint variables.

Every dimensional number in a blueprint's feature graph is a *string* in this
language, never a bare literal — that is what makes "all dimensions derived
from variables" machine-checkable instead of a prompt-time hope.

AST-whitelist evaluation: names, numbers, + - * / // % **, unary +-, and the
function/constant table below. No attributes, no subscripts, no lambdas — a
blueprint that needs more than this is hiding logic that belongs in the
design_plan.
"""

from __future__ import annotations

import ast
import math
from typing import Any, Iterable

FUNCTIONS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "radians": math.radians, "degrees": math.degrees,
    "abs": abs, "min": min, "max": max,
    "floor": math.floor, "ceil": math.ceil, "round": round,
}
CONSTANTS = {"pi": math.pi, "tau": math.tau}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                   ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


class ExprError(ValueError):
    """Malformed, unsafe, or unresolvable blueprint expression."""


def _check(node: ast.AST, variables: dict) -> None:
    if isinstance(node, ast.Expression):
        _check(node.body, variables)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExprError(f"operator {type(node.op).__name__} not allowed")
        _check(node.left, variables)
        _check(node.right, variables)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY):
            raise ExprError(f"unary {type(node.op).__name__} not allowed")
        _check(node.operand, variables)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError("only calls to the whitelisted math functions")
        if node.keywords:
            raise ExprError("keyword arguments not allowed")
        for a in node.args:
            _check(a, variables)
    elif isinstance(node, ast.Name):
        if node.id not in variables and node.id not in CONSTANTS:
            raise ExprError(f"unknown name {node.id!r}")
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ExprError(f"literal {node.value!r} is not a number")
    else:
        raise ExprError(f"{type(node).__name__} not allowed")


def evaluate(expr: str, variables: dict[str, float]) -> float:
    """Evaluate ``expr`` against ``variables``. Raises ExprError, never eval()s."""
    if isinstance(expr, bool):  # bool is an int subclass; refuse the footgun
        raise ExprError("boolean is not an arithmetic expression")
    if isinstance(expr, (int, float)):
        # Bare numbers are accepted by the evaluator (the CHECKER is what
        # forbids them in blueprints) so tests and internal callers can pass
        # already-resolved values through one code path.
        return float(expr)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error in {expr!r}: {e}") from None
    _check(tree, variables)
    scope = {**CONSTANTS, **FUNCTIONS, **variables}
    return float(eval(compile(tree, "<blueprint>", "eval"), {"__builtins__": {}}, scope))  # noqa: S307 - AST-whitelisted above


def names(expr: str) -> set[str]:
    """Variable names referenced by ``expr`` (functions/constants excluded)."""
    if isinstance(expr, (int, float)):
        return set()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error in {expr!r}: {e}") from None
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in FUNCTIONS \
                and node.id not in CONSTANTS:
            out.add(node.id)
    return out


def literals(expr: str) -> list[float]:
    """Numeric literals appearing inside ``expr`` (for the magic-number audit)."""
    if isinstance(expr, (int, float)):
        return [float(expr)]
    tree = ast.parse(expr, mode="eval")
    return [float(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))]


def all_names(exprs: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for e in exprs:
        if isinstance(e, str):
            out |= names(e)
    return out
