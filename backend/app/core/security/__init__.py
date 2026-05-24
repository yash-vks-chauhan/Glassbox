"""Phase E hardening primitives.

Sub-modules:

- ``headers`` — security-headers ASGI middleware (HSTS / nosniff / CSP / etc).
- ``rate_limit`` — persistent sliding-window rate limit middleware.
- ``encryption`` — AES-GCM helpers used by the BYO-key store.
- ``audit_hash`` — canonical-JSON + hash-chain helpers for the audit log.
- ``logging`` — structlog configuration + key redaction.
"""
