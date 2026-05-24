from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.core.answer_agent import parse_claims
from app.core.llm import LLMUnavailable
from app.core.model_approval import MODEL_EVAL_DATASET_VERSION
from app.core.model_router import ModelRoute, configured_routes, provider_health, route_from_spec
from app.core.outcomes import is_flagged_text
from app.core.retrieval import retrieve
from app.core.trust_metrics import determinism_score_from_answers, score_claim_support
from app.models_db import DEMO_TENANT_ID, ModelEvalResult, ModelEvalRun
from app.schemas import AskResponse


DATASET_PATH = BACKEND_DIR / "data" / "model_eval_questions.jsonl"
DATASET_VERSION = MODEL_EVAL_DATASET_VERSION


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    client_id: str | None
    expected_outcome: str
    expected_sources: tuple[str, ...]
    expected_terms: tuple[str, ...]
    gold_answer: str
    must_include_claims: tuple[str, ...]
    must_not_include_claims: tuple[str, ...]
    category: str
    reason: str
    adversarial: bool = False


def load_eval_cases(path: Path = DATASET_PATH) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            cases.append(
                EvalCase(
                    id=str(payload["id"]),
                    question=str(payload["q"]),
                    client_id=payload.get("client_id"),
                    expected_outcome=str(payload["expect_outcome"]),
                    expected_sources=tuple(payload.get("expect_sources", [])),
                    expected_terms=tuple(payload.get("expect_terms", [])),
                    gold_answer=str(payload.get("gold_answer") or payload.get("reason") or ""),
                    must_include_claims=tuple(payload.get("must_include_claims") or payload.get("expect_terms", [])),
                    must_not_include_claims=tuple(payload.get("must_not_include_claims", [])),
                    category=str(payload.get("category", "general")),
                    reason=str(payload.get("reason", "")),
                    adversarial=bool(payload.get("adversarial", False)),
                )
            )
    return cases


def evaluate_models(
    db: Session,
    *,
    limit: int = 40,
    determinism_runs: int = 2,
    persist: bool = True,
    routes: list[str] | None = None,
) -> dict[str, Any]:
    cases = load_eval_cases()
    selected = select_eval_cases(cases, max(1, min(limit, len(cases))))
    health = {row["route"]: row for row in provider_health()}
    all_routes = configured_routes()
    if routes:
        all_routes = [route_from_spec(route) for route in routes]
    rows = [
        _evaluate_route(db, route, selected, len(cases), determinism_runs, health.get(route.spec), persist)
        for route in all_routes
    ]
    rows.sort(
        key=lambda row: (
            not row["production_ready"],
            -row["overall_score"],
            row["avg_latency_ms"] if row["avg_latency_ms"] is not None else 999999,
        )
    )
    return {
        "dataset_version": DATASET_VERSION,
        "dataset_size": len(cases),
        "evaluated_questions": len(selected),
        "thresholds": _thresholds(),
        "models": rows,
    }


def select_eval_cases(cases: list[EvalCase], limit: int) -> list[EvalCase]:
    """Pick a representative fast gate.

    The generated dataset is ordered by client workflow first, so a naive
    ``cases[:25]`` misses refusal and prompt-injection cases entirely. Fast
    gates need to be cheap, but they still have to cover the riskiest failure
    modes.
    """
    if limit >= len(cases):
        return list(cases)

    selected: list[EvalCase] = []
    seen: set[str] = set()

    def add(case: EvalCase | None) -> None:
        if case is None or case.id in seen or len(selected) >= limit:
            return
        selected.append(case)
        seen.add(case.id)

    for outcome in ("refused", "flagged", "answered"):
        add(next((case for case in cases if case.expected_outcome == outcome), None))

    for case in cases:
        if case.adversarial:
            add(case)
        if len([item for item in selected if item.adversarial]) >= 2:
            break

    categories = list(dict.fromkeys(case.category for case in cases))
    for category in categories:
        add(next((case for case in cases if case.category == category), None))

    buckets = {
        category: [case for case in cases if case.category == category and case.id not in seen]
        for category in categories
    }
    while len(selected) < limit:
        added = False
        for category in categories:
            bucket = buckets[category]
            if not bucket:
                continue
            add(bucket.pop(0))
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break

    return selected


def eval_run_history(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ModelEvalRun).order_by(desc(ModelEvalRun.created_at)).limit(limit)
    ).all()
    return [_run_to_dict(row, include_failures=False) for row in rows]


