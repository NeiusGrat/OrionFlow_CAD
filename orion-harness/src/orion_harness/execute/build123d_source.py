"""Raw build123d source -> build123d shape.

Distinct from execute/ofl.py: a `build123d` submission binds `part`
directly to a build123d Shape/Solid/Compound (no orionflow_ofl.Part
wrapper, no OFL safety nets like the disconnected-union guard). Used by
the feature_coverage family (§8.3) to exercise build123d features --
fillet, chamfer, pattern, mirror, loft -- that OFL's own public API does
not expose a method for.
"""

from __future__ import annotations

import ast

from build123d import Shape

from ..runner.errors import TaskOutcome


def parse_build123d(source: str) -> ast.AST:
    try:
        return ast.parse(source, filename="<submission>")
    except SyntaxError as e:
        raise TaskOutcome(
            code="parse_error", reason=f"build123d source does not parse: {e}"
        ) from e


def build_build123d(source: str):
    parse_build123d(source)

    namespace: dict = {"__name__": "__orion_harness_submission__"}
    try:
        exec(compile(source, "<submission>", "exec"), namespace)
    except TaskOutcome:
        raise
    except BaseException as e:
        raise TaskOutcome(code="exec_crash", reason=f"{type(e).__name__}: {e}") from e

    part_obj = namespace.get("part")
    if part_obj is None:
        raise TaskOutcome(
            code="parse_error",
            reason="build123d submission did not bind a module-level `part` variable",
        )
    if not isinstance(part_obj, Shape):
        raise TaskOutcome(
            code="parse_error",
            reason=f"`part` is {type(part_obj).__name__}, expected a build123d Shape",
        )
    return part_obj
