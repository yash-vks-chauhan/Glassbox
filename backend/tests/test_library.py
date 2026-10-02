"""The approved document set: /library and /library/{source_id}."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.db import SessionLocal
from app.main import app
from app.models_db import DEMO_TENANT_ID, User


@pytest.fixture()
def client(monkeypatch, no_auth_override) -> TestClient:
    monkeypatch.setenv("RATE_LIMIT_ASK_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MIN", "1000")
    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def _user(role: str = "advisor", tenant_id: str = DEMO_TENANT_ID) -> User:
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=tenant_id,
            email=f"test+library-{uuid4().hex[:8]}@example.com",
            password="Library-Sup3rSecur3!",
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


def test_library_lists_the_indexed_corpus_for_the_tenant(client):
    res = client.get("/library", headers=_bearer(_user()))
    assert res.status_code == 200, res.text
    docs = {doc["source_id"]: doc for doc in res.json()}
    assert {"F100", "F500", "REG-SUITABILITY", "C001", "PORTFOLIO-C001"} <= docs.keys()
    assert all(doc["indexed_passages"] > 0 for doc in docs.values())
    assert docs["C001"]["source_type"] == "ips" and docs["C001"]["shared"] is False
    assert docs["C001"]["version"] == "v3.2"
    assert docs["F100"]["title"] == "Global Emerging Markets Equity Fund (F100)"
    assert docs["PORTFOLIO-C001"]["updated_on"] == "2026-05-01"


def test_other_tenants_see_shared_documents_only(client):
    from tests.conftest import make_tenant

    outsider = _user(tenant_id=make_tenant())
    ids = {doc["source_id"] for doc in client.get("/library", headers=_bearer(outsider)).json()}
    assert "F100" in ids and "REG-SUITABILITY" in ids
    assert "C001" not in ids and "PORTFOLIO-C001" not in ids
    assert client.get("/library/C001", headers=_bearer(outsider)).status_code == 404


def test_document_detail_has_body_metadata_and_citations(client):
    advisor = _user()
    ask = client.post(
        "/ask",
        headers=_bearer(advisor),
        json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
    )
    assert ask.status_code == 200, ask.text

    res = client.get("/library/C001", headers=_bearer(advisor))
    assert res.status_code == 200, res.text
    doc = res.json()
    assert "Investment Policy Statement" in doc["body"]
    assert doc["metadata"]["max_single_position_pct"] == 25
    assert doc["cited_in_decisions"] >= 1


@pytest.mark.parametrize("source_id", ["..secret", "C001.md..", "nope", "a b"])
def test_unknown_or_unsafe_ids_are_not_found(client, source_id):
    assert client.get(f"/library/{source_id}", headers=_bearer(_user())).status_code == 404
