"""Compliance reviews of decisions: POST/GET /decisions/{id}/reviews."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth.deps import current_user, require_role
from app.core.reviews import review_out, reviews_for_decision, submit_review
from app.db import get_db
from app.models_db import Decision, User
from app.schemas import ReviewCreateRequest, ReviewOut


router = APIRouter(prefix="/decisions", tags=["reviews"])

_REVIEWER_ROLES = ("compliance", "admin", "owner")
_TENANT_WIDE_ROLES = frozenset(_REVIEWER_ROLES)


def _decision_for(db: Session, user: User, decision_id: str, *, with_evidence: bool = False):
    stmt = select(Decision).where(
        Decision.tenant_id == user.tenant_id, Decision.id == decision_id
    )
    if user.role not in _TENANT_WIDE_ROLES:
        stmt = stmt.where(Decision.user_id == user.id)
    if with_evidence:
        stmt = stmt.options(
            selectinload(Decision.claims), selectinload(Decision.retrieved_chunks)
        )
    decision = db.scalar(stmt)
    if decision is None:
        # 404, never 403, so other tenants can't probe for decision ids.
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.post(
    "/{decision_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    decision_id: str,
    payload: ReviewCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_REVIEWER_ROLES)),
) -> ReviewOut:
    decision = _decision_for(db, user, decision_id, with_evidence=True)
    review = submit_review(db, decision=decision, reviewer=user, payload=payload)
    return review_out(db, review)


@router.get("/{decision_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    decision_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ReviewOut]:
    """Advisors see the reviews of their own decisions; reviewers see all
    of the tenant's."""
    decision = _decision_for(db, user, decision_id)
    return reviews_for_decision(db, tenant_id=user.tenant_id, decision_id=decision.id)
