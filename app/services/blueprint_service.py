"""Blueprint → geometry: what the fine-tuned model actually produces, made real.

The OFL path asks a general model for Python and runs it. This path is
different in kind: our model emits a **Blueprint** — named variables, a feature
tree in which every dimension is an expression over them, and assertions that
include a closed-form prediction of the body's own volume. So the build is not
the end of the story, it is the experiment. We freeze the prediction, build the
geometry, measure it, and compare. The model is graded against itself.

That is why this module refuses to reimplement anything. ``Blueprint.resolve``,
``freecad/reconstruct.py`` and ``orion.forge.check_assertions`` are the exact
modules that verified the 42k-record corpus; a second implementation here would
mean the part a user downloads is not the part the assertions were checked
against, and the verdict would be decoration.

Runs the compile under FreeCAD's interpreter as a subprocess (see
``orion/build_export_fc.py``), because FreeCAD cannot be imported into the API
process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Optional

from app.logging_config import get_logger

logger = get_logger(__name__)

#: OCC can wedge on pathological geometry. A bounded failure is a result; an
#: unbounded one stalls the request until the gateway gives up on it.
BUILD_TIMEOUT_S = int(os.environ.get("ORION_BLUEPRINT_TIMEOUT_S", "180"))


class BlueprintBuildError(RuntimeError):
    """Raised when the completion is not a Blueprint we can even attempt."""


# --------------------------------------------------------------------------- #
# interpreter discovery
# --------------------------------------------------------------------------- #
def _freecad_python() -> str:
    """Locate a Python that can ``import FreeCAD``.

    Ordered so an explicit override always wins, then the common case in each
    deployment: in the cloud container FreeCAD is installed into the running
    interpreter's own environment, on the dev box it is a separate install.
    """
    env = os.environ.get("ORION_FREECAD_PYTHON")
    if env:
        return env

    # Container case: FreeCAD importable right here.
    try:
        import FreeCAD  # noqa: F401,PLC0415

        return sys.executable
    except ImportError:
        pass

    for cand in (
        r"C:/Program Files/FreeCAD 1.1/bin/python.exe",
        r"C:/Program Files/FreeCAD 1.0/bin/python.exe",
    ):
        if os.path.exists(cand):
            return cand

    for exe in ("freecadcmd", "FreeCADCmd"):
        found = shutil.which(exe)
        if found:
            return found

    raise BlueprintBuildError("no FreeCAD interpreter found; set ORION_FREECAD_PYTHON")


def freecad_available() -> bool:
    """Whether this process can build Blueprints at all (for /health)."""
    try:
        _freecad_python()
        return True
    except BlueprintBuildError:
        return False


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def split_thinking(completion: str) -> tuple[str, str]:
    """Separate the trained ``<think>`` derivation from the Blueprint JSON.

    The derivation is the part worth showing a user — it is where the model
    picks datums and derives the volume it is about to be graded on.
    """
    if "</think>" not in completion:
        return "", completion
    head, _, tail = completion.partition("</think>")
    return head.replace("<think>", "").strip(), tail.strip()


def parse_completion(completion: str) -> tuple[str, dict]:
    """``completion`` → (thinking, blueprint payload)."""
    from orion.eval_blueprint import extract_blueprint

    thinking, _ = split_thinking(completion)
    try:
        payload = extract_blueprint(completion)
    except ValueError as exc:
        raise BlueprintBuildError(f"no Blueprint JSON in completion: {exc}") from exc
    return thinking, payload


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _extent(bbox: Optional[list]) -> Optional[list]:
    """[XMin,YMin,ZMin,XMax,YMax,ZMax] → [dx, dy, dz]."""
    if not bbox or len(bbox) != 6:
        return None
    return [round(bbox[i + 3] - bbox[i], 4) for i in range(3)]


#: Where the FreeCAD compile actually happens. "local" runs it as a subprocess
#: of this process; "modal" hands it to a container that has FreeCAD installed,
#: because the API image deliberately does not (FreeCAD would add ~1.5 GB and
#: seconds of cold start to every request, including the ones that never build).
BUILDER_MODE = os.environ.get("ORION_BUILDER_MODE", "local").lower()
MODAL_BUILDER_APP = os.environ.get("ORION_MODAL_BUILDER_APP", "orionflow-builder")
MODAL_BUILDER_FN = os.environ.get("ORION_MODAL_BUILDER_FN", "build_blueprint")


def needs_mesh_body(bp) -> bool:
    """Whether this Blueprint's own assertions require mesh sampling.

    A ``body_mesh_converged`` assertion is checked against a tessellation
    series, so skipping the sampling leaves it with nothing to evaluate — and
    an unevaluated check reads as a failure, which would refuse a part that is
    perfectly correct. Same predicate as ``orion/parallel_forge.py``.
    """
    return any(a.get("kind") == "body_mesh_converged" for a in bp.assertions)


def run_builder(
    graph: dict, workdir: str, mesh_body: bool = False
) -> tuple[dict, Optional[dict]]:
    """Compile ``graph`` into ``workdir``, wherever FreeCAD happens to live.

    Postcondition on success: ``part.step`` and ``part.stl`` exist in
    ``workdir``. Returns ``(build_log, measured)``; ``measured`` is None when
    the build failed, and ``build_log`` always explains why.
    """
    if BUILDER_MODE == "modal":
        return _build_on_modal(graph, workdir, mesh_body)
    return _build_locally(graph, workdir, mesh_body)


def _build_locally(
    graph: dict, workdir: str, mesh_body: bool = False
) -> tuple[dict, Optional[dict]]:
    gpath = os.path.join(workdir, "graph.json")
    with open(gpath, "w", encoding="utf-8") as fh:
        json.dump(graph, fh)

    fcstd = os.path.join(workdir, "part.FCStd")
    mpath = os.path.join(workdir, "measured.json")
    runner = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "orion",
        "build_export_fc.py",
    )
    fc_python = _freecad_python()  # raises BlueprintBuildError if absent

    cmd = [
        fc_python,
        runner,
        "--graph",
        gpath,
        "--fcstd",
        fcstd,
        "--out",
        mpath,
        "--step",
        os.path.join(workdir, "part.step"),
        "--stl",
        os.path.join(workdir, "part.stl"),
    ]
    if mesh_body:
        cmd.append("--mesh-body")

    # Output to files, not pipes: a killed FreeCAD child can leave an OCC
    # worker holding the pipe open, and subprocess then blocks forever draining
    # it after the timeout — the exact hang that stalled the OCC harvest.
    opath = os.path.join(workdir, "build.stdout.txt")
    epath = os.path.join(workdir, "build.stderr.txt")
    # Mesh sampling tessellates three times at fine deflection; it needs a
    # bigger budget than a plain build or it reports as a kernel hang.
    budget = BUILD_TIMEOUT_S * 3 if mesh_body else BUILD_TIMEOUT_S
    try:
        with open(opath, "w", encoding="utf-8") as _o, open(
            epath, "w", encoding="utf-8"
        ) as _e:
            proc = subprocess.run(cmd, stdout=_o, stderr=_e, timeout=budget)
        returncode, timed_out = proc.returncode, False
    except subprocess.TimeoutExpired:
        returncode, timed_out = -9, True

    def _read(path: str, n: int = 4000) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()[-n:]
        except OSError:
            return ""

    log = {
        "returncode": returncode,
        "stdout": _read(opath),
        "stderr": _read(epath),
        "timeout": timed_out,
        "where": "local",
    }
    if timed_out or returncode != 0 or not os.path.exists(mpath):
        return log, None
    with open(mpath, encoding="utf-8") as fh:
        return log, json.load(fh)


def _build_on_modal(
    graph: dict, workdir: str, mesh_body: bool = False
) -> tuple[dict, Optional[dict]]:
    """Run the compile in the FreeCAD container and land its artifacts here."""
    try:
        import modal
    except ImportError as exc:  # noqa: BLE001
        raise BlueprintBuildError(
            "ORION_BUILDER_MODE=modal but the modal package is not installed"
        ) from exc

    try:
        fn = modal.Function.from_name(MODAL_BUILDER_APP, MODAL_BUILDER_FN)
        result = fn.remote(graph, mesh_body)
    except Exception as exc:  # noqa: BLE001
        raise BlueprintBuildError(f"the build service is unreachable: {exc}") from exc

    log = dict(result.get("build_log") or {})
    log["where"] = "modal"

    # Artifacts come back as bytes and are written locally so everything
    # downstream (GLB conversion, upload, the download route) is identical to
    # the local path.
    for name, blob in (result.get("artifacts") or {}).items():
        if blob:
            with open(os.path.join(workdir, name), "wb") as fh:
                fh.write(blob)

    return log, result.get("measured")


def build_from_completion(completion: str, request_id: Optional[str] = None) -> dict:
    """Full path: model completion → verified geometry bundle."""
    thinking, payload = parse_completion(completion)
    bundle = build_from_payload(payload, request_id=request_id)
    bundle["thinking"] = thinking
    return bundle


def build_from_payload(payload: dict, request_id: Optional[str] = None) -> dict:
    """Freeze a Blueprint, build it under FreeCAD, measure and grade it.

    Never raises for a *build* failure — a part that will not compile is a
    result the caller must be able to show. Raises only when the input was
    never a Blueprint.
    """
    from orion.blueprint import Blueprint, BlueprintError

    t0 = time.time()
    request_id = request_id or uuid.uuid4().hex[:12]

    bundle: dict[str, Any] = {
        "success": False,
        "request_id": request_id,
        "thinking": "",
        "blueprint": None,
        "part_class": "",
        "variables": {},
        "files": {},
        "stats": None,
        "measured": {},
        "verification": {},
        "build_log": {},
        "error": None,
        "generation_time_ms": 0.0,
    }

    try:
        bp = Blueprint.from_dict(payload).freeze()
    except (BlueprintError, KeyError, TypeError, ValueError) as exc:
        # A static rejection is the model failing its own contract (a bare
        # number where an expression belongs, an unknown feature type). Report
        # it as such rather than as a kernel error.
        bundle["error"] = f"blueprint rejected: {exc}"
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    bundle["blueprint"] = bp.to_dict()
    bundle["part_class"] = bp.part_class
    bundle["variables"] = dict(bp.variables)

    try:
        graph = bp.resolve()
    except (BlueprintError, KeyError, TypeError, ValueError) as exc:
        bundle["error"] = f"blueprint could not be resolved: {exc}"
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    analysis = graph.pop("_analysis", None)

    from app.services import artifacts

    workdir = artifacts.workdir(request_id)

    step = os.path.join(workdir, "part.step")
    stl = os.path.join(workdir, "part.stl")

    try:
        build_log, measured_raw = run_builder(
            graph, workdir, mesh_body=needs_mesh_body(bp)
        )
    except BlueprintBuildError as exc:
        bundle["error"] = str(exc)
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    bundle["build_log"] = build_log
    returncode = build_log.get("returncode", -1)
    timed_out = bool(build_log.get("timeout"))

    def _tail(path: str, n: int = 4000) -> str:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()[-n:]
        except OSError:
            return ""

    if timed_out:
        bundle["error"] = f"the kernel did not converge within " f"{BUILD_TIMEOUT_S}s"
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle
    if returncode != 0 or measured_raw is None:
        bundle["error"] = (build_log.get("stderr") or "")[
            -600:
        ].strip() or f"the build failed (rc={returncode})"
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    measured = dict(measured_raw)
    bundle["build_log"]["build_report"] = measured.pop("build_report", {})
    bundle["measured"] = measured

    # ---- artifacts -------------------------------------------------------- #
    glb = None
    if os.path.exists(stl):
        try:
            from app.services.stl_to_glb import stl_to_glb

            glb = stl_to_glb(stl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("blueprint_glb_failed", error=str(exc))

    files: dict[str, str] = {}
    for kind, path in (("step", step), ("stl", stl), ("glb", glb)):
        if path and os.path.exists(path):
            files[kind] = artifacts.artifact_url(request_id, path)
    bundle["files"] = files

    # Per-request dirs are ephemeral on scale-to-zero hosts; the existing
    # download route redirects to object storage when the local copy is gone.
    from app.config import settings

    if settings.is_s3_configured:
        from pathlib import Path

        from app.services.storage import get_storage

        storage = get_storage()
        for path in (step, stl, glb):
            if path and os.path.exists(path):
                try:
                    storage.publish(
                        Path(path),
                        key=artifacts.storage_key(request_id, path),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("blueprint_upload_failed", error=str(exc))

    # ---- grading ---------------------------------------------------------- #
    volume = measured.get("body_volume")
    extent = _extent(measured.get("bbox"))
    bundle["stats"] = {
        "volume_mm3": volume or 0.0,
        "bbox_mm": extent or [],
        "watertight": bool(measured.get("watertight")),
        "solids": measured.get("solids"),
        "valid": measured.get("valid"),
    }

    from orion import forge
    from orion_physical_ai import verify

    observed = {}
    if volume:
        observed["volume_cm3"] = round(volume / 1000.0, 3)
    if extent:
        observed["bbox_mm"] = extent

    try:
        rows = forge.check_assertions(bp, measured, analysis)
    except Exception as exc:  # noqa: BLE001
        # Grading is the point, so a grader crash must not masquerade as a
        # pass: report it as unproven with the reason attached.
        logger.warning("blueprint_grading_failed", error=str(exc))
        rows = []
        bundle["verification"] = {
            "verdict": "unproven",
            "checks": [],
            "failed": [],
            "measured": observed,
            "error": f"assertions could not be checked: {exc}",
        }
    else:
        bundle["verification"] = verify.from_assertion_rows(rows, measured=observed)

    bundle["assertions"] = rows
    bundle["success"] = bool(files) and bool(volume)
    if not bundle["success"] and not bundle["error"]:
        bundle["error"] = "the build produced no measurable solid"
    bundle["generation_time_ms"] = (time.time() - t0) * 1000
    return bundle
