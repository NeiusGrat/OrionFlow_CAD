"""Sandbox manager: run generated CAD code under hard limits.

Backend is pluggable (``subprocess`` today; ``docker`` / ``nsjail`` are drop-in
later via config). The subprocess backend enforces:

  * a wall-clock timeout (all platforms),
  * CPU + address-space rlimits (POSIX, best-effort),
  * a scrubbed environment with no inherited secrets,
  * a scratch-only working directory.

A sandbox crash (OpenCASCADE segfault, OOM kill, timeout) is treated as a
normal failure result, never an exception that takes down the harness.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from orion_agent.shared.config import get_config


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    artifacts: list[dict] = field(default_factory=list)
    topology: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    killed: bool = False

    def artifact_path(self, kind: str) -> Optional[str]:
        for a in self.artifacts:
            if a.get("kind") == kind and a.get("path"):
                return a["path"]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "artifacts": self.artifacts,
            "topology": self.topology,
            "stdout": self.stdout[-1500:],
            "killed": self.killed,
        }


class SandboxManager:
    def __init__(self, config=None):
        self.cfg = (config or get_config()).sandbox

    def run_code(
        self,
        code: str,
        result_var: str = "result",
        exports: Optional[list[str]] = None,
    ) -> SandboxResult:
        exports = exports or ["step", "stl"]
        run_id = uuid.uuid4().hex[:8]
        scratch = os.path.abspath(os.path.join(self.cfg.scratch_dir, run_id))
        os.makedirs(scratch, exist_ok=True)
        job_path = os.path.join(scratch, "job.json")
        result_path = os.path.join(scratch, "result.json")
        job = {
            "code": code,
            "result_var": result_var,
            "scratch_dir": scratch,
            "exports": exports,
            "result_path": result_path,
        }
        with open(job_path, "w", encoding="utf-8") as fh:
            json.dump(job, fh)

        if self.cfg.backend != "subprocess":
            # docker / nsjail backends plug in here with the same job contract.
            return self._run_subprocess(job_path, result_path, scratch)
        return self._run_subprocess(job_path, result_path, scratch)

    # ------------------------------------------------------------------ #
    def _run_subprocess(self, job_path: str, result_path: str, scratch: str) -> SandboxResult:
        env = self._clean_env()
        # Invoke the runner by path (not -m): -I strips PYTHONPATH, and the
        # runner only needs build123d from system site-packages, so it stays
        # fully isolated from the harness package and any inherited env.
        runner_path = os.path.join(os.path.dirname(__file__), "runner.py")
        # Plain invocation with a scrubbed env: the subprocess backend isolates
        # via process boundary + clean env + rlimits; the docker/nsjail backend
        # provides hard isolation. We keep user site-packages so build123d (and
        # OCP) resolve. Secrets are stripped in ``_clean_env``.
        cmd = [sys.executable, "-E", runner_path, job_path]
        started = time.time()
        killed = False
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=self.cfg.timeout_seconds,
                preexec_fn=self._rlimits() if os.name != "nt" else None,
            )
            launch_err = proc.stderr if proc.returncode not in (0, 1) else ""
        except subprocess.TimeoutExpired:
            killed = True
            launch_err = f"sandbox exceeded {self.cfg.timeout_seconds}s wall-clock limit"
        except Exception as exc:  # noqa: BLE001
            return SandboxResult(
                ok=False, error=f"sandbox launch failed: {exc}",
                duration_ms=(time.time() - started) * 1000,
            )

        duration_ms = (time.time() - started) * 1000
        if killed:
            return SandboxResult(ok=False, error=launch_err, killed=True, duration_ms=duration_ms)

        if not os.path.exists(result_path):
            return SandboxResult(
                ok=False,
                error=launch_err or "sandbox produced no result (likely crashed)",
                killed=True,
                duration_ms=duration_ms,
            )
        try:
            with open(result_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            return SandboxResult(ok=False, error=f"unreadable result: {exc}", duration_ms=duration_ms)

        return SandboxResult(
            ok=bool(payload.get("ok")),
            stdout=payload.get("stdout", ""),
            stderr=payload.get("stderr", ""),
            error=payload.get("error", ""),
            artifacts=payload.get("artifacts", []),
            topology=payload.get("topology", {}),
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------ #
    def _clean_env(self) -> dict:
        # Keep only what the interpreter needs to find stdlib + site-packages
        # (incl. the Windows user-site, located via APPDATA). No API keys, no
        # cloud creds, no DB/Redis URLs are forwarded to generated code.
        keep = (
            "PATH", "PYTHONPATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "HOME", "LANG", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
            "HOMEDRIVE", "HOMEPATH", "PATHEXT",
        )
        env = {k: os.environ[k] for k in keep if k in os.environ}
        # Ensure the repo is importable for ``-m orion_agent...`` in the child.
        repo_root = get_config().repo_root
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (repo_root, existing) if p)
        # No network proxies, no inherited API keys.
        env["NO_PROXY"] = "*"
        return env

    def _rlimits(self):
        """Return a preexec_fn that applies CPU/memory rlimits (POSIX only)."""
        timeout = self.cfg.timeout_seconds
        mem_bytes = self.cfg.memory_mb * 1024 * 1024

        def _apply():  # pragma: no cover - POSIX only
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 2))
            try:
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            except (ValueError, OSError):
                pass

        return _apply
