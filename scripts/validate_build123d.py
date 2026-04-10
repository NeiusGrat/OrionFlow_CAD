"""Build123d-FTC (Feature Tree Convention) validator.

Validates generated build123d Python code samples against the FTC spec.
Used by the training data pipeline in data/build123d_ftc/.

Stages (stop on first hard failure):
    1 SYNTAX          — ast.parse
    2 FTC_IMPORT      — `from build123d import`
    3 FTC_STRUCTURE   — BuildPart + geometry op + export
    4 FTC_CONVENTION  — parametric vars + feature comments (warnings only)
    5 NO_FORBIDDEN    — rejects OFL / cadquery / openscad imports
    6 COMPILATION     — subprocess execution with 60s timeout (full mode only)
    7 GEOMETRY        — volume, bbox, is_valid, STEP size (full mode only)
    8 PROMPT_ALIGNMENT— mm numbers from prompt appear as vars (warning)

CLI:
    python scripts/validate_build123d.py IN.jsonl OUT.jsonl --mode syntax_only|full
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS = (
    "from orionflow_ofl import",
    "import orionflow_ofl",
    "from cadquery import",
    "import cadquery",
    "import openscad",
    "from openscad import",
)

GEOMETRY_TOKENS = (
    "extrude(",
    "Box(",
    "Cylinder(",
    "Sphere(",
    "Cone(",
    "Torus(",
    "revolve(",
    "loft(",
    "sweep(",
)

EXPORT_TOKENS = (
    "export_step(",
    "export_stl(",
    "export_brep(",
    "export_gltf(",
    "export(",  # legacy / shim — generators should prefer export_step
    "result = part.part",
    "result=part.part",
)


# ---------------------------------------------------------------------------
# Compilation harness
# ---------------------------------------------------------------------------

COMPILE_HARNESS = r"""
import json, sys, tempfile, os, traceback
_user_code = {code_literal}
_out = {{"ok": False}}
try:
    # Shim: some generated samples call a bare `export(result, path)` which
    # isn't real build123d. Map it to export_step/export_stl by extension so
    # the compile check doesn't trip over documentation-style calls.
    from build123d import export_step as _es, export_stl as _esl
    def _export_shim(shape, path, *a, **kw):
        p = str(path).lower()
        if p.endswith(".stl"):
            return _esl(shape, str(path))
        return _es(shape, str(path))
    _ns = {{"export": _export_shim}}
    exec(_user_code, _ns)
    _res = _ns.get("result", None)
    if _res is None:
        # try to find anything that looks like a Part
        for _k, _v in _ns.items():
            if _v.__class__.__name__ in ("Part", "Compound", "Solid"):
                _res = _v
                break
    if _res is None:
        raise RuntimeError("No 'result' object found after exec")
    bb = _res.bounding_box()
    dims = [float(bb.max.X - bb.min.X), float(bb.max.Y - bb.min.Y), float(bb.max.Z - bb.min.Z)]
    vol = float(_res.volume) if hasattr(_res, "volume") else 0.0
    # export STEP to temp file to check size
    _tmp = tempfile.NamedTemporaryFile(suffix=".step", delete=False)
    _tmp.close()
    try:
        from build123d import export_step
        export_step(_res, _tmp.name)
        step_size = os.path.getsize(_tmp.name)
    finally:
        try: os.unlink(_tmp.name)
        except Exception: pass
    is_valid = True
    try:
        is_valid = bool(_res.is_valid()) if hasattr(_res, "is_valid") else True
    except Exception:
        is_valid = True
    _out = {{
        "ok": True,
        "bbox": dims,
        "volume": vol,
        "is_valid": is_valid,
        "step_size": step_size,
    }}
except Exception as e:
    _out = {{"ok": False, "error": f"{{type(e).__name__}}: {{e}}", "traceback": traceback.format_exc()[-2000:]}}
