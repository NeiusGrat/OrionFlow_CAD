"""Assemblies reach a CAD kernel the same way single parts do.

Single-part builds have dispatched through ``ORION_BUILDER_MODE`` to the
FreeCAD-capable ``orionflow-builder`` container since the studio went live. The
assembly path did not: ``orion.assembly.build_assembly`` called
``freecad_python()`` directly, which resolves a **local** interpreter. The API
image is debian-slim + pip and deliberately has no FreeCAD, so every assembly
request in production died at ``orion/freecad_python.py`` and the user was shown

    no FreeCAD interpreter found; set ORION_FREECAD_PYTHON to one that can
    `import FreeCAD`

— an internal environment variable, in answer to a request for a gearbox.

These tests are about the *dispatch*, not the geometry: whether the kernel step
goes where it is configured to go, and what a user is told when it cannot. The
geometry is covered by ``test_assemblies.py`` and by the end-to-end run.
"""

import json
import os
import sys
import types

import pytest

from orion import assembly as A


# --------------------------------------------------------------------------- #
# a spec that needs no kernel to talk about
# --------------------------------------------------------------------------- #
@pytest.fixture()
def spec():
    """A real two-component spec, resolved exactly as the live path resolves it."""
    from app.services import assembly_service
    from orion import assembly_spec as S

    raw = assembly_service.catalogue()["bearing_stack"].make(
        {"bore": 30.0, "ring_t": 5.0, "ball_gap": 6.0, "width": 16.0,
         "shaft_len": 90.0}
    )
    return S.resolve_spec(raw)


def _kernel_result(spec):
    """What a kernel returns for ``spec``, with every assertion satisfied.

    Built from the spec's own components so the per-component assertion check
    in zone 3 has something coherent to read; the numbers do not need to be
    physical because no assertion in this file is about geometry.
    """
    return {
        "components": [{"id": p["id"], "measured": {}} for p in spec["parts"]],
        "assembly": {
            "parts": [{"id": p["id"], "volume": 1.0} for p in spec["parts"]],
            "sum_volume": float(len(spec["parts"])),
            "fused_volume": float(len(spec["parts"])),
            "solids": len(spec["parts"]),
            "watertight": True,
            "bbox": [0.0, 0.0, 0.0, 62.0, 62.0, 16.0],
            "step": "/tmp/a.step",
            "stl": "/tmp/a.stl",
        },
    }


# --------------------------------------------------------------------------- #
# A. the API container must not reach for a local FreeCAD
# --------------------------------------------------------------------------- #
def test_modal_mode_never_looks_for_a_local_freecad(spec, tmp_path, monkeypatch):
    """Acceptance criterion A, asserted at the one place it can be.

    A test that merely checks the build succeeds would pass on a developer box
    that happens to have FreeCAD installed — which is every box this suite runs
    on, and precisely why the defect survived. So the resolver is poisoned: if
    anything in the modal path so much as *asks* for a local interpreter, this
    fails.
    """
    asked = []

    def _poisoned():
        asked.append(True)
        raise RuntimeError("no FreeCAD interpreter found; set ORION_FREECAD_PYTHON")

    monkeypatch.setattr("orion.freecad_python.freecad_python", _poisoned)

    from app.services import blueprint_service as B

    monkeypatch.setattr(B, "BUILDER_MODE", "modal")
    sent = {}

    class _Fn:
        @staticmethod
        def remote(payload):
            sent["spec"] = payload
            return {"components": [{"id": p["id"], "measured": {}}
                                   for p in spec["parts"]],
                    "assembly": _kernel_result(spec)["assembly"],
                    "artifacts": {}, "error": None}

    fake = types.SimpleNamespace(
        Function=types.SimpleNamespace(from_name=lambda app, fn: _Fn())
    )
    monkeypatch.setitem(sys.modules, "modal", fake)

    out = B.run_assembly_builder({"components": [{"id": "shaft", "graph": {}}]},
                                 str(tmp_path))

    assert asked == [], "modal mode reached for a local FreeCAD interpreter"
    assert sent["spec"]["components"][0]["id"] == "shaft"
    assert out["assembly"]["solids"] == len(spec["parts"])


