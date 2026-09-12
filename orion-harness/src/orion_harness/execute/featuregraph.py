"""FeatureGraph dict -> build123d shape, via the product's own compiler.

R1: one verifier implementation. The harness does not reimplement CAD
compilation -- it calls `app.compilers.build123d_compiler.Build123dCompiler`,
the same compiler `/generate` and `/regenerate` use in production.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..runner.errors import TaskOutcome


def build_featuregraph(graph: dict):
    try:
        from app.compilers.build123d_compiler import Build123dCompiler, CompilationError
        from app.domain.feature_graph import FeatureGraph
    except ImportError as e:
        raise TaskOutcome(
            code="solver_infra_error", reason=f"product compiler unavailable: {e}"
        ) from e

    try:
        cfg = FeatureGraph.model_validate(graph)
    except Exception as e:
        raise TaskOutcome(code="parse_error", reason=f"invalid FeatureGraph: {e}") from e

    with tempfile.TemporaryDirectory(prefix="orion_harness_fg_") as scratch:
        compiler = Build123dCompiler(output_dir=Path(scratch))
        try:
            paths = compiler.compile(cfg, job_id="submission")
        except CompilationError as e:
            raise TaskOutcome(code="exec_crash", reason=str(e)) from e
        except BaseException as e:
            raise TaskOutcome(code="exec_crash", reason=f"{type(e).__name__}: {e}") from e

        from build123d import import_step

        return import_step(str(paths["step"]))
