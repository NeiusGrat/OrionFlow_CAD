"""Fire-and-forget telemetry for the OFL pipeline.

Every generate/edit/rebuild logs one ofl_events row: the prompt, the code the
LLM produced, whether it executed, and the measured geometry. This is both the
product health metric source and a growing training corpus. A telemetry
failure (DB down, bad token) must never affect the user's generation — every
path here swallows its own errors.
"""

import logging
import uuid
from typing import Optional

from app.domain.ofl_models import OFLGenerateResponse

logger = logging.getLogger(__name__)


def user_id_from_auth_header(authorization: Optional[str]) -> Optional[uuid.UUID]:
    """Best-effort user attribution from a Bearer token; None on any problem."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        from app.auth.jwt import verify_token

        payload = verify_token(authorization.split(" ", 1)[1])
        return uuid.UUID(payload.sub) if payload and payload.sub else None
    except Exception:
        return None


async def log_ofl_event(
    event_type: str,
    response: OFLGenerateResponse,
    prompt: Optional[str] = None,
    input_code: Optional[str] = None,
    authorization: Optional[str] = None,
) -> None:
    """Persist one telemetry row. Designed to run as a BackgroundTask."""
    try:
        from app.db.models import OFLEvent
        from app.db.session import get_db_context

        stats = response.stats
        async with get_db_context() as db:
            db.add(
                OFLEvent(
                    user_id=user_id_from_auth_header(authorization),
                    event_type=event_type,
                    prompt=prompt,
                    input_code=input_code,
                    ofl_code=response.ofl_code or None,
                    success=response.success,
                    error=response.error,
                    repair_attempts=response.repair_attempts,
                    generation_time_ms=int(response.generation_time_ms),
                    watertight=stats.watertight if stats else None,
                    volume_mm3=stats.volume_mm3 if stats else None,
                    bbox_mm=stats.bbox_mm if stats else None,
                    triangles=stats.triangles if stats else None,
                )
            )
    except Exception as e:
        logger.warning(f"OFL telemetry write failed: {e}")
