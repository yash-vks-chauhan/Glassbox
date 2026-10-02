"""Governance metrics for the Insights page.

The rates use one definition everywhere:

- ``hallucination_rate``: share of grounding-scored decisions whose score is
  below ``LOW_GROUNDING`` (shown as "low-grounding rate").
- ``refusal_rate`` / ``flagged_rate``: share of all decisions with that outcome.
- ``audit_completeness``: share of decisions with replayable evidence, i.e.
  refusals and fallbacks, or any decision with at least one recorded claim.

Everything is aggregated in SQL so a large audit log costs one query.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.db import get_db
from app.models_db import (
    ClaimLabel,
    Decision,
    DecisionClaim,
    DecisionReview,
    DeterminismRun,
    User,
)
from app.schemas import MetricsPoint, MetricsSummary, MetricsTimeseries


router = APIRouter(tags=["metrics"])


_METRICS_ROLES = ("compliance", "admin", "owner")
LOW_GROUNDING = 0.6


def _is_complete():
    has_claims = exists().where(DecisionClaim.decision_id == Decision.id)
    return or_(Decision.outcome.in_(("refused", "fallback")), has_claims)


def _utc_day(value: datetime) -> date:
    return (value.astimezone(timezone.utc) if value.tzinfo else value).date()


def _ratio(part: int | None, whole: int | None) -> float | None:
    return (part or 0) / whole if whole else None


@router.get("/metrics/summary", response_model=MetricsSummary)
def metrics_summary(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_METRICS_ROLES)),
) -> MetricsSummary:
    total, scored, low, refused, flagged, complete = db.execute(
        select(
            func.count(Decision.id),
            func.count(Decision.grounding_score),
            func.sum(case((Decision.grounding_score < LOW_GROUNDING, 1), else_=0)),
            func.sum(case((Decision.outcome == "refused", 1), else_=0)),
            func.sum(case((Decision.outcome == "flagged", 1), else_=0)),
            func.sum(case((_is_complete(), 1), else_=0)),
        ).where(Decision.tenant_id == user.tenant_id)
    ).one()
    # Determinism comes from the harness, not from decisions: the latest
    # completed run's average across its sampled questions.
    determinism = db.scalar(
        select(DeterminismRun.avg_score)
        .where(
            DeterminismRun.tenant_id == user.tenant_id,
            DeterminismRun.status == "completed",
            DeterminismRun.avg_score.is_not(None),
        )
        .order_by(DeterminismRun.created_at.desc())
        .limit(1)
    )
    outcome_counts = dict(
        db.execute(
            select(Decision.outcome, func.count(Decision.id))
            .where(Decision.tenant_id == user.tenant_id)
            .group_by(Decision.outcome)
        ).all()
    )
    reviews = db.scalar(
        select(func.count(DecisionReview.id)).where(DecisionReview.tenant_id == user.tenant_id)
    )
    labelled = db.scalar(
        select(func.count(ClaimLabel.id)).where(ClaimLabel.tenant_id == user.tenant_id)
    )
    return MetricsSummary(
        total=total,
        hallucination_rate=_ratio(low, scored) or 0.0,
        refusal_rate=_ratio(refused, total) or 0.0,
        flagged_rate=_ratio(flagged, total) or 0.0,
        avg_determinism=float(determinism) if determinism is not None else None,
        audit_completeness=_ratio(complete, total) if total else 1.0,
        reviews=reviews or 0,
        labelled_claims=labelled or 0,
        outcome_counts={
            outcome: int(outcome_counts.get(outcome, 0))
            for outcome in ("answered", "flagged", "refused", "fallback")
        },
    )


@router.get("/metrics/timeseries", response_model=MetricsTimeseries)
def metrics_timeseries(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_METRICS_ROLES)),
) -> MetricsTimeseries:
    """Daily (UTC) values for the last ``days`` days, oldest first."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    window_start = datetime.combine(start, time.min, tzinfo=timezone.utc)
    rows = db.execute(
        select(
            Decision.created_at,
            Decision.outcome,
            Decision.grounding_score,
            _is_complete(),
        ).where(
            Decision.tenant_id == user.tenant_id,
            Decision.created_at >= window_start,
        )
    ).all()
    runs = db.execute(
        select(DeterminismRun.created_at, DeterminismRun.avg_score).where(
            DeterminismRun.tenant_id == user.tenant_id,
            DeterminismRun.status == "completed",
            DeterminismRun.avg_score.is_not(None),
            DeterminismRun.created_at >= window_start,
        )
    ).all()

    by_day: dict[date, list[tuple]] = {}
    for created_at, outcome, grounding, complete in rows:
        by_day.setdefault(_utc_day(created_at), []).append((outcome, grounding, complete))
    determinism_by_day: dict[date, list[float]] = {}
    for created_at, score in runs:
        determinism_by_day.setdefault(_utc_day(created_at), []).append(score)

    points = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        items = by_day.get(day, [])
        scored = [g for _, g, _ in items if g is not None]
        determinism = determinism_by_day.get(day, [])
        points.append(
            MetricsPoint(
                date=day.isoformat(),
                total=len(items),
                answered=sum(o == "answered" for o, *_ in items),
                flagged=sum(o == "flagged" for o, *_ in items),
                refused=sum(o == "refused" for o, *_ in items),
                fallback=sum(o == "fallback" for o, *_ in items),
                hallucination_rate=_ratio(sum(g < LOW_GROUNDING for g in scored), len(scored)),
                refusal_rate=_ratio(sum(o == "refused" for o, *_ in items), len(items)),
                flagged_rate=_ratio(sum(o == "flagged" for o, *_ in items), len(items)),
                audit_completeness=_ratio(sum(bool(c) for _, _, c in items), len(items)),
                avg_determinism=(sum(determinism) / len(determinism)) if determinism else None,
            )
        )
    return MetricsTimeseries(
        days=days, start=start.isoformat(), end=today.isoformat(), points=points
    )
