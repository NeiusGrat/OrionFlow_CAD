"""The Blueprint build service — FreeCAD, headless, in its own container.

Deploy:  modal deploy deploy/modal_builder.py

Separate from ``modal_app.py`` on purpose, and not merely for tidiness:

* **Image.** FreeCAD comes from conda-forge and costs ~1.5 GB plus a slow
  import. The API image is debian-slim + pip and cold-starts from a memory
  snapshot in seconds. Merging them would tax every request, including the
  many that never build geometry.
* **Blast radius.** Two ``modal.App`` objects in one file means a deploy of one
  can disturb the other. The API is live; the builder is not allowed to put it
  at risk.

What runs here is the *same* code that verified the corpus —
``orion/build_export_fc.py`` calling ``freecad/reconstruct.py`` — so geometry
built in the cloud is the geometry the model's assertions were checked against.
Re-implementing the compile for the cloud would quietly break that guarantee.

The API reaches this by name; see ``app/services/blueprint_service.py``
(``ORION_BUILDER_MODE=modal``).
"""

import modal

#: The kernel every published number is measured against.
#:
#: Pinned 2026-08-05 at 1.1.0, deliberately behind conda-forge's newest so that
#: tightening the verification gate and moving the kernel could not be
#: confounded. That upgrade is now taken, on its own, as that note asked:
#:
#: 1.1.3 (conda-forge's latest stable) since 2026-08-19. The move was gated on
#: the corpus itself rather than on the version string — ``deploy/verify_builder.py``
#: replays frozen Blueprints whose closed-form predictions were confirmed under
#: the old kernel, so a change in how OCC resolves a Pocket or a fillet shows up
#: as a failed assertion rather than as unexplained drift. 1.1.0 and 1.1.3 were
#: each measured over the same 30 records: 30/30 verified on both, no part class
#: regressed, and the reported volumes agree. Re-measure the same way before
#: moving it again.
#:
#: Not the 1.1.1 that may be running on a dev box: conda-forge does not ship
#: 1.1.1 at all (it is a FreeCAD-provided Windows build), so it is not a
#: candidate for this image.
FREECAD_VERSION = "1.1.3"

freecad_image = (
    modal.Image.micromamba(python_version="3.11")
    .micromamba_install(f"freecad={FREECAD_VERSION}", channels=["conda-forge"])
    # conda-forge ships the bindings as /opt/conda/lib/FreeCAD.so rather than
    # into site-packages, so a plain `import FreeCAD` fails with a bare
    # ModuleNotFoundError even though FreeCAD is fully installed. The lib dir
    # has to be on PYTHONPATH for both this process and the build subprocess.
    .env({"PYTHONPATH": "/root:/opt/conda/lib"})
    .add_local_dir("orion", "/root/orion")
    .add_local_dir("freecad", "/root/freecad")
)

app = modal.App("orionflow-builder")


@app.function(
    image=freecad_image,
    cpu=2,
    memory=4096,
    # OCC can wedge on pathological geometry. Bounded here as well as in the
    # caller, so a stuck kernel cannot hold a container open indefinitely.
    timeout=300,
    scaledown_window=300,
)
def build_blueprint(graph: dict, mesh_body: bool = False) -> dict:
    """Compile a resolved FeatureGraph; return measurements and artifacts.

    ``mesh_body`` additionally tessellates the body at three deflections, which
    a ``body_mesh_converged`` assertion is checked against. Without it that
    assertion has nothing to evaluate and reads as a failure — refusing a part
    that is actually correct.

    Returns ``{"build_log": {...}, "measured": {...}|None,
    "artifacts": {"part.step": bytes, "part.stl": bytes}}``. A failed build is
    a normal return with ``measured=None`` and the kernel's own stderr in the
    log — the caller has to be able to show the user why.
    """
    import json
    import os
    import subprocess
    import sys
    import tempfile

    workdir = tempfile.mkdtemp(prefix="bp_")
    gpath = os.path.join(workdir, "graph.json")
    with open(gpath, "w", encoding="utf-8") as fh:
        json.dump(graph, fh)

    step = os.path.join(workdir, "part.step")
    stl = os.path.join(workdir, "part.stl")
    fcstd = os.path.join(workdir, "part.FCStd")
    topology = os.path.join(workdir, "part.topology.json")
    mpath = os.path.join(workdir, "measured.json")

    cmd = [sys.executable, "/root/orion/build_export_fc.py",
           "--graph", gpath, "--fcstd", fcstd,
           "--out", mpath, "--step", step, "--stl", stl,
           "--topology", topology]
    if mesh_body:
        cmd.append("--mesh-body")

    timed_out = False
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=270,
        )
        returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        returncode, timed_out = -9, True
        stdout, stderr = "", "the kernel did not converge within 270s"

    log = {"returncode": returncode, "stdout": stdout[-4000:],
           "stderr": stderr[-4000:], "timeout": timed_out}

    measured = None
    if returncode == 0 and os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            measured = json.load(fh)

    # The FCStd is returned alongside the exchange formats, not instead of
    # them, and it is the one that must never be dropped. STEP and STL are
    # derived views: they carry the final solid and nothing about how it was
    # arrived at. The FCStd carries the parametric document itself — the
    # sketches, the feature history, the expressions binding dimensions to
    # named variables — which is what makes a build re-openable, re-tunable and
    # usable as training evidence. It was already written here and thrown away
    # with the container; the STEP was the only thing that survived, so every
    # part this system has ever built lost its history at the container
    # boundary.
    # The topology sidecar travels with them and can only be made here. It says
    # which feature authored each face, which is a property of the document's
    # feature tree — a STEP is a finished solid and has no tree at all, so once
    # this container exits the mapping is gone for good.
    artifacts = {}
    for name, path in (("part.step", step), ("part.stl", stl),
                       ("part.FCStd", fcstd), ("part.topology.json", topology)):
        if os.path.exists(path):
            with open(path, "rb") as fh:
                artifacts[name] = fh.read()

    return {"build_log": log, "measured": measured, "artifacts": artifacts}


