"""Transactional email service.

Two backends, picked by config:

* `SMTPEmailService` — used when `SMTP_HOST` is set. Real outbound mail via
  smtplib + STARTTLS. Works with Gmail (smtp.gmail.com:587 + App Password),
  Mailgun, SES SMTP, etc.
* `DevFileEmailService` — fallback when SMTP_HOST is unset. Writes each
  message as a `.eml` file into DEV_MAIL_DIR so local flows and tests don't
  need a real server.

Call sites use `get_email_service().send(...)`; the backend is selected
once at process start so behavior is consistent within a request.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from app.config import get_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    # path is set for the dev backend so tests can assert on file contents;
    # None for SMTP since there's nothing local to point at.
    path: Path | None = None


def _build_message(*, sender: str, to: str, subject: str, body_text: str, body_html: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    return msg


class DevFileEmailService:
    """Writes each message to DEV_MAIL_DIR as a .eml file."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> SendResult:
        settings = get_settings()
        out_dir = Path(settings.dev_mail_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        msg = _build_message(
            sender=settings.smtp_from,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = out_dir / f"{stamp}-{uuid4().hex[:8]}-{_safe(to)}.eml"
        path.write_bytes(bytes(msg))
        return SendResult(path=path)


class SMTPEmailService:
    """Sends via SMTP. STARTTLS by default (Gmail/Mailgun/SES on :587)."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> SendResult:
        settings = get_settings()
        msg = _build_message(
            sender=settings.smtp_from,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        # Gmail rejects sends where the From address differs from the
        # authenticated user. If the operator forgot to set SMTP_FROM we
        # quietly fall back to the username so the send still succeeds.
        if (
            settings.smtp_username
            and msg["From"] == "no-reply@glassbox.local"
        ):
            del msg["From"]
            msg["From"] = settings.smtp_username

        host = settings.smtp_host
        assert host, "SMTPEmailService picked but SMTP_HOST is empty"
        with smtplib.SMTP(host, settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if settings.smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
        logger.info("smtp_email_sent to=%s subject=%r", to, subject)
        return SendResult(path=None)


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)[:64]


_cached: object | None = None


def get_email_service():
    """Return the configured email backend. Cached across calls so a single
    process keeps a consistent backend even if settings are reloaded."""
    global _cached
    if _cached is not None:
        return _cached
    settings = get_settings()
    if settings.smtp_host:
        _cached = SMTPEmailService()
    else:
        _cached = DevFileEmailService()
    return _cached


def reset_email_service_cache() -> None:
    """Test hook — drop the cached backend so a fresh settings load picks
    up a different one. Not used in production code paths."""
    global _cached
    _cached = None
