from __future__ import annotations

import re
import time
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.advisor_composer import compose_advisor_answer, compose_refusal_reason
from app.core.answerability import assess_answerability
from app.core.answer_agent import draft_answer_result, parse_claims
from app.core.fallback import fallback_answer
from app.core.llm import LLMUnavailable
from app.core.model_router import LOCAL_EVIDENCE_ROUTE, routes_for_chat
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
    asked_question: str | None = None,
    thread_id: str | None = None,
) -> AskResponse:
    """Answer ``question``. In a thread, ``question`` is the context-resolved
    question used for retrieval and reasoning, and ``asked_question`` is the
    advisor's literal text; both are recorded."""
    from app.models_db import DEMO_TENANT_ID

    started = time.perf_counter()
    settings = get_settings()
    retrieval_started = time.perf_counter()
    effective_tenant = tenant_id or DEMO_TENANT_ID
    retrieved = retrieve(question, client_id=client_id, k=8, tenant_id=effective_tenant)
    retrieval_ms = _elapsed_ms(retrieval_started)
    cache_hit = any(chunk.cache_hit for chunk in retrieved)
    quality = evidence_quality(retrieved)
    model_route = _model_route(model, byo_key)
    actual_model_route = model_route

    def persist_or_fake(
        outcome: str,
        answer: str | None,
        refusal_reason: str | None,
        kept: list[ParsedClaim] | None = None,
        dropped: list[ParsedClaim] | None = None,
        score: float | None = None,
        citations: list[Citation] | None = None,
        llm_model: str | None = None,
    ) -> AskResponse:
        latency_ms = int((time.perf_counter() - started) * 1000)
        shown_refusal = (
            compose_refusal_reason(refusal_reason, question=question)
            if outcome == "refused"
            else refusal_reason
        )
        decision_id = (
            record_decision(
                db,
                question=asked_question or question,
                client_id=client_id,
                outcome=outcome,
                final_answer=answer,
                retrieved_chunks=retrieved,
                kept_claims=kept or [],
                dropped_claims=dropped or [],
                llm_model=llm_model or actual_model_route,
                latency_ms=latency_ms,
                tenant_id=effective_tenant,
                user_id=user_id,
                grounding_score=score,
                thread_id=thread_id,
                retrieval_question=question,
                refusal_reason=shown_refusal,
            )
            if persist
            else str(uuid4())
        )
        return AskResponse(
            decision_id=decision_id,
            outcome=outcome,
            answer=answer,
            citations=citations or _citations_from_claims(kept or []),
            refusal_reason=shown_refusal,
            trust=Trust(
                grounding_score=score,
                determinism_score=None,
                model_route=llm_model or actual_model_route,
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
    if _use_local_evidence_mode(model):
        evidence_started = time.perf_counter()
        kept = _local_evidence_claims(question, client_id, retrieved)
        decision_claims = _claims_for_decision(question, kept)
        generation_ms = _elapsed_ms(evidence_started)
        refuse, reason = refusal_after_verification(len(decision_claims))
        if refuse:
            response = persist_or_fake(
                "refused",
                None,
                "The local evidence engine did not find source-backed decision claims.",
                kept=[],
                dropped=[],
                llm_model=LOCAL_EVIDENCE_ROUTE,
            )
            response.trust.generation_ms = generation_ms
            return response
        score = grounding_score(decision_claims)
        answer = _render_grounded_answer(question, decision_claims)
        response = persist_or_fake(
            outcome_for_claims(decision_claims),
            answer,
            None,
            kept=decision_claims,
            dropped=[],
            score=score,
            llm_model=LOCAL_EVIDENCE_ROUTE,
        )
        response.trust.generation_ms = generation_ms
        response.trust.verification_ms = 0
        response.trust.total_ms = _elapsed_ms(started)
        return response

    try:
        generation_started = time.perf_counter()
        draft_result = draft_answer_result(
            question,
            retrieved,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        actual_model_route = draft_result.model_route
        draft = draft_result.text
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
            model=actual_model_route,
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
            llm_model="local:glassbox-deterministic-fallback",
        )
        response.trust.model_route = "local:glassbox-deterministic-fallback"
        return response

    _append_guardrail_claims(question, client_id, retrieved, kept)
    decision_claims = _claims_for_decision(question, kept)

    refuse, reason = refusal_after_verification(len(decision_claims))
    if refuse:
        response = persist_or_fake("refused", None, reason, kept=[], dropped=dropped)
        response.trust.generation_ms = generation_ms
        response.trust.verification_ms = verification_ms
        return response

    score = grounding_score(decision_claims)
    answer = _render_grounded_answer(question, decision_claims)
    response = persist_or_fake(
        outcome_for_claims(decision_claims),
        answer,
        None,
        kept=decision_claims,
        dropped=dropped,
        score=score,
        llm_model=actual_model_route,
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
    asked_question: str | None = None,
    thread_id: str | None = None,
) -> Iterator[dict]:
    """Streaming twin of ``run_ask``; same ``asked_question``/``thread_id``
    contract."""
    yield {"event": "accepted", "data": {"question": question, "client_id": client_id}}
    context = {"asked_question": asked_question, "thread_id": thread_id}
    from app.models_db import DEMO_TENANT_ID

    effective_tenant = tenant_id or DEMO_TENANT_ID
    started = time.perf_counter()
    retrieval_started = time.perf_counter()
    retrieved = retrieve(question, client_id=client_id, k=8, tenant_id=effective_tenant)
    retrieval_ms = _elapsed_ms(retrieval_started)
    quality = evidence_quality(retrieved)
    cache_hit = any(chunk.cache_hit for chunk in retrieved)
    model_route = _model_route(model, byo_key)
    actual_model_route = model_route
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
            **context,
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=model,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(reason, question=question),
            trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": response}
        return

    answerability = assess_answerability(question, client_id, retrieved)
    if not answerability.answerable:
        response = _persist_stream_response(
            **context,
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=model,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(answerability.reason, question=question),
            trust=Trust(model_route=model_route, retrieval_ms=retrieval_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": response}
        return

    if _use_local_evidence_mode(model):
        yield {"event": "generation_started", "data": {"model_route": LOCAL_EVIDENCE_ROUTE}}
        evidence_started = time.perf_counter()
        kept = _local_evidence_claims(question, client_id, retrieved)
        decision_claims = _claims_for_decision(question, kept)
        generation_ms = _elapsed_ms(evidence_started)
        yield {
            "event": "verification_done",
            "data": {"kept": len(decision_claims), "dropped": 0, "verification_ms": 0},
        }
        refuse, reason = refusal_after_verification(len(decision_claims))
        if refuse:
            response = _persist_stream_response(
                **context,
                db=db,
                persist=persist,
                question=question,
                client_id=client_id,
                model=LOCAL_EVIDENCE_ROUTE,
                retrieved=retrieved,
                started=started,
                outcome="refused",
                answer=None,
                refusal_reason=compose_refusal_reason(
                    "The local evidence engine did not find source-backed decision claims.",
                    question=question,
                ),
                kept=[],
                dropped=[],
                trust=Trust(
                    model_route=LOCAL_EVIDENCE_ROUTE,
                    retrieval_ms=retrieval_ms,
                    generation_ms=generation_ms,
                    verification_ms=0,
                    evidence_quality=quality,
                    cache_hit=cache_hit,
                ),
                tenant_id=effective_tenant,
                user_id=user_id,
            )
            yield {"event": "final", "data": attach_timing(response, generation_ms, 0)}
            return
        score = grounding_score(decision_claims)
        response = _persist_stream_response(
            **context,
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=LOCAL_EVIDENCE_ROUTE,
            retrieved=retrieved,
            started=started,
            outcome=outcome_for_claims(decision_claims),
            answer=_render_grounded_answer(question, decision_claims),
            refusal_reason=None,
            kept=decision_claims,
            dropped=[],
            score=score,
            trust=Trust(
                model_route=LOCAL_EVIDENCE_ROUTE,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
                verification_ms=0,
                evidence_quality=quality,
                cache_hit=cache_hit,
            ),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": attach_timing(response, generation_ms, 0)}
        return

    yield {"event": "generation_started", "data": {"model_route": model_route}}
    try:
        generation_started = time.perf_counter()
        draft_result = draft_answer_result(
            question,
            retrieved,
            temperature=temperature,
            model=model,
            byo_key=byo_key,
            enforce_production_gate=enforce_production_gate,
        )
        actual_model_route = draft_result.model_route
        draft = draft_result.text
        generation_ms = _elapsed_ms(generation_started)
        claims = parse_claims(draft, retrieved)
        if not claims:
            response = _persist_stream_response(
                **context,
                db=db,
                persist=persist,
                question=question,
                client_id=client_id,
                model=actual_model_route,
                retrieved=retrieved,
                started=started,
                outcome="refused",
                answer=None,
                refusal_reason=compose_refusal_reason(
                    "The answer agent did not produce any source-cited claims.",
                    question=question,
                ),
                trust=Trust(model_route=actual_model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, evidence_quality=quality, cache_hit=cache_hit),
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
            model=actual_model_route,
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
            **context,
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
    decision_claims = _claims_for_decision(question, kept)
    yield {
        "event": "verification_done",
        "data": {"kept": len(decision_claims), "dropped": len(dropped), "verification_ms": verification_ms},
    }

    refuse, reason = refusal_after_verification(len(decision_claims))
    if refuse:
        response = _persist_stream_response(
            **context,
            db=db,
            persist=persist,
            question=question,
            client_id=client_id,
            model=actual_model_route,
            retrieved=retrieved,
            started=started,
            outcome="refused",
            answer=None,
            refusal_reason=compose_refusal_reason(reason, question=question),
            kept=[],
            dropped=dropped,
            trust=Trust(model_route=actual_model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, verification_ms=verification_ms, evidence_quality=quality, cache_hit=cache_hit),
            tenant_id=effective_tenant,
            user_id=user_id,
        )
        yield {"event": "final", "data": attach_timing(response, generation_ms, verification_ms)}
        return

    score = grounding_score(decision_claims)
    response = _persist_stream_response(
        **context,
        db=db,
        persist=persist,
        question=question,
        client_id=client_id,
        model=actual_model_route,
        retrieved=retrieved,
        started=started,
        outcome=outcome_for_claims(decision_claims),
        answer=_render_grounded_answer(question, decision_claims),
        refusal_reason=None,
        kept=decision_claims,
        dropped=dropped,
        score=score,
        trust=Trust(model_route=actual_model_route, retrieval_ms=retrieval_ms, generation_ms=generation_ms, verification_ms=verification_ms, evidence_quality=quality, cache_hit=cache_hit),
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
    asked_question: str | None = None,
    thread_id: str | None = None,
) -> AskResponse:
    from app.models_db import DEMO_TENANT_ID

    latency_ms = _elapsed_ms(started)
    decision_id = (
        record_decision(
            db,
            question=asked_question or question,
            thread_id=thread_id,
            retrieval_question=question,
            refusal_reason=refusal_reason,
            client_id=client_id,
            outcome=outcome,
            final_answer=answer,
            retrieved_chunks=retrieved,
            kept_claims=kept or [],
            dropped_claims=dropped or [],
            llm_model=model or (trust.model_route if trust and trust.model_route else get_settings().llm_model),
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
    if _use_local_evidence_mode(model):
        return LOCAL_EVIDENCE_ROUTE
    try:
        return routes_for_chat(model_override=model, api_key=byo_key)[0].spec
    except Exception:
        return model or get_settings().llm_model


def _use_local_evidence_mode(model: str | None) -> bool:
    if model:
        return model == LOCAL_EVIDENCE_ROUTE
    return get_settings().local_evidence_mode


def _local_evidence_claims(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    claims: list[ParsedClaim] = []
    _append_guardrail_claims(question, client_id, retrieved, claims)
    for claim in [
        _single_position_lookup_claim(question, client_id, retrieved),
        _liquidity_lookup_claim(question, client_id, retrieved),
        _client_context_claim(question, client_id, retrieved),
        *_portfolio_evidence_claims(question, client_id, retrieved),
        *_factsheet_evidence_claims(question, retrieved),
        *_regulation_evidence_claims(question, retrieved),
        *_tax_guidance_claims(question, retrieved),
        *_jurisdiction_guidance_claims(question, client_id, retrieved),
        *_exception_guidance_claims(question, retrieved),
    ]:
        if claim:
            _append_claim_once(claims, claim)
    return claims


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


def _claims_for_decision(question: str, claims: list[ParsedClaim]) -> list[ParsedClaim]:
    unique = _dedupe_final_claims(claims)
    relevant = [claim for claim in unique if _claim_relevant_to_decision(question, claim)]
    if relevant:
        if (
            _asks_suitability_or_risk(question)
            and not _asks_sources_to_cite(question)
            and not _asks_portfolio_context(question)
        ):
            high_support = [
                claim
                for claim in relevant
                if (claim.grounding_score if claim.grounding_score is not None else 0.0) >= 0.9
            ]
            if high_support:
                return high_support
        return relevant
    if _has_specific_decision_topic(question):
        return []
    return unique


def _dedupe_final_claims(claims: list[ParsedClaim]) -> list[ParsedClaim]:
    deduped: list[ParsedClaim] = []
    seen: set[tuple[str | None, str]] = set()
    for claim in claims:
        text = re.sub(r"[^a-z0-9%]+", " ", claim.claim_text.lower()).strip()
        key = (claim.cited_source_id, text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _claim_relevant_to_decision(question: str, claim: ParsedClaim) -> bool:
    q = question.lower()
    text = claim.claim_text.lower()
    primary_funds = _primary_fund_ids(question)
    if primary_funds and claim.source_type == "factsheet" and claim.cited_source_id not in primary_funds:
        return False
    if claim.source_type == "portfolio":
        if _asks_sources_to_cite(question):
            return not is_flagged_text(text)
        return _asks_portfolio_context(question) or _asks_suitability_or_risk(question)
    asked_term = _asked_restricted_term(question)
    if _asks_allocation_limit(question):
        if _asks_fund_transaction(question):
            return bool(
                re.search(
                    r"\b(single[- ]position|position limit|portfolio value|allocation|concentration|exceed|violat|breach|risk|suitab\w*|recommend\w*|profile|high|moderate|low|sector|technology|equity|human review)\b",
                    text,
                    re.I,
                )
            )
        return bool(
            re.search(
                r"\b(single[- ]position|position limit|portfolio value|allocation|concentration|exceed|violat|breach)\b",
                text,
                re.I,
            )
        )
    if _asks_tax_guidance(question):
        return claim.cited_source_id == "REG-TAX-GUIDANCE" and bool(
            re.search(r"\b(tax|memo|tax desk|must not quote|jurisdiction)\b", text, re.I)
        )
    if _asks_jurisdiction(question):
        return bool(
            (
                claim.cited_source_id == "REG-JURISDICTION"
                and re.search(r"\b(jurisdiction|cross-border|ips|compliance)\b", text, re.I)
            )
            or (
                claim.source_type == "ips"
                and re.search(r"\b(governed by|jurisdiction|constraints)\b", text, re.I)
            )
        )
    if _asks_exception_process(question):
        if re.search(r"\b(source|cited|cite|process)\b", question, re.I):
            return claim.cited_source_id == "REG-EXCEPTIONS"
        return claim.cited_source_id == "REG-EXCEPTIONS" or bool(
            claim.source_type == "ips" and re.search(r"\b(single[- ]position|liquid|must not)\b", text, re.I)
        )
    if _asks_fund_liquidity_treatment(question):
        return bool(
            re.search(r"\b(liquid|liquidity|30 days|quarterly)\b", text, re.I)
            and claim.source_type in {"factsheet", "ips"}
        )
    if asked_term:
        if asked_term in text:
            return True
        return bool(
            claim.source_type == "ips"
            and re.search(r"\b(exclusion|exclusions|exclude|excludes|restriction|restrictions)\b", text, re.I)
        )
    if _asks_sources_to_cite(question):
        return claim.source_type in {"ips", "factsheet", "portfolio", "regulation"} and not is_flagged_text(text)
    if _asks_suitability_or_risk(question):
        return bool(
            claim.source_type in {"ips", "factsheet", "portfolio", "regulation"}
            and re.search(
                r"\b(risk|suitab\w*|recommend\w*|objective|liquid\w*|concentration|profile|high|moderate|low|asset|equity|fixed income|sector|technology|government|money market|private credit|prohibited|human|escalat\w*|current|portfolio|exposure)\b",
                text,
                re.I,
            )
        )
    if is_flagged_text(text):
        focus_terms = _question_focus_terms(q)
        return bool(focus_terms and any(term in text for term in focus_terms))
    return True


def _has_specific_decision_topic(question: str) -> bool:
    return bool(
        _asks_allocation_limit(question)
        or _asked_restricted_term(question)
        or _asks_suitability_or_risk(question)
        or _asks_tax_guidance(question)
        or _asks_jurisdiction(question)
        or _asks_exception_process(question)
        or _asks_fund_liquidity_treatment(question)
        or _asks_portfolio_context(question)
    )


def _question_focus_terms(question: str) -> set[str]:
    q = question.lower()
    terms = set(re.findall(r"\b[cf]\d{3}\b", q))
    terms.update(term for term in _RESTRICTED_TERMS if term in q)
    if "%" in q or "percent" in q or "allocate" in q or "allocation" in q:
        terms.update({"single", "position", "allocation", "concentration"})
    if "liquid" in q or "liquidity" in q:
        terms.update({"liquid", "liquidity", "30 days", "quarterly"})
    if "risk" in q or "suitable" in q or "recommend" in q:
        terms.update({"risk", "suitability", "recommend"})
    if "current" in q or "portfolio" in q or "holding" in q or "exposure" in q:
        terms.update({"current", "portfolio", "exposure", "holding"})
    return terms


_RESTRICTED_TERMS = ("tobacco", "firearms", "gambling", "cryptocurrency", "russia")


def _asked_restricted_term(question: str) -> str | None:
    q = question.lower()
    return next((term for term in _RESTRICTED_TERMS if term in q), None)


def _asks_allocation_limit(question: str) -> bool:
    q = question.lower()
    if _asks_liquidity_level(question):
        return False
    return bool(
        re.search(r"\d+\s*%|\bpercent\b", q)
        and re.search(
            r"\b(allocat\w*|position|single position|concentration|mandate|breach|cap|limit|put|buy|hold|invest)\b",
            q,
            re.I,
        )
    )


def _asks_suitability_or_risk(question: str) -> bool:
    return bool(
        re.search(
            r"\b(suitable|suitability|recommend\w*|risk|risk evidence|risk profile|risk level|high risk|low risk|asset class)\b",
            question,
            re.I,
        )
        or _asks_fund_transaction(question)
        or _asks_portfolio_context(question)
    )


def _asks_sources_to_cite(question: str) -> bool:
    return bool(
        re.search(r"\b(sources?|cite|citation)\b", question, re.I)
        and re.search(r"\brecommend\w*\b", question, re.I)
    )


def _asks_fund_transaction(question: str) -> bool:
    return bool(
        re.search(r"\b(can|may|should|would)\b", question, re.I)
        and re.search(r"\b(buy|hold|invest|put|allocate|count|use|treat)\b", question, re.I)
        and (re.search(r"\bF\d{3}\b", question, re.I) or re.search(r"\bhigh-risk equity fund\b", question, re.I))
    )


def _asks_liquidity_level(question: str) -> bool:
    return bool(
        re.search(r"\d+\s*%|\bpercent\b", question, re.I)
        and re.search(r"\b(liquid|liquidity|cash)\b", question, re.I)
        and re.search(r"\b(reduce|remain|keep|level|assets?|floor|available)\b", question, re.I)
    )


def _asks_fund_liquidity_treatment(question: str) -> bool:
    return bool(
        re.search(r"\bF\d{3}\b", question, re.I)
        and re.search(r"\b(liquid|liquidity|30-day|30 day|30 days|cash)\b", question, re.I)
        and re.search(r"\b(count|treat|use|qualify)\b", question, re.I)
    )


def _asks_portfolio_context(question: str) -> bool:
    return bool(
        re.search(
            r"\b(current|existing|portfolio|holding|holdings|post[- ]trade|after|before recommending|recommend\w*|add|breach\w*)\b",
            question,
            re.I,
        )
        and re.search(
            r"\b(client|C\d{3}|technology|sector|liquid|liquidity|F\d{3}|suitable|recommend\w*)\b",
            question,
            re.I,
        )
    )


def _asks_tax_guidance(question: str) -> bool:
    return bool(
        re.search(r"\b(tax|tax rate|capital gains|vat)\b", question, re.I)
        and re.search(
            r"\b(source|evidence|memo|approved|before|support|what should|do when|handling|cite|advisor)\b",
            question,
            re.I,
        )
    )


def _asks_jurisdiction(question: str) -> bool:
    return bool(
        re.search(r"\b(jurisdiction|jurisdictions|cross-border|country|countries)\b", question, re.I)
        and re.search(r"\b(C\d{3}|client|ips|constraint|govern|review|documented)\b", question, re.I)
    )


def _asks_exception_process(question: str) -> bool:
    return bool(re.search(r"\b(exception|verbally approves?|waiv\w*)\b", question, re.I))


def _allocation_violation_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not _asks_allocation_limit(question):
        return None
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


def _allocation_limit_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not _asks_allocation_limit(question):
        return None
    proposed = _first_percent(question)
    if proposed is None:
        return None
    limit_chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: "single position" in text.lower(),
    )
    if not limit_chunk:
        return None
    limit = _first_percent(limit_chunk.chunk_text)
    if limit is None or proposed > limit:
        return None
    claim_text = f"No single position may exceed {limit}% of portfolio value for Client {limit_chunk.source_id}."
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
    for claim in [
        _allocation_violation_claim(question, client_id, retrieved),
        _allocation_limit_claim(question, client_id, retrieved),
        _liquidity_violation_claim(question, client_id, retrieved),
        _fund_liquidity_mismatch_claim(question, client_id, retrieved),
        _portfolio_sector_breach_claim(question, client_id, retrieved),
        _override_limit_claim(question, client_id, retrieved),
        _exclusion_violation_claim(question, client_id, retrieved),
        _exclusion_scope_claim(question, client_id, retrieved),
        *_suitability_evidence_claims(question, client_id, retrieved),
    ]:
        if claim:
            _append_claim_once(kept, claim)


def _append_claim_once(claims: list[ParsedClaim], claim: ParsedClaim) -> None:
    normalized = re.sub(r"[^a-z0-9%]+", " ", claim.claim_text.lower()).strip()
    if any(
        existing.cited_source_id == claim.cited_source_id
        and re.sub(r"[^a-z0-9%]+", " ", existing.claim_text.lower()).strip() == normalized
        for existing in claims
    ):
        return
    claims.append(claim)


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


def _fund_liquidity_mismatch_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not _asks_fund_liquidity_treatment(question):
        return None
    fund_id = next(iter(_fund_ids(question)), None)
    if not fund_id:
        return None
    fund_chunk = next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_id == fund_id and chunk.source_type == "factsheet"
            and "liquid within 30 days" in chunk.chunk_text.lower()
        ),
        None,
    )
    if not fund_chunk:
        return None
    sentence = _sentence_for_term(fund_chunk.chunk_text, "liquid within 30 days")
    if not sentence:
        return None
    return _verified_claim(sentence + "." if not sentence.endswith(".") else sentence, fund_chunk)


def _portfolio_sector_breach_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    proposed = _first_percent(question)
    if proposed is None or not client_id:
        return None
    if "F300" not in _fund_ids(question):
        return None
    if not re.search(r"\b(technology|sector|concentration|recommend|buy|hold|invest|put|allocate|after)\b", question, re.I):
        return None
    fund_chunk = next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_id == "F300"
            and chunk.source_type == "factsheet"
            and "technology" in chunk.chunk_text.lower()
        ),
        None,
    )
    if not fund_chunk:
        return None
    current_chunk = _matching_portfolio_chunk(
        retrieved,
        client_id,
        lambda text: "current technology sector exposure" in text.lower(),
    )
    cap_chunk = _matching_portfolio_chunk(
        retrieved,
        client_id,
        lambda text: "maximum technology sector exposure" in text.lower(),
    )
    if not current_chunk or not cap_chunk:
        return None
    current = _first_percent(current_chunk.chunk_text)
    cap = _first_percent(cap_chunk.chunk_text)
    if current is None or cap is None:
        return None
    projected = current + proposed
    if projected <= cap:
        return None
    source_text = f"{current_chunk.chunk_text}\n{cap_chunk.chunk_text}\n{fund_chunk.chunk_text}"
    claim_text = (
        f"The proposed {proposed}% F300 allocation would breach Client {client_id}'s "
        f"technology exposure limit because it would raise technology sector exposure "
        f"to {projected}%, above the {cap}% maximum."
    )
    return ParsedClaim(
        claim_text=claim_text,
        cited_source_id=current_chunk.source_id,
        source_text=source_text,
        source_type=current_chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=0.98,
    )


def _exclusion_scope_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if _asks_portfolio_context(question):
        return None
    term = _asked_restricted_term(question)
    if not term:
        return None
    chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: any(item in text.lower() for item in _RESTRICTED_TERMS),
    )
    if not chunk:
        return None
    lower_text = chunk.chunk_text.lower()
    if term in lower_text and re.search(
        rf"\b(must not|excluded|exclude|prohibited|restriction)\b.*\b{re.escape(term)}\b|\b{re.escape(term)}\b.*\b(must not|excluded|exclude|prohibited|restriction)\b",
        lower_text,
        re.I,
    ):
        return None
    listed = [item for item in _RESTRICTED_TERMS if item in lower_text]
    if not listed:
        return None
    label = _human_list([item.title() if item == "russia" else item for item in listed])
    claim_text = f"Client {chunk.source_id}'s IPS exclusions list {label}."
    return ParsedClaim(
        claim_text=claim_text,
        cited_source_id=chunk.source_id,
        source_text=_restriction_source_text(chunk.chunk_text),
        source_type=chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=score_claim_support(claim_text, _restriction_source_text(chunk.chunk_text)),
    )


def _exclusion_violation_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if _asks_portfolio_context(question):
        return None
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


def _suitability_evidence_claims(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not _asks_suitability_or_risk(question):
        return []
    claims: list[ParsedClaim] = []
    for client_chunk in [
        chunk
        for chunk in retrieved
        if chunk.source_type == "ips" and (client_id is None or chunk.source_id == client_id)
    ]:
        for pattern in [
            rf"Client {re.escape(client_chunk.source_id)} has (?:a|an) (conservative|moderate|aggressive) risk profile\.",
            rf"High-risk equity funds require human review before being recommended to Client {re.escape(client_chunk.source_id)}\.",
            rf"Client {re.escape(client_chunk.source_id)} may hold high-risk equity funds when concentration and liquidity limits are satisfied\.",
        ]:
            match = re.search(pattern, client_chunk.chunk_text, re.I)
            if match:
                _append_claim_once(claims, _verified_claim(match.group(0), client_chunk))

    for fund_id in _fund_ids(question):
        fund_chunk = next(
            (
                chunk
                for chunk in retrieved
                if chunk.source_id == fund_id and chunk.source_type == "factsheet"
            ),
            None,
        )
        if not fund_chunk:
            continue
        match = re.search(
            rf"Fund {re.escape(fund_id)} has a (low|moderate|high) risk level\.",
            fund_chunk.chunk_text,
            re.I,
        )
        if match:
            claims.append(_verified_claim(match.group(0), fund_chunk))

    if re.search(r"\b(suitable|suitability|recommend\w*)\b", question, re.I):
        reg_chunk = next((chunk for chunk in retrieved if chunk.source_id == "REG-SUITABILITY"), None)
        if reg_chunk:
            match = re.search(
                r"An investment recommendation should be consistent with the client's documented risk profile\.",
                reg_chunk.chunk_text,
                re.I,
            )
            if match:
                claims.append(_verified_claim(match.group(0), reg_chunk))
    return claims


def _single_position_lookup_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if _first_percent(question) is not None:
        return None
    if not re.search(
        r"\b(single[- ]position|one fund position|maximum one fund|concentration cap|position limit)\b",
        question,
        re.I,
    ):
        return None
    chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: "single position" in text.lower(),
    )
    if not chunk:
        return None
    sentence = _sentence_for_pattern(chunk.chunk_text, r"no single position may exceed \d+%[^.]*\.")
    if not sentence:
        return None
    return _verified_claim(sentence, chunk)


def _override_limit_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not re.search(r"\b(ignore|override|verbal(?:ly)? approves?|exception|waive)\b", question, re.I):
        return None
    if not re.search(r"\b(concentration|single[- ]position|position|cap|limit)\b", question, re.I):
        return None
    chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: "single position" in text.lower(),
    )
    if not chunk:
        return None
    limit = _first_percent(chunk.chunk_text)
    if limit is None:
        return None
    claim_text = (
        f"Client {chunk.source_id}'s single-position limit cannot be ignored; "
        f"no single position may exceed {limit}% of portfolio value."
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


def _liquidity_lookup_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not re.search(r"\b(liquid|liquidity)\b", question, re.I):
        return None
    chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: "liquid" in text.lower(),
    )
    if not chunk:
        return None
    sentence = _sentence_for_pattern(chunk.chunk_text, r"at least \d+%[^.]*liquid[^.]*\.")
    if not sentence:
        return None
    return _verified_claim(sentence, chunk)


def _client_context_claim(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> ParsedClaim | None:
    if not client_id:
        return None
    if not re.search(
        r"\b(suitable|suitability|recommend\w*|risk evidence|risk profile|sources?|cite|citation|jurisdiction|cross-border)\b",
        question,
        re.I,
    ):
        return None
    if re.search(r"\bhigh-risk equity fund\b", question, re.I):
        chunk = _matching_client_chunk(
            retrieved,
            client_id,
            lambda text: "may hold high-risk equity funds" in text.lower()
            or "high-risk equity funds require human review" in text.lower(),
        )
        if chunk:
            return _verified_claim(chunk.chunk_text.strip().rstrip(".") + ".", chunk)

    chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: bool(
            re.search(
                r"\b(risk profile|suitability constraints|may hold|concentration|liquidity|governed by)\b",
                text,
                re.I,
            )
        ),
    )
    if not chunk:
        chunk = next(
            (
                item
                for item in retrieved
                if item.source_type == "ips" and item.source_id == client_id
            ),
            None,
        )
    if not chunk:
        return None
    text = chunk.chunk_text.strip()
    if not text.endswith("."):
        text = f"{text}."
    return _verified_claim(text, chunk)


def _portfolio_evidence_claims(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not client_id or not (_asks_portfolio_context(question) or _asks_sources_to_cite(question)):
        return []
    q = question.lower()
    terms: list[str] = []
    if _asks_sources_to_cite(question) or re.search(r"\b(recommend|suitable|suitability)\b", q):
        terms.append("approved current-portfolio evidence")
    if re.search(r"\b(technology|sector|F300)\b", question, re.I):
        terms.extend(["current technology sector exposure", "maximum technology sector exposure"])
    if re.search(r"\b(liquid|liquidity|cash|F400|F500)\b", question, re.I):
        terms.append("current liquid assets")
    if re.search(r"\b(high-risk|risk|F100|F500)\b", question, re.I):
        terms.extend(["current high-risk equity fund exposure", "current high-risk fund exposure"])
    restricted_term = _asked_restricted_term(question)
    if restricted_term:
        terms.append(f"current {restricted_term} exposure")
    for fund_id in _fund_ids(question):
        terms.append(f"current {fund_id} position")

    claims: list[ParsedClaim] = []
    for term in list(dict.fromkeys(terms)):
        chunk = _matching_portfolio_chunk(
            retrieved,
            client_id,
            lambda text, needle=term: needle.lower() in text.lower(),
        )
        if chunk:
            sentence = chunk.chunk_text.strip()
            claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, chunk))
    return claims


def _factsheet_evidence_claims(
    question: str,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    fund_ids = _primary_fund_ids(question) or set(_fund_ids(question))
    if not fund_ids:
        return []
    q = question.lower()
    claims: list[ParsedClaim] = []
    for chunk in retrieved:
        if chunk.source_type != "factsheet":
            continue
        if chunk.source_id not in fund_ids:
            continue
        text = chunk.chunk_text
        if _asks_sources_to_cite(question):
            sentence = text.strip()
            claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, chunk))
            continue
        if _asks_fund_transaction(question) or re.search(r"\b(asset class|what .*risk level|risk level|high risk|low risk|recommend\w*|money market|private credit)\b", q):
            for pattern in [
                rf"Fund {re.escape(chunk.source_id)} has a (?:low|moderate|high) risk level\.",
                rf"Fund {re.escape(chunk.source_id)} invests [^.]*\.",
            ]:
                sentence = _sentence_for_pattern(text, pattern)
                if sentence:
                    claims.append(_verified_claim(sentence, chunk))
        if _asks_fund_transaction(question) or re.search(r"\b(suitable|suitability|recommend\w*|sector|technology|concentration|risk|government bond|claiming|as if|liquidity|liquid)\b", q):
            for term in [
                "technology",
                "concentration risk",
                "government bonds",
                "government securities",
                "money market",
                "private credit",
                "daily liquidity",
                "quarterly liquidity",
                "liquid within 30 days",
                "capital preservation",
                "emerging markets",
                "financials",
            ]:
                sentence = _sentence_for_term(text, term)
                if sentence:
                    claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, chunk))
                    break
            risk_sentence = _sentence_for_pattern(
                text,
                rf"Fund {re.escape(chunk.source_id)} has a (?:low|moderate|high) risk level\.",
            )
            if risk_sentence:
                claims.append(_verified_claim(risk_sentence, chunk))
    return claims