def test_local_mode_still_uses_the_local_kernel(monkeypatch, tmp_path):
    """Regression guard for boxes that do have FreeCAD: mode 'local' is unchanged."""
    from app.services import blueprint_service as B

    monkeypatch.setattr(B, "BUILDER_MODE", "local")
    called = {}

    def _local(spec, workdir, **kw):
        called["spec"] = spec
        return {"components": [], "assembly": {}}

    monkeypatch.setattr(A, "local_kernel", _local)
    B.run_assembly_builder({"components": []}, str(tmp_path))
    assert "spec" in called, "local mode did not use the local kernel"


# --------------------------------------------------------------------------- #
# B. the remote call reaches the right function on the right app
# --------------------------------------------------------------------------- #
def test_the_assembly_goes_to_the_builder_app_not_the_part_function(
    monkeypatch, tmp_path
):
    """Same app as single parts, its own entrypoint.

    Reusing ``build_blueprint`` would hand a multi-component spec to a function
    that compiles exactly one graph; a *separate* Modal app would be a second
    deployment to configure and keep in step. Neither is what we want.
    """
    from app.services import blueprint_service as B

    monkeypatch.setattr(B, "BUILDER_MODE", "modal")
    resolved = {}

    def _from_name(app_name, fn_name):
        resolved["app"], resolved["fn"] = app_name, fn_name
        return types.SimpleNamespace(
            remote=lambda spec: {"components": [], "assembly": {},
                                 "artifacts": {}, "error": None}
        )

    monkeypatch.setitem(
        sys.modules, "modal",
        types.SimpleNamespace(Function=types.SimpleNamespace(from_name=_from_name)),
    )
    B.run_assembly_builder({"components": []}, str(tmp_path))

    assert resolved["app"] == B.MODAL_BUILDER_APP == "orionflow-builder"
    assert resolved["fn"] == "build_assembly_graphs"
    assert resolved["fn"] != B.MODAL_BUILDER_FN, "reused the single-part function"


def test_remote_artifacts_land_in_the_workdir_like_a_local_build(
    monkeypatch, tmp_path
):
    """Everything downstream must not be able to tell the modes apart.

    ``assembly_service`` copies ``step``/``stl`` out of the result by path, so
    the remote kernel has to leave real files where the local one does.
    """
    from app.services import blueprint_service as B

    monkeypatch.setattr(B, "BUILDER_MODE", "modal")
    monkeypatch.setitem(
        sys.modules, "modal",
        types.SimpleNamespace(Function=types.SimpleNamespace(
            from_name=lambda a, f: types.SimpleNamespace(
                remote=lambda spec: {
                    "components": [], "assembly": {"solids": 2},
                    "artifacts": {"assembly.step": b"ISO-10303-21;",
                                  "assembly.stl": b"solid x",
                                  "sun.FCStd": b"PK\\x03\\x04"},
                    "error": None,
                }
            )
        )),
    )
    out = B.run_assembly_builder({"components": []}, str(tmp_path))

    assert os.path.exists(out["assembly"]["step"])
    assert os.path.exists(out["assembly"]["stl"])
    with open(out["assembly"]["step"], "rb") as fh:
        assert fh.read().startswith(b"ISO-10303-21")
    # The component document travels back too — it only exists in the builder.
    assert (tmp_path / "sun.FCStd").exists()


# --------------------------------------------------------------------------- #
# D. what the user is told
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "reason,expected",
    [
        ("builder_unavailable", "not reachable right now"),
        ("kernel_unavailable", "No CAD kernel is available"),
        ("component_failed", "could not be built as dimensioned"),
        ("placement_failed", "could not be placed and joined"),
        ("export_failed", "could not be written"),
    ],
)
def test_every_kernel_failure_has_a_sentence_for_the_user(reason, expected):
    from app.services import assembly_service as S

    msg = S._kernel_message(A.AssemblyKernelError(reason, "raw internal detail"))
    assert expected in msg


