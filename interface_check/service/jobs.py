"""Job lifecycle policy: admission, dispatch order, retry and escalation, recovery.

States:  QUEUED -> RUNNING -> SUCCEEDED | FAILED | TIMEOUT | CANCELLED | RESOURCE_LIMIT | UNSUPPORTED
         RUNNING -> QUEUED  (retry on the same tier, or escalation to a larger one)

Failure handling (codes in :mod:`interface_check.errors`):
  retry=never   the input is the problem -> terminal at once, never retried
  retry=same    transient -> one more attempt on the same worker class
  retry=larger  out of memory / time -> next tier up, if the plan allows it;
                at the top tier -> RESOURCE_LIMIT (memory) or TIMEOUT (time)

Concurrency: a QUEUED job is dispatched only while the global count and the
user's own count of active jobs (RUNNING + dispatched) are under their limits;
the rest wait in the queue, oldest first, and :func:`pump` runs again whenever
a job finishes. One job is one isolated worker — never several heavy CAD jobs
in one container.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..errors import retry_policy
from ..inspect_step import TIERS, next_tier
from ..limits import TIER_WEIGHT, limits_for

log = logging.getLogger("interface_check.jobs")

TIER_NAMES = [t[0] for t in TIERS]
MAX_ATTEMPTS = 4
SAME_TIER_RETRIES = 1

#: terminal state for each failure code once retries are exhausted
FINAL_STATE = {
    "INVALID_STEP": "FAILED", "CORRUPTED_FILE": "FAILED", "GEOMETRY_INVALID": "FAILED",
    "UNSUPPORTED_FILE": "UNSUPPORTED", "UNSUPPORTED_MESH": "UNSUPPORTED",
    "TOO_MANY_FACES": "RESOURCE_LIMIT", "TOO_MANY_PARTS": "RESOURCE_LIMIT", "FILE_TOO_LARGE": "RESOURCE_LIMIT",
    "OUTPUT_TOO_LARGE": "RESOURCE_LIMIT", "MEMORY_LIMIT": "RESOURCE_LIMIT", "TIMEOUT": "TIMEOUT",
    "FREECAD_FAILURE": "FAILED", "WORKER_FAILURE": "FAILED", "STORAGE_FAILURE": "FAILED",
}


class QuotaExceeded(Exception):
    pass


def tier_rank(tier: str) -> int:
    return TIER_NAMES.index(tier) if tier in TIER_NAMES else len(TIER_NAMES)


def allowed(tier: str, plan: str) -> bool:
    return tier_rank(tier) <= tier_rank(limits_for(plan).max_tier)


@dataclass
class Decision:
    action: str          # retry | final
    tier: str = ""
    state: str = ""


def after_failure(job: dict, code: str, tier_attempts: int) -> Decision:
    """What to do with a job whose attempt on ``job['tier']`` failed with ``code``."""
    policy = retry_policy(code)
    if job["attempts"] >= MAX_ATTEMPTS or policy == "never":
        return Decision("final", state=FINAL_STATE.get(code, "FAILED"))
    if policy == "same" and tier_attempts <= SAME_TIER_RETRIES:
        return Decision("retry", tier=job["tier"])
    if policy == "larger":
        up = next_tier(job["tier"])
        if up and allowed(up, job["plan"]):
            return Decision("retry", tier=up)
    return Decision("final", state=FINAL_STATE.get(code, "FAILED"))


def admit(store, user_id: str, plan: str) -> None:
    """Reject at the door what the plan does not cover (daily jobs, monthly compute)."""
    lim = limits_for(plan)
    now = datetime.now(timezone.utc)
    if store.jobs_since(user_id, now - timedelta(days=1)) >= lim.daily_jobs:
        raise QuotaExceeded(f"daily limit of {lim.daily_jobs} analyses reached for the {lim.plan} plan")
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = store.compute_seconds_since(user_id, month, TIER_WEIGHT)
    if used >= lim.monthly_compute_s:
        raise QuotaExceeded(f"monthly compute quota ({lim.monthly_compute_s} s) used for the {lim.plan} plan")


def pump(store, dispatcher, global_limit: int) -> int:
    """Dispatch queued jobs while concurrency allows. Safe to call from anywhere, any time."""
    started = 0
    active = store.active_count()
    per_user: dict[str, int] = {}
    for job in store.queued():
        if active >= global_limit:
            break
        uid = job["user_id"]
        if uid not in per_user:
            per_user[uid] = store.active_count(uid)
        if per_user[uid] >= limits_for(job["plan"]).max_concurrent_jobs:
            continue
        if not store.mark_dispatched(job["id"]):
            continue                                  # another pump got it
        try:
            ref = dispatcher.submit(job["id"], job["tier"])
            store.update(job["id"], dispatch_ref=str(ref or ""))
        except Exception as e:  # noqa: BLE001 - dispatch failure leaves the job queued, not lost
            log.warning("dispatch of %s failed: %s", job["id"], e)
            store.update(job["id"], dispatched_at=None, dispatch_ref=None)
            continue
        active += 1
        per_user[uid] += 1
        started += 1
    return started


def sweep(store, dispatcher, global_limit: int, grace_s: float = 180.0) -> dict:
    """Recover what a dead worker left behind; then pump."""
    out = {"stale": 0, "lost": 0}
    for job in store.stale_running(grace_s):
        # No heartbeat for grace_s: the worker (or its container) is gone.
        lim = limits_for(job["plan"])
        code = "TIMEOUT" if _ran_out(job, lim.max_runtime_s) else "WORKER_FAILURE"
        # The lost attempt never wrote its own row (its container is gone); record it here.
        store.add_worker_run(job_id=job["id"], user_id=job["user_id"], attempt=job["attempts"], tier=job["tier"],
                             worker_id="lost", started_at=job["started_at"], finished_at=datetime.now(timezone.utc),
                             stage=job["stage"], outcome="LOST", failure_code=code)
        d = after_failure(job, code, store.run_count(job["id"], job["tier"]))
        if d.action == "retry":
            ok = store.transition(job["id"], ["RUNNING"], state="QUEUED", tier=d.tier, dispatched_at=None,
                                  stage="requeued after lost worker")
        else:
            ok = store.transition(job["id"], ["RUNNING"], state=d.state, failure_code="WORKER_FAILURE",
                                  error="worker stopped sending heartbeats", finished_at=datetime.now(timezone.utc))
        out["stale"] += int(ok)
    for job in store.lost_dispatches(grace_s * 3):
        store.update(job["id"], dispatched_at=None, dispatch_ref=None)
        out["lost"] += 1
    out["dispatched"] = pump(store, dispatcher, global_limit)
    return out


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _ran_out(job: dict, max_runtime_s: int) -> bool:
    if not job.get("started_at"):
        return False
    return (datetime.now(timezone.utc) - _aware(job["started_at"])).total_seconds() > max_runtime_s
