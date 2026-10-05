"""Stateless HTTP API. It authenticates, validates, records and dispatches —
it never opens a CAD file beyond its first bytes.

    POST   /api/uploads                         signed upload URLs for each file
    PUT    /api/uploads/{upload_id}/{kind}/{fn} upload target when storage is local
    POST   /api/analysis                        create the job from an upload -> 202 {job_id}
    POST   /api/analysis/direct                 multipart convenience (CLI, small files)
    GET    /api/analysis                        the caller's jobs
    GET    /api/analysis/{id}                   state, stages, findings, downloads
    GET    /api/analysis/{id}/files/{name}      report.json | report.pdf | model.glb
    POST   /api/analysis/{id}/cancel
    POST   /api/analysis/{id}/findings/{fp}/review
    DELETE /api/analysis/{id}                   files and rows, gone
    GET    /api/admin/metrics                   latency percentiles, memory, failures, cache, cost
    POST   /api/admin/sweep                     recover lost workers, apply retention
"""
from __future__ import annotations

import re
import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..limits import limits_for
from ..version import ENGINE_VERSION
from .auth import User, current_user
from .db import TERMINAL
from .dispatch import context
from .jobs import QuotaExceeded, admit, pump, sweep
from .storage import LocalStorage

app = FastAPI(title="OrionFlow CAD analysis", version=ENGINE_VERSION)
UI = Path(__file__).resolve().parents[1] / "static" / "report.html"

#: kind -> (allowed extensions, many files?, magic check)
KINDS = {
    "step": ({".step", ".stp"}, False, "step"), "prev_step": ({".step", ".stp"}, False, "step"),
    "vendor_step": ({".step", ".stp"}, True, "step"),
    "bom": ({".csv", ".tsv", ".txt"}, False, "text"), "prev_bom": ({".csv", ".tsv", ".txt"}, False, "text"),
    "urdf": ({".urdf", ".xml"}, False, "xml"), "urdf_map": ({".yaml", ".yml"}, False, "text"),
    "drawing": ({".pdf"}, True, "pdf"), "datasheet": ({".pdf"}, True, "pdf"),
}
ARCHIVE_EXT = {".zip", ".gz", ".tgz", ".7z", ".rar", ".tar", ".bz2", ".xz"}
ARCHIVE_MAGIC = (b"PK\x03\x04", b"\x1f\x8b", b"7z\xbc\xaf", b"Rar!", b"BZh", b"\xfd7zXZ")
OUTPUT_NAMES = {"report.json": "application/json", "report.pdf": "application/pdf", "model.glb": "model/gltf-binary"}


def _safe_name(name: str) -> str:
    name = Path(name or "upload").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "upload"


def _check_name(kind: str, filename: str) -> str:
    if kind not in KINDS:
        raise HTTPException(400, f"unknown file kind {kind!r}")
    fn = _safe_name(filename)
    ext = Path(fn).suffix.lower()
    if ext in ARCHIVE_EXT:
        raise HTTPException(415, f"{fn}: archives are not accepted; upload the files themselves")
    if ext not in KINDS[kind][0]:
        raise HTTPException(415, f"{fn}: a {kind} file must be {', '.join(sorted(KINDS[kind][0]))}")
    return fn


def _check_magic(kind: str, fn: str, head: bytes) -> None:
    if head.startswith(ARCHIVE_MAGIC):
        raise HTTPException(415, f"{fn}: this is an archive, not a {kind} file")
    check = KINDS[kind][2]
    ok = {"step": head.lstrip().startswith(b"ISO-10303-21"), "pdf": head.startswith(b"%PDF-"),
          "xml": head.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"),
          "text": b"\x00" not in head}[check]
    if not ok:
        raise HTTPException(415, f"{fn}: content is not a valid {kind} file")


# ------------------------------------------------------------------ uploads

class UploadFileSpec(BaseModel):
    kind: str
    filename: str
    size: int = Field(ge=1)


class UploadInit(BaseModel):
    files: list[UploadFileSpec]


