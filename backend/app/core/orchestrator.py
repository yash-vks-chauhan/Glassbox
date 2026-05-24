from __future__ import annotations

import re
import time
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.advisor_composer import compose_advisor_answer, compose_refusal_reason
from app.core.answerability import assess_answerability
from app.core.answer_agent import draft_answer, parse_claims
from app.core.fallback import fallback_answer
from app.core.llm import LLMUnavailable
from app.core.model_router import routes_for_chat
from app.core.outcomes import is_flagged_text, outcome_for_claims
from app.core.provenance import record_decision
from app.core.refusal import refusal_after_verification, should_refuse
from app.core.retrieval import evidence_quality, retrieve
from app.core.trust_metrics import grounding_score, score_claim_support
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
    allow_fallback: bool = True,
    enforce_production_gate: bool = True,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AskResponse:
    from app.models_db import DEMO_TENANT_ID

    started = time.perf_counter()
    settings = get_settings()
    retrieval_started = time.perf_counter()
    effective_tenant = tenant_id or DEMO_TENANT_ID
    retrieved = retrieve(question, client_id=client_id, k=6, tenant_id=effective_tenant)
    retrieval_ms = _elapsed_ms(retrieval_started)
    cache_hit = any(chunk.cache_hit for chunk in retrieved)
    quality = evidence_quality(retrieved)
    model_route = _model_route(model, byo_key)

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
                tenant_id=effective_tenant,
                user_id=user_id,
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
                refusal_reason=compose_refusal_reason(refusal_reason) if outcome == "refused" else refusal_reason,
            trust=Trust(
                grounding_score=score,
                determinism_score=None,
                model_route=model_route,
                retrieval_ms=retrieval_ms,
                generation_ms=0,
                verification_ms=0,
                total_ms=latency_ms,
                evidence_quality=quality,
                cache_hit=cache_hit,
            ),
        )

    refuse, reason = should_refuse(question, retrieved)
    if refuse:
        return persist_or_fake("refused", None, reason)
    answerability = assess_answerability(question, client_id, retrieved)
    if not answerability.answerable:
        return persist_or_fake("refused", None, answerability.reason)

    generation_ms = 0
    verification_ms = 0
    try:
        generation_started = time.perf_counter()
        draft = draft_answer(
            question,
            retrieved,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        generation_ms = _elapsed_ms(generation_started)
        claims = parse_claims(draft, retrieved)
        if not claims:
            response = persist_or_fake(
                "refused",
                None,
                "The answer agent did not produce any source-cited claims.",
            )
            response.trust.generation_ms = generation_ms
            return response
        verification_started = time.perf_counter()
        kept, dropped = verify_claims(
            claims,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        verification_ms = _elapsed_ms(verification_started)
    except LLMUnavailable:
        if settings.production_mode and enforce_production_gate:
            raise
        if not allow_fallback:
            raise
        answer, refusal_reason, citations, score = fallback_answer(
            question, client_id, retrieved
        )
        response = persist_or_fake(
            "flagged" if is_flagged_text(answer) else "fallback",
            answer,
            refusal_reason,
            score=score,
            citations=citations,
        )
        response.trust.model_route = "local:glassbox-deterministic-fallback"
        return response

    _append_guardrail_claims(question, client_id, retrieved, kept)

    refuse, reason = refusal_after_verification(len(kept))
    if refuse:
        response = persist_or_fake("refused", None, reason, kept=[], dropped=dropped)
        response.trust.generation_ms = generation_ms
        response.trust.verification_ms = verification_ms
        return response

    score = grounding_score(kept)
    answer = _render_grounded_answer(question, kept)
    response = persist_or_fake(
        outcome_for_claims(kept),
        answer,
        None,
        kept=kept,
        dropped=dropped,
        score=score,
    )
    response.trust.generation_ms = generation_ms
    response.trust.verification_ms = verification_ms
    response.trust.total_ms = _elapsed_ms(started)
    return response


def run_ask_events(
    *,
    question: str,
    client_id: str | None,
    byo_key: str | None,
    db: Session,
    persist: bool = True,
    temperature: float | None = None,
    model: str | None = None,
    allow_fallback: bool = True,
    enforce_production_gate: bool = True,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> Iterator[dict]:
    yield {"event": "accepted", "data": {"question": question, "client_id": client_id}}
    from app.models_db import DEMO_TENANT_ID

    effective_tenant = tenant_id or DEMO_TENANT_ID
    started = time.perf_counter()
    retrieval_started = time.perf_counter()
    retrieved = retrieve(question, client_id=client_id, k=6, tenant_id=effective_tenant)
    retrieval_ms = _elapsed_ms(retrieval_started)
    quality = evidence_quality(retrieved)
    cache_hit = any(chunk.cache_hit for chunk in retrieved)
    model_route = _model_route(model, byo_key)
    yield {
        "event": "retrieval_done",
        "data": {
            "retrieval_ms": retrieval_ms,
            "evidence_quality": quality,
            "cache_hit": cache_hit,
            "sources": list(dict.fromkeys(chunk.source_id for chunk in retrieved)),
        },
    }

    def attach_timing(response: AskResponse, generation_ms: int = 0, verification_ms: int = 0) -> AskResponse:
        response.trust.model_route = response.trust.model_route or model_route
        response.trust.retrieval_ms = retrieval_ms
        response.trust.generation_ms = generation_ms
        response.trust.verification_ms = verification_ms
        response.trust.total_ms = _elapsed_ms(started)
        response.trust.evidence_quality = quality
        response.trust.cache_hit = cache_hit
        return response

    refuse, reason = should_refuse(question, retrieved)
    if refuse:
        response = _persist_stream_response(
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=model,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(reason),
            trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": response}
        return

    answerability = assess_answerability(question, client_id, retrieved)
    if not answerability.answerable:
        response = _persist_stream_response(
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=model,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(answerability.reason),
            trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": response}
        return

    yield {"event": "generation_started", "data": {"model_route": model_route}}
    try:
        generation_started = time.perf_counter()
        draft = draft_answer(
            question,
            retrieved,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        generation_ms = _elapsed_ms(generation_started)
        claims = parse_claims(draft, retrieved)
        if not claims:
            response = _persist_stream_response(
                db=db,
                persist=persist,
                question=question,
                client_id=client_id,
                model=model,
                retrieved=retrieved,
                started=started,
                outcome="refused",
                answer=None,
                refusal_reason=compose_refusal_reason("The answer agent did not produce any source-cited claims."),
                trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, evidence_quality=quality, cache_hit=cache_hit),
                tenant_id=effective_tenant,
                user_id=user_id,
            )
            yield {"event": "verification_done", "data": {"kept": 0, "dropped": 0, "verification_ms": 0}}
            yield {"event": "final", "data": attach_timing(response, generation_ms, 0)}
            return
        verification_started = time.perf_counter()
        kept, dropped = verify_claims(
            claims,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        verification_ms = _elapsed_ms(verification_started)
    except LLMUnavailable as exc:
        if get_settings().production_mode and enforce_production_gate:
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        if not allow_fallback:
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        answer, refusal_reason, citations, score = fallback_answer(question, client_id, retrieved)
        response = _persist_stream_response(
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model="local:glassbox-deterministic-fallback",
            retrieved=retrieved,
            started=started,
            outcome="flagged" if is_flagged_text(answer) else "fallback",
            answer=answer,
            refusal_reason=refusal_reason,
            citations=citations,
            score=score,
            trust=Trust(model_route="local:glassbox-deterministic-fallback", retrieval_ms=retrieval_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "verification_done", "data": {"kept": 0, "dropped": 0, "verification_ms": 0}}
        yield {"event": "final", "data": attach_timing(response)}
        return

    _append_guardrail_claims(question, client_id, retrieved, kept)
    yield {
        "event": "verification_done",
        "data": {"kept": len(kept), "dropped": len(dropped), "verification_ms": verification_ms},
    }

    refuse, reason = refusal_after_verification(len(kept))
    if refuse:
        response = _persist_stream_response(
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=model,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(reason),
            kept=[],
            dropped=dropped,
            trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, verification_ms=verification_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": attach_timing(response, generation_ms, verification_ms)}
        return

    score = grounding_score(kept)
    response = _persist_stream_response(
        db=db,
        persist=persist,
        question=question,
        client_id=client_id,
        model=model,
        retrieved=retrieved,
        started=started,
        outcome=outcome_for_claims(kept),
        answer=_render_grounded_answer(question, kept),
        refusal_reason=None,
        kept=kept,
        dropped=dropped,
        score=score,
        trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, verification_ms=verification_ms, evidence_quality=quality, cache_hit=cache_hit),
        tenant_id=effective_tenant,
        user_id=user_id,
    )
    yield {"event": "final", "data": attach_timing(response, generation_ms, verification_ms)}


def _persist_stream_response(
    *,
    db: Session,
    persist: bool,
    question: str,
    client_id: str | None,
    model: str | None,
    retrieved: list[RetrievedChunk],
    started: float,
    outcome: str,
    answer: str | None,
    refusal_reason: str | None,
    kept: list[ParsedClaim] | None = None,
    dropped: list[ParsedClaim] | None = None,
    citations: list[Citation] | None = None,
    score: float | None = None,
    trust: Trust | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AskResponse:
    from app.models_db import DEMO_TENANT_ID

    latency_ms = _elapsed_ms(started)
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
            llm_model=model or get_settings().llm_model,
            latency_ms=latency_ms,
            tenant_id=tenant_id or DEMO_TENANT_ID,
            user_id=user_id,
            grounding_score=score,
        )
        if persist
        else str(uuid4())
    )
    response_trust = trust or Trust()
    response_trust.grounding_score = score
    response_trust.total_ms = latency_ms
    return AskResponse(
        decision_id=decision_id,
        outcome=outcome,
        answer=answer,
        citations=citations or _citations_from_claims(kept or []),
        refusal_reason=refusal_reason,
        trust=response_trust,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _model_route(model: str | None, byo_key: str | None) -> str:
    try:
        return routes_for_chat(model_override=model, api_key=byo_key)[0].spec
    except Exception:
        return model or get_settings().llm_model


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


def _allocation_violation_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    proposed = _first_percent(question)
    if proposed is None:
        return None
    limit_chunk = next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_type == "ips"
            and (client_id is None or chunk.source_id == client_id)
            and "single position" in chunk.chunk_text.lower()
        ),
        None,
    )
    if not limit_chunk:
        return None
    limit = _first_percent(limit_chunk.chunk_text)
    if limit is None or proposed <= limit:
        return None
    claim_text = (
        f"The proposed {proposed}% allocation violates Client {limit_chunk.source_id}'s "
        f"single-position limit because no single position may exceed {limit}% of "
        "portfolio value."
    )
    return ParsedClaim(
        claim_text=claim_text,
        cited_source_id=limit_chunk.source_id,
        source_text=limit_chunk.chunk_text,
        source_type=limit_chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=score_claim_support(claim_text, limit_chunk.chunk_text),
    )


def _append_guardrail_claims(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
    kept: list[ParsedClaim],
) -> None:
    if any(is_flagged_text(claim.claim_text) for claim in kept):
        return
    for claim in [
        _allocation_violation_claim(question, client_id, retrieved),
        _liquidity_violation_claim(question, client_id, retrieved),
        _exclusion_violation_claim(question, client_id, retrieved),
    ]:
        if claim:
            kept.append(claim)
            return


def _liquidity_violation_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not re.search(r"\b(liquid|liquidity)\b", question, re.I):
        return None
    proposed = _first_percent(question)
    if proposed is None:
        return None
    chunk = next(
        (
            item
            for item in retrieved
            if item.source_type == "ips"
            and (client_id is None or item.source_id == client_id)
            and "liquid" in item.chunk_text.lower()
        ),
        None,
    )
    if not chunk:
        return None
    floor = _first_percent(chunk.chunk_text)
    if floor is None or proposed >= floor:
        return None
    claim_text = (
        f"The proposed {proposed}% liquidity level violates Client {chunk.source_id}'s "
        f"liquidity floor because at least {floor}% must remain liquid within 30 days."
    )
    return ParsedClaim(
        claim_text=claim_text,
        cited_source_id=chunk.source_id,
        source_text=chunk.chunk_text,
        source_type=chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=score_claim_support(claim_text, chunk.chunk_text),
    )


def _exclusion_violation_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    q = question.lower()
    terms = ["tobacco", "firearms", "gambling", "cryptocurrency", "russia"]
    term = next((item for item in terms if item in q), None)
    if not term:
        return None
    chunk = next(
        (
            item
            for item in retrieved
            if item.source_type == "ips"
            and (client_id is None or item.source_id == client_id)
            and term in item.chunk_text.lower()
            and re.search(r"\b(must not|excluded|exclude|prohibited|restriction)\b", item.chunk_text, re.I)
        ),
        None,
    )
    if not chunk:
        return None
    claim_text = f"Client {chunk.source_id} must not take exposure to {term} under the sourced IPS restriction."
    return ParsedClaim(
        claim_text=claim_text,
        cited_source_id=chunk.source_id,
        source_text=chunk.chunk_text,
        source_type=chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=score_claim_support(claim_text, chunk.chunk_text),
    )


def _first_percent(text: str) -> int | None:
    match = re.search(r"(\d+)\s*%", text)
    return int(match.group(1)) if match else None


def _render_grounded_answer(question: str, claims: list[ParsedClaim]) -> str:
    lines = [f"{claim.claim_text} [{claim.cited_source_id}]" for claim in claims]
    if get_settings().answer_generation_mode == "claims":
        return "\n".join(lines)
    return compose_advisor_answer(
        question=question,
        outcome=outcome_for_claims(claims),
        claims=claims,
    )
