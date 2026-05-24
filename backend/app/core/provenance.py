from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security.audit_hash import (
    canonical_decision_payload,
    compute_row_hash,
    latest_tail_hash,
)
from app.core.types import ParsedClaim, RetrievedChunk
from app.models_db import (
    DEMO_TENANT_ID,
    Decision,
    DecisionClaim,
    RetrievedChunk as RetrievedChunkRow,
)


def record_decision(
    db: Session,
    *,
    question: str,
    client_id: str | None,
    outcome: str,
    final_answer: str | None,
    retrieved_chunks: list[RetrievedChunk],
    kept_claims: list[ParsedClaim],
    dropped_claims: list[ParsedClaim],
    llm_model: str,
    latency_ms: int,
    tenant_id: str = DEMO_TENANT_ID,
    user_id: str | None = None,
    grounding_score: float | None = None,
    determinism_score: float | None = None,
) -> str:
    decision = Decision(
        tenant_id=tenant_id,
        user_id=user_id,
        question=question,
        client_id=client_id,
        outcome=outcome,
        final_answer=final_answer,
        determinism_score=determinism_score,
        grounding_score=grounding_score,
        llm_model=llm_model,
        latency_ms=latency_ms,
    )
    db.add(decision)
    db.flush()

    chunk_rows: list[RetrievedChunkRow] = []
    for chunk in retrieved_chunks:
        row = RetrievedChunkRow(
            tenant_id=tenant_id,
            decision_id=decision.id,
            source_id=chunk.source_id,
            source_type=chunk.source_type,
            chunk_text=chunk.chunk_text,
            score=chunk.score,
            file=chunk.file,
            chunk_index=chunk.chunk_index,
            source_version=chunk.source_version,
            selected_reason=chunk.selected_reason,
        )
        db.add(row)
        chunk_rows.append(row)

    claim_rows: list[DecisionClaim] = []
    for claim in kept_claims:
        row = DecisionClaim(
            tenant_id=tenant_id,
            decision_id=decision.id,
            claim_text=claim.claim_text,
            cited_source_id=claim.cited_source_id,
            verified=claim.verified,
            kept=True,
        )
        db.add(row)
        claim_rows.append(row)
    for claim in dropped_claims:
        row = DecisionClaim(
            tenant_id=tenant_id,
            decision_id=decision.id,
            claim_text=claim.claim_text,
            cited_source_id=claim.cited_source_id,
            verified=claim.verified,
            kept=False,
        )
        db.add(row)
        claim_rows.append(row)

    # Phase E — link this row into the tenant's hash chain *before* the
    # commit so prev_hash / row_hash land in the same transaction as the
    # decision content. Reading the tail with the same session sees uncommitted
    # work from this transaction too, but every other tenant's chain is
    # invisible to us so concurrent inserts on a different tenant don't race.
    # Genesis rows store ``""`` (not NULL) so verify_chain can distinguish
    # "head of chain" from "legacy pre-Phase-E row".
    db.flush()
    decision.prev_hash = latest_tail_hash(db, tenant_id=tenant_id) or ""
    canonical = canonical_decision_payload(decision, claim_rows, chunk_rows)
    decision.row_hash = compute_row_hash(decision.prev_hash, canonical)

    db.commit()
    db.refresh(decision)
    return decision.id
