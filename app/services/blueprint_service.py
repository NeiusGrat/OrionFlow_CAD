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


def observations(
    measured: dict, volume: Optional[float], extent: Optional[list]
) -> dict:
    """What the kernel reported, in the shape the grader reads.

    Separate from the caller because it is load-bearing and was silently wrong.
    ``verify.solid_validity_checks`` grades ``valid`` and ``solids`` out of this
    dict and treats a *missing* key as "never measured" rather than as a
    failure — so passing only the volume and extent, as this once did, made
    those checks return nothing on the live path. The flag could be on and the
    gate would still be open, with no test failing to say so.

    Absent stays absent on purpose: a build predating the measurement pass
    carries no opinion, and inventing ``False`` for it would refuse parts nobody
    checked.
    """
    obs: dict = {}
    if volume:
        obs["volume_cm3"] = round(volume / 1000.0, 3)
    if extent:
        obs["bbox_mm"] = extent
    for key in ("valid", "solids", "watertight"):
        if measured.get(key) is not None:
            obs[key] = measured[key]
    return obs


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
        "--topology",
        os.path.join(workdir, "part.topology.json"),
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


def _prepare(payload: dict, request_id: str) -> tuple[Any, Optional[dict], str, str]:
    """Freeze, resolve and locate the workdir. Raises ``BlueprintBuildError``.

    Deterministic by construction — the same payload always produces the same
    frozen Blueprint, the same graph and the same analysis — which is what lets
    an asynchronous build redo this at collection time on a completely different
    container instead of persisting intermediate state. Nothing here touches the
    kernel or the network.
    """
    from orion.blueprint import Blueprint, BlueprintError

    try:
        bp = Blueprint.from_dict(payload).freeze()
    except (BlueprintError, KeyError, TypeError, ValueError) as exc:
        # A static rejection is the model failing its own contract (a bare
        # number where an expression belongs, an unknown feature type). Report
        # it as such rather than as a kernel error.
        raise BlueprintBuildError(f"blueprint rejected: {exc}") from exc

    try:
        graph = bp.resolve()
    except (BlueprintError, KeyError, TypeError, ValueError) as exc:
        raise BlueprintBuildError(f"blueprint could not be resolved: {exc}") from exc

    analysis = graph.pop("_analysis", None)

    from app.services import artifacts

    return bp, analysis, graph, artifacts.workdir(request_id)


def _empty_bundle(request_id: str) -> dict:
    from app.services import artifacts as artifacts_mod

    return {
        "success": False,
        "request_id": request_id,
        "thinking": "",
        "blueprint": None,
        "part_class": "",
        "variables": {},
        "files": {},
        # Same keys on the failure path as on the success path: a caller that
        # reads a bundle should not have to know which one it got.
        "artifact_digests": {},
        "builder": artifacts_mod.builder_stamp(),
        "kernel": {},
        "topology": {},
        "stats": None,
        "measured": {},
        "verification": {},
        "build_log": {},
        "error": None,
        "generation_time_ms": 0.0,
    }


