"""One-click demo sign-in for the public showcase.

With ``DEMO_LOGIN_ENABLED=1``, anyone can open a session as the demo
workspace's advisor or compliance user, without an account. Those users are
created on first use with random passwords nobody knows, so this endpoint is
the only way in. They can't change their sign-in settings (password, MFA,
sessions), receive password-reset email, store model keys, or edit the
client list, so one visitor can't lock out or spoil the demo for the next.

An owner of the demo workspace can revoke a demo user like any other user,
which turns that demo role off. Changing a demo user's role turns it off as
well: the demo never signs anyone in with more than its own role.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import service as auth_service
from app.models_db import Tenant, User


DEMO_USERS: dict[str, tuple[str, str]] = {
    "advisor": ("demo.advisor@example.com", "Demo Advisor"),
    "compliance": ("demo.compliance@example.com", "Demo Compliance"),
}
DEMO_EMAILS = frozenset(email for email, _ in DEMO_USERS.values())


class DemoUnavailable(Exception):
    """Demo sign-in is off, the demo workspace is missing, or this demo
    role was revoked or re-roled by an owner."""


def demo_tenant(db: Session) -> Tenant | None:
    settings = get_settings()
    if not settings.demo_login_enabled:
        return None
    return db.scalar(select(Tenant).where(Tenant.slug == settings.demo_tenant_slug))


def is_demo_user(user: User) -> bool:
    """True for the shared demo accounts (in the demo workspace only)."""
    if user.email not in DEMO_EMAILS:
        return False
    tenant = user.tenant
    return tenant is not None and tenant.slug == get_settings().demo_tenant_slug


def demo_login(
    db: Session, *, role: str, ip: str | None, user_agent: str | None
) -> tuple[str, str]:
    """Return (access token, refresh token) for the demo ``role`` user,
    creating it on first use. Raises DemoUnavailable."""
    tenant = demo_tenant(db)
    if tenant is None or role not in DEMO_USERS:
        raise DemoUnavailable()
    email, display_name = DEMO_USERS[role]
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    if user is None:
        user = auth_service.create_user(
            db,
            tenant_id=tenant.id,
            email=email,
            password=secrets.token_urlsafe(32),  # never shown, never used
            role=role,
            display_name=display_name,
            email_verified=True,
        )
    now = datetime.now(timezone.utc)
    locked_until = auth_service._as_utc(user.locked_until)
    if user.role != role or (locked_until is not None and locked_until > now):
        raise DemoUnavailable()
    access, refresh = auth_service._mint_session(
        db, user=user, family_id=str(uuid4()), ip=ip, user_agent=user_agent
    )
    user.last_login_at = now
    auth_service._log_security_event(
        db, kind="demo_login", user=user, ip=ip, user_agent=user_agent,
        metadata={"role": role},
    )
    return access, refresh
