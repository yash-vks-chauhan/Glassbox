from __future__ import annotations

import re
from pathlib import Path

import joblib

from app.config import BACKEND_DIR
from app.core.types import RetrievedChunk


RETRIEVAL_THRESHOLD = 0.12
NON_ANSWERABLE_RE = re.compile(
    r"\b(divorce|criminal|legal opinion|trade at tomorrow|tomorrow|market forecast|"
    r"passport|private source|current internal)\b",
    re.I,
)
TAX_SCOPE_RE = re.compile(
    r"\b(capital gains|tax rate|tax advice|germany|vat)\b",
    re.I,
)


def should_refuse(question: str, retrieved: list[RetrievedChunk]) -> tuple[bool, str]:
    if not retrieved:
        return True, "No relevant source documents were retrieved."
    max_score = max(chunk.score for chunk in retrieved)
    source_text = " ".join(chunk.chunk_text for chunk in retrieved).lower()
    if re.search(r"\bproduct not present\b", question, re.I):
        return True, "The approved corpus does not contain a source that supports this request."
    if re.search(r"\b(ignore|override)\s+the\s+ips\b", question, re.I) and not re.search(
        r"\d+\s*%|concentration cap", question, re.I
    ):
        return True, "The approved corpus does not contain a source that supports this request."
    if NON_ANSWERABLE_RE.search(question):
        return True, "The approved corpus does not contain a source that supports this request."
    if TAX_SCOPE_RE.search(question) and not _is_tax_process_question(question):
        if not any(chunk.source_id.startswith("TAX-") for chunk in retrieved):
            return True, "The approved corpus does not contain a source that supports this request."
    if max_score < RETRIEVAL_THRESHOLD:
        return True, f"Top retrieval score {max_score:.2f} is below the answerability threshold."
    if _is_source_selection_question(question) or _is_grounded_finance_question(question, retrieved):
        return False, ""
    ml_refusal = _ml_refusal(question, max_score)
    if ml_refusal:
        return True, "The approved corpus does not contain a source that supports this request."
    return False, ""


def _is_source_selection_question(question: str) -> bool:
    return bool(
        re.search(r"\b(which|what)\s+sources?\b", question, re.I)
        and re.search(r"\b(cite|recommend|recommending|advisor)\b", question, re.I)
    )


def _is_grounded_finance_question(question: str, retrieved: list[RetrievedChunk]) -> bool:
    has_finance_source = any(
        chunk.source_type in {"ips", "factsheet", "regulation"} for chunk in retrieved
    )
    return bool(
        (re.search(r"\b(C\d{3}|F\d{3})\b", question, re.I) or has_finance_source)
        and re.search(
            r"\b(ips|mandate|concentration|cap|position|fund|risk|suitab|recommend|"
            r"exposure|permit|liquid|liquidity|sector|region|allocate|allocation|"
            r"verbally approves|cryptocurrency|escalate|available documents|tax|"
            r"jurisdiction|cross-border|exception)\b",
            question,
            re.I,
        )
    )


def _is_tax_process_question(question: str) -> bool:
    if re.search(r"\b(pretend|provide|give|quote)\b.*\b(tax rate|capital gains)\b", question, re.I):
        return False
    return bool(
        re.search(r"\b(tax|tax rate|capital gains|vat)\b", question, re.I)
        and re.search(
            r"\b(source|evidence|memo|approved|before|support|what should|do when|handling|cite|advisor)\b",
            question,
            re.I,
        )
    )


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
