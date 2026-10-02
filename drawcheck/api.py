"""HTTP service and review UI.

    python -m drawcheck serve            # http://127.0.0.1:8010

Customer drawings are confidential, so the defaults are conservative: it binds
to localhost, every run lives in one folder that DELETE removes completely,
runs older than DRAWCHECK_RETENTION_DAYS are purged, and when DRAWCHECK_TOKEN
is set every API call needs `Authorization: Bearer <token>`.

Env:
    DRAWCHECK_DATA            run folder root (default data/drawcheck_runs)
    DRAWCHECK_TOKEN           API token; unset = no auth (localhost use)
    DRAWCHECK_RETENTION_DAYS  delete runs older than this (default 30; 0 = keep)
    DRAWCHECK_MAX_MB          upload limit (default 50)
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from .check import check_file
from .ingest import render_page
from .model import Finding, Report
from .report import write_annotated_pdf, write_json, write_query_xlsx
from .store import Store

DATA = Path(os.environ.get("DRAWCHECK_DATA", "data/drawcheck_runs"))
TOKEN = os.environ.get("DRAWCHECK_TOKEN", "")
RETENTION_DAYS = float(os.environ.get("DRAWCHECK_RETENTION_DAYS", "30"))
MAX_BYTES = int(float(os.environ.get("DRAWCHECK_MAX_MB", "50")) * 1024 * 1024)
UI = Path(__file__).with_name("static") / "review.html"

app = FastAPI(title="drawcheck", version="0.1")
_lock = threading.Lock()

#: Called after every write. A hosted deployment points this at its storage's
#: commit (Modal Volume); locally the disk is the storage and nothing is needed.
PERSIST: Callable[[], None] = lambda: None


def _auth(authorization: str = Header(default="")) -> None:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "missing or wrong token")


def _store() -> Store:
    DATA.mkdir(parents=True, exist_ok=True)
    return Store(DATA / "reviews.sqlite")


def _run_dir(rid: str) -> Path:
    if not rid.isalnum():
        raise HTTPException(400, "bad run id")
    d = DATA / rid
    if not d.is_dir():
        raise HTTPException(404, "no such run")
    return d


def _meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


def _write_meta(d: Path, meta: dict) -> None:
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _purge() -> int:
    if RETENTION_DAYS <= 0 or not DATA.exists():
        return 0
    cutoff = time.time() - RETENTION_DAYS * 86400
    n = 0
    for d in DATA.iterdir():
        if d.is_dir() and (d / "meta.json").exists() and _meta(d).get("created", 0) < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def _report_from(d: dict) -> Report:
    r = Report(source=d["source"], pages=d["pages"], stats=d.get("stats", {}), title=d.get("title", {}),
               reader_warnings=d.get("reader_warnings", []))
    r.findings = [Finding(**{k: (tuple(v) if k == "bbox" and v else v) for k, v in f.items()}) for f in d["findings"]]
    r.suppressed = [Finding(**{k: (tuple(v) if k == "bbox" and v else v) for k, v in f.items()}) for f in d["suppressed"]]
    return r


def _write_outputs(d: Path, report: Report, sizes: dict[int, tuple[float, float]]) -> None:
    write_json(report, d / "report.json")
    write_annotated_pdf(report, d / "original.pdf", d / "checked.pdf")
    write_query_xlsx(report, d / "queries.xlsx", sizes)


def _process(rid: str) -> None:
    d = DATA / rid
    meta = _meta(d)
    meta["status"] = "running"
    _write_meta(d, meta)
    try:
        report, drawing = check_file(d / "original.pdf", vision=meta["vision"], store=_store(),
                                     customer=meta["customer"])
        report.source = meta["filename"]
        sizes = {p.index: (p.width, p.height) for p in drawing.pages}
        _write_outputs(d, report, sizes)
        meta.update(status="done", pages=[{"w": p.width, "h": p.height, "layer": p.layer} for p in drawing.pages],
                    errors=report.count("error"), warnings=report.count("warning"), infos=report.count("info"),
                    drawing_number=report.title.get("drawing_number") or report.title.get("part_number") or "",
                    finished=time.time())
    except Exception as e:  # the run records its own failure; the server keeps going
        meta.update(status="error", error=f"{type(e).__name__}: {e}")
    _write_meta(d, meta)
    PERSIST()


# ------------------------------------------------------------------ routes

@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return UI.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "auth": bool(TOKEN), "retention_days": RETENTION_DAYS}


@app.post("/api/runs", dependencies=[Depends(_auth)])
async def create_run(background: BackgroundTasks, file: UploadFile = File(...),
                     customer: str = Form(""), vision: str = Form("scanned")) -> dict:
    if vision not in ("off", "scanned", "all"):
        raise HTTPException(400, "vision must be off, scanned or all")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"file larger than {MAX_BYTES // 1024 // 1024} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "not a PDF")
    _purge()
    rid = uuid.uuid4().hex[:12]
    d = DATA / rid
    d.mkdir(parents=True)
    (d / "original.pdf").write_bytes(data)
    _write_meta(d, {"id": rid, "filename": Path(file.filename or "drawing.pdf").name, "customer": customer.strip(),
                    "vision": vision, "status": "queued", "created": time.time()})
    PERSIST()
    background.add_task(_process, rid)
    return {"id": rid, "status": "queued"}


@app.get("/api/runs", dependencies=[Depends(_auth)])
def list_runs() -> list[dict]:
    _purge()
    if not DATA.exists():
        return []
    runs = [_meta(d) for d in DATA.iterdir() if d.is_dir() and (d / "meta.json").exists()]
    return sorted(runs, key=lambda m: -m.get("created", 0))


@app.get("/api/runs/{rid}", dependencies=[Depends(_auth)])
def get_run(rid: str) -> dict:
    d = _run_dir(rid)
    out = _meta(d)
    if (d / "report.json").exists():
        out["report"] = json.loads((d / "report.json").read_text(encoding="utf-8"))
    return out


@app.delete("/api/runs/{rid}", dependencies=[Depends(_auth)])
def delete_run(rid: str) -> dict:
    shutil.rmtree(_run_dir(rid))
    PERSIST()
    return {"deleted": rid}


@app.get("/api/runs/{rid}/pages/{n}.png", dependencies=[Depends(_auth)])
def page_image(rid: str, n: int, dpi: int = 110) -> Response:
    d = _run_dir(rid)
    dpi = max(50, min(dpi, 220))
    cache = d / f"page{n}_{dpi}.png"
    if not cache.exists():
        try:
            png, _ = render_page(d / "original.pdf", n, dpi=dpi)
        except IndexError:
            raise HTTPException(404, "no such page")
        cache.write_bytes(png)
    return FileResponse(cache, media_type="image/png")


_FILES = {"checked.pdf": "application/pdf", "queries.xlsx":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "report.json": "application/json",
          "original.pdf": "application/pdf"}


@app.get("/api/runs/{rid}/files/{name}", dependencies=[Depends(_auth)])
def run_file(rid: str, name: str) -> FileResponse:
    if name not in _FILES:
        raise HTTPException(404, "unknown file")
    d = _run_dir(rid)
    if not (d / name).exists():
        raise HTTPException(404, "not ready")
    stem = Path(_meta(d)["filename"]).stem
    return FileResponse(d / name, media_type=_FILES[name], filename=f"{stem}.{name}")


class Decision(BaseModel):
    decision: str            # "accepted" | "rejected" | "" (undo)
    note: str = ""
    reviewer: str = ""


@app.post("/api/runs/{rid}/findings/{fid}", dependencies=[Depends(_auth)])
def decide(rid: str, fid: str, body: Decision) -> dict:
    if body.decision not in ("accepted", "rejected", ""):
        raise HTTPException(400, "decision must be accepted, rejected or empty")
    d = _run_dir(rid)
    meta = _meta(d)
    with _lock:
        report = _report_from(json.loads((d / "report.json").read_text(encoding="utf-8")))
        everything = report.findings + report.suppressed
        f = next((x for x in everything if x.id == fid), None)
        if f is None:
            raise HTTPException(404, "no such finding")
        store = _store()
        store.decide(f, body.decision, customer=meta["customer"], drawing=meta.get("drawing_number", ""),
                     source=meta["filename"], note=body.note, reviewer=body.reviewer)
        # Re-apply all decisions so the files match what the reviewer sees.
        for x in everything:
            x.decision = ""
        report.findings, report.suppressed = everything, []
        store.apply(report, meta["customer"])
        order = {"error": 0, "warning": 1, "info": 2}
        report.findings.sort(key=lambda x: (order[x.severity], x.page if x.page is not None else -1, x.rule))
        sizes = {i: (p["w"], p["h"]) for i, p in enumerate(meta.get("pages", []))}
        _write_outputs(d, report, sizes)
    PERSIST()
    return {"ok": True, "open": sum(1 for x in report.findings if not x.decision)}


@app.get("/api/reviews/stats", dependencies=[Depends(_auth)])
def review_stats() -> dict:
    """Per rule: how often reviewers accepted (real, but waived) or rejected (checker wrong)."""
    return _store().stats()