@app.post("/api/uploads")
def init_upload(body: UploadInit, user: User = Depends(current_user)) -> dict:
    ctx = context()
    lim = limits_for(user.plan)
    if not any(f.kind == "step" for f in body.files):
        raise HTTPException(400, "an assembly STEP file (kind 'step') is required")
    total = 0
    seen: dict[str, int] = {}
    out = []
    upload_id = uuid.uuid4().hex
    for f in body.files:
        fn = _check_name(f.kind, f.filename)
        seen[f.kind] = seen.get(f.kind, 0) + 1
        if seen[f.kind] > 1 and not KINDS[f.kind][1]:
            raise HTTPException(400, f"only one {f.kind} file is allowed")
        if f.size > lim.max_file_mb * 2**20:
            raise HTTPException(413, f"{fn} is larger than the {lim.max_file_mb} MB limit of the {lim.plan} plan")
        total += f.size
        key = f"uploads/{user.id}/{upload_id}/{f.kind}/{fn}"
        url = ctx.storage.signed_put(key, ctx.cfg.signed_url_ttl, lim.max_file_mb * 2**20) \
            or f"/api/uploads/{upload_id}/{f.kind}/{fn}"
        out.append({"kind": f.kind, "filename": fn, "key": key, "method": "PUT", "url": url})
    if total > lim.max_total_upload_mb * 2**20:
        raise HTTPException(413, f"uploads total more than the {lim.max_total_upload_mb} MB limit")
    return {"upload_id": upload_id, "files": out, "expires_in": ctx.cfg.signed_url_ttl}


@app.put("/api/uploads/{upload_id}/{kind}/{filename}")
async def local_upload(upload_id: str, kind: str, filename: str, request: Request,
                       user: User = Depends(current_user)) -> dict:
    ctx = context()
    if not isinstance(ctx.storage, LocalStorage):
        raise HTTPException(404, "uploads go to the signed URL")
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise HTTPException(400, "bad upload id")
    fn = _check_name(kind, filename)
    lim = limits_for(user.plan)
    chunks = []
    async for chunk in request.stream():
        chunks.append(chunk)
        if sum(map(len, chunks)) > lim.max_file_mb * 2**20:
            raise HTTPException(413, f"{fn} is larger than the {lim.max_file_mb} MB limit")
    n = ctx.storage.put_stream(f"uploads/{user.id}/{upload_id}/{kind}/{fn}", chunks, lim.max_file_mb * 2**20)
    return {"stored": n}


# ------------------------------------------------------------------ jobs

class CreateAnalysis(BaseModel):
    upload_id: str
    label: str = ""
    project_id: Optional[str] = None
    prev_job_id: Optional[str] = None       # compare against an earlier analysis's assembly


def _create(user: User, upload_id: str, label: str, project_id: str | None, prev_job_id: str | None,
            idempotency_key: str | None) -> dict:
    ctx = context()
    lim = limits_for(user.plan)
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise HTTPException(400, "bad upload id")
    key = idempotency_key or f"upload:{upload_id}"
    existing = ctx.store.job_by_key(user.id, key)      # same request again -> same job, nothing re-run
    if existing:
        return existing
    try:
        admit(ctx.store, user.id, user.plan)
    except QuotaExceeded as e:
        raise HTTPException(429, str(e)) from None
    prefix = f"uploads/{user.id}/{upload_id}/"
    objects = list(ctx.storage.list(prefix))
    if not any(k[len(prefix):].startswith("step/") for k in objects):
        raise HTTPException(400, "the upload has no assembly STEP file (was the PUT completed?)")
    job_id = uuid.uuid4().hex
    docs, total = [], 0
    for k in objects:
        kind, fn = k[len(prefix):].split("/", 1)
        fn = _check_name(kind, fn)
        size = ctx.storage.size(k) or 0
        if size > lim.max_file_mb * 2**20:
            raise HTTPException(413, f"{fn} is larger than the {lim.max_file_mb} MB limit")
        total += size
        _check_magic(kind, fn, ctx.storage.head(k, 512))
        dst = f"jobs/{job_id}/input/{kind}/{fn}"
        ctx.storage.copy(k, dst)                       # inputs become immutable under the job
        docs.append({"kind": kind, "filename": fn, "storage_key": dst, "size_bytes": size})
    if total > lim.max_total_upload_mb * 2**20:
        raise HTTPException(413, f"uploads total more than the {lim.max_total_upload_mb} MB limit")
    if prev_job_id:
        prev = ctx.store.get_job(prev_job_id, user.id)
        if prev is None:
            raise HTTPException(404, "previous analysis not found")
        for d in ctx.store.documents(prev_job_id):
            if d["kind"] in ("step", "bom") and not any(x["kind"] == f"prev_{d['kind']}" for x in docs):
                dst = f"jobs/{job_id}/input/prev_{d['kind']}/{d['filename']}"
                ctx.storage.copy(d["storage_key"], dst)
                docs.append({"kind": f"prev_{d['kind']}", "filename": d["filename"], "storage_key": dst,
                             "size_bytes": d["size_bytes"]})
    job, _ = ctx.store.create_job(user.id, user.plan, "SMALL", {"prev_job_id": prev_job_id}, key,
                                  label or next(d["filename"] for d in docs if d["kind"] == "step"),
                                  project_id, docs, job_id=job_id)
    ctx.storage.delete_prefix(prefix)
    pump(ctx.store, ctx.dispatcher, ctx.cfg.global_concurrency)
    return ctx.store.get_job(job["id"])


