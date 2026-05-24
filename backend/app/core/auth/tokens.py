"""Token primitives — JWT access tokens and opaque refresh tokens.

Access tokens are short-lived JWTs (HS256, 15 min default). Refresh tokens
are 256-bit random strings, stored only as SHA-256 hashes in the DB so a
read of the database can't be used to forge sessions.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from app.config import get_settings


@dataclass(frozen=True)
class AccessTokenClaims:
    sub: str  # user_id
    tid: str  # tenant_id
    role: str
    jti: str
    exp: int
    iat: int
    kid: str


@dataclass(frozen=True)
class MFAChallengeClaims:
    sub: str  # user_id
    tid: str  # tenant_id
    jti: str
    exp: int
    iat: int
    kid: str


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature, expiry, or shape validation."""


def issue_access_token(*, user_id: str, tenant_id: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_signing_key,
        algorithm="HS256",
        headers={"kid": settings.jwt_active_kid},
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        # We currently hold a single key; the `kid` slot is reserved for
        # rotation, so accept any kid for now but require the header to
        # actually carry one — guards against tokens minted without a kid.
        if "kid" not in header:
            raise InvalidTokenError("missing kid")
        payload = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    try:
        return AccessTokenClaims(
            sub=payload["sub"],
            tid=payload["tid"],
            role=payload["role"],
            jti=payload["jti"],
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            kid=header["kid"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError(f"malformed claims: {exc}") from exc


def issue_mfa_challenge_token(*, user_id: str, tenant_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=5)
    payload = {
        "typ": "mfa",
        "sub": user_id,
        "tid": tenant_id,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_signing_key,
        algorithm="HS256",
        headers={"kid": settings.jwt_active_kid},
    )


def decode_mfa_challenge_token(token: str) -> MFAChallengeClaims:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        if "kid" not in header:
            raise InvalidTokenError("missing kid")
        payload = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=["HS256"],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    try:
        if payload.get("typ") != "mfa":
            raise InvalidTokenError("wrong token type")
        return MFAChallengeClaims(
            sub=payload["sub"],
            tid=payload["tid"],
            jti=payload["jti"],
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            kid=header["kid"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError(f"malformed claims: {exc}") from exc


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, hashed at rest)
# ---------------------------------------------------------------------------


def generate_refresh_token() -> str:
    """256-bit URL-safe token. Returned in plaintext to the client exactly
    once; only the hash lives in the DB."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    settings = get_settings()
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)
