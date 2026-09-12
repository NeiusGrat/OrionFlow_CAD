"""OFL source -> build123d shape.

Runs inside an already-isolated worker process (runner/pool.py); this
module assumes sandboxing (network block, memory cap, timeout) is someone
else's job and only does execution + result classification.
"""

from __future__ import annotations

import ast

from ..runner.errors import TaskOutcome


def parse_ofl(source: str) -> ast.AST:
    try:
        return ast.parse(source, filename="<submission>")
    except SyntaxError as e:
        raise TaskOutcome(
            code="parse_error", reason=f"OFL source does not parse: {e}"
        ) from e


def build_ofl(source: str):
    """Execute OFL source and return the resulting build123d solid shape
    (the `._solid` inside the module-level `part` variable, by OFL
    convention -- see orionflow_ofl/examples/*.py)."""

    parse_ofl(source)  # fail fast, before paying for exec

    namespace: dict = {"__name__": "__orion_harness_submission__"}
    try:
        exec(compile(source, "<submission>", "exec"), namespace)
    except TaskOutcome:
        raise
    except BaseException as e:
        # Includes OCCT ValueErrors surfaced through build123d (F6), e.g. an
        # infeasible fillet radius.
        raise TaskOutcome(code="exec_crash", reason=f"{type(e).__name__}: {e}") from e

    part_obj = namespace.get("part")
    if part_obj is None:
        raise TaskOutcome(
            code="parse_error",
            reason="OFL submission did not bind a module-level `part` variable",
        )

    from orionflow_ofl.part import Part as OFLPart

    if not isinstance(part_obj, OFLPart):
        raise TaskOutcome(
            code="parse_error",
            reason=f"`part` is {type(part_obj).__name__}, expected orionflow_ofl.Part",
        )

    return part_obj._solid
