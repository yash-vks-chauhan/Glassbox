from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth.deps import current_user, require_role
from app.core.security.audit_hash import verify_chain
from app.db import get_db
from app.models_db import Decision, User
from app.schemas import (
    AuditDetail,
    AuditSummary,
    AuditVerifyResponse,
    ClaimOut,
    RetrievedChunkOut,
)


router = APIRouter(tags=["audit"])


# Roles permitted to see *every* decision in their tenant. Advisors see only
# their own audits — they don't get to read another advisor's traces.
_TENANT_WIDE_AUDIT_ROLES = frozenset({"compliance", "admin", "owner"})
_VERIFY_ROLES = ("compliance", "admin", "owner")


def _scoped_decision_query(user: User):
    """Base SELECT that already filters by tenant + (for advisors) by user."""
    stmt = select(Decision).where(Decision.tenant_id == user.tenant_id)
    if user.role not in _TENANT_WIDE_AUDIT_ROLES:
        stmt = stmt.where(Decision.user_id == user.id)
    return stmt


@router.get("/audit", response_model=list[AuditSummary])
def list_audit(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[AuditSummary]:
    rows = db.scalars(
        _scoped_decision_query(user)
        .order_by(Decision.created_at.desc())
        .limit(limit)
    ).all()
    return [_summary(row) for row in rows]


# IMPORTANT: register this BEFORE /audit/{decision_id}. FastAPI matches
# top-down, so a generic path-parameter route would otherwise swallow
# /audit/verify and try to load a Decision with id "verify".
@router.get("/audit/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_VERIFY_ROLES)),
) -> AuditVerifyResponse:
    """Walk the caller's tenant hash chain and report the first break, if
    any. Compliance+ only — random advisors don't run integrity audits.

    A 200 with ``ok: true`` means every decision row's stored hash matches
    the canonical hash of its content + the prior row's hash, all the way
    back to genesis. A 200 with ``ok: false`` points at the first row that
    diverges plus an interpretable reason."""
    report = verify_chain(db, tenant_id=user.tenant_id)
    return AuditVerifyResponse(
        tenant_id=report.tenant_id,
        ok=report.ok,
        total=report.total,
        verified=report.verified,
        first_break_decision_id=report.first_break_decision_id,
        first_break_reason=report.first_break_reason,
        tail_hash=report.tail_hash,
    )


@router.get("/audit/{decision_id}", response_model=AuditDetail)
def get_audit(
    decision_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuditDetail:
    row = db.scalar(
        _scoped_decision_query(user)
        .where(Decision.id == decision_id)
        .options(selectinload(Decision.claims), selectinload(Decision.retrieved_chunks))
    )
    if row is None:
        # 404 deliberately — never 403 — so cross-tenant probes can't confirm
        # whether a decision_id exists in another tenant.
        raise HTTPException(status_code=404, detail="Decision not found")
    return AuditDetail(
        **_summary(row).model_dump(),
        final_answer=row.final_answer,
        retrieved_chunks=[
            RetrievedChunkOut(
                source_id=chunk.source_id,
                source_type=chunk.source_type,
                chunk_text=chunk.chunk_text,
                score=chunk.score,
                file=chunk.file,
                chunk_index=chunk.chunk_index,
                source_version=chunk.source_version,
                selected_reason=chunk.selected_reason,
            )
            for chunk in row.retrieved_chunks
        ],
        decision_claims=[
            ClaimOut(
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                verified=claim.verified,
                kept=claim.kept,
            )
            for claim in row.claims
        ],
    )


def _summary(row: Decision) -> AuditSummary:
    return AuditSummary(
        id=row.id,
        created_at=row.created_at.isoformat(),
        question=row.question,
        client_id=row.client_id,
        outcome=row.outcome,
        grounding_score=row.grounding_score,
        determinism_score=row.determinism_score,
        latency_ms=row.latency_ms,
    )
