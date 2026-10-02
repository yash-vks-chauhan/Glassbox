"""Timestamps leave the API as UTC instants, whatever the database.

SQLite hands DateTime columns back without a time zone. The API used to
serialise those naive values as-is, so browsers parsed them as local time
and showed every timestamp (and SLA countdown) shifted by the viewer's UTC
offset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models_db import Decision, DeterminismRun


def test_api_timestamps_carry_a_utc_offset():
    client = TestClient(app)
    asked = client.post(
        "/ask", json={"question": "Can client C001 put 40% into fund F100?", "client_id": "C001"}
    )
    assert asked.status_code == 200, asked.text
    decision_id = asked.json()["decision_id"]

    detail = client.get(f"/audit/{decision_id}").json()
    created = datetime.fromisoformat(detail["created_at"])
    assert created.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - created) < timedelta(minutes=5)

    with SessionLocal() as db:
        assert db.get(Decision, decision_id).created_at.tzinfo is not None


def test_aware_times_in_other_zones_are_stored_as_the_same_instant():
    from tests.conftest import make_tenant

    zurich_noon = datetime(2031, 6, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    with SessionLocal() as db:
        run = DeterminismRun(
            tenant_id=make_tenant(),
            triggered_by="manual",
            status="completed",
            runs_per_question=2,
            created_at=zurich_noon,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    with SessionLocal() as db:
        stored = db.get(DeterminismRun, run_id).created_at
    assert stored == zurich_noon
    assert stored.utcoffset() == timedelta(0) and stored.hour == 10
