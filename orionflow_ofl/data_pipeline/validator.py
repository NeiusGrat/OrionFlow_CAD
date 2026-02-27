"""Validate OFL code strings by executing them in isolated subprocesses.

Default behavior is MVP-friendly:
- run the code
- require a STEP file
- require STEP file size >= 100 bytes

Optional strict geometry checks can be enabled for higher dataset quality:
- volume > min_volume
- bounding box extents > min_bbox_extent
- face count <= max_face_count (optional)
- single connected solid (optional)
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def _project_root() -> str:
    """Return the repo root (parent of orionflow_ofl/)."""
    here = Path(__file__).resolve()
    return str(here.parent.parent.parent)


def _inspect_step_geometry(step_path: Path, timeout: int) -> tuple[dict | None, str | None]:
    """Inspect STEP geometry in a short-lived subprocess.

    Running this in a separate process avoids file-handle locking issues on Windows.
    """
    probe = (
        "import json, sys\n"
        "from build123d import import_step\n"
        "shape = import_step(sys.argv[1])\n"
        "bbox = shape.bounding_box()\n"
        "size = [float(bbox.size.X), float(bbox.size.Y), float(bbox.size.Z)]\n"
        "volume = float(getattr(shape, 'volume', 0.0))\n"
        "face_count = len(shape.faces()) if hasattr(shape, 'faces') else 0\n"
        "solid_count = len(shape.solids()) if hasattr(shape, 'solids') else 0\n"
        "print(json.dumps({'volume': volume, 'bbox': size, 'face_count': face_count, 'solid_count': solid_count}))\n"
    )

    try:
        probe_timeout = max(5, min(timeout, 20))
        result = subprocess.run(
            [sys.executable, "-c", probe, str(step_path)],
            capture_output=True,
            timeout=probe_timeout,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None, "geometry inspection timeout"
    except Exception as exc:
        return None, f"geometry inspection failed: {str(exc)[:200]}"

    if result.returncode != 0:
        err = result.stderr.strip() if result.stderr else "probe exited non-zero"
        return None, f"geometry inspection failed: {err[:200]}"

    stdout = result.stdout.strip()
    if not stdout:
        return None, "geometry inspection returned no output"

    try:
        metrics = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError:
        return None, "geometry inspection returned invalid JSON"

    return metrics, None


def _validate_one(
    ofl_code: str,
    timeout: int,
    min_step_size_bytes: int,
    strict_geometry: bool,
    min_volume: float,
    min_bbox_extent: float,
    max_face_count: int | None,
    require_single_solid: bool,
) -> dict:
    """Run a single validation in the current process (called via pool)."""
    tmp_dir = tempfile.mkdtemp(prefix="ofl_val_")
    script_path = os.path.join(tmp_dir, "ofl_test.py")

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(ofl_code)

        env = os.environ.copy()
        root = _project_root()
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")

        t0 = time.perf_counter()
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            timeout=timeout,
            cwd=tmp_dir,
            text=True,
            env=env,
        )
        elapsed = (time.perf_counter() - t0) * 1000

        if result.returncode != 0:
            return {
                "valid": False,
                "step_file_size": 0,
                "error": result.stderr.strip()[-500:] if result.stderr else "non-zero exit",
                "execution_time_ms": round(elapsed, 1),
            }

        step_files = list(Path(tmp_dir).glob("*.step"))
        if not step_files:
            return {
                "valid": False,
                "step_file_size": 0,
                "error": "no STEP file produced",
                "execution_time_ms": round(elapsed, 1),
            }

        size = step_files[0].stat().st_size
        if size < min_step_size_bytes:
            return {
                "valid": False,
                "step_file_size": size,
                "error": f"STEP file too small ({size} bytes)",
                "execution_time_ms": round(elapsed, 1),
            }

        geometry_metrics = None
        if strict_geometry:
            geometry_metrics, inspect_err = _inspect_step_geometry(step_files[0], timeout=timeout)
            if inspect_err is not None:
                return {
                    "valid": False,
                    "step_file_size": size,
                    "error": inspect_err,
                    "execution_time_ms": round(elapsed, 1),
                }

            volume = float(geometry_metrics.get("volume", 0.0))
            if not math.isfinite(volume) or volume <= min_volume:
                return {
                    "valid": False,
                    "step_file_size": size,
                    "error": f"volume check failed (volume={volume})",
                    "execution_time_ms": round(elapsed, 1),
                    "geometry_metrics": geometry_metrics,
                }

            bbox_raw = geometry_metrics.get("bbox", [])
            try:
                bbox = [float(v) for v in bbox_raw]
            except Exception:
                bbox = []

            bbox_ok = len(bbox) == 3 and all(math.isfinite(v) and v > min_bbox_extent for v in bbox)
            if not bbox_ok:
                return {
                    "valid": False,
                    "step_file_size": size,
                    "error": f"bounding box sanity failed (bbox={bbox_raw})",
                    "execution_time_ms": round(elapsed, 1),
                    "geometry_metrics": geometry_metrics,
                }

            face_count = int(geometry_metrics.get("face_count", 0))
            if max_face_count is not None and face_count > max_face_count:
                return {
                    "valid": False,
                    "step_file_size": size,
                    "error": f"face count too high ({face_count} > {max_face_count})",
                    "execution_time_ms": round(elapsed, 1),
                    "geometry_metrics": geometry_metrics,
                }

            solid_count = int(geometry_metrics.get("solid_count", 0))
            if require_single_solid and solid_count != 1:
                return {
                    "valid": False,
                    "step_file_size": size,
                    "error": f"disconnected geometry ({solid_count} solids)",
                    "execution_time_ms": round(elapsed, 1),
                    "geometry_metrics": geometry_metrics,
                }

        out = {
            "valid": True,
            "step_file_size": size,
            "error": None,
            "execution_time_ms": round(elapsed, 1),
        }
        if geometry_metrics is not None:
            out["geometry_metrics"] = geometry_metrics
        return out

    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "step_file_size": 0,
            "error": "timeout",
            "execution_time_ms": timeout * 1000,
        }
    except Exception as exc:
        return {
            "valid": False,
            "step_file_size": 0,
            "error": str(exc)[:500],
            "execution_time_ms": 0,
        }
    finally:
        for f in Path(tmp_dir).iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


class OFLValidator:
    """Validate OFL code strings by executing them."""

    def __init__(
        self,
        min_step_size_bytes: int = 100,
        strict_geometry: bool = False,
        min_volume: float = 0.0,
        min_bbox_extent: float = 1e-6,
        max_face_count: int | None = None,
        require_single_solid: bool = False,
    ):
        self.min_step_size_bytes = int(min_step_size_bytes)
        self.strict_geometry = bool(strict_geometry)
        self.min_volume = float(min_volume)
        self.min_bbox_extent = float(min_bbox_extent)
        self.max_face_count = max_face_count
        self.require_single_solid = bool(require_single_solid)

    def validate(self, ofl_code: str, timeout: int = 30) -> dict:
        return _validate_one(
            ofl_code,
            timeout,
            self.min_step_size_bytes,
            self.strict_geometry,
            self.min_volume,
            self.min_bbox_extent,
            self.max_face_count,
            self.require_single_solid,
        )

    def batch_validate(
        self,
        pairs: list[dict],
        max_workers: int = 4,
        progress: bool = True,
    ) -> dict:
        """Validate a batch of training pairs.

        Each pair dict must have a ``"code"`` key.
        Returns stats + separated valid / invalid lists.
        """
        total = len(pairs)
        valid_pairs: list[dict] = []
        invalid_pairs: list[dict] = []
        error_summary: dict[str, int] = {}

        def _consume_result(idx: int, res: dict) -> None:
            pair_with_result = {**pairs[idx], **res}
            if res["valid"]:
                valid_pairs.append(pair_with_result)
            else:
                invalid_pairs.append(pair_with_result)
                err_key = (res.get("error") or "unknown")[:80]
                error_summary[err_key] = error_summary.get(err_key, 0) + 1

        done_count = 0

        if max_workers <= 1:
            for idx, pair in enumerate(pairs):
                res = self.validate(pair["code"], timeout=30)
                _consume_result(idx, res)
                done_count += 1
                if progress and done_count % 10 == 0:
                    print(f"  validated {done_count}/{total}")
        else:
            try:
                with ProcessPoolExecutor(max_workers=max_workers) as pool:
                    future_map = {
                        pool.submit(
                            _validate_one,
                            p["code"],
                            30,
                            self.min_step_size_bytes,
                            self.strict_geometry,
                            self.min_volume,
                            self.min_bbox_extent,
                            self.max_face_count,
                            self.require_single_solid,
                        ): idx
                        for idx, p in enumerate(pairs)
                    }
                    for future in as_completed(future_map):
                        idx = future_map[future]
                        res = future.result()
                        _consume_result(idx, res)
                        done_count += 1
                        if progress and done_count % 10 == 0:
                            print(f"  validated {done_count}/{total}")
            except (PermissionError, OSError) as exc:
                if progress:
                    print(f"  process pool unavailable ({exc}); falling back to sequential validation")
                for idx, pair in enumerate(pairs):
                    res = self.validate(pair["code"], timeout=30)
                    _consume_result(idx, res)
                    done_count += 1
                    if progress and done_count % 10 == 0:
                        print(f"  validated {done_count}/{total}")

        return {
            "total": total,
            "valid": len(valid_pairs),
            "invalid": len(invalid_pairs),
            "error_summary": error_summary,
            "valid_pairs": valid_pairs,
            "invalid_pairs": invalid_pairs,
        }
