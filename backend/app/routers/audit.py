from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models_db import Decision
from app.schemas import AuditDetail, AuditSummary, ClaimOut, RetrievedChunkOut


router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditSummary])
def list_audit(
    limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)
) -> list[AuditSummary]:
    rows = db.scalars(
        select(Decision).order_by(Decision.created_at.desc()).limit(limit)
    ).all()
    return [_summary(row) for row in rows]


@router.get("/audit/{decision_id}", response_model=AuditDetail)
def get_audit(decision_id: str, db: Session = Depends(get_db)) -> AuditDetail:
    row = db.scalar(
        select(Decision)
        .where(Decision.id == decision_id)
        .options(selectinload(Decision.claims), selectinload(Decision.retrieved_chunks))
    )
    if row is None:
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
