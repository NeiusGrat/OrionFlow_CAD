"""Every way an analysis can fail, as a code the job system can act on.

``retry`` says what a retry could change:
  never     the input itself is the problem (bad file, too big for the plan)
  same      a transient fault; the same worker class may succeed
  larger    the worker ran out of memory or time; a bigger tier may succeed
"""
from __future__ import annotations

FAILURES: dict[str, tuple[str, str]] = {
    # code: (retry, user-facing meaning)
    "INVALID_STEP": ("never", "The file is not a readable STEP file."),
    "CORRUPTED_FILE": ("never", "The file is truncated or damaged."),
    "UNSUPPORTED_FILE": ("never", "This file type is not accepted."),
    "UNSUPPORTED_MESH": ("never", "Every body is a triangulated mesh; no B-rep analysis is possible."),
    "TOO_MANY_FACES": ("never", "The assembly has more faces than the plan allows."),
    "TOO_MANY_PARTS": ("never", "The assembly has more parts than the plan allows."),
    "FILE_TOO_LARGE": ("never", "The file is larger than the plan allows."),
    "GEOMETRY_INVALID": ("never", "No valid solid geometry could be read."),
    "OUTPUT_TOO_LARGE": ("never", "The result exceeds the output size limit."),
    "MEMORY_LIMIT": ("larger", "The analysis exceeded the worker's memory."),
    "TIMEOUT": ("larger", "The analysis exceeded the time limit."),
    "FREECAD_FAILURE": ("same", "The geometry kernel failed unexpectedly."),
    "WORKER_FAILURE": ("same", "The worker stopped unexpectedly."),
    "STORAGE_FAILURE": ("same", "Input or output storage was unavailable."),
}


class AnalysisError(Exception):
    def __init__(self, code: str, message: str = "", stage: str = ""):
        if code not in FAILURES:
            raise ValueError(f"unknown failure code {code}")
        super().__init__(message or FAILURES[code][1])
        self.code = code
        self.stage = stage

    @property
    def retry(self) -> str:
        return FAILURES[self.code][0]

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "stage": self.stage, "retry": self.retry}


def retry_policy(code: str) -> str:
    return FAILURES.get(code, ("same", ""))[0]
