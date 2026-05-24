"""Security-headers middleware.

Applies the same set of hardening headers to every response leaving the
backend. Headers chosen per Phase E of docs/SECURITY-IMPLEMENTATION.md:

- ``Strict-Transport-Security`` — long max-age, includeSubDomains. Only
  meaningful behind TLS; harmless over HTTP-localhost.
- ``X-Content-Type-Options: nosniff`` — stops MIME sniffing.
- ``X-Frame-Options: DENY`` — blanket clickjacking guard. CSP
  ``frame-ancestors`` does this too on modern browsers; keep both for the
  long tail.
- ``Referrer-Policy: no-referrer`` — we never want client tokens or query
  strings leaking via Referer to third-party sites.
- ``Content-Security-Policy`` — minimal: self-origin only.
- ``Cross-Origin-Opener-Policy: same-origin`` — process isolation.
- ``Cross-Origin-Resource-Policy: same-site`` — defends against Spectre-class
  side-channels.
- ``Permissions-Policy: ()`` — turn off all opt-in browser features.

Pure-ASGI implementation. We did try ``BaseHTTPMiddleware`` originally but
it breaks ``StreamingResponse`` (Starlette issue #472): the SSE endpoint
``/ask/stream`` raises ``RuntimeError: No response returned`` inside the
middleware chain. Operating at the ASGI layer dodges that entirely — we
just splice extra headers into the ``http.response.start`` message.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings


def _headers_for(scope: Scope) -> list[tuple[bytes, bytes]]:
    settings = get_settings()
    pairs: list[tuple[bytes, bytes]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"cross-origin-resource-policy", b"same-site"),
        (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
        (b"content-security-policy", settings.content_security_policy.encode("utf-8")),
    ]
    # HSTS only when production-mode is true *and* the request looks like
    # HTTPS — over plain HTTP it's a no-op but emitting it would mislead
    # operators into thinking transport is secured.
    if settings.production_mode and scope.get("scheme") == "https":
        pairs.append(
            (
                b"strict-transport-security",
                f"max-age={settings.hsts_max_age_seconds}; includeSubDomains".encode("utf-8"),
            )
        )
    return pairs


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        extra = _headers_for(scope)
        existing_lower = set()

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing_lower.update(k.lower() for k, _ in headers)
                for key, value in extra:
                    if key not in existing_lower:
                        headers.append((key, value))
                        existing_lower.add(key)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped_send)