@pytest.mark.parametrize("reason", ["builder_unavailable", "kernel_unavailable",
                                    "component_failed", "placement_failed",
                                    "export_failed"])
def test_no_failure_ever_leaks_the_environment_variable(reason):
    """The defect this whole change exists to remove, pinned per reason."""
    from app.services import assembly_service as S

    exc = A.AssemblyKernelError(
        reason,
        "no FreeCAD interpreter found; set ORION_FREECAD_PYTHON to one that "
        "can `import FreeCAD`",
    )
    msg = S._kernel_message(exc)
    assert "ORION_FREECAD_PYTHON" not in msg
    assert "import FreeCAD" not in msg


def test_infrastructure_details_are_logged_not_shown(monkeypatch):
    """A hostname or a stack trace is evidence for us, not for the user."""
    from app.services import assembly_service as S

    exc = A.AssemblyKernelError(
        "builder_unavailable", "Connection refused to 10.0.4.19:443")
    assert "10.0.4.19" not in S._kernel_message(exc)

    # A geometry failure is different: its detail is the useful part.
    geo = A.AssemblyKernelError("component_failed", "component 'sun': bore > root")
    assert "bore > root" in S._kernel_message(geo)


def test_a_kernel_failure_becomes_a_refusal_carrying_its_reason(
    monkeypatch, tmp_path
):
    """End to end through the service: no exception escapes, the reason survives."""
    from app.services import assembly_service as S

    def _boom(spec, workdir, tag, kernel=None):
        raise A.AssemblyKernelError("builder_unavailable", "socket hung up")

    monkeypatch.setattr(A, "build_assembly", _boom)
    out = S.build("bearing_stack", {"bore": 30.0, "ring_t": 5.0,
                                    "ball_gap": 6.0, "width": 16.0,
                                    "shaft_len": 90.0})

    assert out["success"] is False
    assert out["failure_reason"] == "builder_unavailable"
    assert out["verification"]["verdict"] == "refused"
    assert "ORION_FREECAD_PYTHON" not in out["error"]
    assert "socket hung up" not in out["error"]


# --------------------------------------------------------------------------- #
# the runner's own failure classification
# --------------------------------------------------------------------------- #
def test_the_runner_records_why_it_failed_rather_than_only_dying(tmp_path):
    """``--out`` carries the reason, so the caller never scrapes stderr.

    Run without FreeCAD on purpose: importing it is the first thing the runner
    does, so this exercises the wrapper rather than the kernel.
    """
    import subprocess

    runner = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "orion", "build_assembly_fc.py")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"components": []}), encoding="utf-8")
    out = tmp_path / "measured.json"

    rc = subprocess.run(
        [sys.executable, runner, "--spec", str(spec), "--out", str(out),
         "--workdir", str(tmp_path)],
        capture_output=True, text=True, timeout=120,
    ).returncode

    assert rc != 0
    assert out.exists(), "the runner died without recording a reason"
    err = json.loads(out.read_text(encoding="utf-8"))["error"]
    assert err["reason"] in ("component_failed", "placement_failed")


def test_a_recorded_failure_is_raised_as_its_own_reason(tmp_path):
    """The reason the failing stage chose is the reason the caller receives."""
    mpath = tmp_path / "m.json"
    mpath.write_text(
        json.dumps({"error": {"reason": "component_failed",
                              "detail": "component 'sun': no solid"}}),
        encoding="utf-8",
    )
    with pytest.raises(A.AssemblyKernelError) as exc:
        A._read_kernel_output(str(mpath), 2, "noise on stderr")
    assert exc.value.reason == "component_failed"
    assert "no solid" in exc.value.detail


def test_a_missing_measurement_is_a_placement_failure_not_a_crash(tmp_path):
    with pytest.raises(A.AssemblyKernelError) as exc:
        A._read_kernel_output(str(tmp_path / "absent.json"), 1, "kernel died")
    assert exc.value.reason == "placement_failed"
    assert "kernel died" in exc.value.detail


