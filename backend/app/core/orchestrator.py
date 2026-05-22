from __future__ import annotations

import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.answer_agent import draft_answer, parse_claims
from app.core.fallback import fallback_answer
from app.core.llm import LLMUnavailable
from app.core.outcomes import is_flagged_text, outcome_for_claims
from app.core.provenance import record_decision
from app.core.refusal import refusal_after_verification, should_refuse
from app.core.retrieval import retrieve
from app.core.trust_metrics import grounding_score
from app.core.types import ParsedClaim, RetrievedChunk
from app.core.verify_agent import verify_claims
from app.schemas import AskResponse, Citation, Trust


def run_ask(
    *,
    question: str,
    client_id: str | None,
    byo_key: str | None,
    db: Session,
    persist: bool = True,
    temperature: float | None = None,
    model: str | None = None,
) -> AskResponse:
    started = time.perf_counter()
    settings = get_settings()
    retrieved = retrieve(question, client_id=client_id, k=6)

    def persist_or_fake(
        outcome: str,
        answer: str | None,
        refusal_reason: str | None,
        kept: list[ParsedClaim] | None = None,
        dropped: list[ParsedClaim] | None = None,
        score: float | None = None,
        citations: list[Citation] | None = None,
    ) -> AskResponse:
        latency_ms = int((time.perf_counter() - started) * 1000)
        decision_id = (
            record_decision(
                db,
                question=question,
                client_id=client_id,
                outcome=outcome,
                final_answer=answer,
                retrieved_chunks=retrieved,
                kept_claims=kept or [],
                dropped_claims=dropped or [],
                llm_model=model or settings.llm_model,
                latency_ms=latency_ms,
                grounding_score=score,
            )
            if persist
            else str(uuid4())
        )
        return AskResponse(
            decision_id=decision_id,
            outcome=outcome,
            answer=answer,
            citations=citations or _citations_from_claims(kept or []),
            refusal_reason=refusal_reason,
            trust=Trust(grounding_score=score, determinism_score=None),
        )

    refuse, reason = should_refuse(question, retrieved)
    if refuse:
        return persist_or_fake("refused", None, reason)

    try:
        draft = draft_answer(
            question,
            retrieved,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
        )
        claims = parse_claims(draft, retrieved)
        if not claims:
            return persist_or_fake(
                "refused",
                None,
                "The answer agent did not produce any source-cited claims.",
            )
        kept, dropped = verify_claims(
            claims,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
        )
    except LLMUnavailable:
        answer, refusal_reason, citations, score = fallback_answer(
            question, client_id, retrieved
        )
        return persist_or_fake(
            "flagged" if is_flagged_text(answer) else "fallback",
            answer,
            refusal_reason,
            score=score,
            citations=citations,
        )

    refuse, reason = refusal_after_verification(len(kept))
    if refuse:
        return persist_or_fake("refused", None, reason, kept=[], dropped=dropped)

    score = grounding_score(kept)
    answer = "\n".join(f"{claim.claim_text} [{claim.cited_source_id}]" for claim in kept)
    return persist_or_fake(
        outcome_for_claims(kept),
        answer,
        None,
        kept=kept,
        dropped=dropped,
        score=score,
    )


def _citations_from_claims(claims: list[ParsedClaim]) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        if not claim.cited_source_id or not claim.source_text:
            continue
        key = (claim.cited_source_id, claim.source_text)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                source_id=claim.cited_source_id,
                source_type=claim.source_type or "unknown",
                snippet=claim.source_text[:600],
            )
        )
    return citations
