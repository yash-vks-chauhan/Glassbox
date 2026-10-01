from __future__ import annotations

import json

from sqlalchemy import delete, select

from app.core.auth import mfa
from app.core.auth.passwords import hash_password
from app.db import SessionLocal, init_db
from app.models_db import DEMO_TENANT_ID, RateLimitBucket, User


PASSWORD = "Phase-F-Sup3rSecur3!"
ADMIN_MFA_SECRET = "JBSWY3DPEHPK3PXP"

USERS = {
    "advisor": "e2e-phasef-advisor@example.com",
    "admin": "e2e-phasef-admin@example.com",
}


def upsert_user(*, email: str, role: str, mfa_enrolled: bool = False) -> None:
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.tenant_id == DEMO_TENANT_ID, User.email == email)
        )
        if user is None:
            user = User(
                tenant_id=DEMO_TENANT_ID,
                email=email,
                password_hash=hash_password(PASSWORD),
                role=role,
                display_name=f"Phase F {role.title()}",
                email_verified=True,
            )
            db.add(user)
            db.flush()  # assigns user.id, which the MFA ciphertext is bound to
        else:
            user.password_hash = hash_password(PASSWORD)
            user.role = role
            user.email_verified = True
            user.locked_until = None
            user.failed_login_count = 0
        if mfa_enrolled:
            user.mfa_enrolled = True
            user.mfa_secret = mfa.pack_secret(ADMIN_MFA_SECRET, [], user_id=user.id)
        else:
            user.mfa_enrolled = False
            user.mfa_secret = None
        db.commit()


def main() -> None:
    init_db()
    with SessionLocal() as db:
        db.execute(delete(RateLimitBucket))
        db.commit()
    upsert_user(email=USERS["advisor"], role="advisor")
    upsert_user(email=USERS["admin"], role="admin", mfa_enrolled=True)
    print(
        json.dumps(
            {
                "tenant_slug": "demo",
                "password": PASSWORD,
                "advisor_email": USERS["advisor"],
                "admin_email": USERS["admin"],
                "admin_mfa_secret": ADMIN_MFA_SECRET,
            }
        )
    )


if __name__ == "__main__":
    main()
