from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import assert_secrets_safe_for_mode, get_settings
from app.core.security.body_size import BodySizeLimitMiddleware
from app.core.security.headers import SecurityHeadersMiddleware
from app.core.security.logging import RequestContextMiddleware, configure_logging
from app.core.security.rate_limit import RateLimitMiddleware
from app.db import init_db
from app.routers import (
    admin_users,
    ask,
    audit,
    auth,
    byo_keys,
    clients,
    determinism,
    escalations,
    llm_status,
    metrics,
    models,
)


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    # Refuse to start in production mode if any secret still equals its dev
    # default. Raising here aborts uvicorn before any request is served, which
    # is exactly what we want — a silent boot with `dev-insecure-…` would let
    # an attacker forge JWTs and decrypt BYO keys using values in the repo.
    assert_secrets_safe_for_mode(settings)
    init_db()
    yield


app = FastAPI(title="GlassBox", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware order matters. Starlette runs them in *reverse* of the add order,
# so the *last* `add_middleware` call is the outermost layer. We want:
#   outer -> request-context (so logs/redact wrap everything)
#         -> CORS (so preflights short-circuit before auth-sensitive layers)
#         -> security headers (added to every response)
#         -> rate limit (cheap reject before we touch the body)
#         -> body-size (cheap reject before handler)
#         -> handler
# That means we add them in the inverse order below.
# ---------------------------------------------------------------------------


app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS: explicit single origin (or comma-separated list via FRONTEND_ORIGIN),
# credentials allowed so the refresh cookie travels, methods limited to those
# the API actually serves. Replaces the wildcard from Phase A.
_origins = [o.strip() for o in settings.frontend_origin.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Tenant-Slug",
    ],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    max_age=600,
)

# Outermost: request id + structlog contextvars. Has to wrap CORS so the
# OPTIONS preflight is also tagged with a request_id in logs.
app.add_middleware(RequestContextMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(ask.router)
app.include_router(audit.router)
app.include_router(byo_keys.router)
app.include_router(clients.router)
app.include_router(escalations.router)
app.include_router(metrics.router)
app.include_router(determinism.router)
app.include_router(llm_status.router)
app.include_router(models.router)
app.include_router(admin_users.router)
app.include_router(admin_users.self_router)
