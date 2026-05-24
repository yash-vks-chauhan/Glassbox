"""Structured logging primitives for Phase E.

We use ``structlog`` configured to emit JSON in production (one event per
line) and a pretty console renderer in dev. Three pieces matter:

1. Every event carries ``request_id`` / ``tenant_id`` / ``user_id`` when
   available — populated by the request-context middleware.
2. A redaction processor strips known secret keys (passwords, tokens, BYO
   keys, the full IPS body, etc.) before serialisation.
3. ``log_security_event`` writes both a structured log line *and* a
   persisted ``security_events`` row so auditors can query history.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.models_db import SecurityEvent


_request_id_var: ContextVar[str | None] = ContextVar("glassbox_request_id", default=None)
_tenant_id_var: ContextVar[str | None] = ContextVar("glassbox_tenant_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("glassbox_user_id", default=None)


def set_request_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    if request_id is not None:
        _request_id_var.set(request_id)
    if tenant_id is not None:
        _tenant_id_var.set(tenant_id)
    if user_id is not None:
        _user_id_var.set(user_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


def get_tenant_id() -> str | None:
    return _tenant_id_var.get()


def get_user_id() -> str | None:
    return _user_id_var.get()


def _bind_request_context(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    rid = _request_id_var.get()
    tid = _tenant_id_var.get()
    uid = _user_id_var.get()
    if rid is not None and "request_id" not in event_dict:
        event_dict["request_id"] = rid
    if tid is not None and "tenant_id" not in event_dict:
        event_dict["tenant_id"] = tid
    if uid is not None and "user_id" not in event_dict:
        event_dict["user_id"] = uid
    return event_dict


def _redact(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    keys = get_settings().redact_key_set
    return _redact_mapping(event_dict, keys)


def _redact_mapping(obj: Any, keys: set[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.lower() in keys:
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact_mapping(value, keys)
        return out
    if isinstance(obj, list):
        return [_redact_mapping(item, keys) for item in obj]
    return obj


_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.production_mode
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _bind_request_context,
            _redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str = "glassbox") -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


class RequestContextMiddleware:
    """Generate a request_id and populate the structlog contextvars.

    Tenant/user id are filled later by ``current_user`` (the auth dep is the
    only thing with access to the verified bearer). The middleware just
    seeds the request_id and writes it back on the response so clients can
    correlate. Pure-ASGI so we don't trip the ``BaseHTTPMiddleware`` +
    ``StreamingResponse`` interaction bug (Starlette #472).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or uuid4().hex
        token_request = _request_id_var.set(request_id)
        token_tenant = _tenant_id_var.set(None)
        token_user = _user_id_var.set(None)

        request_id_bytes = request_id.encode("ascii")

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                if not any(k.lower() == b"x-request-id" for k, _ in hdrs):
                    hdrs.append((b"x-request-id", request_id_bytes))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            _request_id_var.reset(token_request)
            _tenant_id_var.reset(token_tenant)
            _user_id_var.reset(token_user)


def log_security_event(
    db: Session,
    *,
    kind: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Persist a security event row *and* emit a structured log line.

    Both surfaces are deliberately redundant: the structured log feeds an
    operator's grep / SIEM, the DB row gives auditors a queryable history
    bound to the tenant.
    """
    db.add(
        SecurityEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            metadata_json=json.dumps(metadata) if metadata else None,
        )
    )
    get_logger("security").info(
        "security_event",
        kind=kind,
        tenant_id=tenant_id,
        user_id=user_id,
        ip=ip,
        metadata=metadata or {},
    )
