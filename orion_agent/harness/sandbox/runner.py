"""Sandbox runner — executed as a subprocess, never imported by the harness.

Reads a JSON job from a file given as ``argv[1]``:

    {
      "code": "<build123d python>",
      "result_var": "result",
      "scratch_dir": "<dir>",
      "exports": ["step", "stl", "glb"],
      "result_path": "<json out>"
    }

Executes the code in a clean namespace with ``build123d`` imported, captures
stdout/stderr and exceptions, exports the chosen formats, and writes a
structured result + topology summary to ``result_path``.

This module must stay importable with only ``build123d`` (+ optional trimesh)
available — it runs in the capped child process.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout


def _topology_summary(shape) -> dict:
    """Compact, token-bounded topology of a build123d result object."""
    summary: dict = {}
    try:
        solids = shape.solids()
        faces = shape.faces()
        edges = shape.edges()
        vertices = shape.vertices()
        summary["solids"] = len(solids)
        summary["faces"] = len(faces)
        summary["edges"] = len(edges)
        summary["vertices"] = len(vertices)

        face_types: dict[str, int] = {}
        for f in faces:
            t = getattr(f, "geom_type", None)
            t = str(t() if callable(t) else t)
            face_types[t] = face_types.get(t, 0) + 1
        summary["surface_types"] = face_types
        summary["cylindrical_faces"] = face_types.get("CYLINDER", 0) + face_types.get(
            "Cylinder", 0
        )
    except Exception as exc:  # noqa: BLE001
        summary["topology_error"] = str(exc)

    try:
        bb = shape.bounding_box()
        summary["bounding_box"] = {
            "min": [round(bb.min.X, 4), round(bb.min.Y, 4), round(bb.min.Z, 4)],
            "max": [round(bb.max.X, 4), round(bb.max.Y, 4), round(bb.max.Z, 4)],
            "size": [round(bb.size.X, 4), round(bb.size.Y, 4), round(bb.size.Z, 4)],
        }
    except Exception:  # noqa: BLE001
        pass
    try:
        summary["volume"] = round(float(shape.volume), 4)
    except Exception:  # noqa: BLE001
        pass
    return summary


def _export(shape, scratch_dir: str, exports: list[str]) -> list[dict]:
    from build123d import export_step, export_stl  # type: ignore

    artifacts: list[dict] = []
    base = os.path.join(scratch_dir, "orion_result")
    for fmt in exports:
        try:
            if fmt == "step":
                path = base + ".step"
                export_step(shape, path)
            elif fmt == "stl":
                path = base + ".stl"
                export_stl(shape, path)
            elif fmt == "glb":
                path = base + ".glb"
                _export_glb(shape, path)
            else:
                continue
            if os.path.exists(path):
                artifacts.append({"kind": fmt, "path": path})
        except Exception as exc:  # noqa: BLE001
            artifacts.append({"kind": fmt, "path": "", "error": str(exc)})
    return artifacts


def _export_glb(shape, path: str) -> None:
    # build123d can export STL; convert to GLB via trimesh if present.
    from build123d import export_stl  # type: ignore

    stl_tmp = path + ".tmp.stl"
    export_stl(shape, stl_tmp)
    try:
        import trimesh  # type: ignore

        mesh = trimesh.load(stl_tmp)
        mesh.export(path)
    finally:
        if os.path.exists(stl_tmp):
            os.remove(stl_tmp)


def main() -> int:
    job_path = sys.argv[1]
    with open(job_path, "r", encoding="utf-8") as fh:
        job = json.load(fh)

    code = job["code"]
    result_var = job.get("result_var", "result")
    scratch_dir = job["scratch_dir"]
    exports = job.get("exports", ["step", "stl"])
    result_path = job["result_path"]
    os.makedirs(scratch_dir, exist_ok=True)

    out, err = io.StringIO(), io.StringIO()
    result = {
        "ok": False,
        "stdout": "",
        "stderr": "",
        "error": "",
        "artifacts": [],
        "topology": {},
    }

    namespace: dict = {"__name__": "__orion_sandbox__"}
    try:
        import build123d  # type: ignore

        # The sandbox auto-exports the `result` shape, so the model's own
        # export_* calls are redundant. Models also frequently swap the argument
        # order (path, shape) which crashes the real exporters. Patch them on the
        # module itself so even `from build123d import *` in the user code picks
        # up the tolerant wrappers (this subprocess is throwaway).
        for _exp in ("export_step", "export_stl", "export_gltf", "export_brep"):
            _real = getattr(build123d, _exp, None)
            if _real is not None and not getattr(_real, "_orion_tolerant", False):
                setattr(build123d, _exp, _tolerant_export(_real))

        namespace["build123d"] = build123d
        for name in dir(build123d):
            if not name.startswith("_"):
                namespace[name] = getattr(build123d, name)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"build123d unavailable: {exc}"
        _write(result_path, result)
        return 1

    try:
        with redirect_stdout(out), redirect_stderr(err):
            exec(compile(code, "<orion_code>", "exec"), namespace)  # noqa: S102
        shape = namespace.get(result_var)
        if shape is None:
            result["error"] = (
                f"code did not assign a result to '{result_var}'"
            )
        else:
            # build123d BuildPart context exposes .part
            if hasattr(shape, "part") and not hasattr(shape, "solids"):
                shape = shape.part
            result["topology"] = _topology_summary(shape)
            result["artifacts"] = _export(shape, scratch_dir, exports)
            result["ok"] = True
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc(limit=6)
    finally:
        result["stdout"] = out.getvalue()[-4000:]
        result["stderr"] = err.getvalue()[-4000:]
        _write(result_path, result)
    return 0 if result["ok"] else 1


def _tolerant_export(real):
    """Wrap a build123d ``export_*`` so it tolerates a swapped (path, shape)
    argument order and never raises — the sandbox exports ``result`` itself."""

    def shim(*args, **kwargs):
        shape = None
        path = None
        for a in args:
            if isinstance(a, str) and path is None:
                path = a
            elif shape is None:
                shape = a
        if shape is None:
            shape = kwargs.get("to_export")
        if path is None:
            path = kwargs.get("file_path") or kwargs.get("path")
        try:
            if shape is not None and isinstance(path, str):
                return real(shape, path)
        except Exception:  # noqa: BLE001
            return None
        return None

    shim._orion_tolerant = True
    return shim


def _write(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


if __name__ == "__main__":
    sys.exit(main())
