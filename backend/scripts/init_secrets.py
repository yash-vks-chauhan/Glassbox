"""Generate per-environment secrets and emit them as env-file lines.

Usage:
    PYTHONPATH=. python scripts/init_secrets.py >> ../.env

We always emit fresh values — *never* reuse Phase E keys across environments.
The output is deliberately a simple env file because that's the deployment
surface for the local-first phase; production swaps in AWS Secrets
Manager / Vault by reading the same env names from a different source.

Each invocation produces:

- ``JWT_SIGNING_KEY`` — 64 bytes (URL-safe base64) for HS256 token signing.
- ``JWT_ACTIVE_KID``  — rotation slot. We just stamp a fresh ``dev-<hex>``
  so old tokens issued under the previous kid are still decodable until
  their TTL expires, while new ones carry the new kid.
- ``APP_ENCRYPTION_KEY`` — 32-byte URL-safe base64. AES-GCM key used by the
  BYO-key store. ``backend.app.core.security.encryption`` will also accept
  arbitrary UTF-8 (SHA-256'd down to 32 bytes), but emitting real raw
  material here means the operator's env *is* the key, no derivation.
- ``APP_ENCRYPTION_KID`` — matching kid for the encryption key. Rotated
  independently from the JWT kid.
- ``COOKIE_SECRET`` — reserved for downstream signed-cookie use (currently
  unused; emitted now so rotation flows are uniform).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone


def main() -> None:
    jwt_kid = "dev-" + secrets.token_hex(3)
    enc_kid = "enc-" + secrets.token_hex(3)
    lines = [
        f"# generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"JWT_SIGNING_KEY={secrets.token_urlsafe(64)}",
        f"JWT_ACTIVE_KID={jwt_kid}",
        f"APP_ENCRYPTION_KEY={secrets.token_urlsafe(32)}",
        f"APP_ENCRYPTION_KID={enc_kid}",
        f"COOKIE_SECRET={secrets.token_urlsafe(32)}",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
