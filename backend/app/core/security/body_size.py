"""Body-size middleware.

Reject oversized request bodies before they hit a handler — both as a
defence against memory blow-ups on `/ask` (256 KB cap) and as a generic
sanity bound on the rest of the API (1 MB).

Why a pure ASGI middleware instead of Starlette's ``BaseHTTPMiddleware``?
We need to *replace* the receive channel so downstream handlers can still
parse the body we already inspected. ``BaseHTTPMiddleware`` doesn't expose
a hook for that — it instantiates its own ``Request`` object whose receive
callable is wired before we can intercept. The straightforward fix is to
operate at the ASGI layer directly: read the body, decide, and either
reject early or re-emit it via a wrapping receive callable.

Limits are route-class scoped via ``classify_route`` in ``rate_limit``.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.core.security.rate_limit import classify_route


_SKIP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})


def _max_bytes_for(path: str) -> int:
    settings = get_settings()
    if classify_route(path) == "ask":
        return settings.body_max_bytes_ask
    return settings.body_max_bytes_default


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in _SKIP_METHODS:
            await self.app(scope, receive, send)
            return

        cap = _max_bytes_for(scope["path"])

        # Fast path: trust Content-Length when present and outrageous.
        headers = Headers(raw=scope["headers"])
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > cap:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds {cap} bytes."},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                # Malformed header — fall through to the streaming check.
                pass

        # Slow path: bound the actual byte stream. We buffer the whole body
        # ourselves (capped at `cap`) and then replay it through a wrapping
        # receive channel so the inner ASGI app reads it once.
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                # Forward disconnects / unknown messages untouched.
                continue
            body += message.get("body") or b""
            if len(body) > cap:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {cap} bytes."},
                )
                await response(scope, receive, send)
                return
            more_body = message.get("more_body", False)

        sent = False

        async def wrapped_receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            # After our replay, forward to the underlying ASGI receive so
            # the handler still observes real disconnects (StreamingResponse
            # uses this to detect client teardown — synthesising a fake
            # disconnect here would tear the stream down prematurely).
            return await receive()

        await self.app(scope, wrapped_receive, send)
