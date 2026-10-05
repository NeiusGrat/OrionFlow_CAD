"""Which plan a user is on, decided by the server, never by the caller.

Order of authority:
  1. billing   an ``active`` or ``trialing`` row in ``subscriptions`` (current
               period not ended), joined to ``pricing_plans.name`` — the same
               tables the main app's billing writes;
  2. operator  ``IC_PLAN_OVERRIDES`` ("user_id=plan,user_id=plan"), for pilot
               customers and QA accounts before billing exists for them;
  3. default   ``IC_DEFAULT_PLAN`` (free), stated as the source so nobody is
               on a plan by accident.

A plan claim inside a token is ignored: tokens are minted by the main API,
which does not know about billing, and a plan is a commercial fact that
belongs to the billing tables. Results are cached per process for a minute.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import sqlalchemy as sa

log = logging.getLogger("interface_check.plans")
TTL_S = 60.0
_cache: dict[str, tuple[float, str, str]] = {}
_lock = threading.Lock()

_BILLING = sa.text("""
    select lower(p.name) as plan
    from subscriptions s join pricing_plans p on p.id = s.plan_id
    where s.user_id::text = :uid
      and lower(s.status::text) in ('active', 'trialing')
      and (s.current_period_end is null or s.current_period_end > now())
    order by p.price_monthly_cents desc
    limit 1
""")


def _overrides() -> dict[str, str]:
    out = {}
    for item in os.environ.get("IC_PLAN_OVERRIDES", "").split(","):
        if "=" in item:
            uid, plan = item.split("=", 1)
            out[uid.strip()] = plan.strip().lower()
    return out


def resolve(engine, user_id: str, default: str = "free") -> tuple[str, str]:
    """(plan, source) for a user. source: billing | operator | default."""
    now = time.time()
    with _lock:
        hit = _cache.get(user_id)
        if hit and now - hit[0] < TTL_S:
            return hit[1], hit[2]
    plan, source = None, "default"
    if engine is not None and engine.dialect.name == "postgresql":
        try:
            with engine.connect() as c:
                plan = c.execute(_BILLING, {"uid": user_id}).scalar()
            source = "billing" if plan else source
        except Exception as e:  # noqa: BLE001 - billing outage must not grant a plan; fall through
            log.warning("plan lookup failed for %s: %s", user_id, e)
    if not plan:
        plan = _overrides().get(user_id)
        source = "operator" if plan else "default"
    plan = plan or default
    with _lock:
        _cache[user_id] = (now, plan, source)
    return plan, source


def clear_cache() -> None:
    with _lock:
        _cache.clear()
