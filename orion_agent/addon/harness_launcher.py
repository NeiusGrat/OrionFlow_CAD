"""Auto-start helper for the harness service.

The FreeCAD chat panel talks to the harness over HTTP at
``127.0.0.1:<harness.port>``. If that service is not running every prompt fails
with "Could not reach the harness service". This module lets the panel bring the
harness up by itself so the user never has to launch a second process by hand.

The harness core is stdlib-only (FastAPI/uvicorn are optional with a stdlib
HTTP fallback), so it runs on any Python 3.x — including FreeCAD's bundled
interpreter — which makes a self-spawn safe and dependency-free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# One harness child per FreeCAD session.
_PROC: Optional[subprocess.Popen] = None


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists() or (parent / ".env").exists():
            return parent
    # addon/ -> orion_agent/ -> repo root
    return here.parents[2]


def harness_base_url(cfg) -> str:
    return f"http://{cfg.harness.host}:{cfg.harness.port}"


def is_harness_up(cfg, timeout: float = 6.0) -> bool:
    """True if the harness answers ``GET /health`` with HTTP 200."""
    try:
        with urllib.request.urlopen(
            harness_base_url(cfg) + "/health", timeout=timeout
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _find_interpreter() -> Optional[str]:
    """Locate a real ``python`` executable usable for ``-m``.

    Inside FreeCAD ``sys.executable`` can point at ``FreeCAD.exe`` (re-launching
    it would open another FreeCAD, not the harness), so we look for a genuine
    python interpreter first.
    """
    # 1. Explicit override.
    override = os.environ.get("ORION_PYTHON")
    if override and Path(override).exists():
        return override

    candidates: list[str] = []
    exe = sys.executable or ""
    exe_dir = os.path.dirname(exe)
    name = os.path.basename(exe).lower()

    # 2. sys.executable, but only if it really is a python (not FreeCAD.exe).
    if exe and ("python" in name):
        candidates.append(exe)

    # 3. python(.exe) sitting next to sys.executable (FreeCAD ships one in bin/).
    if exe_dir:
        for cand in ("python.exe", "python3.exe", "python", "python3"):
            p = os.path.join(exe_dir, cand)
            if os.path.exists(p):
                candidates.append(p)
        # FreeCAD layout: <root>/bin/FreeCAD.exe with python under bin/ too.
        p = os.path.join(exe_dir, "bin", "python.exe")
        if os.path.exists(p):
            candidates.append(p)

    # 4. Whatever is on PATH (Anaconda / system Python).
    for cand in ("python", "python3"):
        found = shutil.which(cand)
        if found:
            candidates.append(found)

    # 5. Last resort: sys.executable even if it's FreeCAD (stdlib path still
    #    works when FreeCAD is invoked as a console interpreter).
    if exe:
        candidates.append(exe)

    seen = set()
    for c in candidates:
        rc = os.path.abspath(c)
        if rc not in seen and os.path.exists(c):
            seen.add(rc)
            return c
    return None


def _is_running() -> bool:
    return _PROC is not None and _PROC.poll() is None


def ensure_harness(cfg, wait_seconds: float = 25.0) -> tuple[bool, str]:
    """Make sure the harness is reachable; spawn it if not.

    Returns ``(ok, message)``. ``ok`` is True once ``/health`` responds.
    """
    global _PROC

    if is_harness_up(cfg):
        return True, "harness already running"

    if _is_running():
        # We already spawned it — just wait for it to bind.
        if _wait_until_up(cfg, wait_seconds):
            return True, "harness started"
        return False, "harness process is starting but not responding yet"

    interp = _find_interpreter()
    if not interp:
        return False, "no python interpreter found to launch the harness"

    repo = _repo_root()
    env = dict(os.environ)
    # Make ``orion_agent`` importable in the child regardless of cwd.
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo) + (os.pathsep + existing_pp if existing_pp else "")
    )
    env["PYTHONUNBUFFERED"] = "1"

    log_path = repo / "data" / "harness.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
    except OSError:
        log_file = subprocess.DEVNULL

    creationflags = 0
    if os.name == "nt":
        # Detach the console so no black window pops up next to FreeCAD.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        _PROC = subprocess.Popen(
            [interp, "-m", "orion_agent.harness.server"],
            cwd=str(repo),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError as exc:
        return False, f"failed to launch harness: {exc}"

    if _wait_until_up(cfg, wait_seconds):
        return True, "harness started"

    # It launched but never bound — surface the tail of its log if we can.
    if _PROC.poll() is not None:
        return False, (
            f"harness exited immediately (code {_PROC.returncode}); "
            f"see {log_path}"
        )
    return False, f"harness did not respond within {wait_seconds:.0f}s; see {log_path}"


def _wait_until_up(cfg, wait_seconds: float) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_harness_up(cfg, timeout=4.0):
            return True
        time.sleep(0.5)
    return False
