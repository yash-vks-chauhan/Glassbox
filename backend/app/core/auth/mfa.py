"""TOTP (RFC 6238) MFA + recovery codes.

`users.mfa_secret` holds one JSON blob with the TOTP secret and the SHA-256
hashes of the unused recovery codes. The blob is encrypted at rest with
AES-GCM under APP_ENCRYPTION_KEY and bound to the user id through the
associated data, so a ciphertext copied onto another user's row won't open:

    enc:v1:<kid>:<base64(nonce || ciphertext || tag)>

Rows written before encryption hold the plain JSON (or, oldest, a bare
base32 secret). They are still read, re-encrypted on their next write, and
`scripts/encrypt_mfa_secrets.py` converts them in one pass.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

import pyotp
import structlog

from app.core.security.encryption import EncryptionError, decrypt, encrypt


_ENCRYPTED_PREFIX = "enc:v1:"
_log = structlog.get_logger(__name__)


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


def _aad(user_id: str) -> bytes:
    return f"mfa:{user_id}".encode("utf-8")


def is_encrypted(blob: str | None) -> bool:
    return bool(blob) and blob.startswith(_ENCRYPTED_PREFIX)


def pack_secret(secret: str, recovery_hashes: list[str], *, user_id: str) -> str:
    """Encrypt the TOTP secret + recovery-code hashes for `users.mfa_secret`."""
    payload = json.dumps({"secret": secret, "recovery": list(recovery_hashes)})
    blob = encrypt(payload, aad=_aad(user_id))
    return f"{_ENCRYPTED_PREFIX}{blob.kid}:{blob.ciphertext_b64}"


def unpack_secret(blob: str | None, *, user_id: str) -> tuple[str | None, list[str]]:
    """Return (totp_secret, recovery_hashes). A blob that can't be decrypted
    (wrong key, or copied from another user) yields (None, []), so MFA simply
    fails instead of erroring."""
    if not blob:
        return None, []
    if is_encrypted(blob):
        kid, _, ciphertext = blob[len(_ENCRYPTED_PREFIX):].partition(":")
        try:
            payload = decrypt(ciphertext, aad=_aad(user_id), kid=kid or None)
        except EncryptionError:
            _log.warning(
                "mfa_secret_undecryptable",
                user_id=user_id,
                kid=kid,
                hint="list the retired key in APP_ENCRYPTION_PREVIOUS_KEYS",
            )
            return None, []
    else:
        payload = blob  # written before encryption at rest
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        # Oldest form, before recovery codes existed: a bare base32 secret.
        return payload, []
    return data.get("secret"), list(data.get("recovery", []))


def consume_recovery_code(
    blob: str | None, attempt: str, *, user_id: str
) -> tuple[bool, str | None]:
    """If `attempt` matches an unused recovery code, return (True, new_blob)
    with that code removed. Otherwise (False, blob)."""
    secret, codes = unpack_secret(blob, user_id=user_id)
    h = hash_recovery_code(attempt)
    if h not in codes:
        return False, blob
    remaining = [c for c in codes if c != h]
    return True, pack_secret(secret or "", remaining, user_id=user_id)