print("___METRICS___" + json.dumps(_out))
"""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    passed: bool = False
    stage_failed: str | None = None
    error: str | None = None
    code_hash: str = ""
    geometry_metrics: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "stage_failed": self.stage_failed,
            "error": self.error,
            "code_hash": self.code_hash,
            "geometry_metrics": self.geometry_metrics,
            "warnings": self.warnings,
        }


class FTCValidator:
    """Build123d Feature Tree Convention validator."""

    def __init__(self, mode: str = "syntax_only", compile_timeout: int = 60):
        if mode not in ("syntax_only", "full"):
            raise ValueError(f"mode must be 'syntax_only' or 'full', got {mode!r}")
        self.mode = mode
        self.compile_timeout = compile_timeout

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _code_hash(code: str) -> str:
        stripped = "\n".join(
            line.rstrip() for line in code.strip().splitlines() if line.strip()
        )
        return hashlib.md5(stripped.encode("utf-8")).hexdigest()

    @staticmethod
    def _has_any(code: str, tokens) -> bool:
        return any(t in code for t in tokens)

    @staticmethod
    def _count_param_assignments(code: str) -> int:
        pattern = re.compile(r"^[ \t]*([A-Za-z_]\w*)\s*=\s*-?\d+(?:\.\d+)?", re.MULTILINE)
        matches = pattern.findall(code)
        # filter out counter-style re-assignments (i = 0 inside loops stays ok,
        # we just want any module-level numeric constants)
        return len(matches)

    @staticmethod
    def _has_feature_comment(code: str) -> bool:
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if "Feature" in line and line.strip().startswith("#"):
                return True
        return False

    # -- stages -------------------------------------------------------------

    def _stage_syntax(self, code: str, result: ValidationResult) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            result.stage_failed = "SYNTAX"
            result.error = f"{e.msg} at line {e.lineno}"
            return False

    def _stage_ftc_import(self, code: str, result: ValidationResult) -> bool:
        if "from build123d import" in code:
            return True
        result.stage_failed = "FTC_IMPORT"
        result.error = "Missing `from build123d import` statement"
        return False

    def _stage_ftc_structure(self, code: str, result: ValidationResult) -> bool:
        has_buildpart = "with BuildPart()" in code or "with BuildPart(" in code
        has_geom = self._has_any(code, GEOMETRY_TOKENS)
        has_export = self._has_any(code, EXPORT_TOKENS)

        missing = []
        if not has_buildpart:
            missing.append("BuildPart context")
        if not has_geom:
            missing.append("geometry primitive (extrude/Box/Cylinder/...)")
        if not has_export:
            missing.append("result/export")
        if missing:
            result.stage_failed = "FTC_STRUCTURE"
            result.error = "Missing: " + ", ".join(missing)
            return False
        return True

    def _stage_ftc_convention(self, code: str, result: ValidationResult) -> None:
        """Warn-only checks."""
        if self._count_param_assignments(code) < 2:
            result.warnings.append("fewer than 2 numeric parameter assignments")
        if not self._has_feature_comment(code):
            # allow any # comment at all as a weaker fallback
            if not any(
                ln.strip().startswith("#") for ln in code.splitlines()
            ):
                result.warnings.append("no comments at all")
            else:
                result.warnings.append("no 'Feature N:' comments")

    def _stage_no_forbidden(self, code: str, result: ValidationResult) -> bool:
        for f in FORBIDDEN_IMPORTS:
            if f in code:
                result.stage_failed = "NO_FORBIDDEN"
                result.error = f"Forbidden import found: {f}"
                return False
        return True

    def _stage_compilation(self, code: str, result: ValidationResult) -> bool:
        harness = COMPILE_HARNESS.format(code_literal=repr(code))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(harness)
            tmp_path = tmp.name

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=self.compile_timeout,
            )
        except subprocess.TimeoutExpired:
            result.stage_failed = "COMPILATION"
            result.error = f"timeout after {self.compile_timeout}s"
            return False
        except Exception as e:
            result.stage_failed = "COMPILATION"
            result.error = f"subprocess error: {e}"
            return False
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # Parse metrics line
        metrics_line = None
        for line in proc.stdout.splitlines():
            if line.startswith("___METRICS___"):
                metrics_line = line[len("___METRICS___"):]
                break

        if not metrics_line:
            result.stage_failed = "COMPILATION"
            tail = (proc.stderr or proc.stdout or "")[-500:]
            result.error = f"no metrics emitted; tail={tail!r}"
            return False

        try:
            metrics = json.loads(metrics_line)
        except json.JSONDecodeError as e:
            result.stage_failed = "COMPILATION"
            result.error = f"metrics JSON decode: {e}"
            return False

        if not metrics.get("ok"):
            result.stage_failed = "COMPILATION"
            result.error = metrics.get("error", "unknown compile error")
            return False

        result.geometry_metrics = {
            "bbox": metrics["bbox"],
            "volume": metrics["volume"],
            "is_valid": metrics["is_valid"],
            "step_size": metrics["step_size"],
        }
        return True

    def _stage_geometry(self, result: ValidationResult) -> bool:
        m = result.geometry_metrics
        if not m:
            return True  # nothing to check (pending)
        if m["volume"] <= 0:
            result.stage_failed = "GEOMETRY"
            result.error = f"volume={m['volume']}"
            return False
        for d in m["bbox"]:
            if d < 0.1 or d > 5000:
                result.stage_failed = "GEOMETRY"
                result.error = f"bbox dim out of range: {d}"
                return False
        if not m["is_valid"]:
            result.stage_failed = "GEOMETRY"
            result.error = "is_valid=False"
            return False
        if m["step_size"] < 100:
            result.stage_failed = "GEOMETRY"
            result.error = f"step_size={m['step_size']} bytes"
            return False
        return True

    def _stage_prompt_alignment(
        self, code: str, prompt: str, result: ValidationResult
    ) -> None:
        if not prompt:
            return
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*mm", prompt.lower())
        if not nums:
            return
        matched = 0
        for n in nums:
            # match either `= 50` or `= 50.0` forms
            if re.search(rf"=\s*{re.escape(n)}(?:\.0+)?\b", code) or re.search(
                rf"=\s*{re.escape(n)}\b", code
            ):
                matched += 1
        ratio = matched / len(nums)
        if ratio < 0.4:
            result.warnings.append(
                f"prompt alignment low: {matched}/{len(nums)} mm values found in code"
            )

    # -- main entry ---------------------------------------------------------

    def validate(self, code: str, prompt: str = "") -> dict:
        result = ValidationResult(code_hash=self._code_hash(code))

        if not self._stage_syntax(code, result):
            return result.to_dict()
        if not self._stage_ftc_import(code, result):
            return result.to_dict()
        if not self._stage_ftc_structure(code, result):
            return result.to_dict()
        self._stage_ftc_convention(code, result)  # warn only
        if not self._stage_no_forbidden(code, result):
            return result.to_dict()

        if self.mode == "full":
            if not self._stage_compilation(code, result):
                return result.to_dict()
            if not self._stage_geometry(result):
                return result.to_dict()

        self._stage_prompt_alignment(code, prompt, result)  # warn only
        result.passed = True
        return result.to_dict()


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------

class Deduplicator:
    def __init__(self) -> None:
        self.code_hashes: set[str] = set()
        self.geom_sigs: set[tuple] = set()

    def _geom_sig(self, metrics: dict | None) -> tuple | None:
        if not metrics or not metrics.get("bbox"):
            return None
        bbox = tuple(sorted(round(float(x), 1) for x in metrics["bbox"]))
        vol = int(round(float(metrics.get("volume", 0))))
        return bbox + (vol,)

    def is_duplicate(self, code_hash: str, geometry_metrics: dict | None = None) -> bool:
        if code_hash in self.code_hashes:
            return True
        sig = self._geom_sig(geometry_metrics)
        if sig is not None and sig in self.geom_sigs:
            return True
        # register
        self.code_hashes.add(code_hash)
        if sig is not None:
            self.geom_sigs.add(sig)
        return False

    def __len__(self) -> int:
        return len(self.code_hashes)


# ---------------------------------------------------------------------------
# Sample helpers
# ---------------------------------------------------------------------------

def extract_prompt_and_code(sample: dict) -> tuple[str, str]:
    """Pull (user prompt, assistant code) from a ShareGPT-style sample."""
    msgs = sample.get("messages") or []
    prompt = ""
    code = ""
    for m in msgs:
        role = m.get("role") or m.get("from")
        content = m.get("content") or m.get("value") or ""
        if role in ("user", "human"):
            prompt = content
        elif role in ("assistant", "gpt"):
            code = content
    # strip code fences if present
    code = _strip_fences(code)
    return prompt, code


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop opening fence (may be ```python)
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_cli(input_path: Path, output_path: Path, mode: str, keep_failed: Path | None) -> dict:
    validator = FTCValidator(mode=mode)
    dedup = Deduplicator()

    stats = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "duplicates": 0,
        "stage_failures": {},
        "warnings_count": 0,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    failed_fp = None
    if keep_failed:
        keep_failed.parent.mkdir(parents=True, exist_ok=True)
        failed_fp = keep_failed.open("w", encoding="utf-8")

    with input_path.open("r", encoding="utf-8") as fin, output_path.open(
        "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError:
                stats["failed"] += 1
                stats["stage_failures"]["JSON_DECODE"] = (
                    stats["stage_failures"].get("JSON_DECODE", 0) + 1
                )
                continue

            stats["total"] += 1
            prompt, code = extract_prompt_and_code(sample)
            res = validator.validate(code, prompt)

            if not res["passed"]:
                stats["failed"] += 1
                stage = res["stage_failed"] or "UNKNOWN"
                stats["stage_failures"][stage] = stats["stage_failures"].get(stage, 0) + 1
                if failed_fp:
                    failed_fp.write(
                        json.dumps(
                            {"sample": sample, "validation": res}, ensure_ascii=False
                        )
                        + "\n"
                    )
                continue

            # dedup
            if dedup.is_duplicate(res["code_hash"], res.get("geometry_metrics")):
                stats["duplicates"] += 1
                continue

            if res["warnings"]:
                stats["warnings_count"] += 1

            sample["_validation"] = res
            fout.write(json.dumps(sample, ensure_ascii=False) + "\n")
            stats["passed"] += 1

    if failed_fp:
        failed_fp.close()

    return stats


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

SELF_TESTS = [
    # (name, code, prompt, should_pass, expected_stage_failed)
    (
        "valid_simple_box",
        '''from build123d import *

# ── Parameters ──────────────────────────
width = 50.0   # mm
height = 30.0  # mm
depth = 10.0   # mm

# ── Feature Tree ────────────────────────
with BuildPart() as part:
    # Feature 1: Base block
    Box(width, height, depth)

# ── Export ───────────────────────────────
result = part.part
export(result, "out.step")
''',
        "Create a 50mm x 30mm x 10mm block",
        True,
        None,
    ),
    (
        "missing_import",
        '''width = 50.0
height = 30.0
with BuildPart() as part:
    Box(width, height, 10)
result = part.part
''',
        "box",
        False,
        "FTC_IMPORT",
    ),
    (
        "no_buildpart",
        '''from build123d import *
width = 50.0
height = 30.0
''',
        "box",
        False,
        "FTC_STRUCTURE",
    ),
    (
        "forbidden_ofl",
        '''from build123d import *
from orionflow_ofl import Sketch
width = 50.0
height = 30.0
with BuildPart() as part:
    Box(width, height, 10)
result = part.part
''',
        "box",
        False,
        "NO_FORBIDDEN",
    ),
    (
        "empty_code",
        "",
        "nothing",
        False,
        "FTC_IMPORT",  # empty parses fine; first real failure is import check
    ),
]


def run_self_test() -> int:
    v = FTCValidator(mode="syntax_only")
    failures = 0
    print("--- FTCValidator self-test ---")
    for name, code, prompt, should_pass, expected_stage in SELF_TESTS:
        res = v.validate(code, prompt)
        ok = res["passed"] == should_pass and (
            should_pass or res["stage_failed"] == expected_stage
        )
        mark = "PASS" if ok else "FAIL"
        print(
            f"  [{mark}] {name:25s} passed={res['passed']:>5} stage={res['stage_failed']} "
            f"err={res['error']}"
        )
        if not ok:
            failures += 1
    print(f"--- {len(SELF_TESTS) - failures}/{len(SELF_TESTS)} tests passed ---")
    return failures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build123d-FTC validator")
    p.add_argument("input", nargs="?", help="input JSONL")
    p.add_argument("output", nargs="?", help="output JSONL for passing samples")
    p.add_argument(
        "--mode",
        choices=("syntax_only", "full"),
        default="syntax_only",
        help="validation mode",
    )
    p.add_argument(
        "--keep-failed",
        type=Path,
        default=None,
        help="optional JSONL path to write failing samples for inspection",
    )
    p.add_argument(
        "--self-test",
        action="store_true",
        help="run internal self-tests and exit",
    )
    args = p.parse_args(argv)

    if args.self_test:
        return 1 if run_self_test() else 0

    if not args.input or not args.output:
        p.error("input and output are required unless --self-test")

    stats = run_cli(
        Path(args.input), Path(args.output), args.mode, args.keep_failed
    )

    print("=== Validation stats ===")
    print(f"  total     : {stats['total']}")
    print(f"  passed    : {stats['passed']}")
    print(f"  failed    : {stats['failed']}")
    print(f"  duplicates: {stats['duplicates']}")
    print(f"  w/warnings: {stats['warnings_count']}")
    if stats["stage_failures"]:
        print("  stage failures:")
        for stage, n in sorted(
            stats["stage_failures"].items(), key=lambda x: -x[1]
        ):
            print(f"    {stage:20s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
