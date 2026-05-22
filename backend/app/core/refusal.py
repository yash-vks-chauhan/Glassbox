from __future__ import annotations

import re
from pathlib import Path

import joblib

from app.config import BACKEND_DIR
from app.core.types import RetrievedChunk


RETRIEVAL_THRESHOLD = 0.12
OUT_OF_SCOPE_RE = re.compile(r"\b(capital gains|tax rate|tax advice|germany|divorce|criminal)\b", re.I)


def should_refuse(question: str, retrieved: list[RetrievedChunk]) -> tuple[bool, str]:
    if not retrieved:
        return True, "No relevant source documents were retrieved."
    max_score = max(chunk.score for chunk in retrieved)
    source_text = " ".join(chunk.chunk_text for chunk in retrieved).lower()
    if OUT_OF_SCOPE_RE.search(question) and not any(
        term in source_text for term in ["capital gains", "tax rate", "germany"]
    ):
        return True, "The available corpus does not contain the required tax or legal source."
    if max_score < RETRIEVAL_THRESHOLD:
        return True, f"Top retrieval score {max_score:.2f} is below the answerability threshold."
    ml_refusal = _ml_refusal(question, max_score)
    if ml_refusal:
        return True, "The refusal router classified the question as requiring escalation."
    return False, ""


def refusal_after_verification(kept_count: int) -> tuple[bool, str]:
    if kept_count == 0:
        return True, "No drafted claims survived source verification."
    return False, ""


def _ml_refusal(question: str, max_score: float) -> bool:
    artifact = BACKEND_DIR / "app" / "ml" / "artifacts" / "refusal_router.joblib"
    if not artifact.exists():
        return False
    try:
        bundle = joblib.load(artifact)
        vectorizer = bundle["vectorizer"]
        model = bundle["model"]
        question_features = vectorizer.transform([question]).toarray()
        import numpy as np

        features = np.hstack([question_features, [[max_score, len(question)]]])
        prediction = model.predict(features)[0]
        return str(prediction) == "escalate"
    except Exception:
        return False
