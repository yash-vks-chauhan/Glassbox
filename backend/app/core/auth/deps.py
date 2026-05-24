"""FastAPI dependencies for Phase C.

`current_user` decodes the bearer token and returns the matching User row.
`require_role(*roles)` returns a dependency that 403s anyone outside the
set. Both raise *401* on a missing/invalid token — 403 is reserved for
"you are authenticated but not allowed", which matches normal HTTP semantics
and keeps the frontend's redirect-to-login logic simple.

`current_user` rejects tokens whose `tid` no longer matches the user's DB
tenant_id — that protects against a stale token after a user was moved
between tenants (rare but worth covering).
"""

from __future__ import annotations

from typing import Callable, Iterable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth.tokens import InvalidTokenError, decode_access_token
from app.db import get_db
from app.models_db import User


# Roles ordered from least to most privileged. Useful for "compliance and up"
# style checks even though we don't currently hierarchy-enforce.
ROLE_ORDER = {"advisor": 0, "compliance": 1, "admin": 2, "owner": 3}


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    token = _bearer_token(request)
    try:
        claims = decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, claims.sub)
    if user is None or user.tenant_id != claims.tid:
        # Either the user was deleted or moved tenants -> burn the session.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Stale token; please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Phase E — populate request-scoped log context so downstream structlog
    # lines automatically carry tenant_id / user_id. Imported here to avoid a
    # boot-time cycle (logging imports models, which imports deps via auth).
    from app.core.security.logging import set_request_context

    set_request_context(tenant_id=user.tenant_id, user_id=user.id)
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Return a dependency that 403s when the current user's role isn't in
    the allowed set."""
    allowed = frozenset(roles)
    if not allowed:
        raise ValueError("require_role needs at least one role")

    def _checker(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role is not permitted to access this resource.",
            )
        return user

    return _checker


def at_least(role: str) -> Callable[..., User]:
    """Shorthand for 'role and anything above it in ROLE_ORDER'."""
    threshold = ROLE_ORDER[role]
    allowed = tuple(r for r, v in ROLE_ORDER.items() if v >= threshold)
    return require_role(*allowed)
