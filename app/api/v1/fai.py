"""OrionFlow Inspect API — FAI projects, revisions, review and sign-off.

Thin: every rule lives in the standalone ``fai`` package. This module only
authenticates, validates uploads and maps the package's errors to HTTP.
"""
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.db.models import User
from fai import service as svc

router = APIRouter()
MAX_BYTES = 80 * 2**20


def _who(user: User) -> tuple[str, str]:
    return str(user.id), getattr(user, "email", "") or str(user.id)


def mapped(fn):
    """NotFound -> 404, Conflict -> 409, ValueError -> 400; the package stays HTTP-free."""
    @wraps(fn)
    async def inner(*a, **kw):
        try:
            return await fn(*a, **kw)
        except svc.NotFound as e:
            raise HTTPException(404, str(e)) from None
        except svc.Conflict as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    return inner


async def _read(f: UploadFile | None, kind: str, exts: tuple[str, ...], magic) -> tuple[str, bytes] | None:
    if f is None or not f.filename:
        return None
    name = f.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not name.lower().endswith(exts):
        raise HTTPException(415, f"{name}: the {kind} must be {' or '.join(exts)}")
    data = await f.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"{name} is larger than {MAX_BYTES // 2**20} MB")
    if not magic(data):
        raise HTTPException(415, f"{name} is not a valid {kind} file")
    return name, data


# ------------------------------------------------------------------ projects

class ProjectIn(BaseModel):
    part_number: str = ""
    part_name: str = ""
    customer: str = ""


@router.get("/projects")
@mapped
async def list_projects(user: User = Depends(get_current_user)) -> list[dict]:
    return await asyncio.to_thread(svc.list_projects, _who(user)[0])


@router.post("/projects", status_code=201)
@mapped
async def create_project(body: ProjectIn, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.create_project, owner, body.part_number, body.part_name, body.customer, actor)


@router.get("/projects/{pid}")
@mapped
async def get_project(pid: str, user: User = Depends(get_current_user)) -> dict:
    return await asyncio.to_thread(svc.get_project, _who(user)[0], pid)


@router.patch("/projects/{pid}")
@mapped
async def update_project(pid: str, body: ProjectIn, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.update_project, owner, pid, body.model_dump(exclude_unset=True), actor)


@router.delete("/projects/{pid}")
@mapped
async def delete_project(pid: str, user: User = Depends(get_current_user)) -> dict:
    await asyncio.to_thread(svc.delete_project, _who(user)[0], pid)
    return {"deleted": pid}


@router.post("/sample", status_code=201)
@mapped
async def sample(user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.create_sample, owner, actor)


# ------------------------------------------------------------------ revisions

@router.post("/projects/{pid}/revisions", status_code=202)
@mapped
async def create_revision(
    pid: str,
    drawing: UploadFile = File(...),
    step: Optional[UploadFile] = File(None),
    bom: Optional[UploadFile] = File(None),
    standard: str = Form("ISO GPS"),
    general_class: str = Form(""),
    label: str = Form(""),
    po_number: str = Form(""),
    user: User = Depends(get_current_user),
) -> dict:
    if standard not in ("ISO GPS", "ASME Y14.5"):
        raise HTTPException(400, "standard must be ISO GPS or ASME Y14.5")
    if general_class not in ("", "f", "m", "c", "v"):
        raise HTTPException(400, "general tolerance class must be f, m, c, v or empty (from the drawing)")
    d = await _read(drawing, "drawing", (".pdf",), lambda b: b.startswith(b"%PDF-"))
    if d is None:
        raise HTTPException(400, "a drawing PDF is required")
    s = await _read(step, "STEP model", (".step", ".stp"), lambda b: b.lstrip()[:12].startswith(b"ISO-10303-21"))
    b = await _read(bom, "BOM / PO", (".csv", ".tsv", ".txt"), lambda x: b"\x00" not in x[:4096])
    owner, actor = _who(user)
    opts = {"standard": standard, "general_class": general_class, "po_number": po_number}
    return await asyncio.to_thread(svc.create_revision, owner, pid, d, s, b, opts, label, actor)


@router.get("/revisions/{rid}")
@mapped
async def get_revision(rid: str, user: User = Depends(get_current_user)) -> dict:
    r = await asyncio.to_thread(svc.get_revision, _who(user)[0], rid)
    if r.get("result", {}).get("status") == "done":
        r["readiness"] = svc.readiness(r["result"])
    return r


@router.delete("/revisions/{rid}")
@mapped
async def delete_revision(rid: str, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    await asyncio.to_thread(svc.delete_revision, owner, rid, actor)
    return {"deleted": rid}


@router.patch("/revisions/{rid}/characteristics/{no}")
@mapped
async def edit_characteristic(rid: str, no: int, body: dict, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.edit_characteristic, owner, rid, no, dict(body), actor)


class DecisionIn(BaseModel):
    decision: str
    note: str = ""
    for_customer: bool = False


@router.post("/revisions/{rid}/findings/{fid}")
@mapped
async def decide(rid: str, fid: str, body: DecisionIn, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.decide_finding, owner, rid, fid, body.decision, body.note, actor,
                                   body.for_customer)


@router.patch("/revisions/{rid}/form1")
@mapped
async def update_form1(rid: str, body: dict, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.update_options, owner, rid, dict(body), actor)


class SignIn(BaseModel):
    name: str
    role: str = "Quality engineer"


@router.post("/revisions/{rid}/sign")
@mapped
async def sign(rid: str, body: SignIn, user: User = Depends(get_current_user)) -> dict:
    owner, actor = _who(user)
    return await asyncio.to_thread(svc.sign, owner, rid, body.name, body.role, actor)


@router.get("/revisions/{rid}/files/{name}")
@mapped
async def revision_file(rid: str, name: str, user: User = Depends(get_current_user)):
    owner, actor = _who(user)
    p = await asyncio.to_thread(svc.file_path, owner, rid, name, actor)
    return FileResponse(p, media_type=svc.FILES[name], filename=f"{rid}-{name}")


@router.get("/revisions/{rid}/pages/{n}.png")
@mapped
async def page(rid: str, n: int, dpi: int = 110, user: User = Depends(get_current_user)):
    try:
        p = await asyncio.to_thread(svc.page_png, _who(user)[0], rid, n, dpi)
    except IndexError:
        raise HTTPException(404, "no such sheet") from None
    return FileResponse(p, media_type="image/png")


@router.get("/compare")
@mapped
async def compare(a: str, b: str, user: User = Depends(get_current_user)) -> dict:
    return await asyncio.to_thread(svc.compare, _who(user)[0], a, b)
