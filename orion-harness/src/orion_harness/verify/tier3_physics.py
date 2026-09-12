"""T3 physics tier (§7.2, §7.3): Gmsh mesh -> CalculiX -> validate.

**Session scope, stated plainly rather than silently:** no CalculiX binary
was reachable in the environment this was built in (no Linux container,
Docker daemon not running) -- see the session report. What is real and
tested here is the part that does not need a live solver: the F3 output
-validation guards, exercised against the *exact* literal stdout text
OF-TR-002 §3 reports it measured (the zero-boundary-condition run's
"Job finished" with a 1.4e10 mm displacement and no error string; the
unrecognized-keyword run's "*WARNING in calinput. Card image cannot be
interpreted"). `run_calculix` itself is real subprocess code, but its
"solver not found" path is the only path exercised in this session's
tests -- that is itself the honest, correct behavior on a machine with no
`ccx` on PATH, not a placeholder.

F3 (measured): CalculiX exited 0 on a model with no boundary conditions
at all (singular system) and on an unrecognized keyword -- in both cases
with no `*ERROR` in stdout. The exit code must never be trusted; every run
is validated by (a) scanning stdout for `*ERROR`/`*WARNING`, promoting an
unrecognized-card warning to an error, and (b) a physical-plausibility
gate on the reported displacement against the model's own bounding-box
diagonal.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import GateResult
from ..registry import register_verifier
from ..runner.errors import TaskOutcome
from .context import VerifyContext

_ERROR_RE = re.compile(r"^\s*\*ERROR\b.*$", re.MULTILINE)
_WARNING_RE = re.compile(r"^\s*\*WARNING\b.*$", re.MULTILINE)
# The exact text CalculiX prints for an unrecognized keyword card (F3,
# measured). A warning matching this is promoted to an error (§3 F3
# implication (b)): the model wrote something the solver could not parse,
# and CalculiX silently solved the rest of the model anyway.
_UNRECOGNIZED_CARD_RE = re.compile(r"Card image cannot be interpreted", re.IGNORECASE)

DEFAULT_PLAUSIBILITY_MULTIPLIER = 10.0  # max displacement must not exceed this x bbox diagonal


@dataclass
class SolverRunResult:
    exit_code: int
    stdout: str
    stderr: str
    frd_path: Path | None
    wall_s: float


def run_calculix(
    deck_path: Path, work_dir: Path, timeout_s: float, binary: str = "ccx"
) -> SolverRunResult:
    """Real subprocess call. Raises TaskOutcome(code='solver_infra_error')
    if the binary is missing -- R3: a missing solver is an infra failure,
    excluded from the denominator, never scored as a model failure."""

    import time

    job_name = deck_path.stem
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [binary, "-i", job_name],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as e:
        raise TaskOutcome(
            code="solver_infra_error", reason=f"solver binary {binary!r} not found: {e}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise TaskOutcome(code="exec_timeout", reason=f"calculix exceeded {timeout_s}s") from e

    wall_s = time.monotonic() - start
    frd_path = work_dir / f"{job_name}.frd"
    return SolverRunResult(
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        frd_path=frd_path if frd_path.exists() else None,
        wall_s=wall_s,
    )


def scan_errors(stdout: str) -> list[str]:
    return _ERROR_RE.findall(stdout)


def scan_warnings(stdout: str) -> list[str]:
    return _WARNING_RE.findall(stdout)


def promoted_errors(stdout: str) -> list[str]:
    """Unrecognized-card warnings promoted to errors (§3 F3)."""

    return [w for w in scan_warnings(stdout) if _UNRECOGNIZED_CARD_RE.search(w)]


@dataclass
class SolverValidation:
    passed: bool
    reason: str | None = None
    evidence: dict = field(default_factory=dict)


def validate_solver_run(
    stdout: str,
    frd_exists: bool,
    max_displacement_mm: float | None,
    bbox_diagonal_mm: float,
    plausibility_multiplier: float = DEFAULT_PLAUSIBILITY_MULTIPLIER,
) -> SolverValidation:
    """F3's guards, composed. Deliberately does not take an exit code --
    the whole point of F3 is that the exit code carries no information
    here (CalculiX returned 0 in both measured failure cases)."""

    if not frd_exists:
        return SolverValidation(passed=False, reason="solver_result_implausible:no .frd produced")

    errors = scan_errors(stdout)
    if errors:
        return SolverValidation(
            passed=False,
            reason=f"solver_result_implausible:*ERROR in stdout: {errors[0]!r}",
            evidence={"errors": errors},
        )

    promoted = promoted_errors(stdout)
    if promoted:
        return SolverValidation(
            passed=False,
            reason=f"solver_result_implausible:unrecognized card promoted to error: {promoted[0]!r}",
            evidence={"promoted_warnings": promoted},
        )

    if max_displacement_mm is None:
        return SolverValidation(
            passed=False,
            reason="solver_result_implausible:no displacement value available to plausibility-check",
        )

    limit = plausibility_multiplier * bbox_diagonal_mm
    if max_displacement_mm > limit:
        return SolverValidation(
            passed=False,
            reason=(
                f"solver_result_implausible:max displacement {max_displacement_mm:g}mm "
                f"exceeds {plausibility_multiplier}x the model's bounding-box diagonal "
                f"({bbox_diagonal_mm:g}mm, limit {limit:g}mm) -- F3: likely missing "
                f"boundary conditions (singular system solved to a huge displacement "
                f"with exit code 0 and no error string)"
            ),
            evidence={
                "max_displacement_mm": max_displacement_mm,
                "bbox_diagonal_mm": bbox_diagonal_mm,
                "limit_mm": limit,
            },
        )

    return SolverValidation(passed=True, evidence={"max_displacement_mm": max_displacement_mm})


@register_verifier("tier3.static", version="1.0.0")
def static_physics_gate(ctx: VerifyContext) -> GateResult:
    """params must include a completed solver run's observables:
    {"stdout": str, "frd_exists": bool, "max_displacement_mm": float|None,
    "bbox_diagonal_mm": float}. This verifier does not call the solver
    itself -- that is orchestration (see module docstring re: session
    scope) -- it only applies F3's validation to whatever run the caller
    already produced, which is the part of this tier that is real and
    tested without a live CalculiX binary."""

    required = ("stdout", "frd_exists", "bbox_diagonal_mm")
    missing = [k for k in required if k not in ctx.params]
    if missing:
        return GateResult(
            name="static_physics",
            passed=False,
            reason=f"static_physics:missing params {missing}",
        )

    validation = validate_solver_run(
        stdout=ctx.params["stdout"],
        frd_exists=ctx.params["frd_exists"],
        max_displacement_mm=ctx.params.get("max_displacement_mm"),
        bbox_diagonal_mm=ctx.params["bbox_diagonal_mm"],
        plausibility_multiplier=ctx.params.get(
            "plausibility_multiplier", DEFAULT_PLAUSIBILITY_MULTIPLIER
        ),
    )
    return GateResult(
        name="static_physics",
        passed=validation.passed,
        reason=validation.reason,
        evidence=validation.evidence,
    )
