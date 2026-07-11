"""Tests for the email service (app/services/email_service.py)."""

from app.config import settings
from app.services import email_service


def _no_backends(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "smtp_host", None)


def test_console_fallback_when_unconfigured(monkeypatch):
    _no_backends(monkeypatch)
    assert email_service.send_email("u@example.com", "Hi", "<p>hi</p>") is True


def test_resend_posts_payload(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return FakeResponse()

    monkeypatch.setattr(email_service.requests, "post", fake_post)
    assert email_service.send_email("u@example.com", "Subject", "<b>x</b>") is True
    assert captured["url"] == email_service.RESEND_API_URL
    assert captured["headers"]["Authorization"] == "Bearer re_test_key"
    assert captured["json"]["to"] == ["u@example.com"]
    assert captured["json"]["subject"] == "Subject"


def test_resend_failure_returns_false(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")

    class FakeResponse:
        status_code = 422
        text = "invalid from address"

    monkeypatch.setattr(email_service.requests, "post", lambda *a, **k: FakeResponse())
    assert email_service.send_email("u@example.com", "Subject", "x") is False


def test_send_email_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")

    def boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(email_service.requests, "post", boom)
    assert email_service.send_email("u@example.com", "Subject", "x") is False


def test_verification_email_link(monkeypatch):
    _no_backends(monkeypatch)
    sent = {}
    monkeypatch.setattr(
        email_service,
        "send_email",
        lambda to, subject, html: sent.update(to=to, html=html) or True,
    )
    assert email_service.send_verification_email("u@example.com", "tok123") is True
    assert f"{settings.frontend_url}/auth/verify-email?token=tok123" in sent["html"]


def test_password_reset_email_link(monkeypatch):
    _no_backends(monkeypatch)
    sent = {}
    monkeypatch.setattr(
        email_service,
        "send_email",
        lambda to, subject, html: sent.update(to=to, html=html) or True,
    )
    assert email_service.send_password_reset_email("u@example.com", "tok456") is True
    assert f"{settings.frontend_url}/auth/reset-password?token=tok456" in sent["html"]
