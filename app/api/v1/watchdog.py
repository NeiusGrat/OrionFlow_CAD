"""Watchdog API: engine status and robot-model runs.

Assembly analysis and drawing checks are served by their own engines, mounted
at ``/verify`` and ``/drawing`` (see :mod:`app.watchdog.engines`); this router
adds what neither covers — physical validity of a robot model (robocheck) and
compiling a robot from a spec (embodiment) — plus one endpoint that says which
engines this deployment can actually run.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.db.models import User
from app.watchdog import robot, samples
from app.watchdog.engines import STATUS

router = APIRouter()

MAX_ROBOT_BYTES = 50 * 2**20
ROBOT_EXT = {".urdf", ".xml"}
MESH_EXT = {".stl", ".obj", ".dae", ".ply", ".glb"}


@router.get("/modules")
async def modules(user: User = Depends(get_current_user)) -> dict:
    py, why = await asyncio.to_thread(robot.interpreter)
    llm, llm_on = None, False
    try:
        from interface_check.llm import NoLLM, from_env

        model = from_env()
        llm, llm_on = model.name, not isinstance(model, NoLLM)
    except Exception:  # noqa: BLE001 - LLM status is informative only
        pass

    def entry(name: str, mount: str | None, what: str) -> dict:
        reason = STATUS.get(name, "not mounted")
        return {"available": reason is None, "reason": reason, "mount": mount, "what": what}

    return {
        "assembly": entry("interface_check", "/verify",
                          "Interfaces, clearances, BOM, revisions, drawings and CAD-to-URDF drift"),
        "drawing": entry("drawcheck", "/drawing", "Incoming drawing check and technical query list"),
        "robot": {"available": py is not None, "reason": why or None, "mount": "/api/v1/watchdog/robot",
                  "what": "Robot-model physics (robocheck) and spec-to-robot compile (embodiment)"},
        "llm": {"configured": llm_on, "name": llm},
    }


@router.post("/robot/runs", status_code=202)
async def create_robot_run(
    mode: str = Form("check"),
    label: str = Form(""),
    target: str = Form("arm"),
    file: Optional[UploadFile] = File(None),
    meshes: List[UploadFile] = File(default=[]),
    spec: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
) -> dict:
    if mode not in ("check", "compile"):
        raise HTTPException(400, "mode must be check or compile")
    robot_file = None
    mesh_files: list[tuple[str, bytes]] = []
    spec_bytes = None
    if mode == "check":
        if file is None or not file.filename:
            raise HTTPException(400, "upload a URDF or MJCF file to check")
        if not any(file.filename.lower().endswith(e) for e in ROBOT_EXT):
            raise HTTPException(415, "a robot model must be .urdf or .xml (MJCF)")
        data = await file.read()
        if len(data) > MAX_ROBOT_BYTES:
            raise HTTPException(413, "robot file larger than 50 MB")
        if not data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
            raise HTTPException(415, f"{file.filename} is not XML")
        robot_file = (file.filename, data)
        total = len(data)
        for m in meshes:
            if not m.filename:
                continue
            if not any(m.filename.lower().endswith(e) for e in MESH_EXT):
                raise HTTPException(415, f"{m.filename}: meshes must be STL, OBJ, DAE, PLY or GLB")
            b = await m.read()
            total += len(b)
            if total > 4 * MAX_ROBOT_BYTES:
                raise HTTPException(413, "robot model and meshes exceed 200 MB")
            mesh_files.append((m.filename, b))
    else:
        if target not in ("arm", "quadruped"):
            raise HTTPException(400, "target must be arm or quadruped")
        if spec is not None and spec.filename:
            spec_bytes = await spec.read()
            if len(spec_bytes) > 2**20:
                raise HTTPException(413, "spec larger than 1 MB")
    return robot.create(str(user.id), mode, label, robot_file, mesh_files, target, spec_bytes)


@router.get("/robot/runs")
async def list_robot_runs(user: User = Depends(get_current_user)) -> list[dict]:
    return robot.list_runs(str(user.id))


@router.get("/robot/runs/{rid}")
async def get_robot_run(rid: str, user: User = Depends(get_current_user)) -> dict:
    out = robot.get(str(user.id), rid)
    if out is None:
        raise HTTPException(404, "no such robot run")
    return out


@router.get("/robot/runs/{rid}/files/{name}")
async def robot_run_file(rid: str, name: str, user: User = Depends(get_current_user)):
    d = robot.run_dir(str(user.id), rid)
    if d is None or name not in robot.FILES or not (d / name).is_file():
        raise HTTPException(404, "not available")
    return FileResponse(d / name, media_type=robot.FILES[name], filename=f"{rid}-{name}")


@router.delete("/robot/runs/{rid}")
async def delete_robot_run(rid: str, user: User = Depends(get_current_user)) -> dict:
    if not robot.delete(str(user.id), rid):
        raise HTTPException(404, "no such robot run")
    return {"deleted": rid}


@router.get("/samples")
async def list_samples(user: User = Depends(get_current_user)) -> list[dict]:
    return [{"id": k, "label": v["label"], "about": v["about"]} for k, v in samples.SAMPLES.items()]


@router.post("/samples/{name}", status_code=202)
async def run_sample(name: str, user: User = Depends(get_current_user)) -> dict:
    """Build a synthetic assembly with seeded problems and analyse it as this user."""
    if name not in samples.SAMPLES:
        raise HTTPException(404, "no such sample")
    if STATUS.get("interface_check", "not mounted") is not None:
        raise HTTPException(503, f"assembly engine unavailable: {STATUS.get('interface_check')}")
    return await asyncio.to_thread(samples.submit, name, str(user.id))