def _finish(
    bp: Any,
    analysis: Optional[dict],
    workdir: str,
    request_id: str,
    build_log: dict,
    measured_raw: Optional[dict],
    t0: float,
) -> dict:
    """Everything after the kernel: artifacts, upload, measurement, grading.

    One implementation, reached by both the synchronous path and the
    asynchronous one. A second copy here would mean the part a user downloads
    could be graded differently depending on which route built it, which is
    exactly the class of divergence this module's docstring exists to prevent.
    """
    bundle = _empty_bundle(request_id)
    bundle["blueprint"] = bp.to_dict()
    bundle["part_class"] = bp.part_class
    bundle["variables"] = dict(bp.variables)
    bundle["build_log"] = build_log

    step = os.path.join(workdir, "part.step")
    stl = os.path.join(workdir, "part.stl")
    fcstd = os.path.join(workdir, "part.FCStd")
    topology = os.path.join(workdir, "part.topology.json")

    returncode = build_log.get("returncode", -1)
    if build_log.get("timeout"):
        bundle["error"] = f"the kernel did not converge within {BUILD_TIMEOUT_S}s"
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

    # The FCStd is listed first among the durable formats because it is the
    # only one that is not lossy: STEP and STL are the finished solid, while
    # the FCStd is the parametric document — sketches, feature history, and the
    # expressions that bind each dimension to a named variable. A part whose
    # FCStd survives can be reopened and retuned; one with only a STEP is a
    # dead shape.
    from app.services import artifacts

    # Digested here rather than in the kernel worker, and deliberately so. On
    # the Modal path the artifacts cross a container boundary as bytes and are
    # rewritten locally; a hash taken before that trip would attest to a file
    # that is no longer the one being served. Hashing the bytes that landed
    # covers both builders with one implementation and catches a truncated
    # transfer as well as a truncated write.
    files: dict[str, str] = {}
    digests: dict[str, dict] = {}
    for kind, path in (
        ("fcstd", fcstd),
        ("step", step),
        ("stl", stl),
        ("glb", glb),
        ("topology", topology),
    ):
        if path and os.path.exists(path):
            files[kind] = artifacts.artifact_url(request_id, path)
            entry = artifacts.file_digest(path)
            if entry:
                digests[kind] = entry
    bundle["files"] = files
    bundle["artifact_digests"] = digests
    bundle["builder"] = artifacts.builder_stamp()
    bundle["kernel"] = measured.get("kernel") or {}

    # The summary, not the record: the full sidecar is megabytes on a dense
    # part and every caller of this bundle would pay for it. What belongs in a
    # build response is how many faces there are and which feature made them;
    # the elements themselves are a query away under /api/v1/topology.
    from app.services import topology as topology_reader

    record = topology_reader.load(workdir)
    bundle["topology"] = topology_reader.summary(record) if record else {}

    manifest = artifacts.new_manifest(
        request_id,
        digests,
        blueprint_hash=str(bundle["blueprint"].get("blueprint_hash") or ""),
        kernel=bundle["kernel"],
        built_where=str(build_log.get("where") or ""),
    )
    manifest_path = artifacts.write_manifest(workdir, manifest)

    # Per-request dirs are ephemeral on scale-to-zero hosts; the existing
    # download route redirects to object storage when the local copy is gone.
    from app.config import settings

    if settings.is_s3_configured:
        from pathlib import Path

        from app.services.storage import get_storage

        storage = get_storage()
        # The manifest goes up with them: an artifact that outlives its
        # container into object storage keeps no other record of what it is.
        for path in (fcstd, step, stl, glb, topology, manifest_path):
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

    observed = observations(measured, volume, extent)

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
    # Success is judged on the exchange formats, not on ``files`` as a whole.
    # An FCStd can save even when a STEP/STL export fails, and counting it here
    # would report success for a build the user cannot see or download in any
    # tool — the viewer needs the GLB, and the GLB comes from the STL.
    bundle["success"] = any(k in files for k in ("step", "stl", "glb")) and bool(volume)
    if not bundle["success"] and not bundle["error"]:
        bundle["error"] = "the build produced no measurable solid"
    bundle["generation_time_ms"] = (time.time() - t0) * 1000
    return bundle


def build_from_payload(payload: dict, request_id: Optional[str] = None) -> dict:
    """Freeze a Blueprint, build it under FreeCAD, measure and grade it.

    Synchronous: blocks for the length of the build. Used by ``/studio/chat``
    and ``/studio/rebuild``, where the request *is* the build and the client is
    holding a stream open for it. Design sessions use ``start_build`` /
    ``collect_build`` instead, because an approval means a build can outlive the
    request that asked for it.

    Never raises for a *build* failure — a part that will not compile is a
    result the caller must be able to show. Raises only when the input was never
    a Blueprint.
    """
    t0 = time.time()
    request_id = request_id or uuid.uuid4().hex[:12]

    try:
        bp, analysis, graph, workdir = _prepare(payload, request_id)
    except BlueprintBuildError as exc:
        bundle = _empty_bundle(request_id)
        bundle["error"] = str(exc)
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    try:
        build_log, measured_raw = run_builder(
            graph, workdir, mesh_body=needs_mesh_body(bp)
        )
    except BlueprintBuildError as exc:
        bundle = _empty_bundle(request_id)
        bundle["blueprint"] = bp.to_dict()
        bundle["part_class"] = bp.part_class
        bundle["variables"] = dict(bp.variables)
        bundle["error"] = str(exc)
        bundle["generation_time_ms"] = (time.time() - t0) * 1000
        return bundle

    return _finish(bp, analysis, workdir, request_id, build_log, measured_raw, t0)


# --------------------------------------------------------------------------- #
# asynchronous build: start here, collect anywhere
# --------------------------------------------------------------------------- #
#: Local-mode builds in flight, keyed by request id. Process-local on purpose:
#: ``ORION_BUILDER_MODE=local`` means FreeCAD is a subprocess of *this* process,
#: so a build genuinely cannot be collected anywhere else. In the cloud the
#: handle is a Modal call id, which any container can resolve — which is the
#: whole reason a session can outlive the request that started its build.
_LOCAL_BUILDS: dict[str, Any] = {}