def _regulation_evidence_claims(
    question: str,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not re.search(
        r"\b(suitability|recommend\w*|escalate|available documents|concentration|liquidity|prohibited sector|sector risk)\b",
        question,
        re.I,
    ):
        return []
    reg_chunks = [chunk for chunk in retrieved if chunk.source_id == "REG-SUITABILITY"]
    if not reg_chunks:
        return []
    q = question.lower()
    terms: list[str] = []
    if "escalate" in q or "available documents" in q or "do not answer" in q:
        terms.append("human reviewer")
    if "concentration" in q:
        terms.append("concentration limits")
    if "liquidity" in q:
        terms.append("liquidity requirements")
    if "prohibited sector" in q or "sector exposure" in q:
        terms.append("prohibited sector")
    if "recommend" in q or "suitability" in q:
        terms.append("risk profile")
    claims: list[ParsedClaim] = []
    seen_sentences: set[str] = set()

    def append_for_term(term: str) -> bool:
        for chunk in reg_chunks:
            sentence = _sentence_for_term(chunk.chunk_text, term)
            if not sentence:
                continue
            sentence = sentence + "." if not sentence.endswith(".") else sentence
            normalized = sentence.lower()
            if normalized in seen_sentences:
                return True
            seen_sentences.add(normalized)
            claims.append(_verified_claim(sentence, chunk))
            return True
        return False

    for term in terms or ["recommendation"]:
        append_for_term(term)
    if not claims and terms:
        for fallback_term in ["risk profile", "recommendation"]:
            if append_for_term(fallback_term):
                break
    return claims


def _tax_guidance_claims(
    question: str,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not _asks_tax_guidance(question):
        return []
    chunk = next((item for item in retrieved if item.source_id == "REG-TAX-GUIDANCE"), None)
    if not chunk:
        return []
    terms = ["approved jurisdictional tax memo", "Tax Desk", "must not quote a tax rate"]
    claims: list[ParsedClaim] = []
    for term in terms:
        sentence = _sentence_for_term(chunk.chunk_text, term)
        if sentence:
            claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, chunk))
    return claims


