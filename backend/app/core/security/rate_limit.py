"""Persistent sliding-window rate limiter.

Keyed on ``(subject, route_class)`` where ``subject`` is the authenticated
user_id when present, otherwise the client IP. We deliberately key on
*user_id over IP* once authenticated so a single misbehaving user can't
spread their budget across NATted teammates.

Window: rolling 60 seconds. We store the unix-second timestamps of recent
hits in ``rate_limit_buckets.hits_json`` (text JSON list). On each request:

1. Load the bucket row (create on first hit).
2. Trim entries older than 60s.
3. If ``len(hits) >= limit``: return 429 with ``Retry-After`` = seconds
   until the oldest hit ages out.
4. Otherwise append now and persist.

Why SQLite + a JSON column instead of Redis? It's the local-first deployment
target for this phase; latency at our scale is dominated by the LLM call,
not 1ms of SQLite write. The interface (``check_and_record``) is small
enough that swapping in Redis later is a backend-only change.

Why pure-ASGI instead of ``BaseHTTPMiddleware``? Starlette's
``BaseHTTPMiddleware`` short-circuits ``StreamingResponse`` (issue #472):
the SSE endpoint ``/ask/stream`` raises ``RuntimeError: No response
returned`` inside the middleware. Operating at the ASGI layer side-steps
that bug.

Route classes (looked up by URL prefix):

- ``auth`` → /auth/login, /auth/refresh, /auth/forgot, /auth/reset,
  /auth/accept-invite, /auth/mfa/*       (strict, 10/min)
- ``ask``  → /ask, /ask/stream                                (60/min)
- ``default`` → everything else                              (120/min)

Health checks, OPTIONS preflights, and unauthenticated GETs to public
endpoints (currently none) bypass the limiter.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.core.auth.tokens import InvalidTokenError, decode_access_token
from app.db import SessionLocal
from app.models_db import RateLimitBucket, utcnow


_WINDOW_SECONDS = 60
_BYPASS_PATHS = frozenset({"/health"})


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until the oldest hit ages out (0 when allowed)
    limit: int


def classify_route(path: str) -> str:
    """Map an HTTP path onto a route class. Kept as a free function so tests
    can assert on it directly."""
    if path.startswith("/auth/"):
        return "auth"
    if path == "/ask" or path.startswith("/ask/"):
        return "ask"
    return "default"


def _limit_for(route_class: str) -> int:
    """Phase E — env wins. We re-read the raw env on every request because
    integration tests rotate the limit via ``monkeypatch.setenv`` between
    calls and ``Settings`` is cached behind ``@lru_cache``. The settings
    object is still the source of truth for defaults — env overrides only
    when explicitly set."""
    import os

    settings = get_settings()
    env_key = {
        "auth": "RATE_LIMIT_AUTH_PER_MIN",
        "ask": "RATE_LIMIT_ASK_PER_MIN",
        "default": "RATE_LIMIT_DEFAULT_PER_MIN",
    }[route_class]
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return {
        "auth": settings.rate_limit_auth_per_min,
        "ask": settings.rate_limit_ask_per_min,
        "default": settings.rate_limit_default_per_min,
    }[route_class]


def check_and_record(
    db: Session,
    *,
    subject: str,
    route_class: str,
    now: float | None = None,
) -> RateLimitDecision:
    """Atomically: trim → check → append. Returns the decision the caller
    must honour. Caller commits the surrounding transaction."""
    limit = _limit_for(route_class)
    if limit <= 0:
        return RateLimitDecision(allowed=True, remaining=0, retry_after=0, limit=limit)

    now = float(now if now is not None else time.time())
    cutoff = now - _WINDOW_SECONDS

    row = db.scalar(
        select(RateLimitBucket).where(
            RateLimitBucket.subject == subject,
            RateLimitBucket.route_class == route_class,
        )
    )
    try:
        hits = json.loads(row.hits_json) if row else []
        if not isinstance(hits, list):
            hits = []
    except (json.JSONDecodeError, TypeError):
        hits = []
    hits = [t for t in hits if isinstance(t, (int, float)) and t >= cutoff]

    if len(hits) >= limit:
        # Oldest hit determines retry-after: as soon as it ages out, the
        # caller has one slot back.
        oldest = min(hits)
        retry_after = max(1, int(_WINDOW_SECONDS - (now - oldest)))
        _persist(db, row, subject, route_class, hits)
        return RateLimitDecision(
            allowed=False, remaining=0, retry_after=retry_after, limit=limit
        )

    hits.append(now)
    _persist(db, row, subject, route_class, hits)
    return RateLimitDecision(
        allowed=True, remaining=max(0, limit - len(hits)), retry_after=0, limit=limit
    )


def _persist(
    db: Session,
    row: RateLimitBucket | None,
    subject: str,
    route_class: str,
    hits: list[float],
) -> None:
    serialised = json.dumps(hits)
    if row is None:
        db.add(
            RateLimitBucket(
                subject=subject,
                route_class=route_class,
                hits_json=serialised,
                updated_at=utcnow(),
            )
        )
    else:
        row.hits_json = serialised
        row.updated_at = utcnow()
    db.flush()


def _bearer_subject(headers: Headers) -> str | None:
    header = headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        claims = decode_access_token(token)
    except InvalidTokenError:
        return None
    return f"user:{claims.sub}"


def _ip_subject(scope: Scope) -> str:
    client = scope.get("client")
    host = client[0] if client else "unknown"
    return f"ip:{host}"


def _decide(scope: Scope) -> RateLimitDecision | None:
    """Open a short-lived session, run the bucket math, close it. Returning
    ``None`` means we couldn't decide and should fail-open."""
    headers = Headers(scope=scope)
    subject = _bearer_subject(headers) or _ip_subject(scope)
    route_class = classify_route(scope["path"])
    db = SessionLocal()
    try:
        decision = check_and_record(db, subject=subject, route_class=route_class)
        db.commit()
        return decision
    except Exception:
        db.rollback()
        return None
    finally:
        db.close()


class RateLimitMiddleware:
    """Pure-ASGI sliding-window rate limiter."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS" or scope["path"] in _BYPASS_PATHS:
            await self.app(scope, receive, send)
            return

        decision = _decide(scope)
        if decision is None:
            await self.app(scope, receive, send)
            return

        if not decision.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please slow down.",
                    "route_class": classify_route(scope["path"]),
                    "limit_per_min": decision.limit,
                },
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            await response(scope, receive, send)
            return

        limit_bytes = str(decision.limit).encode("ascii")
        remaining_bytes = str(decision.remaining).encode("ascii")

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Drop any existing rate-limit headers so the downstream
                # values win (defensive — handlers rarely set these).
                lowered = {k.lower(): i for i, (k, _) in enumerate(headers)}
                for name, value in (
                    (b"x-ratelimit-limit", limit_bytes),
                    (b"x-ratelimit-remaining", remaining_bytes),
                ):
                    if name in lowered:
                        headers[lowered[name]] = (name, value)
                    else:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)
