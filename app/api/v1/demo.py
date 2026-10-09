"""Public "Book a demo" endpoint.

The landing page's demo button opens a short form — name, work email, company,
role, what they want to see — and posts it here before offering the booking
calendar. The row is the lead: someone who never picks a slot has still told us
who they are.

Same shape of defence as the waitlist: insert-only, no reads, a hidden
``website`` honeypot that is never stored, and a per-IP rate limit. Every
submission is kept (no unique email), because a second request from the same
person is usually a different question.

A notification goes to ``settings.sales_notify_email`` as a background task, so
a slow or unconfigured mail provider never delays or fails the visitor's
submission.
"""

from html import escape
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import DemoRequest
from app.db.session import get_db
from app.logging_config import get_logger
from app.middleware.rate_limit import rate_limit
from app.services.email_service import send_email

logger = get_logger(__name__)
router = APIRouter()


class DemoRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    company: str = Field(min_length=1, max_length=200)
    role: Optional[str] = Field(default=None, max_length=200)
    message: Optional[str] = Field(default=None, max_length=4000)
    source: Optional[str] = Field(default="landing", max_length=64)
    #: Honeypot: hidden on the real form, so any value means a bot filled it.
    website: Optional[str] = Field(default=None, max_length=200)


class DemoRequestOut(BaseModel):
    ok: bool = True


def _notify(row: dict) -> None:
    lines = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#666'>{escape(k)}</td>"
        f"<td style='padding:4px 0'>{escape(v or '—')}</td></tr>"
        for k, v in row.items()
    )
    send_email(
        settings.sales_notify_email,
        f"Demo request — {row['Name']} ({row['Company']})",
        f"<h2 style='font-family:sans-serif'>New demo request</h2>"
        f"<table style='font-family:sans-serif;font-size:14px'>{lines}</table>",
    )


@router.post("", response_model=DemoRequestOut)
@rate_limit("5/minute")
async def request_demo(
    request: Request,
    payload: DemoRequestIn,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DemoRequestOut:
    """Record a demo request and announce it."""
    if payload.website:
        # Bot filled the honeypot — pretend success, store nothing.
        return DemoRequestOut()

    name = payload.name.strip()
    company = payload.company.strip()
    role = (payload.role or "").strip() or None
    message = (payload.message or "").strip() or None
    email = payload.email.strip().lower()

    db.add(
        DemoRequest(
            name=name,
            email=email,
            company=company,
            role=role,
            message=message,
            source=payload.source,
        )
    )
    await db.commit()
    logger.info("demo_requested", source=payload.source, company=company)

    background.add_task(
        _notify,
        {
            "Name": name,
            "Email": email,
            "Company": company,
            "Role": role,
            "Wants to see": message,
            "Source": payload.source,
        },
    )
    return DemoRequestOut()
