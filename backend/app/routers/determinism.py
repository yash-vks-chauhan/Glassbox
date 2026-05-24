from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth.deps import require_role
from app.core.trust_metrics import determinism_run
from app.db import get_db
from app.models_db import User
from app.schemas import DeterminismRequest, DeterminismResponse


router = APIRouter(tags=["determinism"])


@router.post("/determinism", response_model=DeterminismResponse)
def determinism(
    request: DeterminismRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("compliance", "admin", "owner")),
) -> DeterminismResponse:
    score, representative_id, responses = determinism_run(
        question=request.question,
        client_id=request.client_id,
        db=db,
        runs=request.runs,
        alternate_model=request.alternate_model,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    return DeterminismResponse(
        determinism_score=score,
        representative_decision_id=representative_id,
        per_run_outcomes=responses,
    )