def _jurisdiction_guidance_claims(
    question: str,
    client_id: str | None,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not _asks_jurisdiction(question):
        return []
    claims: list[ParsedClaim] = []
    client_chunk = _matching_client_chunk(
        retrieved,
        client_id,
        lambda text: "governed by" in text.lower() or "jurisdiction" in text.lower(),
    )
    if client_chunk:
        sentence = _sentence_for_term(client_chunk.chunk_text, "governed by")
        if sentence:
            claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, client_chunk))
    policy_chunk = next((item for item in retrieved if item.source_id == "REG-JURISDICTION"), None)
    if policy_chunk:
        for term in ["client's approved IPS", "cross-border recommendation", "not documented"]:
            sentence = _sentence_for_term(policy_chunk.chunk_text, term)
            if sentence:
                claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, policy_chunk))
    return claims


def _exception_guidance_claims(
    question: str,
    retrieved: list[RetrievedChunk],
) -> list[ParsedClaim]:
    if not _asks_exception_process(question):
        return []
    chunks = [item for item in retrieved if item.source_id == "REG-EXCEPTIONS"]
    if not chunks:
        return []
    claims: list[ParsedClaim] = []
    for term in ["verbal approval", "Compliance approval", "IPS control"]:
        for chunk in chunks:
            sentence = _sentence_for_term(chunk.chunk_text, term)
            if sentence:
                claims.append(_verified_claim(sentence + "." if not sentence.endswith(".") else sentence, chunk))
                break
    return claims


