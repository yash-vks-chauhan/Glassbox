"""Determinism harness: schedule, runs, and the single-question check."""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.core.determinism import get_schedule, results, run_now
from app.core.trust_metrics import determinism_run
from app.db import get_db
from app.models_db import DeterminismRun, DeterminismSchedule, User, utcnow
from app.schemas import (
    DeterminismQuestionResult,
    DeterminismRequest,
    DeterminismResponse,
    DeterminismRunOut,
    DeterminismRunRequest,
    DeterminismScheduleOut,
    DeterminismScheduleUpdate,
)


router = APIRouter(tags=["determinism"])

_READ_ROLES = ("compliance", "admin", "owner")
_ADMIN_ROLES = ("admin", "owner")


def _next_run_at(schedule: DeterminismSchedule, db: Session) -> str | None:
    """Today at the scheduled hour until today's run exists, then tomorrow.
    A time in the past means the run is due and the scheduler's next tick
    will start it."""
    if not schedule.enabled:
        return None
    now = datetime.now(timezone.utc)
    ran_today = db.scalar(
        select(DeterminismRun.id).where(
            DeterminismRun.tenant_id == schedule.tenant_id,
            DeterminismRun.scheduled_for == now.date(),
        )
    )
    day = now.date() + timedelta(days=1) if ran_today else now.date()
    return datetime.combine(day, time(hour=schedule.hour_utc), tzinfo=timezone.utc).isoformat()


def _schedule_out(schedule: DeterminismSchedule, db: Session) -> DeterminismScheduleOut:
    return DeterminismScheduleOut(
        enabled=schedule.enabled,
        hour_utc=schedule.hour_utc,
        runs_per_question=schedule.runs_per_question,
        sample_size=schedule.sample_size,
        updated_at=schedule.updated_at.isoformat() if schedule.updated_at else None,
        next_run_at=_next_run_at(schedule, db),
    )


def _run_out(run: DeterminismRun) -> DeterminismRunOut:
    return DeterminismRunOut(
        id=run.id,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        triggered_by=run.triggered_by,
        scheduled_for=run.scheduled_for.isoformat() if run.scheduled_for else None,
        status=run.status,
        model_route=run.model_route,
        runs_per_question=run.runs_per_question,
        question_count=run.question_count,
        avg_score=run.avg_score,
        min_score=run.min_score,
        error=run.error,
        results=[DeterminismQuestionResult(**item) for item in results(run)],
    )


@router.get("/determinism/schedule", response_model=DeterminismScheduleOut)
def read_schedule(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> DeterminismScheduleOut:
    return _schedule_out(get_schedule(db, user.tenant_id), db)


@router.put("/determinism/schedule", response_model=DeterminismScheduleOut)
def update_schedule(
    payload: DeterminismScheduleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_ADMIN_ROLES)),
) -> DeterminismScheduleOut:
    schedule = db.get(DeterminismSchedule, user.tenant_id)
    if schedule is None:
        schedule = DeterminismSchedule(tenant_id=user.tenant_id)
        db.add(schedule)
    schedule.enabled = payload.enabled
    schedule.hour_utc = payload.hour_utc
    schedule.runs_per_question = payload.runs_per_question
    schedule.sample_size = payload.sample_size
    schedule.updated_by_user_id = user.id
    schedule.updated_at = utcnow()
    db.commit()
    db.refresh(schedule)
    return _schedule_out(schedule, db)


@router.get("/determinism/runs", response_model=list[DeterminismRunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> list[DeterminismRunOut]:
    rows = db.scalars(
        select(DeterminismRun)
        .where(DeterminismRun.tenant_id == user.tenant_id)
        .order_by(DeterminismRun.created_at.desc())
        .limit(limit)
    ).all()
    return [_run_out(row) for row in rows]


@router.post("/determinism/runs", response_model=DeterminismRunOut, status_code=201)
def create_run(
    payload: DeterminismRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> DeterminismRunOut:
    """Run the harness now on the workspace's recent questions."""
    schedule = get_schedule(db, user.tenant_id)
    run = run_now(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        runs_per_question=payload.runs_per_question or schedule.runs_per_question,
        sample_size=payload.sample_size or schedule.sample_size,
    )
    return _run_out(run)


@router.post("/determinism", response_model=DeterminismResponse)
def determinism(
    request: DeterminismRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_READ_ROLES)),
) -> DeterminismResponse:
    """Score one question. The result is stored as a single-question run."""
    score, responses = determinism_run(
        question=request.question,
        client_id=request.client_id,
        db=db,
        runs=request.runs,
        alternate_model=request.alternate_model,
        tenant_id=user.tenant_id,
    )
    answers = [r.answer or r.refusal_reason for r in responses]
    run = DeterminismRun(
        tenant_id=user.tenant_id,
        triggered_by="manual",
        requested_by_user_id=user.id,
        status="completed",
        model_route=responses[0].trust.model_route if responses else None,
        runs_per_question=len(responses),
        question_count=1,
        avg_score=score,
        min_score=score,
        results_json=json.dumps(
            [
                {
                    "question": request.question,
                    "client_id": request.client_id,
                    "source": "manual",
                    "score": round(score, 4),
                    "outcomes": [r.outcome for r in responses],
                    "distinct_answers": len({a or "" for a in answers}),
                }
            ]
        ),
        completed_at=utcnow(),
    )
    db.add(run)
    db.commit()
    return DeterminismResponse(
        determinism_score=score,
        per_run_outcomes=responses,
        run_id=run.id,
    )
