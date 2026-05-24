"""Phase B acceptance tests — auth flows.

Coverage from docs/SECURITY-IMPLEMENTATION.md, Phase B "Done when":

- login → refresh → logout works.
- Refresh-token rotation: each refresh issues a new token; reuse of an
  old refresh revokes the whole family.
- Lockout fires after LOGIN_MAX_FAILED_ATTEMPTS bad passwords.
- MFA happy + sad path; recovery codes consume.
- MFA enrollment is required for admin / owner before they can complete login.
- Password reset: token works exactly once; weak passwords rejected.
- Invite + accept-invite creates a tenant-scoped user.
- No email enumeration: /auth/forgot always 200; /auth/login uses the same
  generic error for unknown email vs wrong password.

These tests drive the FastAPI app via TestClient and a *fresh* SessionLocal
so they share the live SQLite DB with the Phase A migration. Each test
cleans up the users / tokens it creates.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth import mfa as mfa_mod
from app.core.auth.tokens import (
    decode_access_token,
    hash_refresh_token,
    issue_access_token,
)
from app.db import SessionLocal, engine
from app.main import app
from app.models_db import (
    DEMO_TENANT_ID,
    PasswordReset,
    RefreshToken,
    SecurityEvent,
    Tenant,
    User,
    UserInvitation,
)
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _wipe_rate_limit_buckets() -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM rate_limit_buckets"))


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    # Keep the dev mail directory inside the pytest tmp so tests don't write
    # to /tmp across runs.
    monkeypatch.setenv("DEV_MAIL_DIR", str(tmp_path / "mail"))
    monkeypatch.setenv("GLASSBOX_LOCAL_LLM", "1")
    monkeypatch.setenv("LOGIN_MAX_FAILED_ATTEMPTS", "5")
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "15")
    # Phase E — auth endpoints sit in the strict (10/min) tier. The lockout
    # test alone fires 6 logins; we don't want the rate limiter to mask the
    # behaviour under test, so bump the caps for the auth suite.
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_ASK_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "1000")
    get_settings.cache_clear()
    _wipe_rate_limit_buckets()
    yield
    _wipe_rate_limit_buckets()
    get_settings.cache_clear()
    _wipe_test_users()


def _wipe_test_users() -> None:
    """Delete any users/tokens/invitations our tests created so re-runs are
    deterministic. We key on a prefix so we never touch real data."""
    raw = sqlite3.connect(engine.url.database)
    try:
        # Find user ids whose email starts with "test+" — that's our convention.
        user_ids = [
            r[0]
            for r in raw.execute(
                "SELECT id FROM users WHERE email LIKE 'test+%'"
            )
        ]
        if user_ids:
            placeholders = ",".join("?" * len(user_ids))
            raw.execute(
                f"DELETE FROM refresh_tokens WHERE user_id IN ({placeholders})",
                user_ids,
            )
            raw.execute(
                f"DELETE FROM password_resets WHERE user_id IN ({placeholders})",
                user_ids,
            )
            raw.execute(
                f"DELETE FROM security_events WHERE user_id IN ({placeholders})",
                user_ids,
            )
            raw.execute(
                f"DELETE FROM users WHERE id IN ({placeholders})", user_ids
            )
        raw.execute("DELETE FROM user_invitations WHERE email LIKE 'test+%'")
        raw.commit()
    finally:
        raw.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _make_user(
    *,
    role: str = "advisor",
    password: str = "Sup3rSecur3-Pass!",
    email: str | None = None,
    mfa_enrolled: bool = False,
    mfa_secret: str | None = None,
) -> User:
    email = email or f"test+{uuid4().hex[:10]}@example.com"
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=DEMO_TENANT_ID,
            email=email,
            password=password,
            role=role,
            display_name="Phase B Test",
            email_verified=True,
        )
        if mfa_enrolled:
            secret = mfa_secret or mfa_mod.generate_secret()
            user.mfa_secret = mfa_mod.pack_secret(secret, [])
            user.mfa_enrolled = True
        db.commit()
        db.refresh(user)
        # Detach from the closing session.
        db.expunge(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = issue_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Login: happy path
# ---------------------------------------------------------------------------


def test_login_returns_access_token_and_sets_refresh_cookie(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    settings = get_settings()

    res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_ttl_seconds

    # Access token decodes and carries the right tenant + role.
    claims = decode_access_token(body["access_token"])
    assert claims.sub == user.id
    assert claims.tid == DEMO_TENANT_ID
    assert claims.role == "advisor"

    # Refresh cookie set, HttpOnly, path=/auth.
    refresh_cookie = res.cookies.get(settings.refresh_cookie_name)
    assert refresh_cookie, "refresh cookie should be set"
    set_cookie_header = res.headers["set-cookie"].lower()
    assert "httponly" in set_cookie_header
    assert "path=/auth" in set_cookie_header
    assert "samesite=lax" in set_cookie_header


# ---------------------------------------------------------------------------
# Login: generic error + no enumeration
# ---------------------------------------------------------------------------


def test_unknown_email_and_wrong_password_use_identical_error(client):
    user = _make_user(password="Sup3rSecur3-Pass!")

    wrong_pw = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": "totally-wrong-passw0rd!",
            "tenant_slug": "demo",
        },
    )
    unknown = client.post(
        "/auth/login",
        json={
            "email": "test+nobody@example.com",
            "password": "totally-wrong-passw0rd!",
            "tenant_slug": "demo",
        },
    )

    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


def test_forgot_password_always_returns_200_even_for_unknown_email(client):
    for email in ("test+nobody@example.com", "test+anothernobody@example.com"):
        res = client.post(
            "/auth/forgot", json={"email": email, "tenant_slug": "demo"}
        )
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Brute-force lockout
# ---------------------------------------------------------------------------


def test_lockout_after_max_failed_attempts(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    settings = get_settings()

    for _ in range(settings.login_max_failed_attempts):
        res = client.post(
            "/auth/login",
            json={
                "email": user.email,
                "password": "wrong-Pass-w0rd!",
                "tenant_slug": "demo",
            },
        )
        assert res.status_code == 401

    # Next attempt — even with the CORRECT password — is locked.
    res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    assert res.status_code == 423, res.text

    with SessionLocal() as db:
        u = db.get(User, user.id)
        assert u.locked_until is not None
        locked = u.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        assert locked > datetime.now(timezone.utc)


def test_successful_login_clears_failure_counter(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)

    # Two bad attempts, then a good one.
    for _ in range(2):
        client.post(
            "/auth/login",
            json={
                "email": user.email,
                "password": "wrong-Pass-w0rd!",
                "tenant_slug": "demo",
            },
        )
    res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    assert res.status_code == 200

    with SessionLocal() as db:
        u = db.get(User, user.id)
        assert u.failed_login_count == 0
        assert u.locked_until is None
        assert u.last_login_at is not None


# ---------------------------------------------------------------------------
# Refresh + rotation
# ---------------------------------------------------------------------------


def test_refresh_rotates_token_and_returns_new_access(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)

    login_res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    refresh_cookie = login_res.cookies.get(get_settings().refresh_cookie_name)
    assert refresh_cookie

    res = client.post(
        "/auth/refresh",
        cookies={get_settings().refresh_cookie_name: refresh_cookie},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"] != login_res.json()["access_token"]

    new_cookie = res.cookies.get(get_settings().refresh_cookie_name)
    assert new_cookie and new_cookie != refresh_cookie

    # Old token is now revoked.
    with SessionLocal() as db:
        old_row = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(refresh_cookie)
            )
        )
        assert old_row is not None
        assert old_row.revoked_at is not None


def test_refresh_reuse_revokes_entire_family(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    cookie_name = get_settings().refresh_cookie_name

    login_res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    first_refresh = login_res.cookies.get(cookie_name)

    # Legitimate rotation.
    r1 = client.post("/auth/refresh", cookies={cookie_name: first_refresh})
    assert r1.status_code == 200
    second_refresh = r1.cookies.get(cookie_name)

    # Attacker replays the FIRST (now-revoked) refresh -> 401 + family burned.
    r2 = client.post("/auth/refresh", cookies={cookie_name: first_refresh})
    assert r2.status_code == 401

    # The legit current token is now also dead.
    r3 = client.post("/auth/refresh", cookies={cookie_name: second_refresh})
    assert r3.status_code == 401

    with SessionLocal() as db:
        active = db.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == user.id)
            .where(RefreshToken.revoked_at.is_(None))
        )
        assert active is None

        # And a security event was recorded.
        ev = db.scalar(
            select(SecurityEvent)
            .where(SecurityEvent.user_id == user.id)
            .where(SecurityEvent.kind == "refresh_reuse_detected")
        )
        assert ev is not None


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_revokes_refresh_and_clears_cookie(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    cookie_name = get_settings().refresh_cookie_name

    login_res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    refresh_cookie = login_res.cookies.get(cookie_name)

    res = client.post("/auth/logout", cookies={cookie_name: refresh_cookie})
    assert res.status_code == 204
    assert (
        f'{cookie_name}=""' in res.headers.get("set-cookie", "")
        or "max-age=0" in res.headers.get("set-cookie", "").lower()
    )

    # Refresh now fails.
    after = client.post("/auth/refresh", cookies={cookie_name: refresh_cookie})
    assert after.status_code == 401


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------


def test_admin_must_enroll_mfa_before_login_completes(client):
    pw = "Sup3rSecur3-Pass!"
    admin = _make_user(role="admin", password=pw)

    res = client.post(
        "/auth/login",
        json={"email": admin.email, "password": pw, "tenant_slug": "demo"},
    )
    assert res.status_code == 202
    assert res.json()["status"] == "mfa_enrollment_required"


def test_login_with_mfa_happy_path(client):
    import pyotp

    pw = "Sup3rSecur3-Pass!"
    secret = pyotp.random_base32()
    user = _make_user(password=pw, mfa_enrolled=True, mfa_secret=secret)
    cookie_name = get_settings().refresh_cookie_name

    # No mfa_code yet -> 202 challenge.
    challenge = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    assert challenge.status_code == 202
    assert challenge.json()["status"] == "mfa_required"
    assert challenge.json()["mfa_token"]

    # With a valid TOTP, login completes.
    code = pyotp.TOTP(secret).now()
    res = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": pw,
            "tenant_slug": "demo",
            "mfa_code": code,
        },
    )
    assert res.status_code == 200
    assert res.cookies.get(cookie_name)

    token_login = client.post(
        "/auth/login",
        json={"mfa_token": challenge.json()["mfa_token"], "mfa_code": code},
    )
    assert token_login.status_code == 200
    assert token_login.cookies.get(cookie_name)


def test_login_with_wrong_mfa_code_fails_generically(client):
    import pyotp

    pw = "Sup3rSecur3-Pass!"
    user = _make_user(
        password=pw, mfa_enrolled=True, mfa_secret=pyotp.random_base32()
    )

    res = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": pw,
            "tenant_slug": "demo",
            "mfa_code": "000000",
        },
    )
    assert res.status_code == 401


def test_mfa_enroll_then_verify_returns_recovery_codes(client, no_auth_override):
    import pyotp

    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)

    enroll = client.post("/auth/mfa/enroll", headers=_auth_headers(user))
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]
    assert enroll.json()["provisioning_uri"].startswith("otpauth://")

    code = pyotp.TOTP(secret).now()
    verify = client.post(
        "/auth/mfa/verify",
        json={"code": code},
        headers=_auth_headers(user),
    )
    assert verify.status_code == 200
    recovery = verify.json()["recovery_codes"]
    assert len(recovery) == mfa_mod.RECOVERY_CODE_COUNT
    assert all(isinstance(c, str) and len(c) == 10 for c in recovery)

    with SessionLocal() as db:
        u = db.get(User, user.id)
        assert u.mfa_enrolled is True


def test_recovery_code_consumes_once(client):
    import pyotp

    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    secret = pyotp.random_base32()
    # Enroll and grab recovery codes through the service layer.
    with SessionLocal() as db:
        u = db.get(User, user.id)
        u.mfa_secret = mfa_mod.pack_secret(secret, [])
        db.flush()
        recovery_plain = auth_service.complete_mfa_enrollment(
            db, user=u, code=pyotp.TOTP(secret).now()
        )
        db.commit()

    a_code = recovery_plain[0]

    # First use: succeeds, login completes.
    res1 = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": pw,
            "tenant_slug": "demo",
            "mfa_code": a_code,
        },
    )
    assert res1.status_code == 200

    # Second use of the same recovery code: fails.
    res2 = client.post(
        "/auth/login",
        json={
            "email": user.email,
            "password": pw,
            "tenant_slug": "demo",
            "mfa_code": a_code,
        },
    )
    assert res2.status_code == 401


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def test_password_reset_round_trip_and_invalidates_sessions(client):
    pw = "Sup3rSecur3-Pass!"
    user = _make_user(password=pw)
    cookie_name = get_settings().refresh_cookie_name

    # Existing session.
    login_res = client.post(
        "/auth/login",
        json={"email": user.email, "password": pw, "tenant_slug": "demo"},
    )
    refresh_cookie = login_res.cookies.get(cookie_name)
    assert refresh_cookie

    # Trigger reset; harvest the token straight from the DB (no email server).
    client.post(
        "/auth/forgot", json={"email": user.email, "tenant_slug": "demo"}
    )
    with SessionLocal() as db:
        row = db.scalar(
            select(PasswordReset)
            .where(PasswordReset.user_id == user.id)
            .order_by(PasswordReset.created_at.desc())
        )
        assert row is not None
    # We only have the hash in the DB; pull the plaintext from the latest .eml.
    plaintext_token = _read_latest_mail_token()

    new_pw = "Br4nd-New-Pass!"
    res = client.post(
        "/auth/reset", json={"token": plaintext_token, "new_password": new_pw}
    )
    assert res.status_code == 204

    # Old refresh dead.
    bad = client.post("/auth/refresh", cookies={cookie_name: refresh_cookie})
    assert bad.status_code == 401

    # Login with the new password works.
    good = client.post(
        "/auth/login",
        json={"email": user.email, "password": new_pw, "tenant_slug": "demo"},
    )
    assert good.status_code == 200


def test_password_reset_rejects_weak_password(client):
    user = _make_user(password="Sup3rSecur3-Pass!")
    client.post(
        "/auth/forgot", json={"email": user.email, "tenant_slug": "demo"}
    )
    token = _read_latest_mail_token()

    res = client.post(
        "/auth/reset", json={"token": token, "new_password": "password1234"}
    )
    assert res.status_code == 400


def test_password_reset_token_works_only_once(client):
    user = _make_user(password="Sup3rSecur3-Pass!")
    client.post(
        "/auth/forgot", json={"email": user.email, "tenant_slug": "demo"}
    )
    token = _read_latest_mail_token()

    new_pw = "Br4nd-New-Pass!"
    res1 = client.post(
        "/auth/reset", json={"token": token, "new_password": new_pw}
    )
    assert res1.status_code == 204
    res2 = client.post(
        "/auth/reset", json={"token": token, "new_password": "Another-Strong-1!"}
    )
    assert res2.status_code == 400


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def test_invite_then_accept_creates_tenant_scoped_user(client, no_auth_override):
    email = f"test+invitee-{uuid4().hex[:6]}@example.com"
    admin = _make_user(role="admin")

    inv = client.post(
        "/auth/invite",
        json={"email": email, "role": "advisor"},
        headers=_auth_headers(admin),
    )
    assert inv.status_code == 201
    token = _read_latest_mail_token()

    new_pw = "Invit3d-Pass-w0rd!"
    res = client.post(
        "/auth/accept-invite",
        json={"token": token, "password": new_pw, "display_name": "Invitee"},
    )
    assert res.status_code == 201
    user_id = res.json()["user_id"]

    # Logs in immediately.
    login = client.post(
        "/auth/login",
        json={"email": email, "password": new_pw, "tenant_slug": "demo"},
    )
    assert login.status_code == 200

    with SessionLocal() as db:
        u = db.get(User, user_id)
        assert u.tenant_id == DEMO_TENANT_ID
        assert u.role == "advisor"
        assert u.email_verified is True


def test_invite_token_is_single_use(client, no_auth_override):
    email = f"test+invitee-{uuid4().hex[:6]}@example.com"
    admin = _make_user(role="admin")
    invite = client.post(
        "/auth/invite",
        json={"email": email, "role": "advisor"},
        headers=_auth_headers(admin),
    )
    assert invite.status_code == 201
    token = _read_latest_mail_token()

    pw = "Invit3d-Pass-w0rd!"
    r1 = client.post(
        "/auth/accept-invite", json={"token": token, "password": pw}
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/auth/accept-invite",
        json={"token": token, "password": "Another-Strong-1!"},
    )
    assert r2.status_code == 400


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_latest_mail_token() -> str:
    """Pull the most recent .eml in DEV_MAIL_DIR and extract the line that
    begins with 'Token:'. Used to bypass the lack of a real SMTP server."""
    from pathlib import Path

    mail_dir = Path(os.environ["DEV_MAIL_DIR"])
    eml_files = sorted(mail_dir.glob("*.eml"), key=lambda p: p.stat().st_mtime)
    assert eml_files, f"no .eml files in {mail_dir}"
    body = eml_files[-1].read_text(encoding="utf-8")
    for line in body.splitlines():
        if line.startswith("Token:"):
            return line.split("Token:", 1)[1].strip()
    raise AssertionError(f"no Token line in {eml_files[-1]}")