def _verified_claim(text: str, chunk: RetrievedChunk) -> ParsedClaim:
    return ParsedClaim(
        claim_text=text,
        cited_source_id=chunk.source_id,
        source_text=chunk.chunk_text,
        source_type=chunk.source_type,
        verified=True,
        kept=True,
        grounding_score=score_claim_support(text, chunk.chunk_text),
    )


def _matching_client_chunk(
    retrieved: list[RetrievedChunk],
    client_id: str | None,
    predicate,
) -> RetrievedChunk | None:
    return next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_type == "ips"
            and (client_id is None or chunk.source_id == client_id)
            and predicate(chunk.chunk_text)
        ),
        None,
    )


def _matching_portfolio_chunk(
    retrieved: list[RetrievedChunk],
    client_id: str | None,
    predicate,
) -> RetrievedChunk | None:
    expected_source_id = f"PORTFOLIO-{client_id}" if client_id else None
    return next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_type == "portfolio"
            and (expected_source_id is None or chunk.source_id == expected_source_id)
            and predicate(chunk.chunk_text)
        ),
        None,
    )


def _restriction_source_text(text: str) -> str:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
        if any(term in sentence.lower() for term in _RESTRICTED_TERMS)
    ]
    return "\n".join(sentences) or text


def _human_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _fund_ids(question: str) -> list[str]:
    return list(dict.fromkeys(match.upper() for match in re.findall(r"\bF\d{3}\b", question, re.I)))


def _primary_fund_ids(question: str) -> set[str]:
    match = re.search(r"\bclaiming\s+(F\d{3})\b|\bas if\s+(F\d{3})\b", question, re.I)
    if not match:
        return set()
    return {item.upper() for item in match.groups() if item}


def _sentence_for_pattern(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return match.group(0).strip()


def _sentence_for_term(text: str, term: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        cleaned = sentence.strip()
        if term.lower() in cleaned.lower():
            return cleaned.rstrip(".")
    return None


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
