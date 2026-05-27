"""
Sandbox for executing user-supplied build123d code and validating the result.

Pulled out of the original single-file `studio.py` so the FastAPI app stays
focused on routing.
"""
from __future__ import annotations

import io
import sys
import time
import uuid
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


STRIP_PREFIXES = (
    "export_step(",
    "export_stl(",
    "export_gltf(",
    "show(",
    "show_object(",
)

RESULT_NAMES = ("result", "part", "solid", "model", "shape")


@dataclass
class RunArtifact:
    """Files produced for a successful compile."""
    model_id: str
    glb_path: Path
    step_path: Path
    stl_path: Path

    def urls(self, mount: str = "/models") -> Dict[str, str]:
        return {
            "glb_url": f"{mount}/{self.glb_path.name}",
            "step_url": f"{mount}/{self.step_path.name}",
            "stl_url": f"{mount}/{self.stl_path.name}",
        }


def strip_io_lines(code: str) -> str:
    """Drop any export_*/show* calls so the user's snippet can't write files
    or open viewers on the server."""
    keep = []
    for line in code.splitlines():
        s = line.strip()
        if any(s.startswith(p) for p in STRIP_PREFIXES):
            continue
        keep.append(line)
    return "\n".join(keep)


def find_result(ns: dict) -> Any:
    """Locate the geometry the user wants exported."""
    for name in RESULT_NAMES:
        if name in ns:
            obj = ns[name]
            if hasattr(obj, "part") and not hasattr(obj, "wrapped"):
                return obj.part
            return obj
    return None


def validate_shape(shape) -> Dict[str, Any]:
    """Cheap geometry report (volume, bbox, topology, watertight)."""
    report: Dict[str, Any] = {}
    try:
        report["volume_mm3"] = round(float(shape.volume), 4)
    except Exception as e:
        report["volume_error"] = str(e)
    try:
        bb = shape.bounding_box()
        report["bbox"] = {
            "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
            "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
            "size": [
                round(bb.max.X - bb.min.X, 3),
                round(bb.max.Y - bb.min.Y, 3),
                round(bb.max.Z - bb.min.Z, 3),
            ],
            "center": [
                round((bb.min.X + bb.max.X) / 2, 3),
                round((bb.min.Y + bb.max.Y) / 2, 3),
                round((bb.min.Z + bb.max.Z) / 2, 3),
            ],
        }
    except Exception as e:
        report["bbox_error"] = str(e)
    try:
        report["topology"] = {
            "faces": len(shape.faces()),
            "edges": len(shape.edges()),
            "vertices": len(shape.vertices()),
        }
    except Exception as e:
        report["topology_error"] = str(e)
    try:
        from OCP.BRepCheck import BRepCheck_Analyzer
        report["watertight"] = bool(BRepCheck_Analyzer(shape.wrapped).IsValid())
    except Exception as e:
        report["watertight_error"] = str(e)
    return report


def inspect_faces(shape, max_faces: int = 256) -> list[Dict[str, Any]]:
    """Per-face summary for the inspector panel (centre + area)."""
    out = []
    try:
        for idx, f in enumerate(shape.faces()):
            if idx >= max_faces:
                break
            try:
                c = f.center()
                out.append(
                    {
                        "index": idx,
                        "center": [round(c.X, 3), round(c.Y, 3), round(c.Z, 3)],
                        "area": round(float(f.area), 3),
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    return out


def execute_code(code: str, output_dir: Path) -> Dict[str, Any]:
    """
    Run the snippet, locate `result`, export STEP/STL/GLB, return a dict
    suitable for JSON serialisation.
    """
    code = strip_io_lines(code)
    ns: dict = {}
    stdout_buf = io.StringIO()
    real_stdout = sys.stdout
    t0 = time.time()
    try:
        exec("from build123d import *", ns)
        sys.stdout = stdout_buf
        exec(code, ns)
    except Exception as e:
        sys.stdout = real_stdout
        return {
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "stdout": stdout_buf.getvalue(),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
    finally:
        sys.stdout = real_stdout

    shape = find_result(ns)
    if shape is None:
        available = [k for k in ns if not k.startswith("_") and k != "build123d"]
        return {
            "ok": False,
            "error_type": "NoResultVar",
            "error": "No `result`, `part`, `solid`, `model`, or `shape` variable found.",
            "available_vars": available,
            "stdout": stdout_buf.getvalue(),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    model_id = uuid.uuid4().hex[:12]
    glb_path = output_dir / f"{model_id}.glb"
    step_path = output_dir / f"{model_id}.step"
    stl_path = output_dir / f"{model_id}.stl"

    try:
        from build123d import export_gltf, export_step, export_stl
        export_gltf(shape, str(glb_path), binary=True)
        export_step(shape, str(step_path))
        export_stl(shape, str(stl_path))
    except Exception as e:
        return {
            "ok": False,
            "error_type": "ExportError",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "stdout": stdout_buf.getvalue(),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    artifact = RunArtifact(model_id, glb_path, step_path, stl_path)
    return {
        "ok": True,
        "model_id": artifact.model_id,
        **artifact.urls(),
        "validation": validate_shape(shape),
        "faces": inspect_faces(shape),
        "stdout": stdout_buf.getvalue(),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
