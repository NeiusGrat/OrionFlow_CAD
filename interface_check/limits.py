"""Per-plan limits: what one job may cost, and what one user may run.

Every number is overridable by environment (``IC_LIMIT_<PLAN>_<FIELD>``), so a
deployment tunes them without a code change. A job that would exceed a limit
fails with RESOURCE_LIMIT and a specific code; it never gets the chance to OOM
a worker.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class Limits:
    plan: str
    max_file_mb: int
    max_total_upload_mb: int
    max_faces: int
    max_triangles: int
    max_parts: int
    max_instances: int
    max_runtime_s: int
    max_memory_mb: int               # hard cap the watchdog enforces (also bounded by the tier)
    max_output_mb: int
    max_tier: str                    # largest worker class this plan may use
    max_concurrent_jobs: int         # per user, QUEUED + RUNNING
    daily_jobs: int
    monthly_compute_s: int           # tier-weighted worker seconds

    def to_dict(self) -> dict:
        return asdict(self)


_PLANS = {
    "free": Limits("free", 50, 100, 150_000, 300_000, 200, 500, 600, 7_000, 100, "SMALL", 1, 10, 3_600),
    "pro": Limits("pro", 300, 600, 1_000_000, 3_000_000, 2_000, 5_000, 1_800, 28_000, 500, "LARGE", 3, 200,
                  108_000),
    "enterprise": Limits("enterprise", 2_000, 4_000, 5_000_000, 20_000_000, 20_000, 50_000, 7_200, 60_000,
                         2_000, "EXTREME", 10, 5_000, 2_000_000),
}


def _extra_plans() -> dict[str, Limits]:
    """Operator-defined plans: IC_EXTRA_PLANS='{"qa_timeout": {"base": "pro", "max_runtime_s": 2}}'."""
    raw = os.environ.get("IC_EXTRA_PLANS", "")
    if not raw:
        return {}
    import json
    out = {}
    for name, spec in json.loads(raw).items():
        spec = dict(spec)
        base = _PLANS[spec.pop("base", "free")]
        out[name.lower()] = Limits(**{**asdict(base), **spec, "plan": name.lower()})
    return out


def limits_for(plan: str | None) -> Limits:
    plans = {**_PLANS, **_extra_plans()}
    base = plans.get((plan or "free").lower(), _PLANS["free"])
    over = {}
    for f in fields(Limits):
        v = os.environ.get(f"IC_LIMIT_{base.plan.upper()}_{f.name.upper()}")
        if v is not None and f.name != "plan":
            over[f.name] = v if f.type in ("str", str) else int(v)
    return Limits(**{**asdict(base), **over})


#: Relative cost of one second on each tier (memory-dominated); quota counts these.
TIER_WEIGHT = {"SMALL": 1.0, "MEDIUM": 2.0, "LARGE": 4.0, "EXTREME": 8.0}

#: USD per worker-second by tier. Defaults are an estimate (cores x per-core rate +
#: GiB x per-GiB rate); set IC_COST_<TIER>_USD_PER_S from the provider's current price sheet.
TIER_USD_PER_S = {k: float(os.environ.get(f"IC_COST_{k}_USD_PER_S", v)) for k, v in
                  {"SMALL": 0.00007, "MEDIUM": 0.00014, "LARGE": 0.00028, "EXTREME": 0.00056}.items()}
