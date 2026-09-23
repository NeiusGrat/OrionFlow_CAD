"""What a check found, and the report that collects it."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: error    the model is wrong or will not load: a simulator rejects it, or
#:          accepts it and computes nonsense (a massless moving body, an
#:          inertia no rigid body can have, a simulation that diverges).
#: warning  physically suspicious: loads and runs, but a number is implausible
#:          (density lighter than foam, inertia 1e6 off its geometry, parts
#:          interpenetrating at rest).
#: info     worth knowing, not a defect.
SEVERITIES = ("error", "warning", "info")


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    where: str = ""
    value: Any = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")


@dataclass
class Report:
    source: str
    format: str                      # "urdf" | "mjcf"
    loaded: bool = False             # compiled by MuJoCo (possibly after a fallback)
    stats: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, severity: str, message: str, where: str = "", value: Any = None) -> None:
        self.findings.append(Finding(code, severity, message, where, value))

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def ok(self) -> bool:
        return self.loaded and self.count("error") == 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        d["errors"] = self.count("error")
        d["warnings"] = self.count("warning")
        return d