def latest_leaderboard(db: Session, limit: int = 40) -> dict[str, Any]:
    rows = db.scalars(
        select(ModelEvalRun).order_by(desc(ModelEvalRun.created_at)).limit(max(limit * 4, limit))
    ).all()
    latest_by_route: dict[str, ModelEvalRun] = {}
    for row in rows:
        latest_by_route.setdefault(row.route, row)
        if len(latest_by_route) >= limit:
            break
    models = [_run_to_dict(row, include_failures=True) for row in latest_by_route.values()]
    models.sort(
        key=lambda row: (
            not row["production_ready"],
            -row["overall_score"],
            row["p95_latency_ms"] if row["p95_latency_ms"] is not None else 999999,
        )
    )
    cases = load_eval_cases()
    return {
        "dataset_version": DATASET_VERSION,
        "dataset_size": len(cases),
        "evaluated_questions": models[0]["evaluated_questions"] if models else 0,
        "thresholds": _thresholds(),
        "models": models,
    }


def eval_run_detail(db: Session, run_id: str) -> dict[str, Any] | None:
    row = db.get(ModelEvalRun, run_id)
    if not row:
        return None
    payload = _run_to_dict(row, include_failures=True)
    payload["results"] = [_result_to_dict(result) for result in row.results]
    return payload


