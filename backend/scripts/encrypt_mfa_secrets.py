"""Encrypt MFA secrets that were stored before encryption at rest.

Usage (from backend/):
    PYTHONPATH=. python -m scripts.encrypt_mfa_secrets --dry-run
    PYTHONPATH=. python -m scripts.encrypt_mfa_secrets

Every plaintext ``users.mfa_secret`` is rewritten as an AES-GCM blob bound to
its user id. Rows that are already encrypted are skipped, so re-running is
safe. Afterwards keep APP_ENCRYPTION_KEY stable, or list the retired key in
APP_ENCRYPTION_PREVIOUS_KEYS when rotating it.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.auth import mfa
from app.db import SessionLocal
from app.models_db import User


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Encrypt MFA secrets stored before encryption at rest."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change without writing"
    )
    args = parser.parse_args(argv)

    converted = 0
    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.mfa_secret.is_not(None))).all()
        for user in users:
            if mfa.is_encrypted(user.mfa_secret):
                continue
            secret, recovery = mfa.unpack_secret(user.mfa_secret, user_id=user.id)
            if not secret:
                continue
            converted += 1
            if not args.dry_run:
                user.mfa_secret = mfa.pack_secret(secret, recovery, user_id=user.id)
        if not args.dry_run:
            db.commit()

    verb = "Would encrypt" if args.dry_run else "Encrypted"
    print(f"{verb} {converted} MFA secret(s); {len(users) - converted} already encrypted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
