"""OrionFlow Review HTTP API.

Mounted by the main app at ``/review`` (routes below are relative to it), with
:func:`owner` overridden to accept the main app's access tokens. Standalone
(``uvicorn review.api:app``) it accepts ``REVIEW_DEV_TOKEN`` only.

    GET    /api/health
    GET    /api/projects                         POST /api/projects
    GET    /api/projects/{pid}                   DELETE /api/projects/{pid}   (archive)
    POST   /api/projects/{pid}/revisions         multipart: files[], label, git_repo, git_ref
    GET    /api/revisions/{rid}
    PATCH  /api/revisions/{rid}                  {primary_file_id}
    POST   /api/revisions/{rid}/files            multipart: files[] (add to a draft)
    PATCH  /api/revisions/{rid}/files/{fid}      {kind}
    DELETE /api/revisions/{rid}/files/{fid}
    POST   /api/revisions/{rid}/run              -> job
    GET    /api/jobs/{jid}
    GET    /api/revisions/{rid}/graph
    GET    /api/revisions/{rid}/viewer.glb
    GET    /api/revisions/{rid}/findings         findings + check runs (what ran, what did not and why)
    GET    /api/findings/{fid}                   one finding with its audit trail
    PATCH  /api/findings/{fid}                   {status, owner, note}; rejecting needs a reason
    POST   /api/findings/{fid}/comments          {text}
    GET    /api/revisions/{rid}/report.json      the whole review, with check versions and file hashes
    GET    /api/revisions/{rid}/bom              BOM rows matched to CAD parts, with counts, materials, mass
    PUT    /api/revisions/{rid}/bom/links        {row_key, part_id|null}: the engineer's pairing (re-checks)
    DELETE /api/revisions/{rid}/bom/links        {row_key}: back to automatic matching
    GET    /api/revisions/{rid}/bom.csv | bom.xlsx   the reconciled BOM
    POST   /api/demo/yubi                        the YUBI gripper, fetched at pinned tags
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import jobs as jobrunner
from .ingest import classify, expand_zip
from .store import Store, database_url

app = FastAPI(title="OrionFlow Review", version="0.1.0")
KINDS = {"step", "bom", "pdf", "urdf", "mjcf", "mesh", "other"}
MAX_FILE_MB = int(os.environ.get("REVIEW_MAX_FILE_MB", "200"))

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def owner(authorization: str = Header(default="")) -> str:
    """User id. Overridden when mounted; standalone accepts only the dev token."""
    dev = os.environ.get("REVIEW_DEV_TOKEN", "")
    if dev and authorization == f"Bearer {dev}":
        return "dev"
    raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


# ------------------------------------------------------------------ helpers --

def _project_of(pid: str, uid: str) -> dict:
    p = store().project(pid)
    if p is None or p["owner_id"] != uid or p["archived_at"] is not None:
        raise HTTPException(404, "project not found")
    return p


def _revision_of(rid: str, uid: str) -> dict:
    r = store().revision(rid)
    if r is None:
        raise HTTPException(404, "revision not found")
    _project_of(r["project_id"], uid)
    return r


def _file_out(f: dict) -> dict:
    return {k: f[k] for k in ("id", "kind", "kind_source", "name", "sha256", "size")}


def _revision_out(r: dict) -> dict:
    s = store()
    files = s.files_for(r["id"])
    job = s.latest_job(r["id"])
    g = s.graph(r["id"])
    return {
        **{k: r[k] for k in ("id", "project_id", "label", "git_repo", "git_ref", "status", "primary_file_id")},
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "files": [_file_out(f) for f in files],
        "job": _job_out(job) if job else None,
        "stats": (g["graph"] or {}).get("stats") if g else None,
        "findings": _summary(s.findings_for(r["id"])) if g else None,
    }


SEVERITIES = ("critical", "major", "minor", "info")


def _summary(rows: list[dict]) -> dict:
    out = {sev: 0 for sev in SEVERITIES}
    for f in rows:
        if f["status"] in ("open", "deferred"):
            out[f["severity"]] += 1
    out["total"] = len(rows)
    out["open"] = sum(1 for f in rows if f["status"] == "open")
    return out


def _iso(v):
    return v.isoformat() if v else None


def _finding_out(f: dict) -> dict:
    return {k: f[k] for k in ("id", "fingerprint", "check_id", "check_version", "domain", "severity", "status",
                              "provenance", "title", "statement", "measured", "expected", "evidence",
                              "recommendation", "active")} | {
        "owner": f["owner_id"], "created_at": _iso(f["created_at"]), "updated_at": _iso(f["updated_at"])}


def _run_out(r: dict) -> dict:
    return {k: r[k] for k in ("check_id", "check_version", "domain", "title", "kind", "status", "reason",
                              "findings", "seconds")}


def _event_out(e: dict) -> dict:
    return {k: e[k] for k in ("id", "user_id", "action", "from_status", "to_status", "note")} | {"created_at": _iso(e["created_at"])}


def _job_out(j: dict) -> dict:
    return {
        "id": j["id"], "revision_id": j["revision_id"], "state": j["state"], "steps": j["steps"],
        "error": (j["error"] or "").split("\n", 1)[0] or None,
        "created_at": j["created_at"].isoformat() if j["created_at"] else None,
        "started_at": j["started_at"].isoformat() if j["started_at"] else None,
        "ended_at": j["ended_at"].isoformat() if j["ended_at"] else None,
    }


def _ingest_bytes(rid: str, name: str, data: bytes) -> list[dict]:
    """Store one upload (expanding zips) and record each file with its hash and kind."""
    out: list[dict] = []
    if name.lower().endswith(".zip"):
        for member, blob in expand_zip(data):
            out += _ingest_bytes(rid, member, blob)
        return out
    if len(data) > MAX_FILE_MB * 2**20:
        raise HTTPException(413, f"{name} is larger than {MAX_FILE_MB} MB")
    sha = hashlib.sha256(data).hexdigest()
    key = f"review/{rid}/files/{sha[:16]}/{Path(name).name}"
    jobrunner.open_storage().put_bytes(key, data)
    out.append(store().add_file(rid, classify(name, data[:4096]), name, sha, len(data), key))
    return out


async def _ingest_uploads(rid: str, uploads: list[UploadFile]) -> list[dict]:
    added: list[dict] = []
    for up in uploads:
        data = await up.read()
        added += _ingest_bytes(rid, up.filename or "upload", data)
    return added


# ------------------------------------------------------------------- routes --

@app.get("/api/health")
def health() -> dict:
    s = store()
    return {"ok": True, "database": s.engine.dialect.name, "storage": jobrunner.storage_spec()["kind"]}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


@app.get("/api/projects")
def list_projects(uid: str = Depends(owner)) -> list[dict]:
    out = []
    for p in store().projects_for(uid):
        out.append({"id": p["id"], "name": p["name"], "description": p["description"],
                    "revision_count": p["revision_count"], "created_at": p["created_at"].isoformat()})
    return out


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, uid: str = Depends(owner)) -> dict:
    p = store().create_project(uid, body.name, body.description)
    return {"id": p["id"], "name": p["name"], "description": p["description"], "revision_count": 0,
            "created_at": p["created_at"].isoformat()}


@app.get("/api/projects/{pid}")
def get_project(pid: str, uid: str = Depends(owner)) -> dict:
    p = _project_of(pid, uid)
    return {"id": p["id"], "name": p["name"], "description": p["description"],
            "created_at": p["created_at"].isoformat(),
            "revisions": [_revision_out(r) for r in store().revisions_for(pid)]}


@app.delete("/api/projects/{pid}", status_code=204)
def archive_project(pid: str, uid: str = Depends(owner)) -> None:
    _project_of(pid, uid)
    store().archive_project(pid)


@app.post("/api/projects/{pid}/revisions", status_code=201)
async def create_revision(pid: str, files: list[UploadFile] = File(default=[]), label: str = Form("rev A"),
                          git_repo: Optional[str] = Form(None), git_ref: Optional[str] = Form(None),
                          uid: str = Depends(owner)) -> dict:
    _project_of(pid, uid)
    r = store().create_revision(pid, label, git_repo or None, git_ref or None)
    await _ingest_uploads(r["id"], files)
    return _revision_out(store().revision(r["id"]))


@app.get("/api/revisions/{rid}")
def get_revision(rid: str, uid: str = Depends(owner)) -> dict:
    return _revision_out(_revision_of(rid, uid))


class RevisionPatch(BaseModel):
    primary_file_id: Optional[str] = None


@app.patch("/api/revisions/{rid}")
def patch_revision(rid: str, body: RevisionPatch, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    if body.primary_file_id is not None:
        if not any(f["id"] == body.primary_file_id and f["kind"] == "step" for f in store().files_for(rid)):
            raise HTTPException(422, "primary file must be a STEP file of this revision")
        store().set_primary(rid, body.primary_file_id)
    return _revision_out(store().revision(rid))


@app.post("/api/revisions/{rid}/files", status_code=201)
async def add_files(rid: str, files: list[UploadFile] = File(...), uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    await _ingest_uploads(rid, files)
    return _revision_out(store().revision(rid))


class FilePatch(BaseModel):
    kind: str


@app.patch("/api/revisions/{rid}/files/{fid}")
def patch_file(rid: str, fid: str, body: FilePatch, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    if not any(f["id"] == fid for f in store().files_for(rid)):
        raise HTTPException(404, "file not found")
    return _file_out(store().set_file_kind(fid, body.kind))


@app.delete("/api/revisions/{rid}/files/{fid}", status_code=204)
def delete_file(rid: str, fid: str, uid: str = Depends(owner)) -> None:
    _revision_of(rid, uid)
    if not any(f["id"] == fid for f in store().files_for(rid)):
        raise HTTPException(404, "file not found")
    store().delete_file(fid)


@app.post("/api/revisions/{rid}/run", status_code=202)
def run_review(rid: str, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    s = store()
    active = s.active_job(rid)
    if active:
        return _job_out(active)
    if not any(f["kind"] == "step" for f in s.files_for(rid)):
        raise HTTPException(422, "add a STEP file before running a review")
    job = s.create_job(rid, uid)
    s.set_revision_status(rid, "queued")
    jobrunner.submit(job["id"], database_url())
    return _job_out(s.job(job["id"]))


@app.get("/api/jobs/{jid}")
def get_job(jid: str, uid: str = Depends(owner)) -> dict:
    j = store().job(jid)
    if j is None:
        raise HTTPException(404, "job not found")
    _revision_of(j["revision_id"], uid)
    return _job_out(j)


@app.get("/api/revisions/{rid}/graph")
def get_graph(rid: str, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    g = store().graph(rid)
    if g is None:
        raise HTTPException(404, "no model graph yet: run the review first")
    return g["graph"]


@app.get("/api/revisions/{rid}/viewer.glb")
def get_glb(rid: str, uid: str = Depends(owner)):
    _revision_of(rid, uid)
    g = store().graph(rid)
    if g is None or not g["glb_key"]:
        raise HTTPException(404, "no viewer model yet: run the review first")
    st = jobrunner.open_storage()
    url = st.signed_get(g["glb_key"], 600, "viewer.glb")
    if url:
        return RedirectResponse(url, status_code=307)
    tmp = Path(tempfile.gettempdir()) / f"review_{rid}.glb"
    st.get_file(g["glb_key"], tmp)
    return FileResponse(tmp, media_type="model/gltf-binary", filename="viewer.glb")


# ---------------------------------------------------------------------- demo --

YUBI_REPO = "Toyota/yubi-hw"
YUBI = {   # pinned tags -> files, verified against the repository tree on 2026-10-07
    "v1.2.0": ["STEP/gripper/YUBI Gripper Assy_DYNAMIXEL.stp", "docs/BOM/YUBI Gripper_DYNAMIXEL_BOM.md"],
    "v2.0.0": ["STEP/gripper/YUBI Gripper Assy_Dynamixel_ver2.STEP", "docs/BOM/YUBI Gripper_DYNAMIXEL_BOM.md",
               "docs/AssemblyInstruction/YUBI Gripper_DYNAMIXEL_AssemblyGuide.pdf"],
}
YUBI_CREDIT = "YUBI hardware by Toyota Motor Corporation, CERN-OHL-W v2 — https://github.com/Toyota/yubi-hw"


def _fetch(tag: str, path: str) -> bytes:
    import urllib.parse

    import httpx

    url = f"https://raw.githubusercontent.com/{YUBI_REPO}/{tag}/{urllib.parse.quote(path)}"
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.content


@app.post("/api/demo/yubi", status_code=201)
def demo_yubi(uid: str = Depends(owner)) -> dict:
    """Create the YUBI Gripper project from Toyota's repository at pinned tags and start both reviews."""
    s = store()
    p = s.create_project(uid, "YUBI Gripper", f"DYNAMIXEL gripper. {YUBI_CREDIT}")
    for tag, paths in YUBI.items():
        r = s.create_revision(p["id"], tag, YUBI_REPO, tag)
        for path in paths:
            try:
                _ingest_bytes(r["id"], Path(path).name, _fetch(tag, path))
            except Exception as e:  # noqa: BLE001
                raise HTTPException(502, f"could not fetch {path}@{tag} from GitHub: {e}") from None
        job = s.create_job(r["id"], uid)
        s.set_revision_status(r["id"], "queued")
        jobrunner.submit(job["id"], database_url())
    return get_project(p["id"], uid)