def _public(job: dict) -> dict:
    keys = ("id", "label", "state", "tier", "attempts", "stage", "failure_code", "error", "summary",
            "complexity", "plan", "created_at", "started_at", "finished_at")
    out = {k: job.get(k) for k in keys}
    for k in ("created_at", "started_at", "finished_at"):
        if out[k] is not None:
            out[k] = out[k].isoformat()
    if out["complexity"]:
        out["complexity"] = {k: v for k, v in out["complexity"].items() if k != "counts"}
    out["terminal"] = job["state"] in TERMINAL
    return out


@app.post("/api/analysis", status_code=202)
def create_analysis(body: CreateAnalysis, user: User = Depends(current_user),
                    idempotency_key: str = Header(default="")) -> dict:
    return _public(_create(user, body.upload_id, body.label, body.project_id, body.prev_job_id,
                           idempotency_key or None))


@app.post("/api/analysis/direct", status_code=202)
async def create_direct(request: Request, user: User = Depends(current_user),
                        idempotency_key: str = Header(default="")) -> dict:
    """Multipart form: one field per kind (repeat drawing / datasheet / vendor_step)."""
    ctx = context()
    lim = limits_for(user.plan)
    form = await request.form()
    upload_id = uuid.uuid4().hex
    for kind, value in form.multi_items():
        if not hasattr(value, "filename") or not value.filename:
            continue
        fn = _check_name(kind, value.filename)
        data = await value.read()
        if len(data) > lim.max_file_mb * 2**20:
            raise HTTPException(413, f"{fn} is larger than the {lim.max_file_mb} MB limit")
        ctx.storage.put_bytes(f"uploads/{user.id}/{upload_id}/{kind}/{fn}", data)
    return _public(_create(user, upload_id, str(form.get("label") or ""), None,
                           str(form.get("prev_job_id") or "") or None, idempotency_key or None))


@app.get("/api/analysis")
def list_analyses(user: User = Depends(current_user)) -> list[dict]:
    return [_public(j) for j in context().store.list_jobs(user.id)]


@app.get("/api/analysis/{job_id}")
def get_analysis(job_id: str, user: User = Depends(current_user)) -> dict:
    ctx = context()
    job = ctx.store.get_job(job_id, user.id)
    if job is None:
        raise HTTPException(404, "no such analysis")
    out = _public(job)
    out["documents"] = [{"kind": d["kind"], "filename": d["filename"], "size_bytes": d["size_bytes"]}
                        for d in ctx.store.documents(job_id)]
    res = ctx.store.results(job_id)
    if res:
        out.update(stages=res["stages"], narrative=res["narrative"], stats=res["stats"],
                   engine_version=res["engine_version"],
                   downloads=[n for n, k in (("report.json", res["report_key"]), ("report.pdf", res["pdf_key"]),
                                             ("model.glb", res["glb_key"])) if k])
        out["findings"] = [{k: f[k] for k in ("fingerprint", "rule_id", "severity", "message", "parts", "instances",
                                              "measured", "expected", "location", "method", "source",
                                              "change_status", "review", "review_note")}
                           for f in ctx.store.findings(job_id)]
    return out


@app.get("/api/analysis/{job_id}/files/{name}")
def get_file(job_id: str, name: str, user: User = Depends(current_user)):
    ctx = context()
    if name not in OUTPUT_NAMES:
        raise HTTPException(404, "unknown file")
    if ctx.store.get_job(job_id, user.id) is None:
        raise HTTPException(404, "no such analysis")
    key = f"jobs/{job_id}/output/{name}"
    if not ctx.storage.exists(key):
        raise HTTPException(404, "not available")
    url = ctx.storage.signed_get(key, ctx.cfg.signed_url_ttl, f"{job_id}-{name}")
    if url:
        return RedirectResponse(url, status_code=307)
    return FileResponse(ctx.storage.path(key), media_type=OUTPUT_NAMES[name], filename=f"{job_id}-{name}")


