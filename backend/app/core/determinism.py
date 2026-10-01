"""The determinism harness: does the same question get the same answer?

A run takes a sample of recent questions from the tenant (the resolved text
for follow-ups), tops it up from the benchmark set, asks each one several
times without recording decisions, and scores how much the answers drift
(``determinism_score_from_answers``). Runs are stored in
``determinism_runs``; the audit log is never touched.

Scheduled runs happen at most once per tenant per UTC day. A run is claimed
by inserting its (tenant, date) row, so with several server processes only
the first one to claim it does the work.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.core.trust_metrics import determinism_score_from_answers
from app.models_db import (
    ClientRecord,
    Decision,
    DeterminismRun,
    DeterminismSchedule,
    Tenant,
    utcnow,
)


logger = logging.getLogger(__name__)

BENCHMARK_PATH = BACKEND_DIR / "data" / "test_questions.jsonl"
RECENT_WINDOW = timedelta(days=7)
DEFAULT_SCHEDULE = {"hour_utc": 2, "runs_per_question": 5, "sample_size": 10}


@dataclass(frozen=True)
class SampledQuestion:
    question: str
    client_id: str | None
    source: str  # recent | benchmark


def get_schedule(db: Session, tenant_id: str) -> DeterminismSchedule:
    """The tenant's schedule, or an unsaved default one. The default nightly
    run is on only in local evidence mode, where it costs nothing; with a
    hosted model route an admin has to switch it on."""
    schedule = db.get(DeterminismSchedule, tenant_id)
    return schedule or DeterminismSchedule(
        tenant_id=tenant_id, enabled=get_settings().local_evidence_mode, **DEFAULT_SCHEDULE
    )


def sample_questions(db: Session, tenant_id: str, size: int) -> list[SampledQuestion]:
    """Distinct recent questions (newest first), then benchmark questions
    for clients this tenant actually has, up to ``size``."""
    since = datetime.now(timezone.utc) - RECENT_WINDOW
    picked: list[SampledQuestion] = []
    seen: set[tuple[str, str | None]] = set()
    rows = db.execute(
        select(Decision.retrieval_question, Decision.question, Decision.client_id)
        .where(Decision.tenant_id == tenant_id, Decision.created_at >= since)
        .order_by(Decision.created_at.desc())
        .limit(500)
    )
    for retrieval_question, question, client_id in rows:
        text = (retrieval_question or question).strip()
        key = (text.lower(), client_id)
        if key in seen:
            continue
        seen.add(key)
        picked.append(SampledQuestion(text, client_id, "recent"))
        if len(picked) >= size:
            return picked

    clients = set(
        db.scalars(select(ClientRecord.client_code).where(ClientRecord.tenant_id == tenant_id))
    )
    if BENCHMARK_PATH.exists():
        for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            client_id = row.get("client_id")
            if client_id and client_id not in clients:
                continue
            key = (row["q"].strip().lower(), client_id)
            if key in seen:
                continue
            seen.add(key)
            picked.append(SampledQuestion(row["q"].strip(), client_id, "benchmark"))
            if len(picked) >= size:
                break
    return picked


def execute_run(
    db: Session,
    run: DeterminismRun,
    questions: list[SampledQuestion],
) -> DeterminismRun:
    """Ask every question ``run.runs_per_question`` times and record the
    scores on ``run``. Decisions are not persisted. Commits."""
    from app.core.orchestrator import run_ask

    results = []
    model_route = None
    try:
        for item in questions:
            responses = [
                run_ask(
                    question=item.question,
                    client_id=item.client_id,
                    byo_key=None,
                    db=db,
                    persist=False,
                    tenant_id=run.tenant_id,
                )
                for _ in range(run.runs_per_question)
            ]
            model_route = model_route or responses[0].trust.model_route
            answers = [r.answer or r.refusal_reason for r in responses]
            results.append(
                {
                    "question": item.question,
                    "client_id": item.client_id,
                    "source": item.source,
                    "score": round(determinism_score_from_answers(answers), 4),
                    "outcomes": [r.outcome for r in responses],
                    "distinct_answers": len({a or "" for a in answers}),
                }
            )
    except Exception as exc:  # noqa: BLE001 — record the failure on the run
        logger.exception("determinism_run_failed run=%s", run.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    else:
        run.status = "completed"
    scores = [r["score"] for r in results]
    run.question_count = len(results)
    run.avg_score = sum(scores) / len(scores) if scores else None
    run.min_score = min(scores) if scores else None
    run.results_json = json.dumps(results)
    run.model_route = model_route
    run.completed_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def run_now(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    runs_per_question: int,
    sample_size: int,
    questions: list[SampledQuestion] | None = None,
) -> DeterminismRun:
    """A manual run, e.g. from the admin page."""
    run = DeterminismRun(
        tenant_id=tenant_id,
        triggered_by="manual",
        requested_by_user_id=user_id,
        status="running",
        runs_per_question=runs_per_question,
    )
    db.add(run)
    db.commit()
    return execute_run(db, run, questions or sample_questions(db, tenant_id, sample_size))


def claim_scheduled_run(db: Session, schedule: DeterminismSchedule, day: date) -> DeterminismRun | None:
    """Insert the run row for ``day``; None if another process already did."""
    run = DeterminismRun(
        tenant_id=schedule.tenant_id,
        triggered_by="schedule",
        scheduled_for=day,
        status="running",
        runs_per_question=schedule.runs_per_question,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return run


def run_due_schedules(db: Session, now: datetime | None = None) -> list[DeterminismRun]:
    """Run every enabled schedule whose hour has passed today and that has
    no run for today yet. Tenants without a saved schedule use the default."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    completed: list[DeterminismRun] = []
    for tenant_id in db.scalars(select(Tenant.id).where(Tenant.status == "active")).all():
        schedule = get_schedule(db, tenant_id)
        if not schedule.enabled or now.hour < schedule.hour_utc:
            continue
        already = db.scalar(
            select(DeterminismRun.id).where(
                DeterminismRun.tenant_id == tenant_id, DeterminismRun.scheduled_for == today
            )
        )
        if already:
            continue
        run = claim_scheduled_run(db, schedule, today)
        if run is None:
            continue
        questions = sample_questions(db, tenant_id, schedule.sample_size)
        completed.append(execute_run(db, run, questions))
    return completed


def results(run: DeterminismRun) -> list[dict]:
    return json.loads(run.results_json or "[]")
