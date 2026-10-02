"""Threads: persistent per-client conversations with follow-up resolution."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.core.conversation import contextualize
from app.core.security.audit_hash import verify_chain
from app.db import SessionLocal, engine
from app.main import app
from app.models_db import DEMO_TENANT_ID, User


ALLOCATION = "Can client C001 put 40% into fund F100?"


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
            email=f"test+thread-{uuid4().hex[:8]}@example.com",
            password="Thread-Sup3rSecur3!",
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


def _ask(client, user, question, thread_id=None, client_id="C001"):
    body = {"question": question, "client_id": client_id}
    if thread_id:
        body["thread_id"] = thread_id
    return client.post("/ask", headers=_bearer(user), json=body)


@pytest.mark.parametrize(
    "follow_up,previous,expected",
    [
        ("What about F200?", ALLOCATION, "Can client C001 put 40% into fund F200?"),
        ("and 20%?", ALLOCATION, "Can client C001 put 20% into fund F100?"),
        ("Why?", ALLOCATION, ALLOCATION),
        ("What about liquidity?", ALLOCATION, "What about liquidity?"),
        (
            "And what is the capital gains tax rate in Germany?",
            ALLOCATION,
            "And what is the capital gains tax rate in Germany?",
        ),
        ("What about F200?", None, "What about F200?"),
    ],
)
def test_contextualize_rules(follow_up, previous, expected):
    assert contextualize(follow_up, previous) == expected


def test_a_follow_up_is_answered_in_context_and_both_texts_are_kept(client):
    advisor = _user()
    first = _ask(client, advisor, ALLOCATION)
    assert first.status_code == 200, first.text
    thread_id = first.json()["thread_id"]
    assert thread_id and first.json()["retrieval_question"] is None

    follow = _ask(client, advisor, "What about F200?", thread_id=thread_id)
    assert follow.status_code == 200, follow.text
    body = follow.json()
    assert body["thread_id"] == thread_id
    assert body["retrieval_question"] == "Can client C001 put 40% into fund F200?"
    assert any(c["source_id"] == "F200" for c in body["citations"])

    replay = client.get(f"/audit/{body['decision_id']}", headers=_bearer(advisor)).json()
    assert replay["question"] == "What about F200?"
    assert replay["retrieval_question"] == "Can client C001 put 40% into fund F200?"
    assert replay["thread_id"] == thread_id


def test_thread_reloads_with_messages_citations_and_refusals(client):
    advisor = _user()
    thread_id = _ask(client, advisor, ALLOCATION).json()["thread_id"]
    refusal = _ask(
        client, advisor, "What is the capital gains tax rate in Germany?", thread_id=thread_id
    )
    assert refusal.json()["outcome"] == "refused"

    res = client.get(f"/threads/{thread_id}", headers=_bearer(advisor))
    assert res.status_code == 200, res.text
    thread = res.json()
    assert thread["title"] == ALLOCATION and thread["message_count"] == 2
    first, second = thread["messages"]
    assert first["question"] == ALLOCATION and first["citations"]
    assert second["outcome"] == "refused"
    assert second["refusal_reason"] == refusal.json()["refusal_reason"]

    listing = client.get("/threads?client_id=C001", headers=_bearer(advisor)).json()
    assert [t["id"] for t in listing][0] == thread_id
    assert listing[0]["last_outcome"] == "refused"


def test_streaming_ask_continues_the_thread(client):
    advisor = _user()
    thread_id = _ask(client, advisor, ALLOCATION).json()["thread_id"]
    with client.stream(
        "POST",
        "/ask/stream",
        headers=_bearer(advisor),
        json={"question": "and 20%?", "client_id": "C001", "thread_id": thread_id},
    ) as res:
        assert res.status_code == 200
        lines = [line for line in res.iter_lines() if line.startswith("data:")]
    final = json.loads(lines[-1][len("data:"):])
    assert final["thread_id"] == thread_id
    assert final["retrieval_question"] == "Can client C001 put 20% into fund F100?"
    detail = client.get(f"/threads/{thread_id}", headers=_bearer(advisor)).json()
    assert detail["message_count"] == 2


def test_only_the_owner_can_ask_in_a_thread(client):
    owner, other = _user(), _user()
    thread_id = _ask(client, owner, ALLOCATION).json()["thread_id"]
    assert _ask(client, other, "What about F200?", thread_id=thread_id).status_code == 404
    reviewer = _user("compliance")
    # Reviewers can read every thread in the workspace...
    assert client.get(f"/threads/{thread_id}", headers=_bearer(reviewer)).status_code == 200
    # ...but advisors only see their own.
    assert client.get(f"/threads/{thread_id}", headers=_bearer(other)).status_code == 404


def test_a_thread_is_bound_to_its_client(client):
    advisor = _user()
    thread_id = _ask(client, advisor, ALLOCATION).json()["thread_id"]
    res = _ask(client, advisor, "Is fund F100 suitable?", thread_id=thread_id, client_id="C002")
    assert res.status_code == 422


def test_threads_are_tenant_scoped(client):
    from tests.conftest import make_tenant

    thread_id = _ask(client, _user(), ALLOCATION).json()["thread_id"]
    outsider = _user("compliance", tenant_id=make_tenant())
    assert client.get(f"/threads/{thread_id}", headers=_bearer(outsider)).status_code == 404


def test_resolving_and_reopening_a_thread(client):
    advisor = _user()
    thread_id = _ask(client, advisor, ALLOCATION).json()["thread_id"]
    res = client.patch(
        f"/threads/{thread_id}", headers=_bearer(advisor), json={"status": "resolved"}
    )
    assert res.status_code == 200 and res.json()["status"] == "resolved"
    _ask(client, advisor, "What about F200?", thread_id=thread_id)
    assert client.get(f"/threads/{thread_id}", headers=_bearer(advisor)).json()["status"] == "open"


def test_thread_status_follows_its_escalations(client):
    advisor, reviewer = _user(), _user("compliance")
    asked = _ask(client, advisor, ALLOCATION).json()
    thread_id, decision_id = asked["thread_id"], asked["decision_id"]
    client.post("/escalations", headers=_bearer(advisor), json={"decision_id": decision_id})
    assert client.get(f"/threads/{thread_id}", headers=_bearer(advisor)).json()["status"] == "escalated"

    client.post(
        f"/decisions/{decision_id}/reviews",
        headers=_bearer(reviewer),
        json={"assessment": "correct", "reason_code": "concentration_breach"},
    )
    assert client.get(f"/threads/{thread_id}", headers=_bearer(advisor)).json()["status"] == "open"


def test_thread_context_is_covered_by_the_hash_chain(client):
    advisor = _user()
    thread_id = _ask(client, advisor, ALLOCATION).json()["thread_id"]
    follow = _ask(client, advisor, "What about F200?", thread_id=thread_id).json()
    with SessionLocal() as db:
        assert verify_chain(db, tenant_id=DEMO_TENANT_ID).ok

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE decisions SET retrieval_question = :q WHERE id = :id"),
            {"q": "Can client C001 put 40% into fund F500?", "id": follow["decision_id"]},
        )
    try:
        with SessionLocal() as db:
            report = verify_chain(db, tenant_id=DEMO_TENANT_ID)
        assert not report.ok and report.first_break_decision_id == follow["decision_id"]
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE decisions SET retrieval_question = :q WHERE id = :id"),
                {"q": follow["retrieval_question"], "id": follow["decision_id"]},
            )