@app.post("/api/analysis/{job_id}/cancel")
def cancel(job_id: str, user: User = Depends(current_user)) -> dict:
    ctx = context()
    job = ctx.store.get_job(job_id, user.id)
    if job is None:
        raise HTTPException(404, "no such analysis")
    now = datetime.now(timezone.utc)
    if ctx.store.transition(job_id, ["QUEUED"], state="CANCELLED", cancel_requested=True, finished_at=now):
        return _public(ctx.store.get_job(job_id))
    if job["state"] == "RUNNING":
        ctx.store.update(job_id, cancel_requested=True)
        if ctx.cfg.dispatch == "modal":
            ctx.dispatcher.cancel(job.get("dispatch_ref") or "")      # container is stopped: no watchdog left
            ctx.store.transition(job_id, ["RUNNING"], state="CANCELLED", finished_at=now)
    return _public(ctx.store.get_job(job_id))


class Review(BaseModel):
    verdict: str            # real | not_issue | open
    note: str = ""


@app.post("/api/analysis/{job_id}/findings/{fingerprint}/review")
def review(job_id: str, fingerprint: str, body: Review, user: User = Depends(current_user)) -> dict:
    ctx = context()
    if body.verdict not in ("real", "not_issue", "open"):
        raise HTTPException(400, "verdict must be real, not_issue or open")
    if ctx.store.get_job(job_id, user.id) is None:
        raise HTTPException(404, "no such analysis")
    if not ctx.store.review(job_id, fingerprint, body.verdict, body.note):
        raise HTTPException(404, "no such finding")
    return {"fingerprint": fingerprint, "verdict": body.verdict}


@app.delete("/api/analysis/{job_id}")
def delete(job_id: str, user: User = Depends(current_user)) -> dict:
    ctx = context()
    job = ctx.store.get_job(job_id, user.id)
    if job is None:
        raise HTTPException(404, "no such analysis")
    if job["state"] == "RUNNING":
        cancel(job_id, user)
    n = ctx.storage.delete_prefix(f"jobs/{job_id}/")
    ctx.store.delete_job(job_id)
    return {"deleted": job_id, "files": n}


# ------------------------------------------------------------------ operations

def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 3)


@app.get("/api/admin/metrics")
def metrics(days: int = 30, user: User = Depends(current_user)) -> dict:
    if not user.admin:
        raise HTTPException(403, "admin only")
    runs = context().store.worker_runs(datetime.now(timezone.utc) - timedelta(days=days))
    done = [r for r in runs if r["outcome"] == "SUCCEEDED"]
    rt = [r["runtime_s"] for r in done if r["runtime_s"] is not None]
    mem = [r["peak_memory_mb"] for r in runs if r["peak_memory_mb"] is not None]
    hits = sum(r["cache_hits"] or 0 for r in runs)
    misses = sum(r["cache_misses"] or 0 for r in runs)
    by_tier: dict = {}
    for r in runs:
        t = by_tier.setdefault(r["tier"], {"runs": 0, "succeeded": 0, "peak_memory_mb_max": 0, "cost_usd": 0.0})
        t["runs"] += 1
        t["succeeded"] += r["outcome"] == "SUCCEEDED"
        t["peak_memory_mb_max"] = max(t["peak_memory_mb_max"], r["peak_memory_mb"] or 0)
        t["cost_usd"] = round(t["cost_usd"] + (r["cost_usd"] or 0), 4)
    failures: dict = {}
    for r in runs:
        if r["failure_code"]:
            failures[r["failure_code"]] = failures.get(r["failure_code"], 0) + 1
    return {
        "window_days": days, "runs": len(runs), "succeeded": len(done),
        "failure_rate": round(1 - len(done) / len(runs), 4) if runs else None,
        "latency_s": {"p50": _pct(rt, 50), "p95": _pct(rt, 95), "p99": _pct(rt, 99),
                      "mean": round(statistics.mean(rt), 3) if rt else None},
        "peak_memory_mb": {"p50": _pct(mem, 50), "p95": _pct(mem, 95), "max": max(mem) if mem else None},
        "cache_hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
        "cost_usd": {"total": round(sum(r["cost_usd"] or 0 for r in runs), 4),
                     "per_succeeded_job": round(sum(r["cost_usd"] or 0 for r in runs) / len(done), 6)
                     if done else None},
        "by_tier": by_tier, "failures": failures, "engine_version": ENGINE_VERSION,
    }


