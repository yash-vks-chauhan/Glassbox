"""Symmetric AES-GCM encryption used by the BYO-key store.

Per Phase E we never persist a BYO key in plaintext. The format on disk is
``base64(nonce || ciphertext || tag)`` where:

- ``nonce`` is a random 12-byte sequence — must be unique per encryption.
- ``ciphertext`` is the AES-GCM body (same length as plaintext).
- ``tag`` is the 16-byte GCM auth tag, included in the AEAD output.

We accept ``APP_ENCRYPTION_KEY`` as either:

- raw URL-safe base64 (32 bytes after decode), or
- raw UTF-8 (we SHA-256 it down to 32 bytes — useful for dev where the env
  default is human-readable and not exactly 32 bytes).

A dedicated ``EncryptionError`` is raised on decrypt failure (tag mismatch,
short payload, missing key version) so callers can map it to a 400 cleanly
without leaking why a particular blob couldn't be opened.

Key rotation: every ciphertext is stored next to the ``kid`` (key id) that
encrypted it. To rotate, set a new ``APP_ENCRYPTION_KEY`` + bump
``APP_ENCRYPTION_KID`` and list the retired key in
``APP_ENCRYPTION_PREVIOUS_KEYS`` (``kid:key`` pairs) so existing rows keep
decrypting; re-encrypt at leisure, then drop the old entry. The kid isn't
authenticated by GCM, so it only picks which key to try first. Outside
production mode the published dev default key is also tried last, so a local
rotation can't lock anyone out of their MFA.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings, get_settings


_NONCE_BYTES = 12
_KEY_BYTES = 32


class EncryptionError(Exception):
    """Raised when a ciphertext fails to decrypt or is malformed."""


@dataclass(frozen=True)
class EncryptedBlob:
    ciphertext_b64: str
    kid: str


def _derive_key(material: str) -> bytes:
    """Accept either a 32-byte URL-safe-base64 string or arbitrary UTF-8 and
    return 32 bytes. We SHA-256 anything that doesn't decode cleanly so dev
    defaults are usable without forcing operators to pre-hash."""
    if not material:
        raise EncryptionError("APP_ENCRYPTION_KEY is empty — refusing to encrypt.")
    try:
        raw = base64.urlsafe_b64decode(material + "=" * (-len(material) % 4))
    except (ValueError, TypeError):
        raw = b""
    if len(raw) == _KEY_BYTES:
        return raw
    return hashlib.sha256(material.encode("utf-8")).digest()


def _aead() -> tuple[AESGCM, str]:
    settings = get_settings()
    key = _derive_key(settings.app_encryption_key)
    return AESGCM(key), settings.app_encryption_kid


def _keyring() -> list[tuple[str, bytes]]:
    """Every key that may open existing ciphertext, current key first."""
    settings = get_settings()
    ring = [(settings.app_encryption_kid, _derive_key(settings.app_encryption_key))]
    for entry in settings.app_encryption_previous_keys.split(","):
        kid, sep, material = entry.strip().partition(":")
        if sep and kid and material:
            ring.append((kid, _derive_key(material)))
    if not settings.production_mode:
        dev_key = _derive_key(Settings.model_fields["app_encryption_key"].default)
        if all(key != dev_key for _, key in ring):
            ring.append(("dev-default", dev_key))
    return ring


def encrypt(plaintext: str, *, aad: bytes | None = None) -> EncryptedBlob:
    """Encrypt ``plaintext`` with AES-GCM. ``aad`` is optional associated
    data — pass e.g. ``b"byo_key:<user_id>"`` to tightly bind the ciphertext
    to its owner. We ship the kid out-of-band because GCM doesn't carry it."""
    if not plaintext:
        raise EncryptionError("refusing to encrypt empty plaintext")
    aead, kid = _aead()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    body = aead.encrypt(nonce, plaintext.encode("utf-8"), aad)
    payload = nonce + body
    return EncryptedBlob(
        ciphertext_b64=base64.urlsafe_b64encode(payload).decode("ascii"),
        kid=kid,
    )


def decrypt(
    ciphertext_b64: str, *, aad: bytes | None = None, kid: str | None = None
) -> str:
    """Reverse of ``encrypt``. ``kid`` (when the caller stored one) is tried
    first. Raises ``EncryptionError`` when no known key opens the blob."""
    try:
        payload = base64.urlsafe_b64decode(ciphertext_b64)
    except (ValueError, TypeError) as exc:
        raise EncryptionError(f"ciphertext is not valid base64: {exc}") from exc
    if len(payload) < _NONCE_BYTES + 16:
        raise EncryptionError("ciphertext too short — missing nonce or tag")
    nonce, body = payload[:_NONCE_BYTES], payload[_NONCE_BYTES:]
    candidates = sorted(_keyring(), key=lambda item: item[0] != kid)
    for _, key in candidates:
        try:
            return AESGCM(key).decrypt(nonce, body, aad).decode("utf-8")
        except Exception:  # InvalidTag: wrong key or tampered payload
            continue
    raise EncryptionError("decryption failed (tag mismatch or wrong key)")


def safe_last4(plaintext: str) -> str:
    """Return the last 4 characters of a key for display purposes. Never
    log/return more — that's leakable surface area."""
    if not plaintext or len(plaintext) < 4:
        return ""
    return plaintext[-4:]


def _self_test() -> None:
    """Smoke test invoked from CLI: encrypt+decrypt a known string."""
    blob = encrypt("hello world")
    assert decrypt(blob.ciphertext_b64) == "hello world"
    print(f"OK kid={blob.kid} cipher_len={len(blob.ciphertext_b64)}")


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("APP_ENCRYPTION_KEY", "dev-test-key")
    _self_test()