def test_a_missing_local_kernel_is_reported_without_the_variable(
    monkeypatch, tmp_path
):
    """Local mode on a box with no FreeCAD: still a clean reason."""
    monkeypatch.setattr(
        "orion.freecad_python.freecad_python",
        lambda: (_ for _ in ()).throw(
            RuntimeError("no FreeCAD interpreter found; set ORION_FREECAD_PYTHON")
        ),
    )
    with pytest.raises(A.AssemblyKernelError) as exc:
        A.local_kernel({"components": []}, str(tmp_path))
    assert exc.value.reason == "kernel_unavailable"
    assert "ORION_FREECAD_PYTHON" not in str(exc.value)


# --------------------------------------------------------------------------- #
# zone separation
# --------------------------------------------------------------------------- #
def test_build_assembly_hands_the_kernel_numbers_not_expressions(spec, tmp_path):
    """Zone 1 resolves every placement, so the kernel needs no evaluator.

    The builder container holds FreeCAD and nothing else of ours that could
    evaluate ``a*cos(th)``. Sending an expression there would work only until
    one appeared in a position, which is where the planetary stage puts them.
    """
    seen = {}

    def _kernel(payload, workdir):
        seen["payload"] = payload
        return _kernel_result(spec)

    A.build_assembly(spec, workdir=str(tmp_path), tag="t", kernel=_kernel)

    for comp in seen["payload"]["components"]:
        assert isinstance(comp["rot_z"], float)
        assert all(isinstance(c, float) for c in comp["pos"])
        assert isinstance(comp["graph"], dict)
        assert "blueprint" not in comp


def test_one_kernel_call_builds_the_whole_assembly(spec, tmp_path):
    """Consolidation: N components, one invocation.

    It used to be N+1 FreeCAD startups — one per component plus one to place
    and fuse — which was most of a planetary stage's build time.
    """
    calls = []

    def _kernel(payload, workdir):
        calls.append(len(payload["components"]))
        return _kernel_result(spec)

    A.build_assembly(spec, workdir=str(tmp_path), tag="t", kernel=_kernel)
    assert calls == [len(spec["parts"])], (
        f"expected one call carrying every component, got {calls}"
    )


