"""TOTP (RFC 6238) MFA + recovery codes.

The TOTP secret is stored in `users.mfa_secret` for now; Phase E adds
AES-GCM encryption at rest under APP_ENCRYPTION_KEY. Recovery codes are
SHA-256 hashed and stored in the same column as a JSON blob alongside the
secret — keeps the schema small until/unless we need a dedicated table.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

import pyotp


ISSUER = "GlassBox"
RECOVERY_CODE_COUNT = 10


@dataclass(frozen=True)
class EnrollmentChallenge:
    secret: str  # plaintext, shown once during setup
    provisioning_uri: str  # encode into a QR client-side


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def verify_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


def generate_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [secrets.token_hex(5).upper() for _ in range(n)]  # e.g. "A1B2C3D4E5"


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def pack_secret(secret: str, recovery_hashes: list[str]) -> str:
    """Encode TOTP secret + recovery-code hashes into the single mfa_secret
    column. JSON keeps it grep-able locally; encryption arrives in Phase E."""
    return json.dumps({"secret": secret, "recovery": list(recovery_hashes)})


def unpack_secret(blob: str | None) -> tuple[str | None, list[str]]:
    if not blob:
        return None, []
    try:
        data = json.loads(blob)
    except (TypeError, ValueError):
        # Legacy form before recovery codes existed: raw base32 secret.
        return blob, []
    return data.get("secret"), list(data.get("recovery", []))


def consume_recovery_code(blob: str | None, attempt: str) -> tuple[bool, str | None]:
    """If `attempt` matches an unused recovery code, return (True, new_blob)
    with that code removed. Otherwise (False, blob)."""
    secret, codes = unpack_secret(blob)
    h = hash_recovery_code(attempt)
    if h not in codes:
        return False, blob
    remaining = [c for c in codes if c != h]
    return True, pack_secret(secret or "", remaining)