@app.function(
    image=freecad_image,
    cpu=2,
    # An assembly holds every component's shape in memory at once before it
    # fuses them, so it needs more headroom than a single part. A three-planet
    # stage is four involute gears, each a few hundred faces.
    memory=8192,
    # Longer than build_blueprint's 300s: this one call replaces what used to
    # be N+1 separate builds, so its budget has to cover all of them. The
    # runner is still bounded inside, and the caller bounds it again.
    timeout=1800,
    scaledown_window=300,
)
def build_assembly_graphs(spec: dict) -> dict:
    """Compile, place, fuse and measure an assembly. One FreeCAD process.

    The assembly counterpart to :func:`build_blueprint`, and deliberately the
    same shape of contract: a *failed build* is a normal return carrying
    ``error``, an unreachable builder is the caller's problem, and artifacts
    come back as bytes so the API container never needs a filesystem the
    builder can see.

    ``spec`` is ``{"components": [{"id", "graph", "pos", "rot_z"}]}`` — every
    placement already a number, every component already a resolved
    FeatureGraph. Nothing here evaluates an expression or knows what a
    Blueprint is: that arithmetic stays in the API container, which is what
    keeps this function a kernel and not a second copy of the design logic.

    Returns ``{"components": [{"id", "measured"}], "assembly": {...},
    "artifacts": {"assembly.step": bytes, "assembly.stl": bytes,
    "<id>.FCStd": bytes}, "error": {"reason", "detail"} | None}``.
    """
    import json
    import os
    import subprocess
    import sys
    import tempfile

    workdir = tempfile.mkdtemp(prefix="asm_")
    spath = os.path.join(workdir, "assembly.spec.json")
    mpath = os.path.join(workdir, "assembly.measured.json")
    step = os.path.join(workdir, "assembly.step")
    stl = os.path.join(workdir, "assembly.stl")
    with open(spath, "w", encoding="utf-8") as fh:
        json.dump(spec, fh)

    cmd = [sys.executable, "/root/orion/build_assembly_fc.py",
           "--spec", spath, "--out", mpath, "--workdir", workdir,
           "--step", step, "--stl", stl]

    timed_out = False
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1680)
        returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        returncode, timed_out = -9, True
        stdout, stderr = "", "the kernel did not converge"

    log = {"returncode": returncode, "stdout": stdout[-4000:],
           "stderr": stderr[-4000:], "timeout": timed_out}

    payload = None
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            payload = None

    if payload is None or payload.get("error"):
        error = (payload or {}).get("error") or {
            "reason": "placement_failed",
            "detail": ("the kernel did not finish in time" if timed_out
                       else (stderr or "the kernel produced no measurement")[-400:]),
        }
        return {"build_log": log, "components": [], "assembly": {},
                "artifacts": {}, "error": error}

    # The component FCStd files travel back with the assembly for the same
    # reason a single part's does: they carry the parametric document — the
    # sketches and the feature tree — and they only exist inside this
    # container. The STEP is the finished solid and remembers none of it.
    artifacts = {}
    for name, path in [("assembly.step", step), ("assembly.stl", stl)]:
        if os.path.exists(path):
            with open(path, "rb") as fh:
                artifacts[name] = fh.read()
    for comp in payload.get("components") or []:
        fcstd = comp.get("fcstd")
        if fcstd and os.path.exists(fcstd):
            with open(fcstd, "rb") as fh:
                artifacts[os.path.basename(fcstd)] = fh.read()
        # The builder's own paths mean nothing to the caller.
        comp.pop("fcstd", None)

    return {"build_log": log, "components": payload.get("components") or [],
            "assembly": payload.get("assembly") or {},
            "artifacts": artifacts, "error": None}


@app.function(image=freecad_image, cpu=2, memory=4096, timeout=600)
def freecad_version() -> dict:
    """What FreeCAD this container actually has.

    The corpus was verified under FreeCAD 1.1 on Windows; conda-forge may ship
    something else. Version skew here would mean geometry that disagrees with
    the frozen predictions, so it is worth being able to ask directly.
    """
    import FreeCAD  # noqa: PLC0415

    return {
        "version": list(FreeCAD.Version()),
        "build_date": FreeCAD.BuildVersionMajor
        if hasattr(FreeCAD, "BuildVersionMajor") else None,
    }
