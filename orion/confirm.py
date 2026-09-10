"""Closing the loop: build what the search chose, and find out if it was right.

Everything upstream of here is closed form. The design space is arithmetic over
parameters, the frame solver is exact but only for the idealisation it solves,
and the volume a candidate is ranked on is the expression a Blueprint carries
for its own assertion. None of it has touched a kernel, which is why an
:class:`~orion.design_space.Observation` says ``screened`` and never
``VERIFIED`` — a screened candidate has proved it is worth building, and
nothing more.

This is the *and more*. It resolves the winner, builds it in FreeCAD, measures
the solid and grades it against the assertions frozen before the build. Only
then is there a verdict.

**The step that is easy to miss.** ``blueprint_gen`` emits a Blueprint whose
geometry is a ``template`` of expressions; the compiler wants a FeatureGraph of
concrete features. :meth:`orion.blueprint.Blueprint.resolve` is what turns one
into the other, and skipping it does not raise — the compiler is handed a dict
with no ``features`` key, iterates nothing, builds nothing, and reports
success. Measured once, by hand: an empty document, ``built: []``, no errors,
and a null volume. That failure mode has a history in this codebase and it is
why :func:`build` refuses a graph with no features rather than trusting a
process that exited zero.

**The kernel is a subprocess and is allowed to be absent.** FreeCAD is not in
the API container and is not a test dependency, so every entry point here
degrades to a stated reason rather than an exception. A confirmation that could
not run is reported as exactly that, never as a failure of the part.

**What confirmation can tell you that screening cannot.** Whether the geometry
exists at all; whether it is one watertight solid; and whether the closed form
the whole search ranked on describes the thing that got built. Measured on the
first two brackets through this path, predicted and measured volume agreed to
one part in 10^13 — which is evidence about the volume expression, and says
nothing about the frame model's stresses. Those remain unmeasured by anything
here, and the module says so rather than letting a green verdict imply it.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

#: Long enough for the parts this system builds; short enough that a hung
#: kernel is a reported timeout rather than a stuck caller.
DEFAULT_TIMEOUT_S = 300


class ConfirmError(RuntimeError):
    """The build could not be attempted, as distinct from a part that failed."""


@dataclass
class Built:
    """What the kernel did, whether or not it worked."""

    ok: bool
    #: Kernel measurements, or ``None`` when nothing was built.
    measured: Optional[dict] = None
    #: The compiler's own account: what it built, skipped and could not
    #: recompute.
    report: dict = field(default_factory=dict)
    #: Files written, by name. Empty when the build failed.
    artifacts: dict = field(default_factory=dict)
    seconds: float = 0.0
    #: Why it failed, or why it could not be attempted.
    reason: str = ""
    log: str = field(default="", repr=False)


@dataclass
class Confirmation:
    """A screened candidate, put through the kernel and graded."""

    built: Built
    #: ``orion.forge.check_assertions`` rows: the frozen contract against the
    #: measurement.
    assertions: list = field(default_factory=list)
    #: The whole verdict bundle from ``orion_physical_ai.verify``.
    verification: dict = field(default_factory=dict)
    #: What the closed form said the volume would be, and what it was.
    predicted_volume_mm3: Optional[float] = None
    measured_volume_mm3: Optional[float] = None
    notes: list = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """The kernel-backed verdict, or why there is not one."""
        if not self.built.ok:
            return "unbuilt"
        return (self.verification or {}).get("verdict") or "unproven"

    @property
    def volume_agreement(self) -> Optional[float]:
        """Relative difference between the prediction and the solid.

        The number that says whether the search was ranking on a real quantity.
        A search that optimises a volume expression which does not describe the
        built part is optimising a fiction, and nothing before this point could
        have noticed.
        """
        if not self.predicted_volume_mm3 or self.measured_volume_mm3 is None:
            return None
        return (abs(self.measured_volume_mm3 - self.predicted_volume_mm3)
                / abs(self.predicted_volume_mm3))


def kernel_available() -> bool:
    """Whether a FreeCAD interpreter can be found on this machine."""
    try:
        from . import freecad_python

        return bool(freecad_python.freecad_python())
    except Exception:  # noqa: BLE001 - absence is a normal answer here
        return False


def build(blueprint, workdir: Optional[str] = None,
          timeout_s: int = DEFAULT_TIMEOUT_S, exports: bool = True) -> Built:
    """Resolve a frozen Blueprint and build it in FreeCAD.

    ``blueprint`` is an :class:`orion.blueprint.Blueprint`. The template is
    resolved here rather than by the caller, because that is the step whose
    omission looks like success.
    """
    from . import freecad_python

    try:
        interpreter = freecad_python.freecad_python()
    except Exception as exc:  # noqa: BLE001
        return Built(ok=False, reason=f"no FreeCAD interpreter available: "
                                      f"{exc}")

    try:
        graph = blueprint.resolve()
    except Exception as exc:  # noqa: BLE001
        return Built(ok=False, reason=f"the template did not resolve: {exc}")

    if not (graph.get("features") or []):
        # The whole reason this function exists rather than a two-line caller.
        return Built(ok=False,
                     reason="the resolved graph has no features; building it "
                            "would produce an empty document and report "
                            "success")

    owned = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="orion_confirm_")
    os.makedirs(workdir, exist_ok=True)

    paths = {name: os.path.join(workdir, name) for name in
             ("graph.json", "part.FCStd", "measured.json")}
    if exports:
        paths.update({name: os.path.join(workdir, name) for name in
                      ("part.step", "part.stl", "part.topology.json")})

    with open(paths["graph.json"], "w", encoding="utf-8") as fh:
        json.dump(graph, fh)

    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [interpreter, os.path.join(here, "build_export_fc.py"),
           "--graph", paths["graph.json"], "--fcstd", paths["part.FCStd"],
           "--out", paths["measured.json"]]
    if exports:
        cmd += ["--step", paths["part.step"], "--stl", paths["part.stl"],
                "--topology", paths["part.topology.json"]]

    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return Built(ok=False, seconds=time.time() - started,
                     reason=f"the kernel did not finish within {timeout_s}s")
    except Exception as exc:  # noqa: BLE001
        return Built(ok=False, seconds=time.time() - started,
                     reason=f"the kernel could not be started: {exc}")

    elapsed = time.time() - started
    log = (out or "") + (("\n" + err) if err else "")

    if code != 0 or not os.path.exists(paths["measured.json"]):
        return Built(ok=False, seconds=elapsed, log=log,
                     reason=f"the kernel exited {code}: "
                            f"{(err or out or '').strip()[:300]}")

    with open(paths["measured.json"], encoding="utf-8") as fh:
        measured = json.load(fh)
    report = measured.pop("build_report", {}) or {}

    # Exiting zero is not evidence. A compiler that built nothing exits zero.
    if not (report.get("built") or []):
        return Built(ok=False, seconds=elapsed, log=log, report=report,
                     measured=measured,
                     reason="the kernel built no features and still exited "
                            "successfully")
    if measured.get("body_volume") is None:
        return Built(ok=False, seconds=elapsed, log=log, report=report,
                     measured=measured,
                     reason="the kernel produced no measurable body")

    artifacts = {name: path for name, path in paths.items()
                 if os.path.exists(path)}
    return Built(ok=True, measured=measured, report=report,
                 artifacts=artifacts, seconds=elapsed, log=log)


def confirm(blueprint, workdir: Optional[str] = None,
            timeout_s: int = DEFAULT_TIMEOUT_S) -> Confirmation:
    """Build a frozen Blueprint and grade it against its own frozen contract.

    The assertions were written before the build and are inside
    ``blueprint_hash``, so this compares a prediction with a measurement and
    neither can be fitted to the other afterwards.
    """
    from . import engineering, expr as E, forge
    from orion_physical_ai import verify

    made = build(blueprint, workdir=workdir, timeout_s=timeout_s)
    out = Confirmation(built=made)

    predicted = _predicted_volume(blueprint)
    out.predicted_volume_mm3 = predicted

    if not made.ok:
        out.notes.append(made.reason)
        return out

    measured = made.measured or {}
    out.measured_volume_mm3 = measured.get("body_volume")

    try:
        out.assertions = forge.check_assertions(blueprint, measured)
    except Exception as exc:  # noqa: BLE001 - a grader crash is not a pass
        out.notes.append(f"the assertions could not be checked: {exc}")
        return out

    # The analytic tier runs against the *measured* solid here, which is what
    # it was always for: `engineering.run_checks` resolves `@` references from
    # the measurement rather than from a prediction.
    try:
        rows = engineering.run_checks(blueprint.to_dict(), blueprint.variables,
                                      measured)
    except Exception as exc:  # noqa: BLE001
        rows = []
        out.notes.append(f"the engineering checks could not be run: {exc}")

    try:
        out.verification = verify.from_assertion_rows(
            rows=out.assertions,
            measured={"body_volume": measured.get("body_volume"),
                      "watertight": measured.get("watertight"),
                      "solids": measured.get("solids"),
                      "valid": measured.get("valid")},
            engineering=rows,
            design_plan=blueprint.design_plan,
            template=blueprint.template,
            variables=dict(blueprint.variables),
        )
    except Exception as exc:  # noqa: BLE001
        out.notes.append(f"the verdict could not be computed: {exc}")

    agreement = out.volume_agreement
    if agreement is not None and agreement > 1e-6:
        out.notes.append(
            f"the closed form predicted {predicted:.6g} mm^3 and the solid "
            f"measures {out.measured_volume_mm3:.6g} mm^3 — a "
            f"{100.0 * agreement:.4g}% disagreement, so the quantity the "
            f"search ranked on does not describe the part that was built")
    return out


def _predicted_volume(blueprint) -> Optional[float]:
    """The body volume the frozen contract predicts, evaluated."""
    from . import expr as E

    for assertion in blueprint.resolve_assertions():
        if assertion.get("kind") != "body_volume":
            continue
        value = assertion.get("target_value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            return float(E.evaluate(str(assertion.get("target")),
                                    blueprint.variables))
        except Exception:  # noqa: BLE001
            return None
    return None


def confirm_candidate(candidate, workdir: Optional[str] = None,
                      timeout_s: int = DEFAULT_TIMEOUT_S) -> Confirmation:
    """Build and grade one :class:`orion.search.Candidate`.

    The candidate carries the requirements it was reached with, so the part
    that gets built is the one the search actually chose — not a
    reconstruction from its parameters, which could differ if any of them is
    derived.
    """
    from . import blueprint_gen as G
    from .blueprint import Blueprint

    requirements = candidate.requirements or {}
    family = requirements.get("family")
    if not family:
        raise ConfirmError("the candidate carries no family to build")
    blueprint = Blueprint.from_dict(G.generate(family, requirements)).freeze()
    return confirm(blueprint, workdir=workdir, timeout_s=timeout_s)


def explain(confirmation: Confirmation) -> list:
    """The confirmation in sentences, including what it did not establish."""
    built = confirmation.built
    if not built.ok:
        return [f"Not built: {built.reason}",
                "Nothing here is a statement about the design — only about "
                "whether it could be put through a kernel."]

    measured = built.measured or {}
    lines = [
        f"Built in {built.seconds:.1f}s: "
        f"{len(built.report.get('built') or [])} features, "
        f"{measured.get('solids')} solid(s), "
        f"watertight={measured.get('watertight')}, "
        f"valid={measured.get('valid')}.",
    ]

    agreement = confirmation.volume_agreement
    if agreement is not None:
        lines.append(
            f"Predicted volume {confirmation.predicted_volume_mm3:.7g} mm^3, "
            f"measured {confirmation.measured_volume_mm3:.7g} mm^3 "
            f"({agreement * 100.0:.2e}% apart) — the quantity the search "
            f"ranked on describes the part that was built.")

    failed = [row for row in confirmation.assertions if not row.get("ok", True)]
    lines.append(
        f"{len(confirmation.assertions)} frozen assertions checked, "
        f"{len(failed)} failed.")

    lines.append(f"Verdict: {confirmation.verdict.upper()}.")
    lines.extend(confirmation.notes)
    lines.append(
        "This confirms the geometry against its frozen contract. The frame "
        "model's stresses are not measured by anything here, so a passing "
        "verdict says the part is the shape it claimed to be — not that the "
        "stress analysis behind it was right.")
    return lines
