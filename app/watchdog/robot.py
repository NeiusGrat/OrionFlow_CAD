"""Robot-model runs: check an uploaded URDF/MJCF, or compile one from a spec.

MuJoCo will not load inside the Anaconda interpreter the API usually runs in
(``WinError 1114``), so every run is a child process under an interpreter that
can import it — ``ROBOCHECK_PYTHON`` when set, else the first candidate that
passes an import probe. A crashing or hanging simulator costs that run only.

Runs live in ``data/watchdog/robot/<user>/<run>/`` and are visible only to the
user who created them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("WATCHDOG_ROBOT_DATA", "data/watchdog/robot"))
WORKER = Path(__file__).with_name("robot_worker.py")
TIMEOUT_S = int(os.environ.get("WATCHDOG_ROBOT_TIMEOUT_S", "600"))
CANDIDATES = [os.environ.get("ROBOCHECK_PYTHON", ""), sys.executable,
              r"C:\Program Files\Python311\python.exe", "python3", "python"]
FILES = {"model.glb": "model/gltf-binary", "report.json": "application/json"}


@lru_cache(maxsize=1)
def interpreter() -> tuple[str | None, str]:
    """(python able to run robocheck + embodiment, reason when none is)."""
    tried = []
    for py in dict.fromkeys(c for c in CANDIDATES if c):
        try:
            r = subprocess.run([py, "-c", "import mujoco, trimesh, build123d"], capture_output=True,
                               timeout=120, env=_env())
        except (OSError, subprocess.TimeoutExpired) as e:
            tried.append(f"{py}: {type(e).__name__}")
            continue
        if r.returncode == 0:
            return py, ""
        last = (r.stderr.decode(errors="replace").strip().splitlines() or ["failed"])[-1]
        tried.append(f"{py}: {last[:120]}")
    return None, "no interpreter can import mujoco, trimesh and build123d (set ROBOCHECK_PYTHON); " + "; ".join(tried)


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    return env


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "file").name)[:120] or "file"


def _user_dir(user: str) -> Path:
    return DATA / re.sub(r"[^A-Za-z0-9-]", "", user)


def run_dir(user: str, rid: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{12}", rid):
        return None
    d = _user_dir(user) / rid
    return d if (d / "meta.json").is_file() else None


def _meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _write_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def create(user: str, mode: str, label: str, robot: tuple[str, bytes] | None = None,
           meshes: list[tuple[str, bytes]] = (), target: str = "arm", spec: bytes | None = None) -> dict:
    rid = uuid.uuid4().hex[:12]
    d = _user_dir(user) / rid
    d.mkdir(parents=True)
    arg = target
    if mode == "check":
        fn = _safe(robot[0])
        (d / fn).write_bytes(robot[1])
        arg = str((d / fn).resolve())
        if meshes:
            (d / "meshes").mkdir()
            for name, data in meshes:
                (d / "meshes" / _safe(name)).write_bytes(data)
    elif spec:
        (d / "spec.json").write_bytes(spec)
        arg = str((d / "spec.json").resolve())
    meta = {"id": rid, "mode": mode, "label": label or (robot[0] if robot else f"{target} from spec"),
            "status": "queued", "created": time.time()}
    _write_meta(d, meta)
    threading.Thread(target=_execute, args=(d, mode, arg), daemon=True, name=f"robot-{rid}").start()
    return meta


def _execute(d: Path, mode: str, arg: str) -> None:
    meta = _meta(d)
    meta["status"] = "running"
    _write_meta(d, meta)
    py, why = interpreter()
    if py is None:
        meta.update(status="error", error=why, finished=time.time())
        _write_meta(d, meta)
        return
    try:
        r = subprocess.run([py, str(WORKER), mode, str(d.resolve()), arg], capture_output=True,
                           timeout=TIMEOUT_S, env=_env(), cwd=str(ROOT))
        rep_path = d / "report.json"
        if rep_path.is_file():
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
            meta.update(status=rep.get("status", "error"), error=rep.get("error"),
                        accepted=rep.get("accepted"), has_glb=(d / "model.glb").is_file())
            meta["summary"] = summarize(rep)
        else:
            tail = (r.stderr.decode(errors="replace").strip().splitlines() or ["worker exited without a report"])
            meta.update(status="error", error=tail[-1][:400])
    except subprocess.TimeoutExpired:
        meta.update(status="error", error=f"timed out after {TIMEOUT_S} s")
    meta["finished"] = time.time()
    _write_meta(d, meta)


def summarize(rep: dict) -> dict:
    checks = rep.get("robocheck") or {}
    return {"errors": sum(c.get("errors", 0) for c in checks.values()),
            "warnings": sum(c.get("warnings", 0) for c in checks.values()),
            "gates_failed": [k for k, g in (rep.get("gates") or {}).items() if not g.get("passed")]}


def list_runs(user: str) -> list[dict]:
    d = _user_dir(user)
    if not d.is_dir():
        return []
    runs = [_meta(x) for x in d.iterdir() if (x / "meta.json").is_file()]
    return sorted(runs, key=lambda m: -m.get("created", 0))


def get(user: str, rid: str) -> dict | None:
    d = run_dir(user, rid)
    if d is None:
        return None
    out = _meta(d)
    if (d / "report.json").is_file():
        out["report"] = json.loads((d / "report.json").read_text(encoding="utf-8"))
        out["report"].pop("trace", None)
    return out


def delete(user: str, rid: str) -> bool:
    d = run_dir(user, rid)
    if d is None:
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True
