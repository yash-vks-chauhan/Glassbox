"""Audit log filters, paging, and CSV / PDF binder exports."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.db import SessionLocal
from app.main import app
from app.models_db import DEMO_TENANT_ID, SecurityEvent, User


QUESTIONS = {
    "flagged": "Can client C001 put 40% into fund F100?",
    "answered": "Is fund F100 suitable for client C001?",
    "refused": "What is the capital gains tax rate in Germany?",
}


@pytest.fixture()
def client(monkeypatch, no_auth_override) -> TestClient:
    monkeypatch.setenv("RATE_LIMIT_ASK_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "1000")
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def _user(role: str) -> User:
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=DEMO_TENANT_ID,
            email=f"test+export-{uuid4().hex[:8]}@example.com",
            password="Export-Sup3rSecur3!",
            role=role,
            email_verified=True,
        )
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user


def _bearer(user: User) -> dict[str, str]:
    token = issue_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def advisor_decisions(client):
    """Three decisions (flagged, answered, refused) owned by a fresh advisor,
    plus the moment just before they were created."""
    advisor = _user("advisor")
    started = datetime.now(timezone.utc) - timedelta(seconds=1)
    ids = {}
    for expected, question in QUESTIONS.items():
        res = client.post(
            "/ask", headers=_bearer(advisor), json={"question": question, "client_id": "C001"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["outcome"] == expected
        ids[expected] = res.json()["decision_id"]
    return advisor, started, ids


def test_audit_list_filters_and_reports_total(client, advisor_decisions):
    advisor, _, ids = advisor_decisions
    headers = _bearer(advisor)

    everything = client.get("/audit", headers=headers)
    assert everything.status_code == 200
    assert everything.headers["x-total-count"] == "3"

    refused = client.get("/audit?outcome=refused", headers=headers).json()
    assert [row["id"] for row in refused] == [ids["refused"]]

    search = client.get("/audit", headers=headers, params={"q": "capital gains"}).json()
    assert [row["id"] for row in search] == [ids["refused"]]

    by_id = client.get("/audit", headers=headers, params={"q": ids["flagged"][:8]}).json()
    assert [row["id"] for row in by_id] == [ids["flagged"]]

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.get("/audit", headers=headers, params={"since": future}).json() == []

    page = client.get("/audit?limit=1&offset=1", headers=headers)
    assert len(page.json()) == 1 and page.headers["x-total-count"] == "3"


def test_csv_export_matches_filters_and_neutralises_formulas(client, advisor_decisions):
    advisor, started, ids = advisor_decisions
    formula = client.post(
        "/ask",
        headers=_bearer(advisor),
        json={"question": "=HYPERLINK(\"x\") is fund F100 suitable for C001?", "client_id": "C001"},
    )
    assert formula.status_code == 200, formula.text

    reviewer = _user("compliance")
    res = client.get(
        "/audit/export",
        headers=_bearer(reviewer),
        params={"format": "csv", "since": started.isoformat()},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert {row["decision_id"] for row in rows} >= set(ids.values())
    injected = next(r for r in rows if r["decision_id"] == formula.json()["decision_id"])
    assert injected["question"].startswith("'=HYPERLINK")
    assert injected["asked_by"] == advisor.email


def test_pdf_binder_export_is_logged(client, advisor_decisions):
    _, started, _ = advisor_decisions
    reviewer = _user("compliance")
    res = client.get(
        "/audit/export",
        headers=_bearer(reviewer),
        params={"format": "pdf", "since": started.isoformat()},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")

    with SessionLocal() as db:
        event = db.scalar(
            select(SecurityEvent)
            .where(SecurityEvent.user_id == reviewer.id, SecurityEvent.kind == "audit_export")
            .order_by(SecurityEvent.created_at.desc())
        )
    assert event is not None
    assert json.loads(event.metadata_json)["format"] == "pdf"


def test_pdf_binder_refuses_oversized_selections(client, advisor_decisions, monkeypatch):
    from app.routers import audit as audit_router

    _, started, _ = advisor_decisions
    monkeypatch.setattr(audit_router, "PDF_MAX_DECISIONS", 2)
    res = client.get(
        "/audit/export",
        headers=_bearer(_user("compliance")),
        params={"format": "pdf", "since": started.isoformat()},
    )
    assert res.status_code == 422
    assert "at most 2" in res.json()["detail"]


def test_advisors_cannot_export(client):
    assert client.get("/audit/export", headers=_bearer(_user("advisor"))).status_code == 403
