"""Public contact form: POST /public/access-requests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core.auth.email import reset_email_service_cache
from app.core.security.rate_limit import classify_route
from app.db import SessionLocal
from app.main import app
from app.models_db import AccessRequest


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "1000")
    monkeypatch.setenv("DEV_MAIL_DIR", str(tmp_path / "mail"))
    get_settings.cache_clear()
    reset_email_service_cache()
    yield TestClient(app)
    reset_email_service_cache()
    get_settings.cache_clear()


def _payload(**overrides):
    body = {
        "name": "Ada Park",
        "company": f"Acme Wealth {uuid4().hex[:6]}",
        "work_email": "ada@acme.example",
        "role": "Head of Compliance",
        "message": "Two advisors and one reviewer.",
    }
    body.update(overrides)
    return body


def _stored(company: str) -> list[AccessRequest]:
    with SessionLocal() as db:
        return list(db.scalars(select(AccessRequest).where(AccessRequest.company == company)))


def test_submission_is_stored_and_needs_no_login(client, no_auth_override):
    payload = _payload()
    res = client.post("/public/access-requests", json=payload)
    assert res.status_code == 202, res.text
    assert res.json() == {"status": "received"}
    rows = _stored(payload["company"])
    assert len(rows) == 1
    assert rows[0].work_email == "ada@acme.example"
    assert rows[0].message == "Two advisors and one reviewer."


def test_submission_emails_the_configured_inbox(client, monkeypatch, tmp_path):
    monkeypatch.setenv("ACCESS_REQUEST_NOTIFY_EMAIL", "sales@glassbox.example")
    get_settings.cache_clear()
    payload = _payload()
    assert client.post("/public/access-requests", json=payload).status_code == 202
    sent = [p.read_text() for p in (tmp_path / "mail").glob("*.eml")]
    assert any(payload["company"] in body and "sales@glassbox.example" in body for body in sent)


def test_honeypot_submission_is_accepted_but_not_stored(client):
    payload = _payload(website="http://spam.example")
    assert client.post("/public/access-requests", json=payload).status_code == 202
    assert _stored(payload["company"]) == []


@pytest.mark.parametrize(
    "overrides",
    [{"work_email": "not-an-email"}, {"name": ""}, {"unexpected": "field"}],
)
def test_invalid_submissions_are_rejected(client, overrides):
    assert client.post("/public/access-requests", json=_payload(**overrides)).status_code == 422


def test_public_routes_use_the_strict_rate_tier():
    assert classify_route("/public/access-requests") == "auth"
