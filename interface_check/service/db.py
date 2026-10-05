"""Job store: projects, revisions, documents, assemblies, parts, analysis_jobs,
analysis_results, findings, geometry_hashes, worker_runs.

SQLAlchemy Core, so one module serves SQLite (local, tests) and the Supabase
Postgres (hosted; tables created by alembic migration 013). Large binaries are
never stored here — only object-storage keys.

Every job state change is a compare-and-set (``UPDATE ... WHERE state IN
(...)``), so two workers can never both claim a job and a cancel cannot be
overwritten by a finishing worker.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

JSON = sa.JSON().with_variant(JSONB(), "postgresql")
meta = sa.MetaData()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex


TS = sa.DateTime(timezone=True)

projects = sa.Table(
    "projects", meta,
    sa.Column("id", sa.String(32), primary_key=True, default=_id),
    sa.Column("user_id", sa.String(64), nullable=False, index=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("created_at", TS, default=_now))

revisions = sa.Table(
    "revisions", meta,
    sa.Column("id", sa.String(32), primary_key=True, default=_id),
    sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True),
    sa.Column("label", sa.String(100)),
    sa.Column("job_id", sa.String(32), index=True),
    sa.Column("prev_revision_id", sa.String(32)),
    sa.Column("created_at", TS, default=_now))

analysis_jobs = sa.Table(
    "analysis_jobs", meta,
    sa.Column("id", sa.String(32), primary_key=True, default=_id),
    sa.Column("user_id", sa.String(64), nullable=False, index=True),
    sa.Column("project_id", sa.String(32)),
    sa.Column("revision_id", sa.String(32)),
    sa.Column("label", sa.String(200)),
    sa.Column("plan", sa.String(32), nullable=False),
    sa.Column("state", sa.String(20), nullable=False, index=True),
    sa.Column("tier", sa.String(16), nullable=False),
    sa.Column("attempts", sa.Integer, default=0, nullable=False),
    sa.Column("idempotency_key", sa.String(128)),
    sa.Column("failure_code", sa.String(40)),
    sa.Column("error", sa.Text),
    sa.Column("stage", sa.String(40)),
    sa.Column("options", JSON, default=dict),
    sa.Column("complexity", JSON),
    sa.Column("summary", JSON),
    sa.Column("cancel_requested", sa.Boolean, default=False, nullable=False),
    sa.Column("dispatch_ref", sa.String(200)),
    sa.Column("dispatched_at", TS),
    sa.Column("created_at", TS, default=_now, index=True),
    sa.Column("started_at", TS),
    sa.Column("heartbeat_at", TS),
    sa.Column("finished_at", TS),
    sa.UniqueConstraint("user_id", "idempotency_key", name="uq_analysis_jobs_idem"))

documents = sa.Table(
    "documents", meta,
    sa.Column("id", sa.String(32), primary_key=True, default=_id),
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),          # step bom prev_step prev_bom urdf urdf_map drawing ...
    sa.Column("filename", sa.String(200), nullable=False),
    sa.Column("storage_key", sa.String(500), nullable=False),
    sa.Column("size_bytes", sa.BigInteger),
    sa.Column("sha256", sa.String(64)),
    sa.Column("created_at", TS, default=_now))

assemblies = sa.Table(
    "assemblies", meta,
    sa.Column("id", sa.String(32), primary_key=True, default=_id),
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
    sa.Column("revision_id", sa.String(32)),
    sa.Column("part_count", sa.Integer), sa.Column("instance_count", sa.Integer),
    sa.Column("face_count", sa.Integer), sa.Column("mesh_parts", sa.Integer),
    sa.Column("complexity", JSON),
    sa.Column("created_at", TS, default=_now))

parts = sa.Table(
    "parts", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
    sa.Column("name", sa.String(300)),
    sa.Column("instance_count", sa.Integer),
    sa.Column("volume_mm3", sa.Float),
    sa.Column("faces", sa.Integer),
    sa.Column("geometry_type", sa.String(8)),
    sa.Column("geometry_hash", sa.String(64), index=True),
    sa.Column("cached", sa.Boolean))

analysis_results = sa.Table(
    "analysis_results", meta,
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("report_key", sa.String(500)), sa.Column("pdf_key", sa.String(500)),
    sa.Column("glb_key", sa.String(500)),
    sa.Column("stages", JSON), sa.Column("narrative", JSON), sa.Column("stats", JSON),
    sa.Column("engine_version", sa.String(32)),
    sa.Column("created_at", TS, default=_now))

findings = sa.Table(
    "findings", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
    sa.Column("fingerprint", sa.String(16), nullable=False),
    sa.Column("rule_id", sa.String(40), nullable=False),
    sa.Column("severity", sa.String(10), nullable=False),
    sa.Column("message", sa.Text),
    sa.Column("parts", JSON), sa.Column("instances", JSON),
    sa.Column("measured", JSON), sa.Column("expected", JSON), sa.Column("location", JSON),
    sa.Column("method", sa.Text), sa.Column("source", sa.String(16)),
    sa.Column("change_status", sa.String(12)),
    sa.Column("review", sa.String(12), default="open"),
    sa.Column("review_note", sa.Text), sa.Column("reviewed_at", TS))

geometry_hashes = sa.Table(
    "geometry_hashes", meta,
    sa.Column("hash", sa.String(64), primary_key=True),
    sa.Column("extraction_version", sa.String(16)),
    sa.Column("geometry_type", sa.String(8)),
    sa.Column("faces", sa.Integer),
    sa.Column("first_seen", TS, default=_now),
    sa.Column("last_seen", TS, default=_now),
    sa.Column("uses", sa.Integer, default=1))

worker_runs = sa.Table(
    "worker_runs", meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
    sa.Column("user_id", sa.String(64)),
    sa.Column("attempt", sa.Integer), sa.Column("tier", sa.String(16)), sa.Column("worker_id", sa.String(100)),
    sa.Column("started_at", TS), sa.Column("finished_at", TS),
    sa.Column("runtime_s", sa.Float), sa.Column("peak_memory_mb", sa.Float),
    sa.Column("memory_limit_mb", sa.Integer), sa.Column("cpu_count", sa.Integer),
    sa.Column("file_size", sa.BigInteger), sa.Column("file_hash", sa.String(64)),
    sa.Column("face_count", sa.Integer), sa.Column("part_count", sa.Integer),
    sa.Column("cache_hits", sa.Integer), sa.Column("cache_misses", sa.Integer),
    sa.Column("stage", sa.String(40)), sa.Column("outcome", sa.String(20)),
    sa.Column("failure_code", sa.String(40)), sa.Column("cost_usd", sa.Float))

#: terminal states; nothing moves a job out of these
TERMINAL = {"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "RESOURCE_LIMIT", "UNSUPPORTED"}
STATES = TERMINAL | {"QUEUED", "RUNNING"}


class Store:
    def __init__(self, url: str):
        if url.startswith("sqlite:///"):
            from pathlib import Path
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
            self.engine = sa.create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
            meta.create_all(self.engine)
        else:
            # Hosted Postgres: tables come from alembic (migration 013), never create_all.
            # Through Supabase's transaction-mode pooler (port 6543) many short-lived
            # containers share a few server connections; it cannot keep prepared
            # statements, so psycopg must not create them. Pools stay small: every
            # web and worker container holds its own (IC_DB_POOL_SIZE / _MAX_OVERFLOW).
            import os
            self.engine = sa.create_engine(
                url, pool_pre_ping=True, pool_recycle=300, connect_args={"prepare_threshold": None},
                pool_size=int(os.environ.get("IC_DB_POOL_SIZE", "3")),
                max_overflow=int(os.environ.get("IC_DB_MAX_OVERFLOW", "2")))

    # ------------------------------------------------------------ helpers
    def _one(self, q) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(q).mappings().first()
            return dict(r) if r else None

    def _all(self, q) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings().all()]

    # ------------------------------------------------------------ jobs
    def job_by_key(self, user_id: str, key: str) -> dict | None:
        return self._one(sa.select(analysis_jobs).where(
            analysis_jobs.c.user_id == user_id, analysis_jobs.c.idempotency_key == key))

    def create_job(self, user_id: str, plan: str, tier: str, options: dict, idempotency_key: str | None,
                   label: str = "", project_id: str | None = None, docs: Iterable[dict] = (),
                   job_id: str | None = None) -> tuple[dict, bool]:
        """Insert a QUEUED job with its documents; returns (job, created). Same key -> same job."""
        if idempotency_key:
            existing = self.job_by_key(user_id, idempotency_key)
            if existing:
                return existing, False
        jid = job_id or _id()
        with self.engine.begin() as c:
            c.execute(analysis_jobs.insert().values(
                id=jid, user_id=user_id, plan=plan, state="QUEUED", tier=tier, attempts=0, options=options,
                idempotency_key=idempotency_key, label=label[:200], project_id=project_id, created_at=_now()))
            for d in docs:
                c.execute(documents.insert().values(id=_id(), job_id=jid, user_id=user_id, **d))
        return self.get_job(jid), True

    def get_job(self, job_id: str, user_id: str | None = None) -> dict | None:
        q = sa.select(analysis_jobs).where(analysis_jobs.c.id == job_id)
        if user_id is not None:
            q = q.where(analysis_jobs.c.user_id == user_id)
        return self._one(q)

    def list_jobs(self, user_id: str, limit: int = 50) -> list[dict]:
        return self._all(sa.select(analysis_jobs).where(analysis_jobs.c.user_id == user_id)
                         .order_by(analysis_jobs.c.created_at.desc()).limit(limit))

    def documents(self, job_id: str) -> list[dict]:
        return self._all(sa.select(documents).where(documents.c.job_id == job_id))

    def transition(self, job_id: str, from_states: Iterable[str], **values: Any) -> bool:
        """Compare-and-set: update only if the job is in one of ``from_states``."""
        with self.engine.begin() as c:
            r = c.execute(analysis_jobs.update().where(
                analysis_jobs.c.id == job_id, analysis_jobs.c.state.in_(list(from_states))).values(**values))
            return r.rowcount == 1

    def update(self, job_id: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(analysis_jobs.update().where(analysis_jobs.c.id == job_id).values(**values))

    def mark_dispatched(self, job_id: str, ref: str = "") -> bool:
        with self.engine.begin() as c:
            r = c.execute(analysis_jobs.update().where(
                analysis_jobs.c.id == job_id, analysis_jobs.c.state == "QUEUED",
                analysis_jobs.c.dispatched_at.is_(None)).values(dispatched_at=_now(), dispatch_ref=ref))
            return r.rowcount == 1

    def queued(self, limit: int = 100) -> list[dict]:
        return self._all(sa.select(analysis_jobs).where(
            analysis_jobs.c.state == "QUEUED", analysis_jobs.c.dispatched_at.is_(None))
            .order_by(analysis_jobs.c.created_at).limit(limit))

    def active_count(self, user_id: str | None = None) -> int:
        q = sa.select(sa.func.count()).select_from(analysis_jobs).where(sa.or_(
            analysis_jobs.c.state == "RUNNING",
            sa.and_(analysis_jobs.c.state == "QUEUED", analysis_jobs.c.dispatched_at.is_not(None))))
        if user_id is not None:
            q = q.where(analysis_jobs.c.user_id == user_id)
        with self.engine.connect() as c:
            return int(c.execute(q).scalar() or 0)

    def jobs_since(self, user_id: str, since: datetime) -> int:
        q = sa.select(sa.func.count()).select_from(analysis_jobs).where(
            analysis_jobs.c.user_id == user_id, analysis_jobs.c.created_at >= since)
        with self.engine.connect() as c:
            return int(c.execute(q).scalar() or 0)

    def compute_seconds_since(self, user_id: str, since: datetime, weights: dict[str, float]) -> float:
        rows = self._all(sa.select(worker_runs.c.tier, sa.func.sum(worker_runs.c.runtime_s).label("s"))
                         .where(worker_runs.c.user_id == user_id, worker_runs.c.started_at >= since)
                         .group_by(worker_runs.c.tier))
        return sum((r["s"] or 0) * weights.get(r["tier"], 1.0) for r in rows)

    def stale_running(self, older_than_s: float) -> list[dict]:
        cutoff = datetime.fromtimestamp(time.time() - older_than_s, timezone.utc)
        return self._all(sa.select(analysis_jobs).where(
            analysis_jobs.c.state == "RUNNING", analysis_jobs.c.heartbeat_at < cutoff))

    def lost_dispatches(self, older_than_s: float) -> list[dict]:
        cutoff = datetime.fromtimestamp(time.time() - older_than_s, timezone.utc)
        return self._all(sa.select(analysis_jobs).where(
            analysis_jobs.c.state == "QUEUED", analysis_jobs.c.dispatched_at < cutoff))

    def expired(self, days: float) -> list[dict]:
        cutoff = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc)
        return self._all(sa.select(analysis_jobs).where(analysis_jobs.c.created_at < cutoff))

    def delete_job(self, job_id: str) -> None:
        with self.engine.begin() as c:
            for t in (findings, parts, assemblies, analysis_results, worker_runs, documents):
                c.execute(t.delete().where(t.c.job_id == job_id))
            c.execute(revisions.delete().where(revisions.c.job_id == job_id))
            c.execute(analysis_jobs.delete().where(analysis_jobs.c.id == job_id))

    # ------------------------------------------------------------ results
    def save_results(self, job_id: str, report: dict, keys: dict, complexity: dict | None) -> None:
        """Replace this job's results in one transaction (a retried worker overwrites, never duplicates)."""
        with self.engine.begin() as c:
            for t in (findings, parts, assemblies, analysis_results):
                c.execute(t.delete().where(t.c.job_id == job_id))
            if report["findings"]:
                c.execute(findings.insert(), [{
                    "job_id": job_id, "fingerprint": f["fingerprint"], "rule_id": f["rule_id"],
                    "severity": f["severity"], "message": f["message"], "parts": f["parts"],
                    "instances": f["instances"], "measured": f["measured"], "expected": f["expected"],
                    "location": f["location"], "method": f.get("method", ""), "source": f["source"],
                    "change_status": f.get("change_status"), "review": "open"} for f in report["findings"]])
            if report["parts"]:
                c.execute(parts.insert(), [{
                    "job_id": job_id, "name": p["part"], "instance_count": p["count"],
                    "volume_mm3": p["volume_mm3"], "faces": p.get("faces"), "geometry_type": p.get("geometry_type"),
                    "geometry_hash": p.get("geometry_hash") or None, "cached": p.get("cached")}
                    for p in report["parts"]])
            st = report["stats"]
            c.execute(assemblies.insert().values(
                id=_id(), job_id=job_id, part_count=st.get("parts"), instance_count=st.get("instances"),
                face_count=(complexity or {}).get("face_count"),
                mesh_parts=sum(1 for p in report["parts"] if p.get("geometry_type") == "MESH"),
                complexity=complexity))
            c.execute(analysis_results.insert().values(
                job_id=job_id, report_key=keys.get("report.json"), pdf_key=keys.get("report.pdf"),
                glb_key=keys.get("model.glb"), stages=report.get("stages"), narrative=report.get("narrative"),
                stats=st, engine_version=report.get("engine_version")))
            for p in report["parts"]:
                h = p.get("geometry_hash")
                if not h:
                    continue
                r = c.execute(geometry_hashes.update().where(geometry_hashes.c.hash == h).values(
                    last_seen=_now(), uses=geometry_hashes.c.uses + 1))
                if r.rowcount == 0:
                    c.execute(geometry_hashes.insert().values(
                        hash=h, extraction_version=report.get("engine_version"), geometry_type=p.get("geometry_type"),
                        faces=p.get("faces"), first_seen=_now(), last_seen=_now(), uses=1))

    def results(self, job_id: str) -> dict | None:
        return self._one(sa.select(analysis_results).where(analysis_results.c.job_id == job_id))

    def findings(self, job_id: str) -> list[dict]:
        return self._all(sa.select(findings).where(findings.c.job_id == job_id).order_by(findings.c.id))

    def review(self, job_id: str, fingerprint: str, verdict: str, note: str) -> int:
        with self.engine.begin() as c:
            r = c.execute(findings.update().where(findings.c.job_id == job_id, findings.c.fingerprint == fingerprint)
                          .values(review=verdict, review_note=note[:2000], reviewed_at=_now()))
            return r.rowcount

    # ------------------------------------------------------------ observability
    def add_worker_run(self, **row: Any) -> None:
        with self.engine.begin() as c:
            c.execute(worker_runs.insert().values(**row))

    def run_count(self, job_id: str, tier: str) -> int:
        q = sa.select(sa.func.count()).select_from(worker_runs).where(
            worker_runs.c.job_id == job_id, worker_runs.c.tier == tier)
        with self.engine.connect() as c:
            return int(c.execute(q).scalar() or 0)

    def worker_runs(self, since: datetime | None = None) -> list[dict]:
        q = sa.select(worker_runs)
        if since is not None:
            q = q.where(worker_runs.c.started_at >= since)
        return self._all(q)
