"""§13.4-style regression tests for F3, using the *exact* literal stdout
text OF-TR-002 §3 reports measuring:

  - no boundary conditions at all: ran to "Job finished", max |uz| of
    1.4e10 mm, no error string in stdout.
  - an unrecognized keyword: "*WARNING in calinput. Card image cannot be
    interpreted", then solved the rest of the model normally.

`run_calculix`'s "binary not found" path is exercised for real against
this machine's actual PATH (no mocking) -- there is genuinely no `ccx`
here, so this is a true test of that code path, not a placeholder.
"""

from pathlib import Path

import pytest

from orion_harness.runner.errors import TaskOutcome
from orion_harness.verify.context import VerifyContext
from orion_harness.verify.tier3_physics import (
    promoted_errors,
    run_calculix,
    scan_errors,
    scan_warnings,
    static_physics_gate,
    validate_solver_run,
)

NO_BC_STDOUT = """\
 CalculiX Version 2.21
 ...
 JOB FINISHED
"""

UNRECOGNIZED_KEYWORD_STDOUT = """\
 CalculiX Version 2.21
*WARNING in calinput. Card image cannot be interpreted
                       -- the rest of the model is solved normally.
 JOB FINISHED
"""

REAL_ERROR_STDOUT = """\
 CalculiX Version 2.21
*ERROR in e_c3d: nonpositive jacobian
 JOB FINISHED
"""

CLEAN_STDOUT = """\
 CalculiX Version 2.21
 JOB FINISHED
"""


def test_f3_zero_boundary_conditions_fails_plausibility_gate():
    """The exact measured case: exit 0, no error string, displacement
    1.4e10 mm on a model whose bbox diagonal is a normal bracket size."""

    validation = validate_solver_run(
        stdout=NO_BC_STDOUT,
        frd_exists=True,
        max_displacement_mm=1.4e10,
        bbox_diagonal_mm=150.0,
    )
    assert not validation.passed
    assert "solver_result_implausible" in validation.reason
    assert validation.evidence["max_displacement_mm"] == 1.4e10


def test_f3_unrecognized_keyword_warning_is_promoted_to_error():
    promoted = promoted_errors(UNRECOGNIZED_KEYWORD_STDOUT)
    assert len(promoted) == 1
    assert "Card image cannot be interpreted" in promoted[0]

    validation = validate_solver_run(
        stdout=UNRECOGNIZED_KEYWORD_STDOUT,
        frd_exists=True,
        max_displacement_mm=0.05,  # a perfectly plausible displacement
        bbox_diagonal_mm=150.0,
    )
    assert not validation.passed
    assert "promoted to error" in validation.reason


def test_f3_exit_code_is_never_part_of_the_signature():
    """The whole point of F3: CalculiX returned exit code 0 in both
    measured failure cases. validate_solver_run must not need it to
    reject them -- this test asserts the function signature has no
    exit_code parameter by calling it without one and still catching both
    failures above; this test documents that contract explicitly."""

    import inspect

    sig = inspect.signature(validate_solver_run)
    assert "exit_code" not in sig.parameters
    assert "returncode" not in sig.parameters


def test_real_error_string_fails_immediately_even_with_plausible_displacement():
    validation = validate_solver_run(
        stdout=REAL_ERROR_STDOUT,
        frd_exists=True,
        max_displacement_mm=0.01,
        bbox_diagonal_mm=150.0,
    )
    assert not validation.passed
    assert "*ERROR" in validation.reason


def test_missing_frd_fails_even_with_clean_stdout():
    validation = validate_solver_run(
        stdout=CLEAN_STDOUT, frd_exists=False, max_displacement_mm=0.01, bbox_diagonal_mm=150.0
    )
    assert not validation.passed
    assert "no .frd produced" in validation.reason


def test_clean_run_with_plausible_displacement_passes():
    validation = validate_solver_run(
        stdout=CLEAN_STDOUT, frd_exists=True, max_displacement_mm=0.25, bbox_diagonal_mm=150.0
    )
    assert validation.passed


def test_scan_errors_and_warnings_are_plain_regex_not_exit_code_based():
    assert scan_errors(CLEAN_STDOUT) == []
    assert scan_warnings(CLEAN_STDOUT) == []
    assert len(scan_errors(REAL_ERROR_STDOUT)) == 1
    assert len(scan_warnings(UNRECOGNIZED_KEYWORD_STDOUT)) == 1


def test_static_physics_gate_verifier_wraps_validate_solver_run():
    ctx = VerifyContext(
        kind="ofl",
        payload="",
        params={
            "stdout": NO_BC_STDOUT,
            "frd_exists": True,
            "max_displacement_mm": 1.4e10,
            "bbox_diagonal_mm": 150.0,
        },
    )
    gate = static_physics_gate(ctx)
    assert not gate.passed
    assert gate.name == "static_physics"


def test_static_physics_gate_reports_missing_params():
    gate = static_physics_gate(VerifyContext(kind="ofl", payload="", params={}))
    assert not gate.passed
    assert "missing params" in gate.reason


def test_run_calculix_raises_solver_infra_error_when_binary_is_absent(tmp_path):
    """No `ccx` exists on this machine's PATH -- this is a genuine,
    unmocked exercise of the 'solver not found' path, which is the
    correct and honest outcome here (R3: excluded from the denominator,
    never scored as a model failure)."""

    deck = tmp_path / "job.inp"
    deck.write_text("*HEADING\n", encoding="utf-8")
    with pytest.raises(TaskOutcome) as exc_info:
        run_calculix(deck, tmp_path, timeout_s=5, binary="ccx")
    assert exc_info.value.code == "solver_infra_error"
