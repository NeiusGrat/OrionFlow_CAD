"""Failure taxonomy (§6.3). Closed list -- add codes by PR, not ad hoc.

`invalid` = the submission's fault, counts in the denominator, scores 0.
`error`   = the harness/infra's fault, excluded from the denominator.
The distinction is the entire point of R3: a flaky solver must never look
like a weak model.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ErrorCode, Status

CODE_STATUS: dict[ErrorCode, Status] = {
    "model_api_error": "error",
    "model_refusal": "invalid",
    "parse_error": "invalid",
    "exec_timeout": "timeout",
    "exec_crash": "invalid",
    "gate_failed": "scored",
    "solver_infra_error": "error",
    "solver_result_implausible": "invalid",
    "harness_bug": "error",
}

COUNTED_IN_DENOMINATOR: dict[ErrorCode, bool] = {
    "model_api_error": False,
    "model_refusal": True,
    "parse_error": True,
    "exec_timeout": True,
    "exec_crash": True,
    "gate_failed": True,
    "solver_infra_error": False,
    "solver_result_implausible": True,
    "harness_bug": False,
}


@dataclass
class TaskOutcome(Exception):
    """Raised by execute/* and caught by the runner to classify a Result.

    Not a bug report -- a controlled, typed way for execution code to say
    "this submission failed, and here is which of the closed failure codes
    applies", so the runner never has to guess from an exception's type.
    """

    code: ErrorCode
    reason: str
    evidence: dict | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, f"{self.code}: {self.reason}")

    @property
    def status(self) -> Status:
        return CODE_STATUS[self.code]


class HarnessBug(TaskOutcome):
    """Use for an internal assertion failure -- must page you, per §6.3."""

    def __init__(self, reason: str, evidence: dict | None = None):
        super().__init__(code="harness_bug", reason=reason, evidence=evidence)
