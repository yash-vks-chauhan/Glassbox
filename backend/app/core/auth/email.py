"""Transactional email service.

Dev: writes a .eml file per send into DEV_MAIL_DIR so flows are testable
without SMTP. Production drop-in (SES / Postmark) replaces this concrete
class via the same `send(...)` signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from app.config import get_settings


@dataclass(frozen=True)
class SendResult:
    path: Path  # where the .eml landed (dev only)


class EmailService:
    """Pluggable email sender. Default implementation writes to disk."""

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

        msg = EmailMessage()
        msg["From"] = "no-reply@glassbox.local"
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = out_dir / f"{stamp}-{uuid4().hex[:8]}-{_safe(to)}.eml"
        path.write_bytes(bytes(msg))
        return SendResult(path=path)


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)[:64]


_default = EmailService()


def get_email_service() -> EmailService:
    return _default
