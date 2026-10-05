"""CAD analysis platform: jobs, documents, results, findings, cache index, worker runs

The Interface Check engine moves from "run it inside the web container" to a
stateless API plus isolated workers. These tables are the shared state between
them: the API writes jobs and documents, workers claim jobs with a
compare-and-set on ``state`` and write results, findings and one
``worker_runs`` row per attempt (runtime, peak memory, cache hits, cost), which
is what tier sizing and pricing are tuned from.

Binaries never live here, only object-storage keys under jobs/{job_id}/.

RLS is enabled with no policies, exactly as migration 005 does for every other
public table: the backend connects as the owner and bypasses it, and the
anon/authenticated roles behind Supabase's public REST API see nothing.

``user_id`` is text, not a foreign key to users: the engine also serves
API-key and development callers whose ids are not rows in users.

Revision ID: 013
Revises: 012
Create Date: 2026-10-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["worker_runs", "geometry_hashes", "findings", "analysis_results", "parts", "assemblies",
          "documents", "revisions", "analysis_jobs", "projects"]


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", TS, server_default=NOW))
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("revision_id", sa.String(32)),
        sa.Column("label", sa.String(200)),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, index=True),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("failure_code", sa.String(40)),
        sa.Column("error", sa.Text),
        sa.Column("stage", sa.String(40)),
        sa.Column("options", JSONB),
        sa.Column("complexity", JSONB),
        sa.Column("summary", JSONB),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("dispatch_ref", sa.String(200)),
        sa.Column("dispatched_at", TS),
        sa.Column("created_at", TS, server_default=NOW, index=True),
        sa.Column("started_at", TS),
        sa.Column("heartbeat_at", TS),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_analysis_jobs_idem"),
        sa.CheckConstraint("state in ('QUEUED','RUNNING','SUCCEEDED','FAILED','TIMEOUT','CANCELLED',"
                           "'RESOURCE_LIMIT','UNSUPPORTED')", name="ck_analysis_jobs_state"))
    # the dispatcher's hot query: oldest undispatched queued jobs
    op.create_index("ix_analysis_jobs_queue", "analysis_jobs", ["state", "dispatched_at", "created_at"])
    op.create_table(
        "revisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True),
        sa.Column("label", sa.String(100)),
        sa.Column("job_id", sa.String(32), index=True),
        sa.Column("prev_revision_id", sa.String(32)),
        sa.Column("created_at", TS, server_default=NOW))
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("sha256", sa.String(64)),
        sa.Column("created_at", TS, server_default=NOW))
    op.create_table(
        "assemblies",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
        sa.Column("revision_id", sa.String(32)),
        sa.Column("part_count", sa.Integer), sa.Column("instance_count", sa.Integer),
        sa.Column("face_count", sa.Integer), sa.Column("mesh_parts", sa.Integer),
        sa.Column("complexity", JSONB),
        sa.Column("created_at", TS, server_default=NOW))
    op.create_table(
        "parts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
        sa.Column("name", sa.String(300)),
        sa.Column("instance_count", sa.Integer),
        sa.Column("volume_mm3", sa.Float),
        sa.Column("faces", sa.Integer),
        sa.Column("geometry_type", sa.String(8)),
        sa.Column("geometry_hash", sa.String(64), index=True),
        sa.Column("cached", sa.Boolean))
    op.create_table(
        "analysis_results",
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("report_key", sa.String(500)), sa.Column("pdf_key", sa.String(500)),
        sa.Column("glb_key", sa.String(500)),
        sa.Column("stages", JSONB), sa.Column("narrative", JSONB), sa.Column("stats", JSONB),
        sa.Column("engine_version", sa.String(32)),
        sa.Column("created_at", TS, server_default=NOW))
    op.create_table(
        "findings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("parts", JSONB), sa.Column("instances", JSONB),
        sa.Column("measured", JSONB), sa.Column("expected", JSONB), sa.Column("location", JSONB),
        sa.Column("method", sa.Text), sa.Column("source", sa.String(16)),
        sa.Column("change_status", sa.String(12)),
        sa.Column("review", sa.String(12), server_default="open"),
        sa.Column("review_note", sa.Text), sa.Column("reviewed_at", TS))
    op.create_index("ix_findings_rule_review", "findings", ["rule_id", "review"])   # accuracy reporting
    op.create_table(
        "geometry_hashes",
        sa.Column("hash", sa.String(64), primary_key=True),
        sa.Column("extraction_version", sa.String(16)),
        sa.Column("geometry_type", sa.String(8)),
        sa.Column("faces", sa.Integer),
        sa.Column("first_seen", TS, server_default=NOW),
        sa.Column("last_seen", TS, server_default=NOW),
        sa.Column("uses", sa.Integer, server_default="1"))
    op.create_table(
        "worker_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True),
        sa.Column("user_id", sa.String(64), index=True),
        sa.Column("attempt", sa.Integer), sa.Column("tier", sa.String(16)), sa.Column("worker_id", sa.String(100)),
        sa.Column("started_at", TS, index=True), sa.Column("finished_at", TS),
        sa.Column("runtime_s", sa.Float), sa.Column("peak_memory_mb", sa.Float),
        sa.Column("memory_limit_mb", sa.Integer), sa.Column("cpu_count", sa.Integer),
        sa.Column("file_size", sa.BigInteger), sa.Column("file_hash", sa.String(64)),
        sa.Column("face_count", sa.Integer), sa.Column("part_count", sa.Integer),
        sa.Column("cache_hits", sa.Integer), sa.Column("cache_misses", sa.Integer),
        sa.Column("stage", sa.String(40)), sa.Column("outcome", sa.String(20)),
        sa.Column("failure_code", sa.String(40)), sa.Column("cost_usd", sa.Float))
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
