"""Check engine: the Finding schema, the Check protocol, the registry and the runner.

Rules the engine enforces, so no check can break them by accident:

* **Every finding has evidence.** At least one evidence object (instance,
  part, feature, contact, measurement, file). A finding without it is a bug
  in the check and raises.
* **Deterministic checks state measured and expected.** A pass/fail claim
  without both numbers is refused.
* **AI is marked.** Findings with ``provenance`` ``ai_reading`` /
  ``ai_inference`` may only come from ``kind == "ai_assisted"`` checks.
* **Missing input is ``not_run``, never a pass.** A check lists what it
  ``requires`` from the Model Graph; when any of it is empty the engine
  records ``not_run`` with the reason and the check never runs.

A finding's ``fingerprint`` (check id + what it is about) is stable across
re-runs of the same revision, so a status the engineer set (accepted,
rejected with a reason) is carried over when the review is run again.
"""
from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Severity = Literal["critical", "major", "minor", "info"]
Status = Literal["open", "accepted", "rejected", "fixed", "deferred"]
Provenance = Literal["geometry", "rule", "ai_reading", "ai_inference"]
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}

DOMAINS = {
    "structure": "Structure & identity",
    "interfaces": "Interfaces & fasteners",
    "clearance": "Clearance & motion",
    "actuation": "Actuation",
    "sim": "Sim fidelity",
    "manufacturing": "Manufacturability",
    "documentation": "Documentation consistency",
    "revision": "Revision compare",
}


class Evidence(BaseModel):
    type: Literal["instance", "part", "feature", "contact", "measurement", "file", "bom_row", "document", "joint"]
    id: Optional[str] = None
    kind: Optional[str] = None                  # e.g. "hole" for a feature
    label: Optional[str] = None                 # human label for the chip
    points: Optional[list[list[float]]] = None  # measurement endpoints, assembly frame, mm
    value: Optional[float] = None
    unit: Optional[str] = None
    sha256: Optional[str] = None


class Quantity(BaseModel):
    value: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = ""
    basis: Optional[str] = None                 # where an expected value comes from (config, standard, library)
    text: Optional[str] = None                  # a non-numeric value ("named", "unique")


class Finding(BaseModel):
    check_id: str
    check_version: str
    domain: str
    severity: Severity
    title: str
    statement: str
    measured: Optional[Quantity] = None
    expected: Optional[Quantity] = None
    evidence: list[Evidence]
    provenance: Provenance = "geometry"
    recommendation: str = ""
    key: str = ""                               # what the finding is about, for the fingerprint
    status: Status = "open"
    owner: Optional[str] = None
    id: Optional[str] = None

    @model_validator(mode="after")
    def _evidence(self):
        if not self.evidence:
            raise ValueError(f"{self.check_id}: a finding must carry at least one evidence object")
        return self

    @property
    def fingerprint(self) -> str:
        key = self.key or "|".join(sorted(f"{e.type}:{e.id}" for e in self.evidence if e.id))
        return hashlib.sha1(f"{self.check_id}|{key}".encode()).hexdigest()[:16]


@dataclass
class CheckConfig:
    """Per-project tolerances. Defaults are the spec's; every value is quoted as the basis of what it judges."""
    values: dict[str, Any] = field(default_factory=dict)

    DEFAULTS = {
        "contact_gap_mm": 0.05,
        "hole_align_tol_mm": 0.05,
        "min_clearance_mm": 0.3,
        "unit_tiny_mm": 0.05,
        "dup_body_tol_mm": 1e-3,
        "max_fastener_hole_mm": 7.1,      # robotics scale (up to M6 coarse clearance); raise for machinery
        "sim_mass_rel": 0.05,
        "sim_com_mm": 2.0,
        "sim_inertia_rel": 0.10,
        "sim_axis_deg": 0.5,
    }

    def get(self, key: str) -> Any:
        return self.values.get(key, self.DEFAULTS[key])

    def basis(self, key: str) -> str:
        src = "project setting" if key in self.values else "default"
        return f"{src}: {key} = {self.get(key)}"


@dataclass
class Check:
    id: str
    version: str
    domain: str
    title: str
    requires: list[str]                         # Model Graph keys that must be non-empty
    kind: Literal["deterministic", "ai_assisted"]
    run: Callable[[Any, CheckConfig], list[Finding]]
    description: str = ""


REGISTRY: dict[str, Check] = {}


def check(id: str, version: str, domain: str, title: str, requires: list[str] | None = None,
          kind: Literal["deterministic", "ai_assisted"] = "deterministic", description: str = ""):
    """Decorator: register a check function ``(graph, config) -> list[Finding]``."""
    def wrap(fn):
        REGISTRY[id] = Check(id, version, domain, title, requires or [], kind, fn, description or (fn.__doc__ or "").strip())
        return fn
    return wrap


# ------------------------------------------------------------------- runner --

def _missing(graph, requires: list[str]) -> list[str]:
    return [r for r in requires if not getattr(graph, r, None)]


REASONS = {
    "bom_rows": "no BOM in this revision",
    "joints": "no joints: add a URDF/MJCF or confirm inferred joints",
    "documents": "no drawings or instructions (PDF) in this revision",
    "contacts": "no touching parts were found",
    "features": "no holes or cylinders were found",
    "instances": "no geometry",
    "sim": "no URDF or MJCF in this revision",
    "motion": "no joint swept yet: confirm a joint in the Motion lens and run its sweep",
}


def run_checks(graph, config: CheckConfig | None = None, only: list[str] | None = None) -> tuple[list[Finding], list[dict]]:
    """Run every registered check (or ``only``). Returns (findings, check-run records)."""
    from . import load_all
    load_all()
    config = config or CheckConfig()
    findings: list[Finding] = []
    runs: list[dict] = []
    for cid, chk in sorted(REGISTRY.items()):
        if only and cid not in only:
            continue
        rec = {"check_id": cid, "check_version": chk.version, "domain": chk.domain, "title": chk.title,
               "kind": chk.kind, "status": "", "reason": None, "findings": 0, "seconds": 0.0, "error": None}
        miss = _missing(graph, chk.requires)
        if miss:
            rec.update(status="not_run", reason="; ".join(REASONS.get(m, f"missing {m}") for m in miss))
            runs.append(rec)
            continue
        t0 = time.perf_counter()
        try:
            out = chk.run(graph, config) or []
            for f in out:
                if f.check_id != cid or f.check_version != chk.version:
                    raise ValueError(f"{cid}: finding labelled {f.check_id}@{f.check_version}")
                if chk.kind == "deterministic":
                    if f.provenance in ("ai_reading", "ai_inference"):
                        raise ValueError(f"{cid}: a deterministic check cannot emit AI provenance")
                    if f.severity != "info" and (f.measured is None or f.expected is None):
                        raise ValueError(f"{cid}: deterministic findings above info need measured and expected")
            findings.extend(out)
            rec.update(status="findings" if out else "passed", findings=len(out))
        except Exception as e:  # noqa: BLE001 - one broken check never sinks the review
            rec.update(status="error", error=f"{type(e).__name__}: {e}", reason=traceback.format_exc()[-800:])
        rec["seconds"] = round(time.perf_counter() - t0, 3)
        runs.append(rec)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.domain, f.check_id))
    return findings, runs
