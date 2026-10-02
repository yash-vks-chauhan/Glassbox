"""Compliance reviews, reviewer claim labels, and the metrics built on them."""

from __future__ import annotations

import json
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


def _user(role: str, tenant_id: str = DEMO_TENANT_ID) -> User:
    with SessionLocal() as db:
        user = auth_service.create_user(
            db,
            tenant_id=tenant_id,
            email=f"test+review-{uuid4().hex[:8]}@example.com",
            password="Review-Sup3rSecur3!",
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


def _flagged_decision(client: TestClient, advisor: User) -> dict:
    res = client.post(
        "/ask",
        headers=_bearer(advisor),
        json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"},
    )
    assert res.status_code == 200, res.text
    detail = client.get(f"/audit/{res.json()['decision_id']}", headers=_bearer(advisor))
    assert detail.status_code == 200, detail.text
    return detail.json()


def _review(client, reviewer, decision_id, **overrides):
    body = {"assessment": "correct", "reason_code": "concentration_breach"}
    body.update(overrides)
    return client.post(f"/decisions/{decision_id}/reviews", headers=_bearer(reviewer), json=body)


def test_review_resolves_escalation_and_stores_claim_labels(client):
    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    escalation = client.post(
        "/escalations", headers=_bearer(advisor), json={"decision_id": decision["id"]}
    )
    assert escalation.status_code == 201, escalation.text

    claim = next(c for c in decision["decision_claims"] if c["kept"] and c["cited_source_id"])
    res = _review(
        client,
        reviewer,
        decision["id"],
        notes="Concur: the 25% single-position cap applies.",
        claim_verdicts=[{"claim_id": claim["id"], "supported": True}],
    )
    assert res.status_code == 201, res.text
    review = res.json()
    assert review["escalation_status"] == "resolved"
    assert review["reviewer_email"] == reviewer.email
    assert review["claim_labels"] == [
        {
            "claim_id": claim["id"],
            "claim_text": claim["claim_text"],
            "cited_source_id": claim["cited_source_id"],
            "supported": True,
        }
    ]

    replay = client.get(f"/audit/{decision['id']}", headers=_bearer(reviewer)).json()
    assert [r["id"] for r in replay["reviews"]] == [review["id"]]
    assert replay["active_escalation"] is None
    # The advisor sees the verdict on their own decision.
    own = client.get(f"/decisions/{decision['id']}/reviews", headers=_bearer(advisor))
    assert [r["assessment"] for r in own.json()] == ["correct"]


def test_incorrect_review_appends_a_correction(client):
    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    res = _review(
        client,
        reviewer,
        decision["id"],
        assessment="incorrect",
        reason_code="other",
        corrected_outcome="refused",
        notes="Out of scope; should have been refused.",
    )
    assert res.status_code == 201, res.text
    replay = client.get(f"/audit/{decision['id']}", headers=_bearer(reviewer)).json()
    assert replay["corrections"][0]["corrected_outcome"] == "refused"
    assert replay["corrections"][0]["note"] == "Out of scope; should have been refused."
    # The original decision stays exactly as recorded.
    assert replay["outcome"] == decision["outcome"]


def test_needs_signoff_opens_a_high_priority_escalation(client):
    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    res = _review(client, reviewer, decision["id"], assessment="needs_signoff")
    assert res.status_code == 201, res.text
    replay = client.get(f"/audit/{decision['id']}", headers=_bearer(reviewer)).json()
    assert replay["active_escalation"]["status"] == "open"
    assert replay["active_escalation"]["priority"] == "high"


def test_four_eyes_rule_blocks_reviewing_your_own_decision(client):
    reviewer = _user("compliance")
    decision = _flagged_decision(client, reviewer)
    res = _review(client, reviewer, decision["id"])
    assert res.status_code == 403
    assert "four-eyes" in res.json()["detail"].lower()


def test_advisors_cannot_submit_reviews(client):
    advisor, other = _user("advisor"), _user("advisor")
    decision = _flagged_decision(client, advisor)
    assert _review(client, other, decision["id"]).status_code == 403


def test_reviews_are_tenant_scoped(client):
    from tests.conftest import make_tenant

    advisor = _user("advisor")
    decision = _flagged_decision(client, advisor)
    outsider = _user("compliance", tenant_id=make_tenant())
    assert _review(client, outsider, decision["id"]).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"claim_verdicts": [{"claim_id": "not-a-claim", "supported": True}]},
        {"corrected_outcome": "refused"},
        {"assessment": "maybe"},
        {"reason_code": "made_up"},
    ],
)
def test_invalid_reviews_are_rejected(client, overrides):
    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    assert _review(client, reviewer, decision["id"], **overrides).status_code == 422


def test_metrics_count_reviews_and_report_daily_points(client):
    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    claim = decision["decision_claims"][0]
    before = client.get("/metrics/summary", headers=_bearer(reviewer)).json()
    _review(
        client, reviewer, decision["id"],
        claim_verdicts=[{"claim_id": claim["id"], "supported": False}],
    )
    after = client.get("/metrics/summary", headers=_bearer(reviewer)).json()
    assert after["reviews"] == before["reviews"] + 1
    assert after["labelled_claims"] == before["labelled_claims"] + 1

    series = client.get("/metrics/timeseries?days=7", headers=_bearer(reviewer))
    assert series.status_code == 200, series.text
    body = series.json()
    assert body["days"] == 7 and len(body["points"]) == 7
    today = body["points"][-1]
    assert today["date"] == body["end"]
    assert today["total"] >= 1
    assert today["flagged"] >= 1
    assert today["flagged_rate"] is not None
    summary = client.get("/metrics/summary", headers=_bearer(reviewer)).json()
    assert summary["outcome_counts"]["flagged"] >= 1
    assert sum(summary["outcome_counts"].values()) == summary["total"]


def test_metrics_timeseries_is_compliance_only(client):
    advisor = _user("advisor")
    assert client.get("/metrics/timeseries", headers=_bearer(advisor)).status_code == 403


def test_review_labels_export_feeds_grounding_training(client, monkeypatch, tmp_path):
    from app.ml import train_grounding
    from scripts import export_review_labels

    advisor, reviewer = _user("advisor"), _user("compliance")
    decision = _flagged_decision(client, advisor)
    claim = next(c for c in decision["decision_claims"] if c["cited_source_id"])
    _review(
        client, reviewer, decision["id"],
        claim_verdicts=[{"claim_id": claim["id"], "supported": True}],
    )

    output = tmp_path / "review_labels.jsonl"
    monkeypatch.setattr(export_review_labels, "OUTPUT", output)
    assert export_review_labels.main(["--tenant", DEMO_TENANT_ID]) == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert {"claim": claim["claim_text"], "label": 1} == {
        "claim": rows[-1]["claim"], "label": rows[-1]["label"]
    }
    assert rows[-1]["source"]

    monkeypatch.setattr(train_grounding, "REVIEW_LABELS_PATH", output)
    synthetic = train_grounding._read_jsonl(train_grounding.DATA_PATH)
    assert len(train_grounding.load_rows()) == len(synthetic) + len(rows)