def start_build(payload: dict, request_id: Optional[str] = None) -> dict:
    """Hand a Blueprint to the builder and return a handle, without waiting.

    The handle is everything a *different* container needs to finish the job:
    the request id (which is where the artifacts land) and the builder's own
    call id. Nothing else is persisted, because ``_prepare`` is deterministic —
    re-freezing and re-resolving the stored payload at collection time gives
    back exactly the Blueprint and the analysis the assertions must be checked
    against.

    A handle with ``error`` set never reached the builder at all.
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    handle = {
        "request_id": request_id,
        "call_id": "",
        "mode": BUILDER_MODE,
        "error": None,
        "started_at": time.time(),
    }

    try:
        bp, _analysis, graph, workdir = _prepare(payload, request_id)
    except BlueprintBuildError as exc:
        handle["error"] = str(exc)
        return handle

    mesh_body = needs_mesh_body(bp)

    if BUILDER_MODE == "modal":
        try:
            import modal
        except ImportError as exc:
            handle["error"] = (
                "ORION_BUILDER_MODE=modal but the modal package is not installed"
            )
            logger.warning("blueprint_spawn_no_modal", error=str(exc))
            return handle
        try:
            fn = modal.Function.from_name(MODAL_BUILDER_APP, MODAL_BUILDER_FN)
            call = fn.spawn(graph, mesh_body)
        except Exception as exc:  # noqa: BLE001
            handle["error"] = f"the build service is unreachable: {exc}"
            return handle
        handle["call_id"] = call.object_id
        return handle

    # Local: a thread, so the caller still returns immediately and the same
    # start/collect shape is exercised on a dev box.
    from concurrent.futures import ThreadPoolExecutor

    executor = _LOCAL_BUILDS.setdefault(
        "_executor", ThreadPoolExecutor(max_workers=2, thread_name_prefix="build")
    )
    _LOCAL_BUILDS[request_id] = executor.submit(run_builder, graph, workdir, mesh_body)
    handle["call_id"] = f"local:{request_id}"
    return handle


def collect_build(
    payload: dict, request_id: str, call_id: str, wait: float = 0.0
) -> Optional[dict]:
    """The finished bundle, or None if the builder has not finished yet.

    ``wait`` is the number of seconds to block for. Zero — the default — makes
    this a poll, which is what a reconcile-on-read wants: any request touching a
    building session tries to collect, and a client that never comes back costs
    nothing because the result is held by the builder, not by us.

    Raising is reserved for a handle that cannot be resolved at all. A build
    that ran and failed comes back as a bundle with ``error`` set, because that
    is a result the user has to be able to see.
    """
    t0 = time.time()

    try:
        bp, analysis, _graph, workdir = _prepare(payload, request_id)
    except BlueprintBuildError as exc:
        bundle = _empty_bundle(request_id)
        bundle["error"] = str(exc)
        return bundle

    if call_id.startswith("local:"):
        future = _LOCAL_BUILDS.get(request_id)
        if future is None:
            bundle = _empty_bundle(request_id)
            bundle["error"] = "the build was lost — this process did not start it"
            return bundle
        if not future.done() and wait <= 0:
            return None
        try:
            build_log, measured_raw = future.result(timeout=wait or None)
        except TimeoutError:
            return None
        except Exception as exc:  # noqa: BLE001
            bundle = _empty_bundle(request_id)
            bundle["error"] = f"the build failed to run: {exc}"
            return bundle
        finally:
            if future.done():
                _LOCAL_BUILDS.pop(request_id, None)
        return _finish(bp, analysis, workdir, request_id, build_log, measured_raw, t0)

    try:
        import modal
    except ImportError:
        bundle = _empty_bundle(request_id)
        bundle["error"] = "the modal package is not installed"
        return bundle

    try:
        call = modal.FunctionCall.from_id(call_id)
        result = call.get(timeout=wait)
    except TimeoutError:
        return None
    except Exception as exc:  # noqa: BLE001
        # Modal raises its own timeout type on a poll that finds nothing ready;
        # anything whose name says timeout is "not finished", not "broken".
        if "timeout" in type(exc).__name__.lower():
            return None
        bundle = _empty_bundle(request_id)
        bundle["error"] = f"the build could not be collected: {exc}"
        return bundle

    build_log = dict((result or {}).get("build_log") or {})
    build_log["where"] = "modal"

    # Artifacts come back as bytes and are written into this container's copy of
    # the workdir, so the GLB conversion, the upload and the download route are
    # identical to the synchronous path — including on a container that had
    # nothing to do with starting the build.
    for name, blob in ((result or {}).get("artifacts") or {}).items():
        if blob:
            with open(os.path.join(workdir, name), "wb") as fh:
                fh.write(blob)

    return _finish(
        bp, analysis, workdir, request_id, build_log, (result or {}).get("measured"), t0
    )