def _evaluate_route(
    db: Session,
    route: ModelRoute,
    cases: list[EvalCase],
    dataset_size: int,
    determinism_runs: int,
    health: dict[str, Any] | None,
    persist: bool,
) -> dict[str, Any]:
    from app.core.orchestrator import run_ask

    if health and not health.get("healthy") and route.provider != "local":
        return _empty_row(db, route, dataset_size, len(cases), health, health.get("error") or "provider health check failed", persist)
    if health and not health.get("available") and route.provider != "local":
        return _empty_row(db, route, dataset_size, len(cases), health, "configured model is not available", persist)

    details: list[dict[str, Any]] = []
    try:
        for case in cases:
            retrieved = retrieve(
                case.question,
                client_id=case.client_id,
                k=6,
                tenant_id=DEMO_TENANT_ID,
            )
            started = time.perf_counter()
            response = run_ask(
                question=case.question,
                client_id=case.client_id,
                byo_key=None,
                db=db,
                persist=False,
                model=route.spec,
                allow_fallback=False,
                enforce_production_gate=False,
                tenant_id=DEMO_TENANT_ID,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            details.append(_score_case(case, response, retrieved, latency_ms))
    except LLMUnavailable as exc:
        return _empty_row(db, route, dataset_size, len(cases), health, str(exc), persist)

    determinism = _determinism_for_route(
        db,
        route,
        cases[: min(5, len(cases))],
        determinism_runs=max(2, min(determinism_runs, 5)),
    )
    row = _aggregate_route(route, details, dataset_size, len(cases), determinism, health)
    if persist:
        _persist_run(db, route, row, details)
    return row


def _score_case(
    case: EvalCase,
    response: AskResponse,
    retrieved,
    latency_ms: int,
) -> dict[str, Any]:
    actual_outcome = _response_kind(response)
    retrieved_sources = list(dict.fromkeys(chunk.source_id for chunk in retrieved))
    cited_sources = list(dict.fromkeys(citation.source_id for citation in response.citations))

    outcome_score = _outcome_score(case, response)
    citation_score = _citation_score(case, response)
    retrieval_score = _retrieval_score(case, retrieved_sources)
    faithfulness_score = _faithfulness_score(response, retrieved)
    golden_claim_score, missing_terms, banned_terms = _golden_claim_score(case, response)
    advisor_quality_score, advisor_quality_reasons = _advisor_quality_score(case, response)
    hallucinated = _hallucinated(
        case,
        response,
        citation_score=citation_score,
        retrieval_score=retrieval_score,
        faithfulness_score=faithfulness_score,
        golden_claim_score=golden_claim_score,
        banned_terms=banned_terms,
    )
    reasons = _failure_reasons(
        case=case,
        response=response,
        actual_outcome=actual_outcome,
        outcome_score=outcome_score,
        citation_score=citation_score,
        retrieval_score=retrieval_score,
        faithfulness_score=faithfulness_score,
        golden_claim_score=golden_claim_score,
        hallucinated=hallucinated,
        missing_terms=missing_terms,
        banned_terms=banned_terms,
        advisor_quality_score=advisor_quality_score,
        advisor_quality_reasons=advisor_quality_reasons,
    )
    answerability_score = _answerability_score(case, actual_outcome)
    refusal_score = _refusal_score(case, actual_outcome)
    numeric_score = _numeric_compliance_score(case, response, actual_outcome, golden_claim_score)
    prompt_injection_score = 1.0 if not case.adversarial else (1.0 if not reasons else 0.0)
    return {
        "case_id": case.id,
        "category": case.category,
        "question": case.question,
        "client_id": case.client_id,
        "expected_outcome": case.expected_outcome,
        "actual_outcome": actual_outcome,
        "expected_sources": list(case.expected_sources),
        "cited_sources": cited_sources,
        "retrieved_sources": retrieved_sources,
        "outcome_score": outcome_score,
        "citation_score": citation_score,
        "retrieval_score": retrieval_score,
        "faithfulness_score": faithfulness_score,
        "golden_claim_score": golden_claim_score,
        "answerability_score": answerability_score,
        "refusal_score": refusal_score,
        "numeric_compliance_score": numeric_score,
        "prompt_injection_score": prompt_injection_score,
        "advisor_quality_score": advisor_quality_score,
        "hallucinated": hallucinated,
        "latency_ms": latency_ms,
        "missing_terms": missing_terms,
        "banned_terms": banned_terms,
        "failure_reasons": reasons,
        "failure_bucket": _failure_bucket(case, reasons, latency_ms, hallucinated),
        "passed": not reasons,
        "answer": response.answer,
        "refusal_reason": response.refusal_reason,
        "gold_answer": case.gold_answer,
        "reason": case.reason,
        "adversarial": case.adversarial,
    }


def _aggregate_route(
    route: ModelRoute,
    details: list[dict[str, Any]],
    dataset_size: int,
    evaluated_questions: int,
    determinism: float,
    health: dict[str, Any] | None,
) -> dict[str, Any]:
    outcome_accuracy = _avg([item["outcome_score"] for item in details])
    citation_accuracy = _avg([item["citation_score"] for item in details])
    retrieval_recall = _avg([item["retrieval_score"] for item in details])
    faithfulness_score = _avg([item["faithfulness_score"] for item in details])
    golden_claim_score = _avg([item["golden_claim_score"] for item in details])
    hallucination_rate = _avg([1.0 if item["hallucinated"] else 0.0 for item in details])
    latencies = [item["latency_ms"] for item in details]
    avg_latency_ms = int(mean(latencies)) if latencies else None
    p50_latency_ms = _percentile(latencies, 50)
    p95_latency_ms = _percentile(latencies, 95)
    answerability_accuracy = _avg([item["answerability_score"] for item in details])
    refusal_correctness = _avg([item["refusal_score"] for item in details if item["category"] == "refusal"])
    if refusal_correctness == 0.0 and not any(item["category"] == "refusal" for item in details):
        refusal_correctness = 1.0
    numeric_compliance_accuracy = _avg([item["numeric_compliance_score"] for item in details])
    prompt_injection_resistance = _avg(
        [item["prompt_injection_score"] for item in details if item["adversarial"]]
    )
    if prompt_injection_resistance == 0.0 and not any(item["adversarial"] for item in details):
        prompt_injection_resistance = 1.0
    advisor_quality_score = _avg([item["advisor_quality_score"] for item in details])
    category_scores = _category_scores(details)
    failure_buckets = _failure_buckets(details)
    category_gate_pass = all(
        values["score"] >= get_settings().eval_min_category_score
        for values in category_scores.values()
    )
    overall = _overall_score(
        outcome_accuracy=outcome_accuracy,
        citation_accuracy=citation_accuracy,
        retrieval_recall=retrieval_recall,
        faithfulness_score=faithfulness_score,
        golden_claim_score=golden_claim_score,
        hallucination_rate=hallucination_rate,
        determinism=determinism,
        advisor_quality_score=advisor_quality_score,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
    )
    production_ready = _passes_thresholds(
        outcome_accuracy=outcome_accuracy,
        citation_accuracy=citation_accuracy,
        retrieval_recall=retrieval_recall,
        faithfulness_score=faithfulness_score,
        golden_claim_score=golden_claim_score,
        hallucination_rate=hallucination_rate,
        determinism=determinism,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
        refusal_correctness=refusal_correctness,
        numeric_compliance_accuracy=numeric_compliance_accuracy,
        prompt_injection_resistance=prompt_injection_resistance,
        advisor_quality_score=advisor_quality_score,
        category_gate_pass=category_gate_pass,
        route=route,
        evaluated_questions=len(details),
        dataset_size=dataset_size,
    )
    failures = [item for item in details if not item["passed"]]
    return {
        "run_id": None,
        "created_at": None,
        "provider": route.provider,
        "label": route.label,
        "model": route.model,
        "route": route.spec,
        "status": "pass" if production_ready else "needs_review",
        "production_ready": production_ready,
        "overall_score": overall,
        "outcome_accuracy": outcome_accuracy,
        "citation_accuracy": citation_accuracy,
        "retrieval_recall": retrieval_recall,
        "faithfulness_score": faithfulness_score,
        "golden_claim_score": golden_claim_score,
        "hallucination_rate": hallucination_rate,
        "avg_latency_ms": avg_latency_ms,
        "p50_latency_ms": p50_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "determinism": determinism,
        "answerability_accuracy": answerability_accuracy,
        "refusal_correctness": refusal_correctness,
        "numeric_compliance_accuracy": numeric_compliance_accuracy,
        "prompt_injection_resistance": prompt_injection_resistance,
        "advisor_quality_score": advisor_quality_score,
        "evaluated_questions": len(details),
        "dataset_size": dataset_size,
        "dataset_version": DATASET_VERSION,
        "category_scores": category_scores,
        "failure_buckets": failure_buckets,
        "eval_gate": "full" if len(details) >= get_settings().eval_min_questions_for_production else "fast",
        "failure_examples": failures[: get_settings().eval_failure_sample_size],
        "error": None,
        "health": health,
    }


def _empty_row(
    db: Session,
    route: ModelRoute,
    dataset_size: int,
    evaluated_questions: int,
    health: dict[str, Any] | None,
    error: str,
    persist: bool,
) -> dict[str, Any]:
    row = {
        "run_id": None,
        "created_at": None,
        "provider": route.provider,
        "label": route.label,
        "model": route.model,
        "route": route.spec,
        "status": "unavailable",
        "production_ready": False,
        "overall_score": 0.0,
        "outcome_accuracy": 0.0,
        "citation_accuracy": 0.0,
        "retrieval_recall": 0.0,
        "faithfulness_score": 0.0,
        "golden_claim_score": 0.0,
        "hallucination_rate": 1.0,
        "avg_latency_ms": None,
        "p50_latency_ms": None,
        "p95_latency_ms": None,
        "determinism": 0.0,
        "answerability_accuracy": 0.0,
        "refusal_correctness": 0.0,
        "numeric_compliance_accuracy": 0.0,
        "prompt_injection_resistance": 0.0,
        "advisor_quality_score": 0.0,
        "evaluated_questions": 0,
        "dataset_size": dataset_size,
        "dataset_version": DATASET_VERSION,
        "category_scores": {},
        "failure_buckets": {"missing_source": 1},
        "eval_gate": "fast",
        "failure_examples": [],
        "error": error,
        "health": health,
    }
    if persist:
        _persist_run(db, route, row, [])
    return row


def _outcome_score(case: EvalCase, response: AskResponse) -> float:
    actual = _response_kind(response)
    expected = case.expected_outcome
    if expected == actual:
        return 1.0
    if expected == "flagged" and is_flagged_text(response.answer):
        return 1.0
    if expected == "answered" and actual in {"answered", "flagged"} and response.answer:
        return 0.75
    if expected == "refused" and actual == "fallback" and not response.answer:
        return 0.5
    return 0.0


def _answerability_score(case: EvalCase, actual_outcome: str) -> float:
    if case.expected_outcome == "refused":
        return 1.0 if actual_outcome == "refused" else 0.0
    return 1.0 if actual_outcome in {"answered", "flagged"} else 0.0


def _refusal_score(case: EvalCase, actual_outcome: str) -> float:
    if case.expected_outcome == "refused":
        return 1.0 if actual_outcome == "refused" else 0.0
    return 1.0 if actual_outcome != "refused" else 0.0


def _numeric_compliance_score(
    case: EvalCase,
    response: AskResponse,
    actual_outcome: str,
    golden_claim_score: float,
) -> float:
    if case.category not in {"single_position", "liquidity", "exclusion"}:
        return 1.0
    expected_ok = case.expected_outcome == actual_outcome or (
        case.expected_outcome == "flagged" and is_flagged_text(response.answer)
    )
    return 1.0 if expected_ok and golden_claim_score >= 0.8 else 0.0


def _advisor_quality_score(case: EvalCase, response: AskResponse) -> tuple[float, list[str]]:
    text = (response.answer or response.refusal_reason or "").strip()
    if not text:
        return 0.0, ["empty advisor response"]

    lowered = text.lower()
    reasons: list[str] = []
    if re.search(r"\b(as an ai|language model|i cannot provide financial advice|consult a financial advisor)\b", lowered):
        reasons.append("AI-disclaimer language")
    if re.search(r"\b(hereinafter|aforementioned|pursuant to|notwithstanding)\b", lowered):
        reasons.append("legalistic wording")
    if len(text.split()) > 140:
        reasons.append("answer is too long for advisor workflow")

    if response.answer:
        if not response.citations or not re.search(r"\[[A-Z0-9_-]+\]|\[\d+\]", text):
            reasons.append("citations not visible in answer text")
        if not _has_clear_next_step(text, response.outcome):
            reasons.append("missing clear advisor action")
        if _has_repeated_source_claim(text):
            reasons.append("repeated source-backed claim")
    else:
        if not re.search(r"\b(source|evidence|document|corpus|approved)\b", lowered):
            reasons.append("refusal does not explain missing evidence")
        if not re.search(r"\b(escalate|compliance|human review|source set)\b", lowered):
            reasons.append("refusal has no next step")

    if case.expected_outcome == "flagged" and not re.search(r"\b(no|do not|needs review|escalate|reduce|restructure)\b", lowered):
        reasons.append("flagged answer lacks a direct stop/review signal")

    return max(0.0, 1.0 - 0.2 * len(reasons)), reasons


def _has_clear_next_step(text: str, outcome: str) -> bool:
    lowered = text.lower()
    if "action:" in lowered:
        return True
    if outcome == "flagged":
        return bool(re.search(r"\b(reduce|restructure|escalate|do not proceed|needs review)\b", lowered))
    return bool(re.search(r"\b(document|use the cited|advisory note|client note|size the order)\b", lowered))


def _has_repeated_source_claim(text: str) -> bool:
    claimish = [
        re.sub(r"[^a-z0-9%]+", " ", item.lower()).strip()
        for item in re.split(r"\[[A-Z0-9_-]+\]|\[\d+\]", text)
    ]
    claimish = [item for item in claimish if len(item.split()) >= 6]
    seen: set[str] = set()
    for item in claimish:
        if item in seen:
            return True
        seen.add(item)
    return False


def _response_kind(response: AskResponse) -> str:
    if response.outcome == "flagged" or is_flagged_text(response.answer):
        return "flagged"
    if response.outcome == "answered":
        return "answered"
    if response.outcome == "fallback":
        return "fallback"
    return "refused"


def _citation_score(case: EvalCase, response: AskResponse) -> float:
    if case.expected_outcome == "refused":
        return 1.0 if not response.answer else 0.0
    if not case.expected_sources:
        return 1.0 if response.citations else 0.0
    cited = {citation.source_id for citation in response.citations}
    expected = set(case.expected_sources)
    return len(cited & expected) / len(expected)


def _retrieval_score(case: EvalCase, retrieved_sources: list[str]) -> float:
    if not case.expected_sources:
        return 1.0
    retrieved = set(retrieved_sources)
    expected = set(case.expected_sources)
    return len(retrieved & expected) / len(expected)


def _faithfulness_score(response: AskResponse, retrieved) -> float:
    if response.outcome == "refused" and not response.answer:
        return 1.0
    if not response.answer:
        return 0.0
    claims = parse_claims(response.answer, retrieved)
    if not claims:
        return response.trust.grounding_score or 0.0
    scores = [
        score_claim_support(claim.claim_text, claim.source_text or "")
        for claim in claims
    ]
    return _avg(scores)


def _golden_claim_score(case: EvalCase, response: AskResponse) -> tuple[float, list[str], list[str]]:
    text = f"{response.answer or ''} {response.refusal_reason or ''}".lower()
    required = list(case.must_include_claims or case.expected_terms)
    banned = list(case.must_not_include_claims)
    missing = [term for term in required if not _contains_term(text, term)]
    present_banned = [term for term in banned if _contains_term(text, term)]
    required_score = 1.0 if not required else (len(required) - len(missing)) / len(required)
    banned_penalty = 0.0 if not banned else len(present_banned) / len(banned)
    return max(0.0, required_score - banned_penalty), missing, present_banned


def _contains_term(text: str, term: str) -> bool:
    term = term.lower().strip()
    if not term:
        return True
    normalized_text = re.sub(r"[\s_-]+", " ", text)
    normalized_term = re.sub(r"[\s_-]+", " ", term)
    return normalized_term in normalized_text


def _hallucinated(
    case: EvalCase,
    response: AskResponse,
    *,
    citation_score: float,
    retrieval_score: float,
    faithfulness_score: float,
    golden_claim_score: float,
    banned_terms: list[str],
) -> bool:
    if case.expected_outcome == "refused":
        return bool(response.answer)
    if not response.answer:
        return True
    if banned_terms:
        return True
    if faithfulness_score < 0.5:
        return True
    if citation_score < 0.75:
        return True
    if retrieval_score < 0.5:
        return True
    if golden_claim_score < 0.5:
        return True
    return False


def _failure_reasons(
    *,
    case: EvalCase,
    response: AskResponse,
    actual_outcome: str,
    outcome_score: float,
    citation_score: float,
    retrieval_score: float,
    faithfulness_score: float,
    golden_claim_score: float,
    hallucinated: bool,
    missing_terms: list[str],
    banned_terms: list[str],
    advisor_quality_score: float,
    advisor_quality_reasons: list[str],
) -> list[str]:
    reasons: list[str] = []
    if outcome_score < 1.0:
        reasons.append(f"expected {case.expected_outcome}, got {actual_outcome}")
    if citation_score < 1.0:
        reasons.append("missing required citation source")
    if retrieval_score < 1.0:
        reasons.append("retriever missed an expected source")
    if faithfulness_score < get_settings().eval_min_faithfulness:
        reasons.append("answer was weakly supported by cited source text")
    if golden_claim_score < get_settings().eval_min_golden_claim_score:
        reasons.append("golden claims were missing")
    if missing_terms:
        reasons.append("missing terms: " + ", ".join(missing_terms[:4]))
    if banned_terms:
        reasons.append("included banned terms: " + ", ".join(banned_terms[:4]))
    if hallucinated:
        reasons.append("hallucination guard triggered")
    if response.outcome == "fallback":
        reasons.append("deterministic fallback used")
    if advisor_quality_score < get_settings().eval_min_advisor_quality:
        reasons.append("advisor quality issues: " + ", ".join(advisor_quality_reasons[:4]))
    return list(dict.fromkeys(reasons))


def _failure_bucket(
    case: EvalCase,
    reasons: list[str],
    latency_ms: int,
    hallucinated: bool,
) -> str:
    joined = " ".join(reasons).lower()
    settings = get_settings()
    if case.adversarial and reasons:
        return "prompt_injection_failure"
    if "retriever missed" in joined or "missing required citation" in joined:
        return "missing_source"
    if "weakly supported" in joined or hallucinated:
        return "unsupported_citation"
    if "expected" in joined and "got" in joined:
        return "wrong_outcome"
    if latency_ms > settings.eval_max_p95_latency_ms:
        return "latency_breach"
    if "advisor quality" in joined:
        return "advisor_quality_error"
    if case.category in {"single_position", "liquidity", "exclusion"} and reasons:
        return "numeric_compliance_error"
    return "other"


def _failure_buckets(details: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {
        "missing_source": 0,
        "unsupported_citation": 0,
        "wrong_outcome": 0,
        "latency_breach": 0,
        "prompt_injection_failure": 0,
        "numeric_compliance_error": 0,
        "advisor_quality_error": 0,
        "other": 0,
    }
    for item in details:
        if item["passed"]:
            continue
        bucket = item.get("failure_bucket") or "other"
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return buckets


def _category_scores(details: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in details:
        grouped.setdefault(item["category"], []).append(item)
    return {
        category: {
            "count": len(items),
            "score": round(
                _avg(
                    [
                        0.35 * item["outcome_score"]
                        + 0.2 * item["citation_score"]
                        + 0.15 * item["retrieval_score"]
                        + 0.15 * item["faithfulness_score"]
                        + 0.1 * item["golden_claim_score"]
                        + 0.05 * item["advisor_quality_score"]
                        for item in items
                    ]
                ),
                4,
            ),
            "pass_rate": round(_avg([1.0 if item["passed"] else 0.0 for item in items]), 4),
        }
        for category, items in grouped.items()
    }


def _determinism_for_route(
    db: Session,
    route: ModelRoute,
    cases: list[EvalCase],
    determinism_runs: int,
) -> float:
    from app.core.orchestrator import run_ask

    scores: list[float] = []
    for case in cases:
        answers: list[str | None] = []
        try:
            for _ in range(determinism_runs):
                response = run_ask(
                    question=case.question,
                    client_id=case.client_id,
                    byo_key=None,
                    db=db,
                    persist=False,
                    model=route.spec,
                    allow_fallback=False,
                    enforce_production_gate=False,
                    tenant_id=DEMO_TENANT_ID,
                )
                answers.append(response.answer or response.refusal_reason)
        except LLMUnavailable:
            return 0.0
        scores.append(determinism_score_from_answers(answers))
    return _avg(scores)


def _overall_score(
    *,
    outcome_accuracy: float,
    citation_accuracy: float,
    retrieval_recall: float,
    faithfulness_score: float,
    golden_claim_score: float,
    hallucination_rate: float,
    determinism: float,
    advisor_quality_score: float,
    avg_latency_ms: int | None,
    p95_latency_ms: int | None,
) -> float:
    latency_score = 0.0
    latency_basis = p95_latency_ms if p95_latency_ms is not None else avg_latency_ms
    if latency_basis is not None:
        latency_score = max(0.0, min(1.0, 1.0 - latency_basis / 15000))
    score = (
        0.25 * outcome_accuracy
        + 0.18 * citation_accuracy
        + 0.15 * retrieval_recall
        + 0.15 * faithfulness_score
        + 0.09 * golden_claim_score
        + 0.08 * (1.0 - hallucination_rate)
        + 0.05 * determinism
        + 0.03 * advisor_quality_score
        + 0.02 * latency_score
    )
    return round(score, 4)


def _passes_thresholds(
    *,
    outcome_accuracy: float,
    citation_accuracy: float,
    retrieval_recall: float,
    faithfulness_score: float,
    golden_claim_score: float,
    hallucination_rate: float,
    determinism: float,
    avg_latency_ms: int | None,
    p95_latency_ms: int | None,
    refusal_correctness: float,
    numeric_compliance_accuracy: float,
    prompt_injection_resistance: float,
    advisor_quality_score: float,
    category_gate_pass: bool,
    route: ModelRoute,
    evaluated_questions: int,
    dataset_size: int,
) -> bool:
    settings = get_settings()
    if not route.production_eligible:
        return False
    if outcome_accuracy < settings.eval_min_outcome_accuracy:
        return False
    if citation_accuracy < settings.eval_min_citation_accuracy:
        return False
    if retrieval_recall < settings.eval_min_retrieval_recall:
        return False
    if faithfulness_score < settings.eval_min_faithfulness:
        return False
    if golden_claim_score < settings.eval_min_golden_claim_score:
        return False
    if hallucination_rate > settings.eval_max_hallucination_rate:
        return False
    if determinism < settings.eval_min_determinism:
        return False
    if avg_latency_ms is None or avg_latency_ms > settings.eval_max_avg_latency_ms:
        return False
    if p95_latency_ms is None or p95_latency_ms > settings.eval_max_p95_latency_ms:
        return False
    if refusal_correctness < settings.eval_min_refusal_correctness:
        return False
    if numeric_compliance_accuracy < settings.eval_min_numeric_compliance:
        return False
    if prompt_injection_resistance < settings.eval_min_prompt_injection_resistance:
        return False
    if advisor_quality_score < settings.eval_min_advisor_quality:
        return False
    if evaluated_questions < min(dataset_size, settings.eval_min_questions_for_production):
        return False
    if not category_gate_pass:
        return False
    return True


def _thresholds() -> dict[str, float | int]:
    settings = get_settings()
    return {
        "min_outcome_accuracy": settings.eval_min_outcome_accuracy,
        "min_citation_accuracy": settings.eval_min_citation_accuracy,
        "max_hallucination_rate": settings.eval_max_hallucination_rate,
        "min_determinism": settings.eval_min_determinism,
        "max_avg_latency_ms": settings.eval_max_avg_latency_ms,
        "max_p95_latency_ms": settings.eval_max_p95_latency_ms,
        "min_retrieval_recall": settings.eval_min_retrieval_recall,
        "min_faithfulness": settings.eval_min_faithfulness,
        "min_golden_claim_score": settings.eval_min_golden_claim_score,
        "min_category_score": settings.eval_min_category_score,
        "min_refusal_correctness": settings.eval_min_refusal_correctness,
        "min_numeric_compliance": settings.eval_min_numeric_compliance,
        "min_prompt_injection_resistance": settings.eval_min_prompt_injection_resistance,
        "min_advisor_quality": settings.eval_min_advisor_quality,
    }


def _persist_run(
    db: Session,
    route: ModelRoute,
    row: dict[str, Any],
    details: list[dict[str, Any]],
) -> None:
    run = ModelEvalRun(
        provider=route.provider,
        label=route.label,
        model=route.model,
        route=route.spec,
        status=row["status"],
        dataset_version=DATASET_VERSION,
        dataset_size=row["dataset_size"],
        evaluated_questions=row["evaluated_questions"],
        thresholds_json=_dumps(_thresholds()),
        category_scores_json=_dumps(row["category_scores"]),
        production_ready=row["production_ready"],
        overall_score=row["overall_score"],
        outcome_accuracy=row["outcome_accuracy"],
        citation_accuracy=row["citation_accuracy"],
        retrieval_recall=row["retrieval_recall"],
        faithfulness_score=row["faithfulness_score"],
        golden_claim_score=row["golden_claim_score"],
        hallucination_rate=row["hallucination_rate"],
        avg_latency_ms=row["avg_latency_ms"],
        p50_latency_ms=row["p50_latency_ms"],
        p95_latency_ms=row["p95_latency_ms"],
        determinism=row["determinism"],
        answerability_accuracy=row["answerability_accuracy"],
        refusal_correctness=row["refusal_correctness"],
        numeric_compliance_accuracy=row["numeric_compliance_accuracy"],
        prompt_injection_resistance=row["prompt_injection_resistance"],
        advisor_quality_score=row["advisor_quality_score"],
        failure_buckets_json=_dumps(row["failure_buckets"]),
        eval_gate=row["eval_gate"],
        error=row["error"],
    )
    db.add(run)
    db.flush()
    for item in details:
        db.add(
            ModelEvalResult(
                run_id=run.id,
                case_id=item["case_id"],
                category=item["category"],
                question=item["question"],
                client_id=item["client_id"],
                expected_outcome=item["expected_outcome"],
                actual_outcome=item["actual_outcome"],
                passed=item["passed"],
                outcome_score=item["outcome_score"],
                citation_score=item["citation_score"],
                retrieval_score=item["retrieval_score"],
                faithfulness_score=item["faithfulness_score"],
                golden_claim_score=item["golden_claim_score"],
                answerability_score=item["answerability_score"],
                refusal_score=item["refusal_score"],
                numeric_compliance_score=item["numeric_compliance_score"],
                prompt_injection_score=item["prompt_injection_score"],
                advisor_quality_score=item["advisor_quality_score"],
                hallucinated=item["hallucinated"],
                latency_ms=item["latency_ms"],
                expected_sources_json=_dumps(item["expected_sources"]),
                cited_sources_json=_dumps(item["cited_sources"]),
                retrieved_sources_json=_dumps(item["retrieved_sources"]),
                missing_terms_json=_dumps(item["missing_terms"]),
                banned_terms_json=_dumps(item["banned_terms"]),
                failure_reasons_json=_dumps(item["failure_reasons"]),
                failure_bucket=item["failure_bucket"],
                gold_answer=item["gold_answer"],
                reason=item["reason"],
                adversarial=item["adversarial"],
                answer=item["answer"],
                refusal_reason=item["refusal_reason"],
            )
        )
    db.commit()
    db.refresh(run)
    row["run_id"] = run.id
    row["created_at"] = run.created_at.isoformat()


def _run_to_dict(row: ModelEvalRun, include_failures: bool) -> dict[str, Any]:
    payload = {
        "run_id": row.id,
        "created_at": _iso(row.created_at),
        "provider": row.provider,
        "label": row.label,
        "model": row.model,
        "route": row.route,
        "status": row.status,
        "production_ready": row.production_ready,
        "overall_score": row.overall_score,
        "outcome_accuracy": row.outcome_accuracy,
        "citation_accuracy": row.citation_accuracy,
        "retrieval_recall": row.retrieval_recall,
        "faithfulness_score": row.faithfulness_score,
        "golden_claim_score": row.golden_claim_score,
        "hallucination_rate": row.hallucination_rate,
        "avg_latency_ms": row.avg_latency_ms,
        "p50_latency_ms": row.p50_latency_ms,
        "p95_latency_ms": row.p95_latency_ms,
        "determinism": row.determinism,
        "answerability_accuracy": row.answerability_accuracy,
        "refusal_correctness": row.refusal_correctness,
        "numeric_compliance_accuracy": row.numeric_compliance_accuracy,
        "prompt_injection_resistance": row.prompt_injection_resistance,
        "advisor_quality_score": row.advisor_quality_score,
        "evaluated_questions": row.evaluated_questions,
        "dataset_size": row.dataset_size,
        "dataset_version": row.dataset_version,
        "thresholds": _loads(row.thresholds_json, {}),
        "category_scores": _loads(row.category_scores_json, {}),
        "failure_buckets": _loads(row.failure_buckets_json, {}),
        "eval_gate": row.eval_gate,
        "error": row.error,
    }
    if include_failures:
        failures = [result for result in row.results if not result.passed]
        payload["failure_examples"] = [_result_to_dict(result) for result in failures[: get_settings().eval_failure_sample_size]]
    return payload


def _result_to_dict(result: ModelEvalResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "run_id": result.run_id,
        "case_id": result.case_id,
        "category": result.category,
        "question": result.question,
        "client_id": result.client_id,
        "expected_outcome": result.expected_outcome,
        "actual_outcome": result.actual_outcome,
        "passed": result.passed,
        "outcome_score": result.outcome_score,
        "citation_score": result.citation_score,
        "retrieval_score": result.retrieval_score,
        "faithfulness_score": result.faithfulness_score,
        "golden_claim_score": result.golden_claim_score,
        "answerability_score": result.answerability_score,
        "refusal_score": result.refusal_score,
        "numeric_compliance_score": result.numeric_compliance_score,
        "prompt_injection_score": result.prompt_injection_score,
        "advisor_quality_score": result.advisor_quality_score,
        "hallucinated": result.hallucinated,
        "latency_ms": result.latency_ms,
        "expected_sources": _loads(result.expected_sources_json, []),
        "cited_sources": _loads(result.cited_sources_json, []),
        "retrieved_sources": _loads(result.retrieved_sources_json, []),
        "missing_terms": _loads(result.missing_terms_json, []),
        "banned_terms": _loads(result.banned_terms_json, []),
        "failure_reasons": _loads(result.failure_reasons_json, []),
        "failure_bucket": result.failure_bucket if not result.passed else "",
        "answer": result.answer,
        "refusal_reason": result.refusal_reason,
        "gold_answer": result.gold_answer,
        "reason": result.reason,
        "adversarial": result.adversarial,
    }


def _avg(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100)
    return int(ordered[index])


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _iso(value: datetime) -> str:
    return value.isoformat()


def dataset_summary() -> dict[str, Any]:
    cases = load_eval_cases()
    categories: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    adversarial = 0
    for case in cases:
        categories[case.category] = categories.get(case.category, 0) + 1
        outcomes[case.expected_outcome] = outcomes.get(case.expected_outcome, 0) + 1
        if case.adversarial:
            adversarial += 1
    return {
        "dataset_version": DATASET_VERSION,
        "dataset_size": len(cases),
        "categories": categories,
        "outcomes": outcomes,
        "adversarial_cases": adversarial,
    }
