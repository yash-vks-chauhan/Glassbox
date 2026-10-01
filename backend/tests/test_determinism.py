"""Determinism harness: schedules, runs, scheduler, and metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.core.auth import service as auth_service
from app.core.auth.tokens import issue_access_token
from app.core.determinism import claim_scheduled_run, get_schedule, run_due_schedules
from app.core.scheduler import DeterminismScheduler
from app.core.security.audit_hash import verify_chain
from app.db import SessionLocal
from app.main import app
from app.models_db import DEMO_TENANT_ID, Decision, DeterminismRun, DeterminismSchedule, User


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
            email=f"test+det-{uuid4().hex[:8]}@example.com",
            password="Determinism-Sup3rSecur3!",
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


def _decision_count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(Decision.id)))


def test_default_schedule_and_admin_update(client):
    from tests.conftest import make_tenant

    tenant_id = make_tenant()
    reviewer, admin = _user("compliance", tenant_id), _user("admin", tenant_id)

    default = client.get("/determinism/schedule", headers=_bearer(reviewer)).json()
    assert default["enabled"] is True  # local evidence mode: free to run nightly
    assert (default["hour_utc"], default["runs_per_question"], default["sample_size"]) == (2, 5, 10)
    assert default["next_run_at"]

    body = {"enabled": False, "hour_utc": 4, "runs_per_question": 3, "sample_size": 5}
    assert client.put("/determinism/schedule", headers=_bearer(reviewer), json=body).status_code == 403
    saved = client.put("/determinism/schedule", headers=_bearer(admin), json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is False and saved.json()["next_run_at"] is None
    assert client.get("/determinism/schedule", headers=_bearer(reviewer)).json()["hour_utc"] == 4


def test_manual_run_uses_recent_questions_and_records_no_decisions(client):
    advisor, reviewer = _user("advisor"), _user("compliance")
    question = f"Can client C001 put 40% into fund F100? ({uuid4().hex[:6]})"
    client.post("/ask", headers=_bearer(advisor), json={"question": question, "client_id": "C001"})
    before = _decision_count()

    res = client.post(
        "/determinism/runs",
        headers=_bearer(reviewer),
        json={"runs_per_question": 3, "sample_size": 4},
    )
    assert res.status_code == 201, res.text
    run = res.json()
    assert run["status"] == "completed" and run["triggered_by"] == "manual"
    assert run["question_count"] == 4 and 0.0 <= run["avg_score"] <= 1.0
    assert run["results"][0]["question"] == question
    assert run["results"][0]["source"] == "recent"
    assert len(run["results"][0]["outcomes"]) == 3
    # Measurement only: nothing lands in the audit log, and the chain holds.
    assert _decision_count() == before
    with SessionLocal() as db:
        assert verify_chain(db, tenant_id=DEMO_TENANT_ID).ok

    listed = client.get("/determinism/runs", headers=_bearer(reviewer)).json()
    assert listed[0]["id"] == run["id"]


def test_metrics_report_the_latest_run(client):
    reviewer = _user("compliance")
    run = client.post(
        "/determinism/runs", headers=_bearer(reviewer), json={"runs_per_question": 2, "sample_size": 2}
    ).json()
    summary = client.get("/metrics/summary", headers=_bearer(reviewer)).json()
    assert summary["avg_determinism"] == pytest.approx(run["avg_score"])
    today = client.get("/metrics/timeseries?days=1", headers=_bearer(reviewer)).json()["points"][-1]
    assert today["avg_determinism"] is not None


def test_scheduled_runs_happen_once_per_tenant_per_day(client):
    from tests.conftest import make_tenant

    tenant_id = make_tenant()
    with SessionLocal() as db:
        db.add(
            DeterminismSchedule(
                tenant_id=tenant_id, enabled=True, hour_utc=0, runs_per_question=2, sample_size=1
            )
        )
        db.commit()
        now = datetime(2031, 1, 15, 3, 0, tzinfo=timezone.utc)
        first = [r for r in run_due_schedules(db, now=now) if r.tenant_id == tenant_id]
        second = [r for r in run_due_schedules(db, now=now) if r.tenant_id == tenant_id]
        assert len(first) == 1 and first[0].triggered_by == "schedule"
        assert second == []
        # A second process trying to claim the same day gets nothing.
        assert claim_scheduled_run(db, get_schedule(db, tenant_id), now.date()) is None
        runs = db.scalar(
            select(func.count(DeterminismRun.id)).where(DeterminismRun.tenant_id == tenant_id)
        )
        assert runs == 1


def test_disabled_or_not_yet_due_schedules_do_not_run(client):
    from tests.conftest import make_tenant

    off, later = make_tenant(), make_tenant()
    with SessionLocal() as db:
        db.add(DeterminismSchedule(tenant_id=off, enabled=False, hour_utc=0))
        db.add(DeterminismSchedule(tenant_id=later, enabled=True, hour_utc=23))
        db.commit()
        ran = {r.tenant_id for r in run_due_schedules(db, now=datetime(2031, 2, 1, 5, tzinfo=timezone.utc))}
    assert off not in ran and later not in ran


def test_scheduler_tick_runs_due_schedules(client, monkeypatch):
    from app.core import scheduler as scheduler_module

    calls = []
    monkeypatch.setattr(scheduler_module, "run_due_schedules", lambda db: calls.append(db) or [])
    DeterminismScheduler(interval_seconds=60).tick()
    assert len(calls) == 1


def test_single_question_check_is_stored_as_a_run(client):
    reviewer = _user("compliance")
    before = _decision_count()
    res = client.post(
        "/determinism",
        headers=_bearer(reviewer),
        json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001", "runs": 3},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["representative_decision_id"] is None and body["run_id"]
    assert len(body["per_run_outcomes"]) == 3
    assert _decision_count() == before


def test_advisors_cannot_use_the_harness(client):
    advisor = _user("advisor")
    assert client.get("/determinism/runs", headers=_bearer(advisor)).status_code == 403
    assert client.post("/determinism/runs", headers=_bearer(advisor), json={}).status_code == 403
    assert client.get("/determinism/schedule", headers=_bearer(advisor)).status_code == 403
