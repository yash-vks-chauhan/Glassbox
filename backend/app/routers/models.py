from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.core.model_eval import (
    dataset_summary,
    eval_run_detail,
    eval_run_history,
    evaluate_models,
    latest_leaderboard,
)
from app.core.model_approval import approved_model_routes, route_eval_approval
from app.core.model_router import production_model_status, provider_health
from app.config import get_settings
from app.db import get_db
from app.models_db import User
from app.schemas import ModelHealth, ModelLeaderboard, ProductionModelStatus


# Platform infra — model routing, eval gates, approval. Tenant admins don't
# control these (they're platform-wide); only platform-level admins / owners do.
# We map "admin" + "owner" to that here because we don't yet have a separate
# super-admin role.
_PLATFORM_ROLES = ("admin", "owner")


router = APIRouter(prefix="/models", tags=["models"])


@router.get("/health", response_model=list[ModelHealth])
def model_health(
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> list[dict]:
    return provider_health()


@router.get("/production-status", response_model=ProductionModelStatus)
def model_production_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    return production_model_status(db=db)


def _route_filter(raw: str | None) -> list[str] | None:
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else None


def _eval_limit(limit: int, gate: str | None) -> int:
    if gate == "fast":
        return get_settings().eval_fast_gate_size
    if gate == "full":
        return 10_000
    return limit


@router.get("/leaderboard", response_model=ModelLeaderboard)
def model_leaderboard(
    limit: int = Query(default=40, ge=8, le=164),
    gate: str | None = Query(default=None, pattern="^(fast|full)$"),
    determinism_runs: int = Query(default=2, ge=2, le=5),
    persist: bool = Query(default=False),
    live: bool = Query(default=False),
    routes: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    if not live:
        return latest_leaderboard(db, limit=limit)
    return evaluate_models(
        db,
        limit=_eval_limit(limit, gate),
        determinism_runs=determinism_runs,
        persist=persist,
        routes=_route_filter(routes),
    )


@router.post("/eval-runs", response_model=ModelLeaderboard)
def run_model_eval(
    limit: int = Query(default=40, ge=8, le=164),
    gate: str | None = Query(default="fast", pattern="^(fast|full)$"),
    determinism_runs: int = Query(default=2, ge=2, le=5),
    routes: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    return evaluate_models(
        db,
        limit=_eval_limit(limit, gate),
        determinism_runs=determinism_runs,
        persist=True,
        routes=_route_filter(routes),
    )


@router.get("/eval-runs")
def model_eval_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> list[dict]:
    return eval_run_history(db, limit=limit)


@router.get("/eval-runs/{run_id}")
def model_eval_run(
    run_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    detail = eval_run_detail(db, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return detail


@router.get("/eval-dataset")
def eval_dataset(
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    return dataset_summary()


@router.get("/approved")
def approved_models(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    routes = approved_model_routes(db)
    return {
        "approved_models": routes,
        "env": f"APPROVED_MODELS={','.join(routes)}",
    }


@router.get("/approval/{route:path}")
def model_approval(
    route: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_PLATFORM_ROLES)),
) -> dict:
    return route_eval_approval(route, db=db)
