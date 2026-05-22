from __future__ import annotations

import re

import joblib

from app.config import BACKEND_DIR
from app.core.types import RetrievedChunk
from app.schemas import Citation


def fallback_answer(
    question: str, client_id: str | None, retrieved: list[RetrievedChunk]
) -> tuple[str | None, str | None, list[Citation], float]:
    verdict = _predict_verdict(question, retrieved)
    citations = [
        Citation(
            source_id=chunk.source_id,
            source_type=chunk.source_type,
            snippet=chunk.chunk_text,
        )
        for chunk in retrieved[:3]
    ]

    q = question.lower()
    proposed = _first_percent(question)
    limit_chunk = next(
        (
            chunk
            for chunk in retrieved
            if chunk.source_type == "ips" and "single position" in chunk.chunk_text.lower()
        ),
        None,
    )
    if limit_chunk and proposed is not None:
        limit = _first_percent(limit_chunk.chunk_text)
        if limit is not None and proposed > limit:
            return (
                f"Offline fallback verdict: violation. The proposed {proposed}% allocation exceeds the documented {limit}% single-position limit for {client_id}.",
                None,
                citations,
                0.65,
            )

    if any(term in q for term in ["capital gains", "tax rate", "germany"]):
        return (
            None,
            "Offline fallback verdict: escalate. The local corpus does not contain the requested tax source.",
            citations,
            0.4,
        )

    if any(term in q for term in ["suitable", "suitability"]):
        fund_chunk = next(
            (
                chunk
                for chunk in retrieved
                if chunk.source_type == "factsheet" and "risk" in chunk.chunk_text.lower()
            ),
            None,
        )
        client_chunk = next(
            (
                chunk
                for chunk in retrieved
                if chunk.source_type == "ips" and "risk profile" in chunk.chunk_text.lower()
            ),
            None,
        )
        fund_risk = _risk_label(fund_chunk.chunk_text if fund_chunk else "")
        client_risk = _risk_label(client_chunk.chunk_text if client_chunk else "")
        if fund_risk and client_risk:
            if fund_risk == "high" and client_risk in {"conservative", "moderate"}:
                return (
                    f"Offline fallback verdict: review. Fund {fund_chunk.source_id} is high risk while {client_chunk.source_id} has a {client_risk} risk profile, so a human should review before recommendation.",
                    None,
                    citations,
                    0.55,
                )
            return (
                f"Offline fallback verdict: likely suitable based on retrieved risk evidence. Fund {fund_chunk.source_id} is {fund_risk} risk and {client_chunk.source_id} has a {client_risk} risk profile.",
                None,
                citations,
                0.55,
            )

    if verdict == "allowed":
        return (
            "Offline fallback verdict: likely allowed based on retrieved rules, but a human should review before action.",
            None,
            citations,
            0.55,
        )
    if verdict == "violation":
        return (
            "Offline fallback verdict: potential rule violation found in the retrieved mandate.",
            None,
            citations,
            0.55,
        )
    return (
        None,
        "Offline fallback verdict: escalate to a human reviewer because the hosted LLM was unavailable.",
        citations,
        0.35,
    )


def _predict_verdict(question: str, retrieved: list[RetrievedChunk]) -> str:
    artifact = BACKEND_DIR / "app" / "ml" / "artifacts" / "fallback_classifier.joblib"
    if artifact.exists():
        try:
            bundle = joblib.load(artifact)
            vectorizer = bundle["vectorizer"]
            model = bundle["model"]
            features = vectorizer.transform([question]).toarray()
            return str(model.predict(features)[0])
        except Exception:
            pass
    text = " ".join(chunk.chunk_text.lower() for chunk in retrieved)
    if "exceed" in text and _first_percent(question) is not None:
        return "violation"
    if retrieved:
        return "allowed"
    return "escalate"


def _first_percent(text: str) -> int | None:
    match = re.search(r"(\d+)\s*%", text)
    return int(match.group(1)) if match else None


def _risk_label(text: str) -> str | None:
    lowered = text.lower()
    for label in ["conservative", "moderate", "aggressive", "low", "medium", "high"]:
        if label in lowered:
            return label
    return None
