"""Auth core — Phase B of docs/SECURITY-IMPLEMENTATION.md.

Split by concern so each piece stays testable in isolation:

- passwords: Argon2id hash/verify + weak-password rejection.
- tokens:    JWT access tokens + opaque refresh tokens (hashed-at-rest).
- mfa:       TOTP secrets, recovery codes.
- email:     dev EmailService that writes .eml files; pluggable for SES later.
- service:   high-level flows (login, refresh+rotate, logout, reset, invite).

Routers (app/routers/auth.py) call into `service` only.
"""