# ------------------------------------------------------------------ findings --

def _finding_of(fid: str, uid: str) -> dict:
    f = store().finding(fid)
    if f is None:
        raise HTTPException(404, "finding not found")
    _revision_of(f["revision_id"], uid)
    return f


@app.get("/api/revisions/{rid}/findings")
def list_findings(rid: str, include_resolved: bool = False, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    s = store()
    rows = s.findings_for(rid, active_only=not include_resolved)
    order = {sev: i for i, sev in enumerate(SEVERITIES)}
    rows.sort(key=lambda f: (order[f["severity"]], f["domain"], f["check_id"], f["title"]))
    from .checks.base import DOMAINS
    return {"findings": [_finding_out(f) for f in rows], "check_runs": [_run_out(r) for r in s.check_runs_for(rid)],
            "summary": _summary([f for f in rows if f["active"]]), "domains": DOMAINS}


@app.get("/api/findings/{fid}")
def get_finding(fid: str, uid: str = Depends(owner)) -> dict:
    f = _finding_of(fid, uid)
    return _finding_out(f) | {"events": [_event_out(e) for e in store().events_for(fid)]}


class FindingPatch(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|accepted|rejected|fixed|deferred)$")
    owner: Optional[str] = Field(default=None, max_length=120)
    clear_owner: bool = False
    note: Optional[str] = Field(default=None, max_length=4000)


@app.patch("/api/findings/{fid}")
def patch_finding(fid: str, body: FindingPatch, uid: str = Depends(owner)) -> dict:
    f = _finding_of(fid, uid)
    if body.status == "rejected" and body.status != f["status"] and not (body.note or "").strip():
        raise HTTPException(422, "rejecting a finding needs a reason")
    store().update_finding(fid, uid, status=body.status, owner=body.owner, note=(body.note or "").strip() or None,
                           clear_owner=body.clear_owner)
    return get_finding(fid, uid)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.post("/api/findings/{fid}/comments", status_code=201)
def comment_finding(fid: str, body: CommentIn, uid: str = Depends(owner)) -> dict:
    _finding_of(fid, uid)
    store().update_finding(fid, uid, note=body.text.strip())
    return get_finding(fid, uid)


@app.get("/api/revisions/{rid}/report.json")
def report_json(rid: str, uid: str = Depends(owner)):
    """Everything needed to audit the review later: inputs by hash, check versions, findings and their history."""
    from datetime import datetime, timezone

    from fastapi.responses import JSONResponse

    r = _revision_of(rid, uid)
    s = store()
    p = s.project(r["project_id"])
    g = s.graph(rid)
    rows = s.findings_for(rid, active_only=False)
    report = {
        "report": "OrionFlow Review", "generated_at": datetime.now(timezone.utc).isoformat(), "generated_by": uid,
        "project": {"id": p["id"], "name": p["name"]},
        "revision": {"id": r["id"], "label": r["label"], "git_repo": r["git_repo"], "git_ref": r["git_ref"]},
        "inputs": [_file_out(f) for f in s.files_for(rid)],
        "model_graph": {"schema_version": g["schema_version"], "stats": g["graph"]["stats"],
                        "source": g["graph"]["source"]} if g else None,
        "check_runs": [_run_out(c) for c in s.check_runs_for(rid)],
        "summary": _summary([f for f in rows if f["active"]]),
        "findings": [_finding_out(f) | {"events": [_event_out(e) for e in s.events_for(f["id"])]} for f in rows],
    }
    name = f"orionflow-review-{p['name']}-{r['label']}.json".replace(" ", "_")
    return JSONResponse(report, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ----------------------------------------------------------------------- BOM --

def _graph_model(rid: str):
    from .schema import ModelGraph
    g = store().graph(rid)
    if g is None:
        raise HTTPException(404, "no model graph yet: run the review first")
    return ModelGraph.model_validate(g["graph"]), g


def _bom_out(graph) -> dict:
    from collections import Counter
    count = Counter(i.part_id for i in graph.instances)
    matched: dict[str, list[str]] = {}
    for r in graph.bom_rows:
        if r["part_id"] and r["method"] != "none":
            matched.setdefault(r["part_id"], []).append(r["key"])
    return {
        "rows": graph.bom_rows,
        "parts": [{"id": p.id, "name": p.name, "count": count[p.id], "material": p.material, "process": p.process,
                   "mass": p.mass, "volume": p.volume, "rows": matched.get(p.id, [])} for p in graph.parts],
        "files": [d for d in graph.documents if d.get("kind") == "bom"],
    }


@app.get("/api/revisions/{rid}/bom")
def get_bom(rid: str, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    graph, _ = _graph_model(rid)
    return _bom_out(graph)


class BomLinkIn(BaseModel):
    row_key: str = Field(min_length=1, max_length=500)
    part_id: Optional[str] = None


def _relink(rid: str, job_owner: str) -> dict:
    """Re-apply matching with the engineer's links, save the graph and re-run the checks (no geometry)."""
    import json as _json

    from .bom import apply, reconcile, rows_from_records
    from .checks import run_checks

    s = store()
    graph, row = _graph_model(rid)
    human = s.bom_links_for(rid)
    prior = {r["key"]: (r["part_id"], "ai", r["confidence"]) for r in graph.bom_rows if r["method"] == "ai"}
    records = reconcile(rows_from_records(graph.bom_rows), graph, human=human, prior=prior)
    apply(graph, records)
    s.save_graph(rid, graph.schema_version, _json.loads(graph.model_dump_json()), row["glb_key"])
    results, runs = run_checks(graph)
    s.save_check_results(rid, None, results, runs)
    return _bom_out(graph)


@app.put("/api/revisions/{rid}/bom/links")
def put_bom_link(rid: str, body: BomLinkIn, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    graph, _ = _graph_model(rid)
    if not any(r["key"] == body.row_key for r in graph.bom_rows):
        raise HTTPException(404, "no such BOM row")
    if body.part_id is not None and not any(p.id == body.part_id for p in graph.parts):
        raise HTTPException(422, "no such CAD part")
    store().set_bom_link(rid, body.row_key, body.part_id, uid)
    return _relink(rid, uid)


class BomUnlinkIn(BaseModel):
    row_key: str = Field(min_length=1, max_length=500)


@app.delete("/api/revisions/{rid}/bom/links")
def delete_bom_link(rid: str, body: BomUnlinkIn, uid: str = Depends(owner)) -> dict:
    _revision_of(rid, uid)
    store().clear_bom_link(rid, body.row_key)
    return _relink(rid, uid)


@app.get("/api/revisions/{rid}/bom.{fmt}")
def export_bom(rid: str, fmt: str, uid: str = Depends(owner)):
    import csv
    import io

    from fastapi.responses import Response

    from .bom import export_rows

    if fmt not in ("csv", "xlsx"):
        raise HTTPException(404, "csv or xlsx")
    r = _revision_of(rid, uid)
    graph, _ = _graph_model(rid)
    rows = export_rows(graph)
    cols = list(rows[0].keys()) if rows else ["status"]
    name = f"bom-reconciled-{store().project(r['project_id'])['name']}-{r['label']}".replace(" ", "_")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reconciled BOM"
    ws.append(cols)
    for row in rows:
        ws.append([row.get(c) for c in cols])
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
