from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_db import Decision
from app.schemas import MetricsSummary


router = APIRouter(tags=["metrics"])


@router.get("/metrics/summary", response_model=MetricsSummary)
def metrics_summary(db: Session = Depends(get_db)) -> MetricsSummary:
    decisions = db.scalars(select(Decision)).all()
    total = len(decisions)
    if total == 0:
        return MetricsSummary(
            total=0,
            hallucination_rate=0.0,
            refusal_rate=0.0,
            flagged_rate=0.0,
            avg_determinism=None,
            audit_completeness=1.0,
        )

    low_grounding = [
        decision
        for decision in decisions
        if decision.grounding_score is not None and decision.grounding_score < 0.6
    ]
    scored = [decision for decision in decisions if decision.grounding_score is not None]
    refusals = [decision for decision in decisions if decision.outcome == "refused"]
    flagged = [decision for decision in decisions if decision.outcome == "flagged"]
    determinism_values = [
        decision.determinism_score
        for decision in decisions
        if decision.determinism_score is not None
    ]
    complete = [
        decision
        for decision in decisions
        if decision.outcome in {"refused", "fallback"} or decision.claims
    ]
    return MetricsSummary(
        total=total,
        hallucination_rate=(len(low_grounding) / len(scored)) if scored else 0.0,
        refusal_rate=len(refusals) / total,
        flagged_rate=len(flagged) / total,
        avg_determinism=(
            sum(determinism_values) / len(determinism_values)
            if determinism_values
            else None
        ),
        audit_completeness=len(complete) / total,
    )