# --------------------------------------------------------------------------- #
# the whole path, as production runs it
# --------------------------------------------------------------------------- #
def test_a_studio_assembly_request_reaches_the_remote_builder(
    monkeypatch, tmp_path
):
    """Goal 10, and acceptance criteria A + B + C in one pass.

    Simulates the production API container exactly: ``BUILDER_MODE='modal'``
    and **no local FreeCAD at all** — the resolver raises the way it does on
    debian-slim. Then drives ``assembly_service.build``, the same call the
    studio makes, and asserts the request left the container.

    The poisoned resolver is the load-bearing part. Every box this suite runs
    on has FreeCAD installed, so a test that only checked the result would have
    passed against the old code too, which is how an assembly path that could
    never work in production shipped and stayed shipped.
    """
    from app.services import assembly_service as S
    from app.services import blueprint_service as B

    reached_local_freecad = []
    monkeypatch.setattr(
        "orion.freecad_python.freecad_python",
        lambda: reached_local_freecad.append(True) or "/nonexistent/python",
    )
    monkeypatch.setattr(B, "BUILDER_MODE", "modal")

    dispatched = {}

    def _remote(spec):
        dispatched["components"] = [c["id"] for c in spec["components"]]
        step = tmp_path / "assembly.step"
        step.write_bytes(b"ISO-10303-21;")
        return {
            "components": [{"id": c["id"],
                            "measured": {"body_volume": 1.0, "solids": 1}}
                           for c in spec["components"]],
            "assembly": {
                "parts": [{"id": c["id"], "volume": 1.0}
                          for c in spec["components"]],
                "sum_volume": float(len(spec["components"])),
                "fused_volume": float(len(spec["components"])),
                "solids": len(spec["components"]),
                "watertight": True,
                "bbox": [0.0, 0.0, 0.0, 62.0, 62.0, 16.0],
            },
            "artifacts": {"assembly.step": b"ISO-10303-21;",
                          "assembly.stl": b"solid a"},
            "error": None,
        }

    monkeypatch.setitem(
        sys.modules, "modal",
        types.SimpleNamespace(Function=types.SimpleNamespace(
            from_name=lambda a, f: types.SimpleNamespace(remote=_remote))),
    )

    # Zone 3 grades each component against its own assertions from the returned
    # measurement. Fabricating a measurement that satisfies a bearing ring's
    # closed-form volume would be inventing geometry to make a transport test
    # pass — and would then be checking the fabrication, not the dispatch. The
    # grading itself is covered against real kernel output by
    # ``test_assemblies.py`` and by the end-to-end build.
    from orion import forge

    monkeypatch.setattr(
        forge, "check_assertions",
        lambda bp, measured, analysis=None: [
            {"id": "stub", "passed": True, "kind": "bbox_extent"}],
    )

    out = S.build("bearing_stack", {"bore": 30.0, "ring_t": 5.0,
                                    "ball_gap": 6.0, "width": 16.0,
                                    "shaft_len": 90.0})

    # A — the API container never reached for a kernel of its own.
    assert reached_local_freecad == [], (
        "the API container tried to run FreeCAD locally in modal mode"
    )
    # B — it reached the builder, carrying every component.
    assert dispatched["components"] == ["shaft", "inner_ring", "outer_ring"]
    # C — and the artifact came back through the normal studio bundle.
    assert out["success"] is True
    assert out["files"]["step"].endswith(".step")
    assert out["stats"]["components"] == 3


# --------------------------------------------------------------------------- #
# the viewer's one requirement
# --------------------------------------------------------------------------- #
def test_an_assembly_offers_the_glb_the_viewer_actually_renders(
    monkeypatch, tmp_path
):
    """A verified assembly with no GLB is an empty viewport.

    The studio renders GLB and nothing else: ``Workspace.tsx`` passes
    ``files.glb`` to the viewer, ``Viewer.tsx`` rejects any URL not ending in
    ``.glb``, and ``studioStore`` only calls ``showInViewer`` when that key is
    present. Single parts have always converted their STL; assemblies emitted
    only STEP and STL, so a planetary stage that built and passed all eleven
    checks in production showed the user nothing at all — every check green,
    the STEP downloadable, and a blank screen.
    """
    import trimesh

    from app.config import settings
    from app.services import assembly_service as S

    # A real STL, because the converter is real: a stub would prove nothing
    # about whether an assembly's mesh actually survives the trip.
    stl = tmp_path / "asm.stl"
    trimesh.creation.box(extents=(10.0, 20.0, 30.0)).export(str(stl))
    step = tmp_path / "asm.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")

    def _built(spec, workdir, tag, kernel=None):
        return {
            "tag": tag, "passed": True, "build_ok": True,
            "parts": [{"id": "a", "passed": True, "assertions": []}],
            "assertions": [], "step": str(step), "stl": str(stl),
            "measured": {"parts": [{"id": "a", "volume": 6000.0}],
                         "sum_volume": 6000.0, "fused_volume": 6000.0,
                         "solids": 1, "watertight": True,
                         "bbox": [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]},
        }

    monkeypatch.setattr(A, "build_assembly", _built)
    monkeypatch.setattr(settings, "output_dir", tmp_path / "out")

    out = S.build("bearing_stack", {"bore": 30.0, "ring_t": 5.0,
                                    "ball_gap": 6.0, "width": 16.0,
                                    "shaft_len": 90.0})

    assert "glb" in out["files"], (
        "no GLB: the studio viewer has nothing to render for this assembly"
    )
    assert out["files"]["glb"].endswith(".glb")
    # Same three keys a single part offers the viewer and the download menu.
    assert {"step", "stl", "glb"} <= set(out["files"])

    produced = tmp_path / "out" / os.path.basename(out["files"]["glb"])
    assert produced.exists() and produced.stat().st_size > 0
    assert len(trimesh.load(str(produced)).geometry) >= 1


