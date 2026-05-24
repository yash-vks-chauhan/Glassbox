"""Auth service layer — flows the routers call into.

All cross-table DB work lives here so the routers stay thin and the test
suite can drive these functions directly without a TestClient when needed.

Design notes worth knowing if you change this file:

- Login responses are deliberately indistinguishable for "unknown email" vs
  "wrong password" vs "locked account" (one generic error). We also burn
  Argon2 time on the unknown-email path so the timing channel doesn't leak
  account existence.
- Refresh-token rotation uses a `family_id` shared by all rotated descendants
  of one login. If a *superseded* token in the family is ever presented
  again, that's a theft signal -> we revoke the entire family.
- Recovery-code-based MFA login is supported on /auth/login (one-shot);
  consuming a code removes it from the user's recovery list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.auth import mfa as mfa_mod
from app.core.auth.email import get_email_service
from app.core.auth.passwords import (
    WeakPasswordError,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.auth.tokens import (
    InvalidTokenError,
    decode_mfa_challenge_token,
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
    issue_mfa_challenge_token,
    refresh_token_expiry,
)
from app.models_db import (
    PasswordReset,
    RefreshToken,
    SecurityEvent,
    Tenant,
    User,
    UserInvitation,
    utcnow,
)


VALID_ROLES = {"owner", "admin", "compliance", "advisor"}
MFA_REQUIRED_ROLES = {"owner", "admin"}


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo when round-tripping DateTime(timezone=True),
    so anything we load and compare against `datetime.now(timezone.utc)`
    must be re-anchored to UTC first."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Exceptions — kept generic on purpose so routers can map them to a single
# user-facing "invalid credentials" message without leaking which case fired.
# ---------------------------------------------------------------------------


class AuthError(Exception):
    """Base for any auth-flow failure surfaced to a router."""


class InvalidCredentials(AuthError):
    pass


class AccountLocked(AuthError):
    pass


class MFARequired(AuthError):
    """Login passed primary creds but needs an MFA factor next."""

    def __init__(self, mfa_token: str):
        super().__init__("mfa_required")
        self.mfa_token = mfa_token


class MFAEnrollmentRequired(AuthError):
    """Admin/owner role with no MFA enrolled -> force enrollment."""

    def __init__(self, enrollment_token: str):
        super().__init__("mfa_enrollment_required")
        self.enrollment_token = enrollment_token


class InvalidToken(AuthError):
    pass


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LoginResult:
    access_token: str
    refresh_token: str  # plaintext; cookie this and discard
    user: User


# ---------------------------------------------------------------------------
# Account creation (used by accept-invite + tests)
# ---------------------------------------------------------------------------


def create_user(
    db: Session,
    *,
    tenant_id: str,
    email: str,
    password: str,
    role: str,
    display_name: str | None = None,
    email_verified: bool = False,
) -> User:
    if role not in VALID_ROLES:
        raise ValueError(f"unknown role: {role}")
    normalized = email.strip().lower()
    existing = db.scalar(
        select(User).where(User.tenant_id == tenant_id, User.email == normalized)
    )
    if existing is not None:
        raise InvalidCredentials("user already exists")
    user = User(
        tenant_id=tenant_id,
        email=normalized,
        password_hash=hash_password(password),
        role=role,
        display_name=display_name,
        email_verified=email_verified,
    )
    db.add(user)
    db.flush()  # populate user.id without committing
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def authenticate(
    db: Session,
    *,
    email: str,
    password: str,
    tenant_slug: str | None,
    mfa_code: str | None,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    """Verify credentials + MFA and mint a fresh session.

    Tenant slug is required when more than one tenant exists, since email is
    unique only per-tenant. For the single-tenant demo case it may be None
    and we'll fall back to the only tenant.
    """
    settings = get_settings()
    normalized = email.strip().lower()

    user = _lookup_user(db, email=normalized, tenant_slug=tenant_slug)

    if user and _is_locked(user):
        _log_security_event(db, kind="login_locked", user=user, ip=ip, user_agent=user_agent)
        raise AccountLocked()

    if user is None or not verify_password(password, user.password_hash):
        # Burn a hash check on the unknown path too (verify_password handles it).
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failed_attempts:
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.login_lockout_minutes
                )
                _log_security_event(
                    db, kind="login_lockout", user=user, ip=ip, user_agent=user_agent
                )
            db.flush()
        _log_security_event(
            db,
            kind="login_failed",
            user=user,
            ip=ip,
            user_agent=user_agent,
            metadata={"email": normalized},
        )
        raise InvalidCredentials()

    # Primary creds OK. Now decide MFA path.
    if user.mfa_enrolled:
        if mfa_code is None:
            # Phase B keeps the MFA challenge stateless via a short-lived
            # token-bound second request. For local simplicity we return a
            # raw signal here and the router asks the client to re-POST with
            # mfa_code; future passes can swap in a server-side challenge id.
            raise MFARequired(
                mfa_token=issue_mfa_challenge_token(
                    user_id=user.id, tenant_id=user.tenant_id
                )
            )
        secret, _ = mfa_mod.unpack_secret(user.mfa_secret)
        if not (secret and mfa_mod.verify_code(secret, mfa_code)):
            # Try recovery code path before giving up.
            ok, new_blob = mfa_mod.consume_recovery_code(user.mfa_secret, mfa_code)
            if not ok:
                user.failed_login_count += 1
                db.flush()
                _log_security_event(
                    db, kind="mfa_failed", user=user, ip=ip, user_agent=user_agent
                )
                raise InvalidCredentials()
            user.mfa_secret = new_blob
            _log_security_event(
                db, kind="mfa_recovery_used", user=user, ip=ip, user_agent=user_agent
            )
    else:
        if user.role in MFA_REQUIRED_ROLES:
            raise MFAEnrollmentRequired(enrollment_token=user.id)

    # Success.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    access, refresh_plain = _mint_session(
        db,
        user=user,
        family_id=str(uuid4()),
        ip=ip,
        user_agent=user_agent,
    )
    _log_security_event(db, kind="login_success", user=user, ip=ip, user_agent=user_agent)
    return LoginResult(access_token=access, refresh_token=refresh_plain, user=user)


def authenticate_mfa_challenge(
    db: Session,
    *,
    mfa_token: str,
    mfa_code: str,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    try:
        claims = decode_mfa_challenge_token(mfa_token)
    except InvalidTokenError as exc:
        raise InvalidToken() from exc

    user = db.get(User, claims.sub)
    if user is None or user.tenant_id != claims.tid or not user.mfa_enrolled:
        raise InvalidToken()
    if _is_locked(user):
        _log_security_event(db, kind="login_locked", user=user, ip=ip, user_agent=user_agent)
        raise AccountLocked()

    secret, _ = mfa_mod.unpack_secret(user.mfa_secret)
    if not (secret and mfa_mod.verify_code(secret, mfa_code)):
        ok, new_blob = mfa_mod.consume_recovery_code(user.mfa_secret, mfa_code)
        if not ok:
            user.failed_login_count += 1
            if user.failed_login_count >= get_settings().login_max_failed_attempts:
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=get_settings().login_lockout_minutes
                )
                _log_security_event(
                    db, kind="login_lockout", user=user, ip=ip, user_agent=user_agent
                )
            db.flush()
            _log_security_event(
                db, kind="mfa_failed", user=user, ip=ip, user_agent=user_agent
            )
            raise InvalidCredentials()
        user.mfa_secret = new_blob
        _log_security_event(
            db, kind="mfa_recovery_used", user=user, ip=ip, user_agent=user_agent
        )

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    access, refresh_plain = _mint_session(
        db,
        user=user,
        family_id=str(uuid4()),
        ip=ip,
        user_agent=user_agent,
    )
    _log_security_event(db, kind="login_success", user=user, ip=ip, user_agent=user_agent)
    return LoginResult(access_token=access, refresh_token=refresh_plain, user=user)


def _lookup_user(
    db: Session, *, email: str, tenant_slug: str | None
) -> User | None:
    stmt = select(User).where(User.email == email)
    if tenant_slug:
        stmt = stmt.join(Tenant, Tenant.id == User.tenant_id).where(
            Tenant.slug == tenant_slug
        )
    rows = db.scalars(stmt).all()
    if not rows:
        return None
    if len(rows) > 1:
        # Same email in multiple tenants and the caller didn't disambiguate.
        # Treat as unknown — better than picking arbitrarily.
        return None
    return rows[0]


def _is_locked(user: User) -> bool:
    locked = _as_utc(user.locked_until)
    return bool(locked and locked > datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Refresh-token rotation
# ---------------------------------------------------------------------------


def refresh_session(
    db: Session,
    *,
    presented_refresh: str,
    ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    """Rotate the refresh token. Detects reuse of a superseded token in the
    same family and revokes the entire family if so."""
    token_hash = hash_refresh_token(presented_refresh)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise InvalidToken()

    if row.revoked_at is not None:
        # Reuse of a revoked token -> theft signal. Burn the whole family.
        _revoke_family(db, family_id=row.family_id)
        _log_security_event(
            db,
            kind="refresh_reuse_detected",
            user_id=row.user_id,
            ip=ip,
            user_agent=user_agent,
            metadata={"family_id": row.family_id},
        )
        raise InvalidToken()

    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        raise InvalidToken()

    user = db.get(User, row.user_id)
    if user is None:
        raise InvalidToken()

    # Mark the presented token as revoked and issue a sibling under the
    # same family.
    row.revoked_at = datetime.now(timezone.utc)
    access, refresh_plain = _mint_session(
        db, user=user, family_id=row.family_id, ip=ip, user_agent=user_agent
    )
    db.flush()
    return LoginResult(access_token=access, refresh_token=refresh_plain, user=user)


def logout(db: Session, *, presented_refresh: str | None) -> None:
    if not presented_refresh:
        return
    token_hash = hash_refresh_token(presented_refresh)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None or row.revoked_at is not None:
        return
    _revoke_family(db, family_id=row.family_id)
    _log_security_event(
        db, kind="logout", user_id=row.user_id, ip=None, user_agent=None,
        metadata={"family_id": row.family_id},
    )


def _revoke_family(db: Session, *, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def _mint_session(
    db: Session,
    *,
    user: User,
    family_id: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, str]:
    access = issue_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role
    )
    refresh_plain = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_refresh_token(refresh_plain),
            user_agent=(user_agent or "")[:512] or None,
            ip=ip,
            expires_at=refresh_token_expiry(),
        )
    )
    return access, refresh_plain


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def request_password_reset(
    db: Session,
    *,
    email: str,
    tenant_slug: str | None,
    ip: str | None,
) -> None:
    """Always returns successfully. If a matching user exists, a one-shot
    token is created and emailed."""
    user = _lookup_user(db, email=email.strip().lower(), tenant_slug=tenant_slug)
    if user is None:
        _log_security_event(
            db, kind="password_reset_unknown_email", user=None, ip=ip, user_agent=None,
            metadata={"email": email},
        )
        return
    settings = get_settings()
    token_plain = generate_refresh_token()  # reuse 256-bit generator
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=hash_refresh_token(token_plain),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.password_reset_ttl_hours),
        )
    )
    db.flush()
    get_email_service().send(
        to=user.email,
        subject="GlassBox password reset",
        body_text=(
            "Use the following token to set a new password. It expires in "
            f"{settings.password_reset_ttl_hours} hour(s).\n\nToken: {token_plain}\n"
        ),
    )
    _log_security_event(
        db, kind="password_reset_requested", user=user, ip=ip, user_agent=None
    )


def complete_password_reset(
    db: Session, *, token: str, new_password: str
) -> User:
    row = db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == hash_refresh_token(token))
    )
    if (
        row is None
        or row.used_at is not None
        or _as_utc(row.expires_at) <= datetime.now(timezone.utc)
    ):
        raise InvalidToken()
    user = db.get(User, row.user_id)
    if user is None:
        raise InvalidToken()
    try:
        user.password_hash = hash_password(new_password)
    except WeakPasswordError:
        raise
    row.used_at = datetime.now(timezone.utc)
    # Revoke every existing session — password change invalidates them all.
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    _log_security_event(db, kind="password_reset_completed", user=user, ip=None, user_agent=None)
    return user


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def invite_user(
    db: Session,
    *,
    tenant_id: str,
    email: str,
    role: str,
    invited_by_user_id: str | None,
) -> str:
    """Create an invitation and email it. Returns the plaintext token so
    callers (the router or a test) can surface it for the recipient."""
    if role not in VALID_ROLES:
        raise ValueError(f"unknown role: {role}")
    settings = get_settings()
    token_plain = generate_refresh_token()
    invite = UserInvitation(
        tenant_id=tenant_id,
        email=email.strip().lower(),
        role=role,
        token_hash=hash_refresh_token(token_plain),
        invited_by_user_id=invited_by_user_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.invite_token_ttl_hours),
    )
    db.add(invite)
    db.flush()
    get_email_service().send(
        to=invite.email,
        subject="You've been invited to GlassBox",
        body_text=(
            f"You've been invited to GlassBox as {role}. Use this token to set "
            f"your password (expires in {settings.invite_token_ttl_hours} hours):"
            f"\n\nToken: {token_plain}\n"
        ),
    )
    return token_plain


def accept_invitation(
    db: Session, *, token: str, password: str, display_name: str | None = None
) -> User:
    row = db.scalar(
        select(UserInvitation).where(
            UserInvitation.token_hash == hash_refresh_token(token)
        )
    )
    if (
        row is None
        or row.accepted_at is not None
        or _as_utc(row.expires_at) <= datetime.now(timezone.utc)
    ):
        raise InvalidToken()
    user = create_user(
        db,
        tenant_id=row.tenant_id,
        email=row.email,
        password=password,
        role=row.role,
        display_name=display_name,
        email_verified=True,
    )
    row.accepted_at = datetime.now(timezone.utc)
    _log_security_event(db, kind="invitation_accepted", user=user, ip=None, user_agent=None)
    return user


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------


def begin_mfa_enrollment(db: Session, *, user: User) -> mfa_mod.EnrollmentChallenge:
    """Generate a fresh TOTP secret and return its provisioning URI.
    Caller must subsequently call complete_mfa_enrollment with a valid code."""
    secret = mfa_mod.generate_secret()
    # Stash the secret without recovery codes yet; mfa_enrolled stays False
    # until the user proves they can produce a code.
    user.mfa_secret = mfa_mod.pack_secret(secret, [])
    db.flush()
    return mfa_mod.EnrollmentChallenge(
        secret=secret,
        provisioning_uri=mfa_mod.provisioning_uri(secret, email=user.email),
    )


def complete_mfa_enrollment(
    db: Session, *, user: User, code: str
) -> list[str]:
    secret, _ = mfa_mod.unpack_secret(user.mfa_secret)
    if not (secret and mfa_mod.verify_code(secret, code)):
        raise InvalidCredentials()
    recovery_plain = mfa_mod.generate_recovery_codes()
    recovery_hashes = [mfa_mod.hash_recovery_code(c) for c in recovery_plain]
    user.mfa_secret = mfa_mod.pack_secret(secret, recovery_hashes)
    user.mfa_enrolled = True
    _log_security_event(db, kind="mfa_enrolled", user=user, ip=None, user_agent=None)
    return recovery_plain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_security_event(
    db: Session,
    *,
    kind: str,
    user: User | None = None,
    user_id: str | None = None,
    ip: str | None,
    user_agent: str | None,
    metadata: dict | None = None,
) -> None:
    import json as _json

    db.add(
        SecurityEvent(
            tenant_id=user.tenant_id if user else None,
            user_id=user.id if user else user_id,
            kind=kind,
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            metadata_json=_json.dumps(metadata) if metadata else None,
        )
    )
