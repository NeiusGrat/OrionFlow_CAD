"""
Email delivery for auth flows (verification, password reset).

The backend is picked from settings at send time:

- Resend HTTP API when ``resend_api_key`` is set (recommended; free tier,
  needs a verified domain)
- SMTP when ``smtp_host`` is set
- Console logging otherwise, so dev signups never block on email config

Senders are used from FastAPI BackgroundTasks: they log failures and return
False instead of raising, so a mail outage never fails a signup or reset.
"""

import smtplib
from email.message import EmailMessage

import requests

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def _send_via_resend(to_email: str, subject: str, html: str) -> bool:
    response = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": f"{settings.smtp_from_name} <{settings.smtp_from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=15,
    )
    if response.status_code >= 400:
        logger.error(
            "resend_send_failed",
            status=response.status_code,
            body=response.text[:500],
        )
        return False
    return True


def _send_via_smtp(to_email: str, subject: str, html: str) -> bool:
    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password or "")
        server.send_message(msg)
    return True


def send_email(to_email: str, subject: str, html: str) -> bool:
    """Send an email via the first configured backend. Never raises."""
    try:
        if settings.resend_api_key:
            return _send_via_resend(to_email, subject, html)
        if settings.smtp_host:
            return _send_via_smtp(to_email, subject, html)
        logger.info(
            "email_console_fallback",
            to=to_email,
            subject=subject,
            body=html,
        )
        return True
    except Exception as e:
        logger.error("email_send_failed", to=to_email, subject=subject, error=str(e))
        return False


def _button_email(heading: str, body: str, link: str, button_text: str) -> str:
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="color:#111">{heading}</h2>
  <p style="color:#444;line-height:1.5">{body}</p>
  <p style="margin:28px 0">
    <a href="{link}" style="background:#2563eb;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none">{button_text}</a>
  </p>
  <p style="color:#888;font-size:13px">If the button doesn't work, copy this link:<br>{link}</p>
  <p style="color:#888;font-size:13px">If you didn't request this, you can ignore this email.</p>
</div>"""


def send_verification_email(to_email: str, token: str) -> bool:
    link = f"{settings.frontend_url}/auth/verify-email?token={token}"
    return send_email(
        to_email,
        "Verify your OrionFlow email",
        _button_email(
            "Welcome to OrionFlow",
            "Confirm your email address to activate your account.",
            link,
            "Verify email",
        ),
    )


def send_password_reset_email(to_email: str, token: str) -> bool:
    link = f"{settings.frontend_url}/auth/reset-password?token={token}"
    return send_email(
        to_email,
        "Reset your OrionFlow password",
        _button_email(
            "Password reset",
            "We received a request to reset your password. The link expires in 1 hour.",
            link,
            "Reset password",
        ),
    )