def test_each_component_is_its_own_node_in_the_assembly_glb(monkeypatch, tmp_path):
    """One node per component, named for it — not one welded body.

    The fused assembly.stl is a single mesh, so a GLB made from it can only
    ever be shown as one undifferentiated lump: no per-part colour, and no way
    to click a planet and be told which it is. The node names are the same ids
    the mates, the per-component verdicts and the assertion rows use, so a
    selection in the viewport resolves back to the engineering record directly.
    """
    import trimesh

    from app.config import settings
    from app.services import assembly_service as S

    parts = {"shaft": (10.0, 10.0, 40.0), "inner_ring": (20.0, 20.0, 8.0),
             "outer_ring": (30.0, 30.0, 8.0)}
    meshes = {}
    for cid, extents in parts.items():
        path = tmp_path / f"{cid}.stl"
        trimesh.creation.box(extents=extents).export(str(path))
        meshes[cid] = str(path)

    fused = tmp_path / "asm.stl"
    trimesh.creation.box(extents=(30.0, 30.0, 40.0)).export(str(fused))
    step = tmp_path / "asm.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")

    def _built(spec, workdir, tag, kernel=None):
        return {
            "tag": tag, "passed": True, "build_ok": True,
            "parts": [{"id": c, "passed": True, "assertions": []} for c in parts],
            "assertions": [], "step": str(step), "stl": str(fused),
            "component_meshes": meshes,
            "measured": {"parts": [{"id": c, "volume": 1.0} for c in parts],
                         "sum_volume": 3.0, "fused_volume": 3.0, "solids": 3,
                         "watertight": True,
                         "bbox": [0.0, 0.0, 0.0, 30.0, 30.0, 40.0]},
        }

    monkeypatch.setattr(A, "build_assembly", _built)
    monkeypatch.setattr(settings, "output_dir", tmp_path / "out")

    out = S.build("bearing_stack", {"bore": 30.0, "ring_t": 5.0,
                                    "ball_gap": 6.0, "width": 16.0,
                                    "shaft_len": 90.0})

    glb = tmp_path / "out" / os.path.basename(out["files"]["glb"])
    loaded = trimesh.load(str(glb))
    assert set(loaded.geometry) == set(parts), (
        f"expected one node per component, got {sorted(loaded.geometry)}"
    )


def test_an_assembly_without_component_meshes_still_gets_a_preview(
    monkeypatch, tmp_path
):
    """Falling back to the fused mesh beats showing the user nothing.

    A single-body preview is worth far more than an empty viewport, so a
    builder that could not write the per-component meshes must not cost the
    user the picture entirely.
    """
    import trimesh

    from app.config import settings
    from app.services import assembly_service as S

    fused = tmp_path / "asm.stl"
    trimesh.creation.box(extents=(10.0, 20.0, 30.0)).export(str(fused))
    step = tmp_path / "asm.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")

    monkeypatch.setattr(A, "build_assembly", lambda *a, **k: {
        "tag": "t", "passed": True, "build_ok": True,
        "parts": [{"id": "a", "passed": True, "assertions": []}],
        "assertions": [], "step": str(step), "stl": str(fused),
        "component_meshes": {},            # the builder gave us none
        "measured": {"parts": [{"id": "a", "volume": 1.0}], "sum_volume": 1.0,
                     "fused_volume": 1.0, "solids": 1, "watertight": True,
                     "bbox": [0.0, 0.0, 0.0, 10.0, 20.0, 30.0]},
    })
    monkeypatch.setattr(settings, "output_dir", tmp_path / "out")

    out = S.build("bearing_stack", {"bore": 30.0, "ring_t": 5.0,
                                    "ball_gap": 6.0, "width": 16.0,
                                    "shaft_len": 90.0})
    assert "glb" in out["files"]
