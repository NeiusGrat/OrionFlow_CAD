"""Validate OFL code strings by executing them in isolated subprocesses."""

from __future__ import annotations

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
    # validator.py -> data_pipeline -> orionflow_ofl -> repo root
    return str(here.parent.parent.parent)


def _validate_one(ofl_code: str, timeout: int) -> dict:
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

        # find any .step file produced
        step_files = list(Path(tmp_dir).glob("*.step"))
        if not step_files:
            return {
                "valid": False,
                "step_file_size": 0,
                "error": "no STEP file produced",
                "execution_time_ms": round(elapsed, 1),
            }
        size = step_files[0].stat().st_size
        if size < 100:
            return {
                "valid": False,
                "step_file_size": size,
                "error": f"STEP file too small ({size} bytes)",
                "execution_time_ms": round(elapsed, 1),
            }
        return {
            "valid": True,
            "step_file_size": size,
            "error": None,
            "execution_time_ms": round(elapsed, 1),
        }

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
        # cleanup
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
    """Validates OFL code strings by actually executing them."""

    def validate(self, ofl_code: str, timeout: int = 30) -> dict:
        return _validate_one(ofl_code, timeout)

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

        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_validate_one, p["code"], 30): idx
                for idx, p in enumerate(pairs)
            }
            done_count = 0
            for future in as_completed(future_map):
                idx = future_map[future]
                res = future.result()
                pair_with_result = {**pairs[idx], **res}
                if res["valid"]:
                    valid_pairs.append(pair_with_result)
                else:
                    invalid_pairs.append(pair_with_result)
                    err_key = (res.get("error") or "unknown")[:80]
                    error_summary[err_key] = error_summary.get(err_key, 0) + 1
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
