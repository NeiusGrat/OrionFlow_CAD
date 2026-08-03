"""What the studio remembers about a build, and what it charges for it.

Until now a studio turn wrote nothing. The model produced a Blueprint, FreeCAD
built and measured it, the assertions were checked — and when the response
finished, all of it was discarded unless the user happened to press save, which
stores only the Blueprint. Three consequences, all of them load-bearing:

* **Nothing could be charged.** ``check_usage_limit`` has existed and worked for
  months, called from the legacy job route that no user reaches. The live path
  ran unmetered.
* **Nothing could be debugged.** A user reporting "it said refused" left no
  record of which assertion missed or which feature failed to recompute.
* **The evidence for a feature tree was thrown away.** ``measured["features"]``
  carries each feature's own added/subtracted volume, and the build report
  carries per-feature recompute errors. Both are computed on every build and
  neither survived the request.

This module fixes all three from one place, on two rules.

**A telemetry or billing failure must never cost a user their part.** Every
write here swallows its own errors, and the quota gate fails *open* when the
database is unreachable. A billing system that takes the product down when it
breaks is worse than no billing system.

**The gate holds no connection while geometry is built.** It deliberately does
not take ``Depends(get_db)``: that session would stay open for the life of the
response, and a studio response is a stream that lasts as long as the build —
up to three minutes. Fifteen concurrent designers would exhaust the pool and the
symptom would be database timeouts on login, a very long way from the cause.
A short-lived context manager returns the connection before the build starts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Header

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class StudioGate:
    """Who is asking, and whether they may."""

    user_id: Optional[uuid.UUID] = None
    allowed: bool = True
    reason: str = ""
    message: str = ""
    used: Optional[int] = None
    limit: Optional[int] = None

    @property
    def known(self) -> bool:
        """Whether this turn can be attributed to an account at all."""
        return self.user_id is not None


async def studio_gate(authorization: Optional[str] = Header(None)) -> StudioGate:
    """Resolve the caller and check their monthly allowance.

    Anonymous callers come back with ``known=False`` and no verdict. This
    function does not decide what that means — it reports who is asking and what
    their allowance says, and the route decides. ``/studio/chat`` refuses them
    outright, because both of its roles call a model we pay for; a route that
    charges nobody is a way to spend the inference budget without limit, and
    signing out would otherwise be a way around the quota.
    """
    from app.services.ofl_telemetry import user_id_from_auth_header

    user_id = user_id_from_auth_header(authorization)
    if user_id is None:
        return StudioGate()

    try:
        from app.billing.usage import check_usage_limit
        from app.db.session import get_db_context

        async with get_db_context() as db:
            verdict = await check_usage_limit(db, user_id)
    except Exception as exc:  # noqa: BLE001 — see module docstring: fail open
        logger.warning(
            "studio_quota_check_failed", user_id=str(user_id), error=repr(exc)
        )
        return StudioGate(user_id=user_id)

    return StudioGate(
        user_id=user_id,
        allowed=bool(verdict.get("allowed", True)),
        reason=str(verdict.get("reason") or ""),
        message=str(verdict.get("message") or ""),
        used=verdict.get("used"),
        limit=verdict.get("limit"),
    )


def build_evidence(bundle: dict) -> dict[str, Any]:
    """The per-feature record of what the kernel actually did.

    Everything here is measured or reported by FreeCAD, never authored by the
    model — which is what makes it usable as the spine of a feature tree. The
    two fields that matter most are the ones that used to be dropped:

    ``features``
        one row per solid feature, each with the volume that feature added or
        removed (``addsub_volume``) and the running total after it. This is what
        turns a flat list of names into a history a user can reason about.
    ``recompute_errors``
        keyed by feature **id**, not by position — a feature can fail while the
        ones after it succeed, and the tree has to mark the right node.

    ``artifacts`` and ``blueprint_hash``
        where the built files landed, and the hash of the contract they were
        built from. Recorded on *every* build, not only on the ones a user
        chooses to save, because the FCStd is the parametric document and a
        build is the only moment it exists. ``designs.fcstd_path`` covers the
        saved case; this covers the other 90% — the builds that were tried,
        judged and moved on from, which are exactly the ones a training corpus
        of real design sessions is made of. The hash travels with them so a
        stored artifact can always be tied back to the frozen Blueprint that
        produced it, and a mismatch is detectable rather than assumed away.
    """
    measured = bundle.get("measured") or {}
    log = bundle.get("build_log") or {}
    report = log.get("build_report") or {}
    return {
        "features": measured.get("features") or [],
        "recompute_errors": report.get("recompute_errors") or [],
        "unsupported": report.get("unsupported") or [],
        "built": report.get("built") or [],
        "assertions": bundle.get("assertions") or [],
        "verification": bundle.get("verification") or {},
        "stats": bundle.get("stats"),
        "variables": bundle.get("variables") or {},
        "part_class": bundle.get("part_class") or "",
        "model": bundle.get("model") or "",
        "volume_claim": bundle.get("volume_claim"),
        "attempts": bundle.get("attempts", 1),
        "built_where": log.get("where") or "",
        "artifacts": bundle.get("files") or {},
        "blueprint_hash": (bundle.get("blueprint") or {}).get("blueprint_hash", ""),
        # What was known before the kernel ran. Stored beside what it measured
        # so a record says both what the design claimed about itself and what
        # the geometry turned out to be — a pair, not two separate facts.
        "critique": bundle.get("critique") or {},
        # The deterministic engineering review of the resolved geometry. Kept
        # beside the critique rather than merged into it: one grades the model
        # against its own contract, the other grades the part against mechanics,
        # and a corpus that cannot tell them apart cannot learn from either.
        "mechanical": bundle.get("mechanical") or {},
    }


def _error_code(bundle: dict) -> Optional[str]:
    """A coarse, stable class for the failure — for grouping, not for display.

    Mirrors the vocabulary ``orion.repair_loop`` already switches on, so a
    query over this column and a diagnosis in the repair loop describe the same
    partition of failures.
    """
    error = str(bundle.get("error") or "")
    if not error:
        return None
    if error.startswith("blueprint rejected:"):
        return "freeze"
    if error.startswith("blueprint could not be resolved:"):
        return "resolve"
    if "did not converge" in error:
        return "timeout"
    if "no Blueprint JSON" in error:
        return "parse"
    if "no model is reachable" in error:
        return "model_unreachable"
    verdict = (bundle.get("verification") or {}).get("verdict")
    if verdict == "refused":
        return "assert"
    return "build"


async def record_studio_build(
    bundle: dict, prompt: str, user_id: Optional[uuid.UUID]
) -> None:
    """Persist one design turn, and charge for it if it produced geometry.

    Designed to run as a ``BackgroundTasks`` callback, so it happens after the
    stream has closed and cannot add latency to the turn it describes.

    Anonymous turns are not recorded: both ``generation_history.user_id`` and
    ``designs.user_id`` are NOT NULL, and inventing a placeholder account to
    satisfy that would corrupt every per-user metric computed from these tables.

    Charging follows geometry, not requests. A turn that produced a solid
    consumed the expensive half of the system whether or not the assertions
    passed, so a *refused* part is billable; a turn that produced nothing —
    model unreachable, kernel crash, an answer that was not a Blueprint — is
    not. Billing a user for our own failure is the kind of thing that loses the
    account, and the compute it saves is not worth it.
    """
    if user_id is None:
        return

    try:
        from datetime import datetime, timezone

        from app.billing.usage import BILLABLE_ACTION, track_usage
        from app.db.models import GenerationHistory, GenerationStatus
        from app.db.session import get_db_context

        success = bool(bundle.get("success"))
        duration = bundle.get("generation_time_ms") or 0
        request_id = str(bundle.get("request_id") or "")[:32]

        # Two transactions, not one, and the order is the point. The record of
        # what happened is worth more than the charge for it: a lost history row
        # cannot be reconstructed, while an unmetered build is a known quantity
        # that can be reconciled from the record later.
        #
        # They shared a transaction until now, and ``track_usage`` commits it —
        # so when its INSERT failed, the history row went with it. Splitting
        # them means a billing fault can only ever cost the billing row.
        async with get_db_context() as db:
            db.add(
                GenerationHistory(
                    user_id=user_id,
                    prompt=prompt[:8000],
                    request_id=request_id or None,
                    feature_graph=bundle.get("blueprint"),
                    status=(
                        GenerationStatus.COMPLETED
                        if success
                        else GenerationStatus.FAILED
                    ),
                    error_message=(
                        str(bundle.get("error"))[:2000] if bundle.get("error") else None
                    ),
                    error_code=_error_code(bundle),
                    duration_ms=int(duration),
                    # attempts counts draws; retries are the ones after the first.
                    retry_count=max(0, int(bundle.get("attempts", 1)) - 1),
                    execution_trace=build_evidence(bundle),
                    completed_at=datetime.now(timezone.utc),
                )
            )

        if success:
            # Charged in its own transaction, and its own try: the history row
            # is already committed above and must stay committed whatever
            # happens here.
            #
            # The action MUST be the one the quota queries filter on, hence the
            # imported constant rather than a descriptive name of our own.
            # Writing "studio_design" here — which this did first — produces a
            # usage row the free-tier counter cannot see, so the limit never
            # trips and metering silently does nothing. What distinguishes a
            # studio build from any other billable one goes in the metadata,
            # where nothing depends on it.
            try:
                async with get_db_context() as db:
                    await track_usage(
                        db,
                        user_id,
                        action=BILLABLE_ACTION,
                        metadata={
                            "source": "studio",
                            "request_id": request_id,
                            "part_class": bundle.get("part_class") or "",
                            "verdict": (bundle.get("verification") or {}).get(
                                "verdict", ""
                            ),
                            "model": bundle.get("model") or "",
                        },
                    )
            except Exception as exc:  # noqa: BLE001 — never costs the record
                logger.warning(
                    "studio_usage_track_failed",
                    user_id=str(user_id),
                    request_id=request_id,
                    error=repr(exc),
                )
    except Exception as exc:  # noqa: BLE001 — never costs the user their part
        logger.warning(
            "studio_build_record_failed", user_id=str(user_id), error=repr(exc)
        )


async def link_design_to_build(
    db, design_id: uuid.UUID, request_id: str, user_id: uuid.UUID
) -> bool:
    """Point the build record at the design the user saved from it.

    Scoped by ``user_id`` as well as ``request_id``: request ids are short and
    handed to the client, so without the ownership predicate a caller could
    attach someone else's build evidence — and therefore someone else's
    dimensions — to a design of their own.
    """
    from sqlalchemy import update

    from app.db.models import GenerationHistory

    try:
        result = await db.execute(
            update(GenerationHistory)
            .where(
                GenerationHistory.request_id == request_id,
                GenerationHistory.user_id == user_id,
                GenerationHistory.design_id.is_(None),
            )
            .values(design_id=design_id)
        )
        return bool(result.rowcount)
    except Exception as exc:  # noqa: BLE001 — a missing link is not a failed save
        logger.warning(
            "design_build_link_failed", design_id=str(design_id), error=repr(exc)
        )
        return False
