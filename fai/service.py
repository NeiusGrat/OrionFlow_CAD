"""Projects, revisions, decisions and sign-off — the record an FAI leaves behind.

Storage is one SQLite file plus one folder per revision:

    <root>/fai.sqlite
    <root>/<owner>/<project>/<revision>/input/{drawing.pdf, model.step, bom.csv}
                                        result.json  model.glb  exports/

Every change a person makes (edit a characteristic, decide a finding, sign) is
an event row: who, when, what, before and after. A signed revision is frozen:
edits are refused, and its exports are written once without the DRAFT stamp.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import forms
from .compare import compare as compare_chars
from .pipeline import STEPS, run_safe

ROOT = Path(os.environ.get("FAI_DATA", "data/fai"))
_lock = threading.RLock()

SCHEMA = """
create table if not exists projects (
    id text primary key, owner text not null, part_number text, part_name text, customer text,
    created real not null);
create table if not exists revisions (
    id text primary key, project_id text not null, owner text not null, label text, status text not null,
    created real not null, finished real, drawing_name text, drawing_sha text, step_name text, step_sha text,
    bom_name text, bom_sha text, options text, error text, progress text, signoff text);
create table if not exists events (
    id integer primary key autoincrement, project_id text, revision_id text, owner text not null,
    at real not null, actor text, action text not null, target text, detail text);
create table if not exists ignores (
    owner text not null, customer text not null, rule text not null, evidence text not null,
    created real not null, primary key (owner, customer, rule, evidence));
