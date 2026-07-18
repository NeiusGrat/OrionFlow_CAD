"""Public waitlist endpoint — early-access signups from the landing page.

Deliberately minimal attack surface: one insert-only POST, no auth, no reads.
The email column is unique, so repeat submissions are idempotent and the
response never reveals whether an address was already on the list. A hidden
honeypot field silently drops naive bots, and the endpoint is rate limited
per client IP.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WaitlistEntry
from app.db.session import get_db
from app.logging_config import get_logger
from app.middleware.rate_limit import rate_limit

logger = get_logger(__name__)
router = APIRouter()


class WaitlistRequest(BaseModel):
    email: EmailStr
    source: Optional[str] = Field(default="landing", max_length=64)
    # Honeypot: hidden on the real form, so any value means a bot filled it.
    company: Optional[str] = Field(default=None, max_length=200)


class WaitlistResponse(BaseModel):
    ok: bool = True


@router.post("", response_model=WaitlistResponse)
@rate_limit("10/minute")
async def join_waitlist(
    request: Request,
    payload: WaitlistRequest,
    db: AsyncSession = Depends(get_db),
) -> WaitlistResponse:
    """Add an email to the early-access waitlist."""
    if payload.company:
        # Bot filled the honeypot — pretend success, store nothing.
        return WaitlistResponse()

    email = payload.email.strip().lower()
    db.add(WaitlistEntry(email=email, source=payload.source))
    try:
        await db.commit()
        logger.info("waitlist_signup", source=payload.source)
    except IntegrityError:
        # Already on the list — same response, no information leak.
        await db.rollback()
    return WaitlistResponse()
