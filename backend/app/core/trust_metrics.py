from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations

import joblib
import numpy as np
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.core.embeddings import embed_texts
from app.core.types import ParsedClaim


def token_overlap_ratio(claim: str, source: str) -> float:
    claim_tokens = _tokens(claim) - {"the", "a", "an", "is", "has", "have", "client", "fund"}
    source_tokens = _tokens(source)
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & source_tokens) / len(claim_tokens)


def numeric_match(claim: str, source: str) -> float:
    claim_numbers = set(re.findall(r"\d+%?", claim))
    if not claim_numbers:
        return 1.0
    source_numbers = set(re.findall(r"\d+%?", source))
    if claim_numbers.issubset(source_numbers):
        return 1.0
    if source_numbers and re.search(r"\b(violate|violates|exceed|exceeds|above|greater)\b", claim, re.I):
        claim_values = [int(re.sub(r"\D", "", number)) for number in claim_numbers]
        source_values = [int(re.sub(r"\D", "", number)) for number in source_numbers]
        if claim_values and source_values and max(claim_values) > min(source_values):
            return 1.0
    return 0.0


def score_claim_support(claim: str, source: str) -> float:
    artifact = BACKEND_DIR / "app" / "ml" / "artifacts" / "grounding_scorer.joblib"
    features = _support_features(claim, source)
    cosine, overlap, numbers = features
    heuristic = float(max(0.0, min(1.0, 0.5 * cosine + 0.35 * overlap + 0.15 * numbers)))
    if numbers == 1.0 and re.search(r"\b(violate|violates|exceed|exceeds)\b", claim, re.I):
        heuristic = max(heuristic, 0.72)
    if artifact.exists():
        try:
            model = joblib.load(artifact)
            return float(max(model.predict_proba([features])[0][1], heuristic))
        except Exception:
            pass
    return heuristic


def grounding_score(claims: list[ParsedClaim]) -> float | None:
    scores = [
        claim.grounding_score
        if claim.grounding_score is not None
        else score_claim_support(claim.claim_text, claim.source_text or "")
        for claim in claims
    ]
    if not scores:
        return None
    return float(sum(scores) / len(scores))


def _support_features(claim: str, source: str) -> list[float]:
    vectors = embed_texts([claim, source])
    cosine = float(vectors[0] @ vectors[1])
    return [cosine, token_overlap_ratio(claim, source), numeric_match(claim, source)]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9%_]+", text.lower()))


def normalize_answer(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()


def claim_source_set(answer: str | None) -> set[tuple[str, str]]:
    if not answer:
        return set()
    pairs = set()
    for match in re.finditer(r"(.*?)\s*\[([A-Z0-9_-]+)\]", answer):
        claim = normalize_answer(match.group(1))
        if claim:
            pairs.add((claim, match.group(2)))
    return pairs


def determinism_score_from_answers(answers: list[str | None]) -> float:
    if len(answers) < 2:
        return 1.0
    scores: list[float] = []
    for left, right in combinations(answers, 2):
        text_sim = SequenceMatcher(None, normalize_answer(left), normalize_answer(right)).ratio()
        left_claims = claim_source_set(left)
        right_claims = claim_source_set(right)
        if not left_claims and not right_claims:
            jaccard = 1.0
        else:
            union = left_claims | right_claims
            jaccard = len(left_claims & right_claims) / len(union) if union else 0.0
        scores.append(0.6 * text_sim + 0.4 * jaccard)
    return float(np.mean(scores))


def determinism_run(
    question: str,
    client_id: str | None,
    db: Session,
    runs: int | None = None,
    alternate_model: str | None = None,
):
    from app.core.orchestrator import run_ask
    from app.models_db import Decision

    settings = get_settings()
    run_count = runs or settings.determinism_runs
    responses = [
        run_ask(
            question=question,
            client_id=client_id,
            byo_key=None,
            db=db,
            persist=True,
            temperature=settings.llm_temperature,
            model=alternate_model,
        )
        for _ in range(run_count)
    ]
    score = determinism_score_from_answers([response.answer for response in responses])
    representative_id = responses[0].decision_id if responses else None
    if representative_id:
        row = db.get(Decision, representative_id)
        if row:
            row.determinism_score = score
            db.commit()
    return score, representative_id, responses