create index if not exists ix_rev_project on revisions(project_id);
create index if not exists ix_ev_project on events(project_id);
"""

EDITABLE = {"result", "status", "nc_number", "tooling", "reviewer_note", "requirement", "nominal", "lower", "upper",
            "key"}
STATUSES = {"open", "pass", "fail", "accepted", "waived"}
DECISIONS = {"", "accepted", "rejected", "ignored"}


def _spawn(fn, *args) -> None:
    """Run a check off the request thread. One hook, so tests can run it inline."""
    threading.Thread(target=fn, args=args, daemon=True, name=f"fai-{args[-1]}").start()


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _db() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ROOT / "fai.sqlite", timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def db():
    with _lock:
        con = _db()
        try:
            yield con
        finally:
            con.close()


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", s)[:64] or "x"


def _rev_dir(owner: str, pid: str, rid: str) -> Path:
    return ROOT / _safe(owner) / _safe(pid) / _safe(rid)


def _event(con, owner: str, pid: str | None, rid: str | None, actor: str, action: str, target: str = "",
           detail: dict | None = None) -> None:
    con.execute("insert into events (project_id, revision_id, owner, at, actor, action, target, detail) "
                "values (?,?,?,?,?,?,?,?)", (pid, rid, owner, time.time(), actor, action, target,
                                              json.dumps(detail or {}, default=str)))


# ------------------------------------------------------------------ projects

def create_project(owner: str, part_number: str = "", part_name: str = "", customer: str = "",
                   actor: str = "") -> dict:
    pid = _id()
    with db() as con:
        con.execute("insert into projects values (?,?,?,?,?,?)",
                    (pid, owner, part_number.strip(), part_name.strip(), customer.strip(), time.time()))
        _event(con, owner, pid, None, actor, "project_created",
               detail={"part_number": part_number, "customer": customer})
    return get_project(owner, pid)


def list_projects(owner: str) -> list[dict]:
    with db() as con:
        rows = [dict(r) for r in con.execute("select * from projects where owner=? order by created desc", (owner,))]
        for p in rows:
            last = con.execute("select * from revisions where project_id=? order by created desc limit 1",
                               (p["id"],)).fetchone()
            p["revisions"] = con.execute("select count(*) from revisions where project_id=?", (p["id"],)).fetchone()[0]
            p["latest"] = _rev_public(dict(last)) if last else None
    for p in rows:
        if p["latest"]:
            f = _rev_dir(owner, p["id"], p["latest"]["id"]) / "result.json"
            if f.exists():
                try:
                    p["latest"]["result"] = {"stats": json.loads(f.read_text(encoding="utf-8")).get("stats", {})}
                except ValueError:
                    pass
    return rows


def get_project(owner: str, pid: str) -> dict:
    with db() as con:
        p = con.execute("select * from projects where id=? and owner=?", (pid, owner)).fetchone()
        if p is None:
            raise NotFound("no such project")
        p = dict(p)
        revs = [_rev_public(dict(r)) for r in
                con.execute("select * from revisions where project_id=? order by created", (pid,))]
        prev = None
        for r in revs:
            r["drawing_changed"] = None if prev is None else (r["drawing_sha"] != prev["drawing_sha"])
            prev = r
        p["revisions"] = list(reversed(revs))
        p["events"] = [_event_public(dict(e)) for e in
                       con.execute("select * from events where project_id=? order by at desc limit 500", (pid,))]
    return p


def update_project(owner: str, pid: str, fields: dict, actor: str = "") -> dict:
    allowed = {k: str(v).strip() for k, v in fields.items() if k in ("part_number", "part_name", "customer")}
    with db() as con:
        if con.execute("select 1 from projects where id=? and owner=?", (pid, owner)).fetchone() is None:
            raise NotFound("no such project")
        for k, v in allowed.items():
            con.execute(f"update projects set {k}=? where id=?", (v, pid))  # noqa: S608 - k is whitelisted
        _event(con, owner, pid, None, actor, "project_updated", detail=allowed)
    return get_project(owner, pid)


def delete_project(owner: str, pid: str) -> None:
    with db() as con:
        if con.execute("select 1 from projects where id=? and owner=?", (pid, owner)).fetchone() is None:
            raise NotFound("no such project")
        for t, col in (("events", "project_id"), ("revisions", "project_id"), ("projects", "id")):
            con.execute(f"delete from {t} where {col}=?", (pid,))  # noqa: S608
    shutil.rmtree(ROOT / _safe(owner) / _safe(pid), ignore_errors=True)


def _rev_public(r: dict) -> dict:
    r["options"] = json.loads(r.get("options") or "{}")
    r["progress"] = json.loads(r.get("progress") or "[]")
    r["signoff"] = json.loads(r["signoff"]) if r.get("signoff") else None
    return r


def _event_public(e: dict) -> dict:
    e["detail"] = json.loads(e.get("detail") or "{}")
    return e


# ------------------------------------------------------------------ revisions

def create_revision(owner: str, pid: str, drawing: tuple[str, bytes], step: tuple[str, bytes] | None = None,
                    bom: tuple[str, bytes] | None = None, options: dict | None = None, label: str = "",
                    actor: str = "", background: bool = True) -> dict:
    get_project(owner, pid)
    rid = _id()
    d = _rev_dir(owner, pid, rid)
    (d / "input").mkdir(parents=True)
    paths = {"drawing": d / "input" / "drawing.pdf"}
    paths["drawing"].write_bytes(drawing[1])
    if step:
        paths["step"] = d / "input" / "model.step"
        paths["step"].write_bytes(step[1])
    if bom:
        ext = Path(bom[0]).suffix.lower() if Path(bom[0]).suffix.lower() in (".csv", ".tsv", ".txt") else ".csv"
        paths["bom"] = d / "input" / f"bom{ext}"
        paths["bom"].write_bytes(bom[1])
    from .pipeline import sha256
    options = dict(options or {})
    if step:
        options["step_name"] = step[0]
    with db() as con:
        con.execute("insert into revisions (id, project_id, owner, label, status, created, drawing_name, drawing_sha, "
                    "step_name, step_sha, bom_name, bom_sha, options, progress) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, pid, owner, label, "queued", time.time(), drawing[0], sha256(paths["drawing"]),
                     step[0] if step else None, sha256(paths["step"]) if step else None,
                     bom[0] if bom else None, sha256(paths["bom"]) if bom else None, json.dumps(options),
                     json.dumps([{"id": k, "name": n, "status": "pending"} for k, n in STEPS])))
        _event(con, owner, pid, rid, actor, "revision_uploaded",
               detail={"drawing": drawing[0], "step": step[0] if step else None, "bom": bom[0] if bom else None,
                       "label": label})
    if background:
        _spawn(_process, owner, pid, rid)
    else:
        _process(owner, pid, rid)
    return get_revision(owner, rid)


def _process(owner: str, pid: str, rid: str) -> None:
    d = _rev_dir(owner, pid, rid)
    with db() as con:
        r = dict(con.execute("select * from revisions where id=?", (rid,)).fetchone())
        con.execute("update revisions set status='running' where id=?", (rid,))
        cust = (con.execute("select customer from projects where id=?", (pid,)).fetchone() or [""])[0]

    def progress(rows):
        with db() as con:
            con.execute("update revisions set progress=? where id=?", (json.dumps(rows), rid))

    inp = d / "input"
    bom = next(iter(inp.glob("bom.*")), None)
    res = run_safe(inp / "drawing.pdf", inp / "model.step" if (inp / "model.step").exists() else None, bom,
                   json.loads(r["options"] or "{}"), d, progress)
    if res["status"] == "done":
        res["label"] = r["label"]
        _apply_ignores(owner, cust, res)
        res["forms"] = forms.build(res, _project_brief(owner, pid), None)
    (d / "result.json").write_text(json.dumps(res, default=str), encoding="utf-8")
    with db() as con:
        con.execute("update revisions set status=?, finished=?, error=?, progress=?, label=coalesce(nullif(label,''), ?) "
                    "where id=?", (res["status"], time.time(), res.get("error"), json.dumps(res.get("steps", [])),
                                   (res.get("title") or {}).get("revision", ""), rid))
        _event(con, owner, pid, rid, "system", "revision_checked" if res["status"] == "done" else "revision_failed",
               detail={"stats": res.get("stats"), "error": res.get("error")})


def _project_brief(owner: str, pid: str) -> dict:
    with db() as con:
        p = con.execute("select part_number, part_name, customer from projects where id=?", (pid,)).fetchone()
    return dict(p) if p else {}


def _apply_ignores(owner: str, customer: str, res: dict) -> None:
    if not customer:
        return
    with db() as con:
        ign = {(r["rule"], r["evidence"]) for r in
               con.execute("select rule, evidence from ignores where owner=? and customer=?", (owner, customer))}
    for f in res.get("findings", []):
        if (f["rule"], f["evidence"]) in ign:
            f["decision"], f["note"] = "ignored", f"ignored for {customer} (standing decision)"


def _row(owner: str, rid: str) -> dict:
    with db() as con:
        r = con.execute("select * from revisions where id=? and owner=?", (rid, owner)).fetchone()
    if r is None:
        raise NotFound("no such revision")
    return _rev_public(dict(r))


def get_revision(owner: str, rid: str) -> dict:
    r = _row(owner, rid)
    p = _rev_dir(owner, r["project_id"], rid) / "result.json"
    if p.exists():
        res = json.loads(p.read_text(encoding="utf-8"))
        res.pop("trace", None)
        r["result"] = res
    with db() as con:
        r["project"] = dict(con.execute("select * from projects where id=?", (r["project_id"],)).fetchone())
        r["events"] = [_event_public(dict(e)) for e in
                       con.execute("select * from events where revision_id=? order by at desc limit 300", (rid,))]
        prev = con.execute("select id, drawing_sha, label from revisions where project_id=? and created<? "
                           "order by created desc limit 1", (r["project_id"], r["created"])).fetchone()
    r["previous"] = dict(prev) if prev else None
    r["drawing_changed"] = None if not prev else prev["drawing_sha"] != r["drawing_sha"]
    return r


def _load(owner: str, rid: str) -> tuple[dict, Path, dict]:
    r = _row(owner, rid)
    d = _rev_dir(owner, r["project_id"], rid)
    if not (d / "result.json").exists():
        raise Conflict("the revision has not finished checking")
    res = json.loads((d / "result.json").read_text(encoding="utf-8"))
    if res.get("status") != "done":
        raise Conflict("the revision failed to check; upload it again")
    return r, d, res


def _save(d: Path, res: dict) -> None:
    tmp = d / "result.json.tmp"
    tmp.write_text(json.dumps(res, default=str), encoding="utf-8")
    tmp.replace(d / "result.json")


def _num(v) -> float | None:
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def edit_characteristic(owner: str, rid: str, no: int, fields: dict, actor: str = "") -> dict:
    with _lock:
        r, d, res = _load(owner, rid)
        if r["signoff"]:
            raise Conflict("this revision is signed; start a new revision to change it")
        c = next((x for x in res["characteristics"] if x["no"] == no), None)
        if c is None:
            raise NotFound("no such characteristic")
        bad = set(fields) - EDITABLE
        if bad:
            raise ValueError(f"cannot edit {', '.join(sorted(bad))}")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(sorted(STATUSES))}")
        before = {k: c.get(k) for k in fields}
        for k in ("nominal", "lower", "upper"):
            if k in fields:
                fields[k] = _num(fields[k]) if fields[k] not in ("", None) else None
        c.update(fields)
        if "result" in fields and "status" not in fields:
            c["status"] = auto_status(c)
        if any(k in fields for k in ("nominal", "lower", "upper", "requirement")):
            c["edited"] = True
            c["tol_source"] = "reviewer" if any(k in fields for k in ("lower", "upper")) else c["tol_source"]
        res["forms"] = forms.build(res, _project_brief(owner, r["project_id"]), None)
        _save(d, res)
        with db() as con:
            _event(con, owner, r["project_id"], rid, actor, "characteristic_edited", f"#{no}",
                   {"before": before, "after": {k: c.get(k) for k in fields}, "status": c["status"]})
        return c


def auto_status(c: dict) -> str:
    """pass/fail from the entered result(s) against the limits; 'open' when it cannot be judged."""
    vals = [_num(v) for v in re.split(r"[;,/\s]+", str(c.get("result", "")).strip()) if v]
    vals = [v for v in vals if v is not None]
    if not vals:
        return "pass" if str(c.get("result", "")).strip().lower() in ("ok", "pass", "conforms", "accept") else (
            "fail" if str(c.get("result", "")).strip().lower() in ("ng", "fail", "reject") else "open")
    lo, hi = c.get("lower"), c.get("upper")
    if lo is None and hi is None:
        return "open"
    ok = all((lo is None or v >= lo - 1e-9) and (hi is None or v <= hi + 1e-9) for v in vals)
    return "pass" if ok else "fail"


def decide_finding(owner: str, rid: str, fid: str, decision: str, note: str = "", actor: str = "",
                   for_customer: bool = False) -> dict:
    if decision not in DECISIONS:
        raise ValueError("decision must be accepted, rejected, ignored or empty")
    with _lock:
        r, d, res = _load(owner, rid)
        if r["signoff"]:
            raise Conflict("this revision is signed")
        f = next((x for x in res["findings"] if x["id"] == fid), None)
        if f is None:
            raise NotFound("no such finding")
        before = f.get("decision", "")
        f["decision"], f["note"] = decision, note
        _save(d, res)
        with db() as con:
            cust = con.execute("select customer from projects where id=?", (r["project_id"],)).fetchone()[0] or ""
            if for_customer and decision == "ignored":
                if not cust:
                    raise ValueError("set the project's customer before ignoring a finding for that customer")
                con.execute("insert or replace into ignores values (?,?,?,?,?)",
                            (owner, cust, f["rule"], f["evidence"], time.time()))
            _event(con, owner, r["project_id"], rid, actor, "finding_decided", f["id"],
                   {"title": f["title"], "before": before, "after": decision, "note": note,
                    "standing_for_customer": cust if for_customer else None})
        return f


def update_options(owner: str, rid: str, fields: dict, actor: str = "") -> dict:
    """Form 1 fields only a person can supply: serial number, PO, organisation..."""
    keys = {"serial_number", "fai_report_number", "po_number", "organization", "supplier_code", "process_reference",
            "additional_changes", "fai_type", "fai_scope", "reason"}
    with _lock:
        r, d, res = _load(owner, rid)
        if r["signoff"]:
            raise Conflict("this revision is signed")
        clean = {k: str(v)[:200] for k, v in fields.items() if k in keys}
        res.setdefault("options", {}).update(clean)
        res["forms"] = forms.build(res, _project_brief(owner, r["project_id"]), None)
        _save(d, res)
        with db() as con:
            con.execute("update revisions set options=? where id=?", (json.dumps(res["options"]), rid))
            _event(con, owner, r["project_id"], rid, actor, "form1_updated", detail=clean)
        return res["forms"]["form1"]


def readiness(res: dict) -> dict:
    crit = [f for f in res["findings"] if f["severity"] == "critical" and not f.get("decision")]
    open_chars = [c["no"] for c in res["characteristics"] if c.get("inspect", True) and c.get("status") == "open"]
    failed = [c["no"] for c in res["characteristics"] if c.get("status") == "fail" and not c.get("nc_number")]
    return {"undecided_critical": [f["id"] for f in crit], "open_characteristics": open_chars,
            "failed_without_nc": failed, "can_sign": not crit and not failed}


def sign(owner: str, rid: str, name: str, role: str, actor: str = "") -> dict:
    if not name.strip():
        raise ValueError("the signer's name is required")
    with _lock:
        r, d, res = _load(owner, rid)
        if r["signoff"]:
            raise Conflict("already signed")
        ready = readiness(res)
        if not ready["can_sign"]:
            raise Conflict("cannot sign yet: " + "; ".join(
                ([f"{len(ready['undecided_critical'])} critical finding(s) undecided"] if ready["undecided_critical"] else [])
                + ([f"characteristic(s) {', '.join(map(str, ready['failed_without_nc']))} failed with no "
                    "nonconformance number"] if ready["failed_without_nc"] else [])))
        signoff = {"name": name.strip(), "role": role.strip(), "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                   "actor": actor, "open_characteristics": ready["open_characteristics"],
                   "fai_scope": "Partial FAI" if ready["open_characteristics"] else "Full FAI"}
        res["forms"] = forms.build(res, _project_brief(owner, r["project_id"]), signoff)
        for s in res.get("steps", []):
            if s["id"] in ("review", "export"):
                s["status"] = "done"
        _save(d, res)
        files = write_exports(d, res, draft=False)
        signoff["exports"] = files
        with db() as con:
            con.execute("update revisions set signoff=?, status='signed', progress=? where id=?",
                        (json.dumps(signoff), json.dumps(res.get("steps", [])), rid))
            _event(con, owner, r["project_id"], rid, actor, "revision_signed", detail=signoff)
        return signoff


EXPORTS = {"fai.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
           "fai.pdf": "application/pdf", "ballooned.pdf": "application/pdf"}
FILES = {"drawing.pdf": "application/pdf", "model.glb": "model/gltf-binary", **EXPORTS}


def write_exports(d: Path, res: dict, draft: bool) -> list[str]:
    out = d / ("exports_draft" if draft else "exports")
    out.mkdir(exist_ok=True)
    forms.write_xlsx(res["forms"], out / "fai.xlsx", draft)
    forms.write_pdf(res["forms"], out / "fai.pdf", draft)
    forms.write_ballooned(d / "input" / "drawing.pdf", res["characteristics"], out / "ballooned.pdf", draft)
    return sorted(EXPORTS)


def file_path(owner: str, rid: str, name: str, actor: str = "") -> Path:
    if name not in FILES:
        raise NotFound("unknown file")
    r = _row(owner, rid)
    d = _rev_dir(owner, r["project_id"], rid)
    if name == "drawing.pdf":
        return d / "input" / "drawing.pdf"
    if name == "model.glb":
        if not (d / "model.glb").exists():
            raise NotFound("no 3D model for this revision")
        return d / "model.glb"
    if r["signoff"]:
        return d / "exports" / name
    _, _, res = _load(owner, rid)
    res["forms"] = forms.build(res, _project_brief(owner, r["project_id"]), None)
    write_exports(d, res, draft=True)
    with db() as con:
        _event(con, owner, r["project_id"], rid, actor, "draft_exported", name)
    return d / "exports_draft" / name


def page_png(owner: str, rid: str, page: int, dpi: int = 110) -> Path:
    from drawcheck.ingest import render_page

    r = _row(owner, rid)
    d = _rev_dir(owner, r["project_id"], rid)
    dpi = max(50, min(int(dpi), 220))
    cache = d / f"page{int(page)}_{dpi}.png"
    if not cache.exists():
        png, _ = render_page(d / "input" / "drawing.pdf", int(page), dpi=dpi)
        cache.write_bytes(png)
    return cache


def compare(owner: str, rid_a: str, rid_b: str) -> dict:
    a, _, ra = _load(owner, rid_a)
    b, _, rb = _load(owner, rid_b)
    if a["project_id"] != b["project_id"]:
        raise ValueError("both revisions must belong to the same project")
    out = compare_chars(ra["characteristics"], rb["characteristics"])
    out.update(a={"id": rid_a, "label": a["label"], "drawing_sha": a["drawing_sha"],
                  "pages": ra["drawing"]["pages"], "title": ra["title"]},
               b={"id": rid_b, "label": b["label"], "drawing_sha": b["drawing_sha"],
                  "pages": rb["drawing"]["pages"], "title": rb["title"]},
               same_drawing=a["drawing_sha"] == b["drawing_sha"])
    return out


def delete_revision(owner: str, rid: str, actor: str = "") -> None:
    r = _row(owner, rid)
    if r["signoff"]:
        raise Conflict("a signed revision is part of the record and cannot be deleted")
    with db() as con:
        con.execute("delete from revisions where id=?", (rid,))
        _event(con, owner, r["project_id"], rid, actor, "revision_deleted", detail={"label": r["label"]})
    shutil.rmtree(_rev_dir(owner, r["project_id"], rid), ignore_errors=True)


# ------------------------------------------------------------------ sample

def create_sample(owner: str, actor: str = "") -> dict:
    """OF-1001 bracket: rev A (drawing only) then rev B (drawing + STEP + PO)."""
    import tempfile

    from . import samples

    p = create_project(owner, "OF-1001", "Mounting bracket", "Acme Aerostructures", actor)
    with tempfile.TemporaryDirectory(prefix="fai_sample_") as tmp:
        t = Path(tmp)
        a = samples.drawing("A", t / "OF-1001_revA.pdf")
        b = samples.drawing("B", t / "OF-1001_revB.pdf")
        s = samples.step(t / "OF-1001_revB.step")
        po = samples.bom(t / "PO-4471.csv")
        create_revision(owner, p["id"], (a.name, a.read_bytes()), options={"general_class": ""}, label="A",
                        actor=actor, background=False)
        create_revision(owner, p["id"], (b.name, b.read_bytes()), (s.name, s.read_bytes()),
                        (po.name, po.read_bytes()), options={"po_number": "PO-4471", "organization": "Your company"},
                        label="B", actor=actor, background=True)
    return get_project(owner, p["id"])
