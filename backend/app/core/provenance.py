from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.types import ParsedClaim, RetrievedChunk
from app.models_db import Decision, DecisionClaim, RetrievedChunk as RetrievedChunkRow


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
    grounding_score: float | None = None,
    determinism_score: float | None = None,
) -> str:
    decision = Decision(
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

    for chunk in retrieved_chunks:
        db.add(
            RetrievedChunkRow(
                decision_id=decision.id,
                source_id=chunk.source_id,
                source_type=chunk.source_type,
                chunk_text=chunk.chunk_text,
                score=chunk.score,
            )
        )

    for claim in kept_claims:
        db.add(
            DecisionClaim(
                decision_id=decision.id,
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                verified=claim.verified,
                kept=True,
            )
        )
    for claim in dropped_claims:
        db.add(
            DecisionClaim(
                decision_id=decision.id,
                claim_text=claim.claim_text,
                cited_source_id=claim.cited_source_id,
                verified=claim.verified,
                kept=False,
            )
        )
    db.commit()
    db.refresh(decision)
    return decision.id
