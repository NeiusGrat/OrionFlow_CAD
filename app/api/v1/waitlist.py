"""Public waitlist endpoint — early-access signups.

Deliberately minimal attack surface: one insert-only POST, no auth, no reads.
The email column is unique, so repeat submissions are idempotent and the
response never reveals whether an address was already on the list. A hidden
honeypot field silently drops naive bots, and the endpoint is rate limited
per client IP.

Two callers, one row:

  * the landing page, which asks for an email and nothing else;
  * the studio's ``/start`` intake, which asks for a name, a company and a work
    email before handing the visitor to sign-up.

The second exists because a list of addresses answers "how many" and no other
question. Name and company are therefore optional at the schema level and
required only by the form that collects them — an email-only signup is still a
real signup, and refusing it to keep the columns full would trade leads for
tidiness.

Note on the honeypot: it used to be ``company``, which is a real field now. It
is ``website`` instead, and that value is never stored under any circumstances.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, update
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
    name: Optional[str] = Field(default=None, max_length=200)
    company: Optional[str] = Field(default=None, max_length=200)
    source: Optional[str] = Field(default="landing", max_length=64)
    #: Honeypot: hidden on the real form, so any value means a bot filled it.
    website: Optional[str] = Field(default=None, max_length=200)


class WaitlistResponse(BaseModel):
    ok: bool = True


@router.post("", response_model=WaitlistResponse)
@rate_limit("10/minute")
async def join_waitlist(
    request: Request,
    payload: WaitlistRequest,
    db: AsyncSession = Depends(get_db),
) -> WaitlistResponse:
    """Add someone to the early-access list."""
    if payload.website:
        # Bot filled the honeypot — pretend success, store nothing.
        return WaitlistResponse()

    email = payload.email.strip().lower()
    name = (payload.name or "").strip() or None
    company = (payload.company or "").strip() or None

    db.add(
        WaitlistEntry(email=email, name=name, source=payload.source, company=company)
    )
    try:
        await db.commit()
        logger.info("waitlist_signup", source=payload.source, identified=bool(name))
    except IntegrityError:
        # Already on the list. Same response either way — no information leak —
        # but if this submission carries a name and the stored row does not,
        # the row is filled in. Someone who left an email on the landing page
        # months ago and has now come through the intake form is the same lead
        # with more known about them, and dropping that would be discarding the
        # only thing this endpoint exists to collect.
        await db.rollback()
        if name or company:
            try:
                # `coalesce` is doing the work: fill the column only where it is
                # still empty. A second submission never overwrites what the
                # first one said, so this cannot be used to edit an existing
                # row's identity from an unauthenticated endpoint.
                await db.execute(
                    update(WaitlistEntry)
                    .where(WaitlistEntry.email == email)
                    .where(
                        WaitlistEntry.name.is_(None) | WaitlistEntry.company.is_(None)
                    )
                    .values(
                        name=func.coalesce(WaitlistEntry.name, name),
                        company=func.coalesce(WaitlistEntry.company, company),
                    )
                )
                await db.commit()
            except Exception:  # noqa: BLE001
                # An enrichment that fails must never turn a successful signup
                # into an error the visitor sees — they are already on the list.
                await db.rollback()
                logger.warning("waitlist_enrich_failed", exc_info=True)
    return WaitlistResponse()
