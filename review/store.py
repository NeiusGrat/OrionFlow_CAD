"""Persistence for OrionFlow Review: projects, revisions, files, model graphs, jobs.

SQLAlchemy Core, so the same module serves SQLite (local and tests) and the
Supabase Postgres. Tables are prefixed ``rv_`` because the same database
already holds interface_check's ``projects`` / ``revisions``.

Large binaries never live here, only storage keys. Job state changes are
compare-and-set, so a cancelled job cannot be overwritten by a worker that
finishes late.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)
meta = sa.MetaData()


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


projects = sa.Table(
    "rv_projects", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("owner_id", sa.String(64), nullable=False, index=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, default=""),
    sa.Column("created_at", TS, default=now),
    sa.Column("archived_at", TS, nullable=True))

revisions = sa.Table(
    "rv_revisions", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("project_id", sa.String(32), sa.ForeignKey("rv_projects.id", ondelete="CASCADE"), index=True),
    sa.Column("label", sa.String(120), nullable=False),
    sa.Column("git_repo", sa.String(300)),
    sa.Column("git_ref", sa.String(120)),
    sa.Column("status", sa.String(20), nullable=False, default="draft"),  # draft|queued|running|done|failed
    sa.Column("primary_file_id", sa.String(32)),      # the STEP the review analyses; default = largest STEP
    sa.Column("created_at", TS, default=now))

files = sa.Table(
    "rv_files", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), index=True),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("kind_source", sa.String(8), nullable=False, default="auto"),   # auto | user
    sa.Column("name", sa.String(400), nullable=False),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("size", sa.BigInteger, nullable=False),
    sa.Column("storage_key", sa.String(500), nullable=False),
    sa.Column("created_at", TS, default=now))

model_graphs = sa.Table(
    "rv_model_graphs", meta,
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("schema_version", sa.String(16), nullable=False),
    sa.Column("graph", JSON, nullable=False),
    sa.Column("glb_key", sa.String(500)),
    sa.Column("created_at", TS, default=now))

jobs = sa.Table(
    "rv_jobs", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), index=True),
    sa.Column("owner_id", sa.String(64), nullable=False),
    sa.Column("state", sa.String(16), nullable=False, index=True),   # queued|running|done|failed|cancelled
    sa.Column("steps", JSON, nullable=False),     # [{key, label, state, started_at, ended_at, seconds, note}]
    sa.Column("error", sa.Text),
    sa.Column("created_at", TS, default=now),
    sa.Column("started_at", TS),
    sa.Column("ended_at", TS))

check_runs = sa.Table(
    "rv_check_runs", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), index=True),
    sa.Column("job_id", sa.String(32)),
    sa.Column("check_id", sa.String(40), nullable=False),
    sa.Column("check_version", sa.String(20), nullable=False),
    sa.Column("domain", sa.String(30), nullable=False),
    sa.Column("title", sa.String(200)),
    sa.Column("kind", sa.String(20)),
    sa.Column("status", sa.String(16), nullable=False),        # passed | findings | not_run | error
    sa.Column("reason", sa.Text),
    sa.Column("findings", sa.Integer, default=0),
    sa.Column("seconds", sa.Float),
    sa.Column("created_at", TS, default=now))

findings = sa.Table(
    "rv_findings", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), index=True),
    sa.Column("fingerprint", sa.String(32), nullable=False, index=True),
    sa.Column("check_id", sa.String(40), nullable=False),
    sa.Column("check_version", sa.String(20), nullable=False),
    sa.Column("domain", sa.String(30), nullable=False),
    sa.Column("severity", sa.String(10), nullable=False),
    sa.Column("status", sa.String(10), nullable=False, default="open"),
    sa.Column("provenance", sa.String(16), nullable=False),
    sa.Column("title", sa.String(300), nullable=False),
    sa.Column("statement", sa.Text, nullable=False),
    sa.Column("measured", JSON),
    sa.Column("expected", JSON),
    sa.Column("evidence", JSON, nullable=False),
    sa.Column("recommendation", sa.Text),
    sa.Column("owner_id", sa.String(64)),
    sa.Column("active", sa.Boolean, nullable=False, default=True),   # false: no longer detected on the last run
    sa.Column("created_at", TS, default=now),
    sa.Column("updated_at", TS, default=now))

finding_events = sa.Table(
    "rv_finding_events", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("finding_id", sa.String(32), sa.ForeignKey("rv_findings.id", ondelete="CASCADE"), index=True),
    sa.Column("user_id", sa.String(64), nullable=False),           # "system" for engine events
    sa.Column("action", sa.String(20), nullable=False),            # detected | status | owner | comment | redetected | resolved
    sa.Column("from_status", sa.String(10)),
    sa.Column("to_status", sa.String(10)),
    sa.Column("note", sa.Text),
    sa.Column("created_at", TS, default=now))

bom_links = sa.Table(
    "rv_bom_links", meta,
    sa.Column("revision_id", sa.String(32), sa.ForeignKey("rv_revisions.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("row_key", sa.String(500), primary_key=True),       # "<bom file>#<row>"
    sa.Column("part_id", sa.String(32)),                          # null = the engineer says: no CAD part
    sa.Column("set_by", sa.String(64), nullable=False),
    sa.Column("created_at", TS, default=now))

llm_calls = sa.Table(
    "rv_llm_calls", meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("job_id", sa.String(32), index=True),
    sa.Column("task", sa.String(40), nullable=False),
    sa.Column("provider", sa.String(200)),
    sa.Column("model", sa.String(120)),
    sa.Column("tokens_in", sa.Integer, default=0),
    sa.Column("tokens_out", sa.Integer, default=0),
    sa.Column("cost_usd", sa.Float, default=0.0),
    sa.Column("latency_ms", sa.Integer),
    sa.Column("cached", sa.Boolean, default=False),
    sa.Column("prompt_version", sa.String(40)),
    sa.Column("inputs_hash", sa.String(40)),
    sa.Column("error", sa.Text),
    sa.Column("created_at", TS, default=now))

#: The step list a review job reports, in order. Later milestones append to it.
STEPS = [("parse", "Parse"), ("features", "Features"), ("contacts", "Contacts"), ("mesh", "Mesh"),
         ("bom", "BOM"), ("graph", "Model graph"), ("checks", "Checks")]


def database_url() -> str:
    return os.environ.get("REVIEW_DATABASE_URL", "sqlite:///data/review/review.sqlite")


class Store:
    def __init__(self, url: str | None = None):
        url = url or database_url()
        if url.startswith("sqlite:///"):
            os.makedirs(os.path.dirname(url[len("sqlite:///"):]) or ".", exist_ok=True)
            self.engine = sa.create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

            @sa.event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):  # WAL: worker processes write while the API reads
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        else:
            kw: dict[str, Any] = {"pool_pre_ping": True, "pool_size": 3, "max_overflow": 2}
            if "6543" in url:   # Supabase transaction pooler: no server-side prepared statements
                kw["connect_args"] = {"prepare_threshold": None}
            self.engine = sa.create_engine(url, **kw)
        meta.create_all(self.engine)

    # ---- generic ---------------------------------------------------------------
    def _one(self, q) -> Optional[dict]:
        with self.engine.connect() as c:
            r = c.execute(q).mappings().first()
            return dict(r) if r else None

    def _all(self, q) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings().all()]

    def _exec(self, q):
        with self.engine.begin() as c:
            return c.execute(q)

    # ---- projects ----------------------------------------------------------------
    def create_project(self, owner: str, name: str, description: str = "") -> dict:
        pid = new_id()
        self._exec(projects.insert().values(id=pid, owner_id=owner, name=name.strip()[:200],
                                            description=description, created_at=now()))
        return self.project(pid)

    def project(self, pid: str) -> Optional[dict]:
        return self._one(projects.select().where(projects.c.id == pid))

    def projects_for(self, owner: str) -> list[dict]:
        rev_count = (sa.select(sa.func.count()).select_from(revisions)
                     .where(revisions.c.project_id == projects.c.id).scalar_subquery())
        q = (sa.select(projects, rev_count.label("revision_count"))
             .where(projects.c.owner_id == owner, projects.c.archived_at.is_(None))
             .order_by(projects.c.created_at.desc()))
        return self._all(q)

    def archive_project(self, pid: str) -> None:
        self._exec(projects.update().where(projects.c.id == pid).values(archived_at=now()))

    # ---- revisions -----------------------------------------------------------------
    def create_revision(self, project_id: str, label: str, git_repo: str | None = None,
                        git_ref: str | None = None) -> dict:
        rid = new_id()
        self._exec(revisions.insert().values(id=rid, project_id=project_id, label=label.strip()[:120] or "rev",
                                             git_repo=git_repo, git_ref=git_ref, status="draft", created_at=now()))
        return self.revision(rid)

    def revision(self, rid: str) -> Optional[dict]:
        return self._one(revisions.select().where(revisions.c.id == rid))

    def revisions_for(self, project_id: str) -> list[dict]:
        return self._all(revisions.select().where(revisions.c.project_id == project_id)
                         .order_by(revisions.c.created_at))

    def set_primary(self, rid: str, fid: str | None) -> None:
        self._exec(revisions.update().where(revisions.c.id == rid).values(primary_file_id=fid))

    def set_revision_status(self, rid: str, status: str) -> None:
        self._exec(revisions.update().where(revisions.c.id == rid).values(status=status))

    # ---- files ---------------------------------------------------------------------
    def add_file(self, revision_id: str, kind: str, name: str, sha256: str, size: int, key: str) -> dict:
        fid = new_id()
        self._exec(files.insert().values(id=fid, revision_id=revision_id, kind=kind, kind_source="auto", name=name,
                                         sha256=sha256, size=size, storage_key=key, created_at=now()))
        return self._one(files.select().where(files.c.id == fid))

    def files_for(self, revision_id: str) -> list[dict]:
        return self._all(files.select().where(files.c.revision_id == revision_id).order_by(files.c.name))

    def set_file_kind(self, fid: str, kind: str) -> Optional[dict]:
        self._exec(files.update().where(files.c.id == fid).values(kind=kind, kind_source="user"))
        return self._one(files.select().where(files.c.id == fid))

    def delete_file(self, fid: str) -> None:
        self._exec(files.delete().where(files.c.id == fid))

    # ---- graphs --------------------------------------------------------------------
    def save_graph(self, revision_id: str, schema_version: str, graph: dict, glb_key: str | None) -> None:
        with self.engine.begin() as c:
            c.execute(model_graphs.delete().where(model_graphs.c.revision_id == revision_id))
            c.execute(model_graphs.insert().values(revision_id=revision_id, schema_version=schema_version,
                                                   graph=graph, glb_key=glb_key, created_at=now()))

    def graph(self, revision_id: str) -> Optional[dict]:
        return self._one(model_graphs.select().where(model_graphs.c.revision_id == revision_id))

    # ---- jobs ----------------------------------------------------------------------
    def create_job(self, revision_id: str, owner: str) -> dict:
        jid = new_id()
        steps = [{"key": k, "label": lbl, "state": "pending", "seconds": None, "note": ""} for k, lbl in STEPS]
        self._exec(jobs.insert().values(id=jid, revision_id=revision_id, owner_id=owner, state="queued",
                                        steps=steps, created_at=now()))
        return self.job(jid)

    def job(self, jid: str) -> Optional[dict]:
        return self._one(jobs.select().where(jobs.c.id == jid))

    def latest_job(self, revision_id: str) -> Optional[dict]:
        return self._one(jobs.select().where(jobs.c.revision_id == revision_id)
                         .order_by(jobs.c.created_at.desc()).limit(1))

    def active_job(self, revision_id: str) -> Optional[dict]:
        return self._one(jobs.select().where(jobs.c.revision_id == revision_id,
                                             jobs.c.state.in_(("queued", "running"))).limit(1))

    def update_job(self, jid: str, *, only_if: tuple[str, ...] | None = None, **values) -> bool:
        q = jobs.update().where(jobs.c.id == jid)
        if only_if:
            q = q.where(jobs.c.state.in_(only_if))
        return self._exec(q.values(**values)).rowcount == 1

    # ---- check runs + findings -----------------------------------------------------
    def save_check_results(self, revision_id: str, job_id: str | None, results: list, runs: list[dict]) -> dict:
        """Persist a run's findings, matched to earlier ones by fingerprint.

        A finding seen before keeps its id, status, owner and history. One that
        is gone is marked inactive (and ``fixed`` if it was open) with a system
        event; one that comes back after being marked fixed is reopened.
        """
        t = now()
        counts = {"new": 0, "kept": 0, "resolved": 0, "reopened": 0}
        with self.engine.begin() as c:
            c.execute(check_runs.delete().where(check_runs.c.revision_id == revision_id))
            for r in runs:
                c.execute(check_runs.insert().values(
                    id=new_id(), revision_id=revision_id, job_id=job_id, created_at=t,
                    **{k: r.get(k) for k in ("check_id", "check_version", "domain", "title", "kind", "status",
                                             "reason", "findings", "seconds")}))
            old = {row["fingerprint"]: dict(row) for row in
                   c.execute(findings.select().where(findings.c.revision_id == revision_id)).mappings()}
            seen = set()
            for f in results:
                fp = f.fingerprint
                seen.add(fp)
                body = dict(check_id=f.check_id, check_version=f.check_version, domain=f.domain, severity=f.severity,
                            provenance=f.provenance, title=f.title, statement=f.statement,
                            measured=f.measured.model_dump(exclude_none=True) if f.measured else None,
                            expected=f.expected.model_dump(exclude_none=True) if f.expected else None,
                            evidence=[e.model_dump(exclude_none=True) for e in f.evidence],
                            recommendation=f.recommendation, active=True, updated_at=t)
                prev = old.get(fp)
                if prev is None:
                    fid = new_id()
                    c.execute(findings.insert().values(id=fid, revision_id=revision_id, fingerprint=fp, status="open",
                                                       created_at=t, **body))
                    c.execute(finding_events.insert().values(id=new_id(), finding_id=fid, user_id="system",
                                                             action="detected", to_status="open", created_at=t))
                    counts["new"] += 1
                else:
                    status = prev["status"]
                    if status == "fixed" or not prev["active"]:
                        c.execute(finding_events.insert().values(
                            id=new_id(), finding_id=prev["id"], user_id="system", action="redetected",
                            from_status=status, to_status="open", note="detected again on a new run", created_at=t))
                        status = "open"
                        counts["reopened"] += 1
                    else:
                        counts["kept"] += 1
                    c.execute(findings.update().where(findings.c.id == prev["id"]).values(status=status, **body))
            for fp, prev in old.items():
                if fp in seen or not prev["active"]:
                    continue
                to = "fixed" if prev["status"] == "open" else prev["status"]
                c.execute(findings.update().where(findings.c.id == prev["id"]).values(active=False, status=to, updated_at=t))
                c.execute(finding_events.insert().values(
                    id=new_id(), finding_id=prev["id"], user_id="system", action="resolved", from_status=prev["status"],
                    to_status=to, note="no longer detected on the latest run", created_at=t))
                counts["resolved"] += 1
        return counts

    def check_runs_for(self, revision_id: str) -> list[dict]:
        return self._all(check_runs.select().where(check_runs.c.revision_id == revision_id).order_by(check_runs.c.check_id))

    def findings_for(self, revision_id: str, active_only: bool = True) -> list[dict]:
        q = findings.select().where(findings.c.revision_id == revision_id)
        if active_only:
            q = q.where(findings.c.active.is_(True))
        return self._all(q)

    def finding(self, fid: str) -> Optional[dict]:
        return self._one(findings.select().where(findings.c.id == fid))

    def events_for(self, fid: str) -> list[dict]:
        return self._all(finding_events.select().where(finding_events.c.finding_id == fid)
                         .order_by(finding_events.c.created_at))

    def update_finding(self, fid: str, user: str, *, status: str | None = None, owner: str | None = None,
                       note: str | None = None, clear_owner: bool = False) -> Optional[dict]:
        cur = self.finding(fid)
        if cur is None:
            return None
        t = now()
        with self.engine.begin() as c:
            if status and status != cur["status"]:
                c.execute(findings.update().where(findings.c.id == fid).values(status=status, updated_at=t))
                c.execute(finding_events.insert().values(id=new_id(), finding_id=fid, user_id=user, action="status",
                                                         from_status=cur["status"], to_status=status, note=note,
                                                         created_at=t))
                note = None                     # the note travelled with the status change
            if owner is not None or clear_owner:
                c.execute(findings.update().where(findings.c.id == fid)
                          .values(owner_id=None if clear_owner else owner, updated_at=t))
                c.execute(finding_events.insert().values(id=new_id(), finding_id=fid, user_id=user, action="owner",
                                                         note=None if clear_owner else owner, created_at=t))
            if note:
                c.execute(finding_events.insert().values(id=new_id(), finding_id=fid, user_id=user, action="comment",
                                                         note=note, created_at=t))
        return self.finding(fid)

    # ---- BOM links (the engineer's own pairings) -------------------------------------
    def bom_links_for(self, revision_id: str) -> dict[str, Optional[str]]:
        return {r["row_key"]: r["part_id"] for r in self._all(bom_links.select().where(bom_links.c.revision_id == revision_id))}

    def set_bom_link(self, revision_id: str, row_key: str, part_id: Optional[str], user: str) -> None:
        with self.engine.begin() as c:
            c.execute(bom_links.delete().where(bom_links.c.revision_id == revision_id, bom_links.c.row_key == row_key))
            c.execute(bom_links.insert().values(revision_id=revision_id, row_key=row_key, part_id=part_id, set_by=user,
                                                created_at=now()))

    def clear_bom_link(self, revision_id: str, row_key: str) -> None:
        self._exec(bom_links.delete().where(bom_links.c.revision_id == revision_id, bom_links.c.row_key == row_key))

    # ---- LLM call log -----------------------------------------------------------------
    def log_llm_call(self, **values) -> None:
        self._exec(llm_calls.insert().values(id=new_id(), created_at=now(), **values))

    def llm_calls_for(self, job_id: str) -> list[dict]:
        return self._all(llm_calls.select().where(llm_calls.c.job_id == job_id).order_by(llm_calls.c.created_at))
