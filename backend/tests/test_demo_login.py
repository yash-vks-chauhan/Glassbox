"""One-click demo sign-in for the public showcase (app/core/auth/demo.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core.auth.demo import DEMO_USERS
from app.db import SessionLocal
from app.main import app
from app.models_db import DEMO_TENANT_ID, PasswordReset, User


@pytest.fixture()
def client(monkeypatch, no_auth_override) -> TestClient:
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_ASK_PER_MIN", "1000")
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def _demo(client: TestClient, role: str) -> dict[str, str]:
    res = client.post("/auth/demo-login", json={"role": role})
    assert res.status_code == 200, res.text
    assert res.cookies.get(get_settings().refresh_cookie_name)
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_demo_is_off_unless_enabled(monkeypatch, no_auth_override):
    monkeypatch.setenv("DEMO_LOGIN_ENABLED", "0")
    get_settings.cache_clear()
    try:
        plain = TestClient(app)
        assert plain.get("/public/demo").json() == {"enabled": False, "workspace": None, "roles": []}
        assert plain.post("/auth/demo-login", json={"role": "advisor"}).status_code == 404
    finally:
        get_settings.cache_clear()


def test_demo_roles_sign_in_without_an_account(client):
    assert client.get("/public/demo").json() == {
        "enabled": True, "workspace": "demo", "roles": ["advisor", "compliance"],
    }
    for role in ("advisor", "compliance"):
        me = client.get("/auth/me", headers=_demo(client, role)).json()
        assert me["role"] == role and me["is_demo"] is True and me["tenant_slug"] == "demo"
    # Signing in again reuses the same demo user.
    _demo(client, "advisor")
    with SessionLocal() as db:
        email = DEMO_USERS["advisor"][0]
        assert len(db.scalars(select(User).where(User.email == email)).all()) == 1


def test_only_the_two_demo_roles_exist(client):
    for role in ("admin", "owner", "nobody"):
        assert client.post("/auth/demo-login", json={"role": role}).status_code == 422


def test_demo_advisor_can_ask_but_not_change_the_demo(client):
    headers = _demo(client, "advisor")
    asked = client.post(
        "/ask", headers=headers,
        json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
    )
    assert asked.status_code == 200 and asked.json()["outcome"] == "flagged"

    blocked = [
        client.post("/users/me/change-password", headers=headers,
                    json={"current_password": "anything-at-all", "new_password": "New-Sup3rSecur3-Pass!"}),
        client.post("/users/me/sessions/revoke-all", headers=headers),
        client.post("/auth/mfa/enroll", headers=headers),
        client.post("/clients", headers=headers, json={
            "client_code": "C777", "display_name": "Spam", "risk_profile": "moderate",
        }),
    ]
    assert [r.status_code for r in blocked] == [403, 403, 403, 403]
    assert client.get("/auth/me", headers=headers).json()["can_use_byo_keys"] is False


def test_demo_users_get_no_password_reset_email(client):
    _demo(client, "compliance")
    email = DEMO_USERS["compliance"][0]
    assert client.post("/auth/forgot", json={"email": email, "tenant_slug": "demo"}).status_code == 200
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.tenant_id == DEMO_TENANT_ID, User.email == email))
        assert db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id)) is None


def test_revoking_or_re_roling_a_demo_user_turns_that_role_off(client):
    _demo(client, "advisor")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_USERS["advisor"][0]))
        user.role = "admin"
        db.commit()
    try:
        assert client.post("/auth/demo-login", json={"role": "advisor"}).status_code == 404
    finally:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == DEMO_USERS["advisor"][0]))
            user.role = "advisor"
            db.commit()