@app.post("/api/admin/sweep")
def admin_sweep(user: User = Depends(current_user)) -> dict:
    if not user.admin:
        raise HTTPException(403, "admin only")
    return run_maintenance()


def run_maintenance() -> dict:
    """Recover lost workers, re-pump the queue, delete expired jobs. Run on a schedule."""
    ctx = context()
    out = sweep(ctx.store, ctx.dispatcher, ctx.cfg.global_concurrency)
    purged = 0
    if ctx.cfg.retention_days > 0:
        for job in ctx.store.expired(ctx.cfg.retention_days):
            if job["state"] in TERMINAL:
                ctx.storage.delete_prefix(f"jobs/{job['id']}/")
                ctx.store.delete_job(job["id"])
                purged += 1
    out["purged"] = purged
    return out


@app.on_event("startup")
def _local_maintenance() -> None:
    """Hosted, a scheduled function runs maintenance; locally a daemon thread does."""
    import threading
    import time as _time

    ctx = context()
    if ctx.cfg.dispatch != "local":
        return

    def loop() -> None:
        while True:
            _time.sleep(60)
            try:
                run_maintenance()
            except Exception:  # noqa: BLE001 - maintenance retries next minute
                pass
    threading.Thread(target=loop, daemon=True, name="ic-maintenance").start()


@app.get("/api/health")
def health() -> dict:
    """Liveness: cheap, unauthenticated, touches nothing external."""
    ctx = context()
    return {"ok": True, "engine_version": ENGINE_VERSION, "dispatch": ctx.cfg.dispatch,
            "storage": ctx.cfg.storage, "auth": bool(ctx.cfg.jwt_secret or ctx.cfg.dev_token)}


def _check(fn) -> dict:
    t0 = time.time()
    try:
        out = fn() or {}
        out.setdefault("ok", True)
    except Exception as e:  # noqa: BLE001 - every dependency reports, none raises
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out["ms"] = round((time.time() - t0) * 1000, 1)
    return out


@app.get("/api/health/deep")
def deep_health(workers: bool = False, user: User = Depends(current_user)) -> dict:
    """Readiness of every dependency. ``workers=true`` also starts one probe container per tier."""
    if not user.admin:
        raise HTTPException(403, "admin only")
    ctx = context()

    def database() -> dict:
        import sqlalchemy as sa
        with ctx.store.engine.connect() as c:
            c.execute(sa.text("select 1"))
            out = {"dialect": ctx.store.engine.dialect.name}
            if out["dialect"] == "postgresql":
                out["alembic"] = c.execute(sa.text("select version_num from alembic_version")).scalar()
                out["tables"] = int(c.execute(sa.text(
                    "select count(*) from pg_tables where schemaname='public' and tablename = any(:t)"),
                    {"t": ["projects", "revisions", "analysis_jobs", "documents", "assemblies", "parts",
                           "analysis_results", "findings", "geometry_hashes", "worker_runs"]}).scalar())
                out["rls_off"] = [r[0] for r in c.execute(sa.text(
                    "select tablename from pg_tables where schemaname='public' and not rowsecurity"))]
                out["ok"] = out["tables"] == 10 and not out["rls_off"] and out["alembic"] >= "013"
            out["queued"] = len(ctx.store.queued())
            out["active"] = ctx.store.active_count()
        return out

    def storage() -> dict:
        key = f"health/{uuid.uuid4().hex}"
        ctx.storage.put_bytes(key, b"probe")
        ok = ctx.storage.get_bytes(key) == b"probe"
        ctx.storage.delete_prefix(key)
        return {"ok": ok and not ctx.storage.exists(key), "kind": ctx.cfg.storage,
                "bucket": ctx.cfg.s3_bucket or None}

    checks = {"api": {"ok": True, "engine_version": ENGINE_VERSION}, "database": _check(database),
              "storage": _check(storage), "dispatcher": _check(lambda: ctx.dispatcher.health(workers))}
    return {"ok": all(c["ok"] for c in checks.values()), **checks}


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return UI.read_text(encoding="utf-8")

