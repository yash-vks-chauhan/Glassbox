from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models_db import ModelEvalRun


MODEL_EVAL_DATASET_VERSION = "glassbox-eval-v2"
_APPROVAL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def route_eval_approval(route: str, db: Session | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.require_recent_model_eval_in_production:
        return {
            "approved": True,
            "reason": "recent eval gate is disabled",
            "run_id": None,
            "created_at": None,
        }

    owns_session = db is None
    if owns_session:
        cached = _APPROVAL_CACHE.get(route)
        if cached and (datetime.now(timezone.utc).timestamp() - cached[0]) <= settings.model_approval_cache_ttl_seconds:
            return dict(cached[1])
    if db is None:
        from app.db import SessionLocal

        db = SessionLocal()
    try:
        result = _route_eval_approval_uncached(route, db)
        if owns_session:
            _APPROVAL_CACHE[route] = (datetime.now(timezone.utc).timestamp(), result)
        return result
    except Exception as exc:
        return _denied(f"eval approval check failed: {exc}")
    finally:
        if owns_session:
            db.close()


def _route_eval_approval_uncached(route: str, db: Session) -> dict[str, Any]:
    settings = get_settings()
    latest = latest_eval_run_for_route(db, route)
    if latest is None:
        return _denied("no eval run exists for this route")
    if latest.dataset_version != MODEL_EVAL_DATASET_VERSION:
        return _denied(
            f"latest eval used {latest.dataset_version}, expected {MODEL_EVAL_DATASET_VERSION}",
            latest,
        )
    if latest.evaluated_questions < settings.eval_min_questions_for_production:
        return _denied(
            f"latest eval covered {latest.evaluated_questions} questions; "
            f"{settings.eval_min_questions_for_production} required",
            latest,
        )
    if _is_stale(latest.created_at, settings.model_eval_freshness_hours):
        return _denied(
            f"latest passing eval is older than {settings.model_eval_freshness_hours} hours",
            latest,
        )
    threshold_failure = _threshold_failure(latest)
    if threshold_failure:
        return _denied(threshold_failure, latest)
    if not latest.production_ready:
        return _denied("latest eval did not pass production thresholds", latest)
    return {
        "approved": True,
        "reason": "latest eval passed production thresholds",
        "run_id": latest.id,
        "created_at": _iso(latest.created_at),
    }


def latest_eval_run_for_route(db: Session, route: str) -> ModelEvalRun | None:
    return db.scalars(
        select(ModelEvalRun)
        .where(ModelEvalRun.route == route)
        .order_by(desc(ModelEvalRun.created_at))
        .limit(1)
    ).first()


def approved_model_routes(db: Session) -> list[str]:
    routes = db.scalars(select(ModelEvalRun.route).distinct()).all()
    approved: list[str] = []
    for route in routes:
        if route_eval_approval(route, db=db)["approved"]:
            approved.append(route)
    return sorted(approved)


def _threshold_failure(run: ModelEvalRun) -> str | None:
    settings = get_settings()
    checks: list[tuple[str, bool]] = [
        ("outcome accuracy", run.outcome_accuracy >= settings.eval_min_outcome_accuracy),
        ("citation accuracy", run.citation_accuracy >= settings.eval_min_citation_accuracy),
        ("retrieval recall", run.retrieval_recall >= settings.eval_min_retrieval_recall),
        ("faithfulness", run.faithfulness_score >= settings.eval_min_faithfulness),
        (
            "golden claim coverage",
            run.golden_claim_score >= settings.eval_min_golden_claim_score,
        ),
        ("hallucination rate", run.hallucination_rate <= settings.eval_max_hallucination_rate),
        ("determinism", run.determinism >= settings.eval_min_determinism),
        (
            "average latency",
            run.avg_latency_ms is not None
            and run.avg_latency_ms <= settings.eval_max_avg_latency_ms,
        ),
        (
            "p95 latency",
            run.p95_latency_ms is not None
            and run.p95_latency_ms <= settings.eval_max_p95_latency_ms,
        ),
        (
            "refusal correctness",
            run.refusal_correctness >= settings.eval_min_refusal_correctness,
        ),
        (
            "numeric compliance",
            run.numeric_compliance_accuracy >= settings.eval_min_numeric_compliance,
        ),
        (
            "prompt-injection resistance",
            run.prompt_injection_resistance
            >= settings.eval_min_prompt_injection_resistance,
        ),
        (
            "advisor answer quality",
            run.advisor_quality_score >= settings.eval_min_advisor_quality,
        ),
    ]
    failed = [name for name, passed in checks if not passed]
    if failed:
        return "latest eval failed thresholds: " + ", ".join(failed)
    return None


def _denied(reason: str, run: ModelEvalRun | None = None) -> dict[str, Any]:
    return {
        "approved": False,
        "reason": reason,
        "run_id": run.id if run else None,
        "created_at": _iso(run.created_at) if run else None,
    }


def _is_stale(created_at: datetime, freshness_hours: int) -> bool:
    if freshness_hours <= 0:
        return False
    created = created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
    return age_seconds > freshness_hours * 3600


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
